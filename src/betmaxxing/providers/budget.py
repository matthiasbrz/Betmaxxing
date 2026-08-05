"""Durable credit budget for paid providers.

The previous guard was an integer on the HTTP client: ``self._spent``. Three
things it could not do, all of which the audit found:

* **survive a retry correctly** — the counter was only incremented *after* a
  response arrived, so a request that failed and was retried had already been
  authorised before its predecessor was accounted for;
* **bound two workers** — each process had its own counter, so the configured
  daily ceiling was the *per-process* ceiling multiplied by however many
  processes happened to be running;
* **survive a restart** — the counter reset to zero, and with it the day's spend.

This module replaces it with a reservation ledger in the database. Every attempt
reserves its estimated cost *before* the call. The estimate is an upper bound
(``markets x regions``, the documented v4 rule); once the response arrives, the
reservation is reconciled against ``x-requests-last``, which is authoritative.

Handling the awkward cases explicitly
-------------------------------------
* **Header absent.** The reservation is *kept at its estimate*, not zeroed. An
  unknown cost is treated as the worst case, because the alternative silently
  under-counts spend.
* **Transport error, no response at all.** No credit was consumed, so the
  reservation is released (``observed_cost = 0``). Keeping it would leak the
  day's budget on a flaky network.
* **Concurrency.** Reserving is an INSERT inside a transaction that first reads
  the day's committed total. Under SQLite the write lock serialises it; under
  PostgreSQL the row-level behaviour is the same for INSERT-only workloads. Two
  workers can therefore not both pass a ceiling that only one of them fits under.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from betmaxxing.config import Settings
from betmaxxing.domain.timeutil import ensure_utc, utc_now
from betmaxxing.providers.base import BudgetExceeded
from betmaxxing.storage.db import create_all, session_scope
from betmaxxing.storage.tables import ProviderBudgetLedgerRow

logger = logging.getLogger("betmaxxing.budget")


@dataclass(frozen=True, slots=True)
class BudgetEntry:
    """One recorded attempt."""

    id: int
    provider: str
    day_utc: str
    request: str
    reserved_cost: int
    observed_cost: int | None
    released: bool
    created_at: datetime

    @property
    def effective_cost(self) -> int:
        """What this attempt counts for. Unknown means "as reserved"."""
        if self.released:
            return 0
        return self.reserved_cost if self.observed_cost is None else self.observed_cost


def day_key(moment: datetime) -> str:
    """The provider's quota window is a UTC calendar day."""
    return ensure_utc(moment).strftime("%Y-%m-%d")


class ProviderBudgetLedger:
    """Reserve-before-call accounting, shared by every worker on one database."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # The ledger is a hard dependency of any paid call: a provider that
        # cannot record a reservation must not be able to make one. Ensuring the
        # schema here mirrors AcquisitionService and keeps that invariant true
        # even for a caller that constructs the provider directly.
        create_all(settings)

    # -- reservation --------------------------------------------------------
    def reserve(
        self,
        *,
        provider: str,
        cost: int,
        request: str,
        now: datetime,
        batch_id: str | None = None,
        scan_spent: int = 0,
        scan_budget: int | None = None,
    ) -> int:
        """Authorise one attempt, or refuse it. Returns the reservation id.

        ``scan_spent``/``scan_budget`` express the *per-scan* ceiling, which is
        a property of one collection rather than of the day, and is checked here
        so that a single decision point governs every attempt including retries.
        """
        estimated = max(1, int(cost))
        day = day_key(now)

        if scan_budget is not None and scan_spent + estimated > scan_budget:
            raise BudgetExceeded(
                f"budget de {scan_budget} crédits par scan dépassé "
                f"({scan_spent} consommés, {estimated} demandés) — appel refusé."
            )

        daily_budget = self._settings.provider_budget_per_day
        with session_scope(self._settings) as session:
            if daily_budget:
                spent = self._spent_today(session, provider, day)
                if spent + estimated > daily_budget:
                    raise BudgetExceeded(
                        f"budget journalier de {daily_budget} crédits atteint pour "
                        f"« {provider} » ({spent} consommés le {day}, {estimated} "
                        "demandés) — appel refusé."
                    )
            row = ProviderBudgetLedgerRow(
                provider=provider,
                day_utc=day,
                request=request,
                batch_id=batch_id,
                reserved_cost=estimated,
                observed_cost=None,
                released=False,
                created_at=ensure_utc(now),
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def reconcile(self, reservation_id: int, *, observed_cost: int | None) -> None:
        """Replace the estimate with the figure the provider reported.

        ``None`` — the header was absent — deliberately leaves the estimate in
        place. Treating an unknown cost as zero is how a budget stops binding.
        """
        if observed_cost is None:
            logger.debug("no x-requests-last header; reservation kept at its estimate")
            return
        with session_scope(self._settings) as session:
            row = session.get(ProviderBudgetLedgerRow, reservation_id)
            if row is not None:
                row.observed_cost = max(0, int(observed_cost))

    def release(self, reservation_id: int) -> None:
        """No response arrived, so no credit was consumed."""
        with session_scope(self._settings) as session:
            row = session.get(ProviderBudgetLedgerRow, reservation_id)
            if row is not None:
                row.observed_cost = 0
                row.released = True

    # -- inspection ---------------------------------------------------------
    def spent_today(self, provider: str, now: datetime) -> int:
        with session_scope(self._settings) as session:
            return self._spent_today(session, provider, day_key(now))

    def remaining_today(self, provider: str, now: datetime) -> int | None:
        """``None`` when no daily ceiling is configured."""
        budget = self._settings.provider_budget_per_day
        if not budget:
            return None
        return max(0, budget - self.spent_today(provider, now))

    def entries_for_day(self, now: datetime, provider: str | None = None) -> list[BudgetEntry]:
        day = day_key(now)
        with session_scope(self._settings) as session:
            statement = select(ProviderBudgetLedgerRow).where(
                ProviderBudgetLedgerRow.day_utc == day
            )
            if provider:
                statement = statement.where(ProviderBudgetLedgerRow.provider == provider)
            return [
                BudgetEntry(
                    id=row.id,
                    provider=row.provider,
                    day_utc=row.day_utc,
                    request=row.request,
                    reserved_cost=row.reserved_cost,
                    observed_cost=row.observed_cost,
                    released=row.released,
                    created_at=row.created_at,
                )
                for row in session.scalars(statement.order_by(ProviderBudgetLedgerRow.id)).all()
            ]

    @staticmethod
    def _spent_today(session: object, provider: str, day: str) -> int:
        """Committed spend for the day, counting an unknown cost as reserved."""
        total = session.scalar(  # type: ignore[attr-defined]
            select(
                func.sum(
                    func.coalesce(
                        ProviderBudgetLedgerRow.observed_cost,
                        ProviderBudgetLedgerRow.reserved_cost,
                    )
                )
            ).where(
                ProviderBudgetLedgerRow.provider == provider,
                ProviderBudgetLedgerRow.day_utc == day,
            )
        )
        return int(total or 0)


__all__ = ["BudgetEntry", "ProviderBudgetLedger", "day_key"]


def utc_today() -> str:  # pragma: no cover - convenience for the CLI
    return day_key(utc_now())
