"""Durable, atomic credit budget for paid providers.

The original guard was an integer on the HTTP client: ``self._spent``. Three
things it could not do:

* **bound a retry** — the counter only moved after a response arrived;
* **bound two workers** — each process had its own;
* **survive a restart** — it reset to zero, and with it the day's spend.

The previous tranche replaced it with a ledger table and a ``SELECT SUM(...)``
before each ``INSERT``. That is correct on SQLite for an accidental reason —
SQLite serialises every writer behind one database-level lock — and **wrong on
PostgreSQL**, where two ``READ COMMITTED`` transactions read the same total and
both insert. Two reservations that each fit under the ceiling together exceed it.

The synchronisation primitive is now a single row per ``(provider, UTC day)``,
updated conditionally:

.. code-block:: sql

    UPDATE provider_budget_days
       SET reserved_total = reserved_total + :cost
     WHERE provider = :p AND day_utc = :d
       AND reserved_total + :cost <= :ceiling

PostgreSQL locks the row and re-evaluates the predicate against the *updated*
tuple after the lock is released, so the loser's condition fails and it changes
zero rows. SQLite serialises. Both give "one winner", and both are tested — the
PostgreSQL case with barrier-synchronised threads in
``tests/test_postgres_concurrency.py``.

Reservation and audit detail are written in **one** transaction, so a refusal
leaves no trace and a rollback cannot desynchronise the counter from the log.

Accounting the awkward cases
----------------------------
* **Header absent.** The reservation stays at its estimate. An unknown cost is
  charged as the worst case; the alternative under-counts spend.
* **Request may have been received.** Also stays charged — see
  :func:`betmaxxing.providers.the_odds_api.client.may_have_been_billed`. Only a
  request that demonstrably never left the client is released.
* **Reconcile and release are idempotent**, and neither can drive the counter
  below zero.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from betmaxxing.config import Settings
from betmaxxing.domain.timeutil import ensure_utc, utc_now
from betmaxxing.providers.base import BudgetExceeded
from betmaxxing.storage.db import create_all, session_scope
from betmaxxing.storage.tables import ProviderBudgetDayRow, ProviderBudgetLedgerRow

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


@dataclass(frozen=True, slots=True)
class BudgetInvariant:
    """Whether the daily counter still matches the detail it summarises."""

    provider: str
    day_utc: str
    counter: int
    detail: int
    ok: bool

    def __bool__(self) -> bool:
        return self.ok

    def describe(self) -> str:
        verdict = "cohérent" if self.ok else "INCOHÉRENT"
        return (
            f"{self.provider} {self.day_utc} : compteur={self.counter} "
            f"détail={self.detail} → {verdict}"
        )


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

        ``scan_spent``/``scan_budget`` express the *per-scan* ceiling, which is a
        property of one collection rather than of the day. It is checked here so
        a single decision point governs every attempt, retries included.
        """
        estimated = max(1, int(cost))
        day = day_key(now)
        moment = ensure_utc(now)

        if scan_budget is not None and scan_spent + estimated > scan_budget:
            raise BudgetExceeded(
                f"budget de {scan_budget} crédits par scan dépassé "
                f"({scan_spent} consommés, {estimated} demandés) — appel refusé."
            )

        # 0 (or unset) means "no daily ceiling": the counter still moves, so the
        # audit stays complete, but nothing can refuse the attempt.
        ceiling = self._settings.provider_budget_per_day or None
        with session_scope(self._settings) as session:
            self._ensure_day_row(session, provider, day, moment)
            if not self._charge(session, provider, day, estimated, ceiling, moment):
                spent = self._counter(session, provider, day)
                raise BudgetExceeded(
                    f"budget journalier de {ceiling} crédits atteint pour "
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
                created_at=moment,
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def reconcile(self, reservation_id: int, *, observed_cost: int | None) -> None:
        """Replace the estimate with the figure the provider reported.

        ``None`` — the header was absent — deliberately leaves the estimate in
        place. Treating an unknown cost as zero is how a budget stops binding.

        Idempotent: the detail row is claimed with a conditional UPDATE, so a
        repeated call changes nothing and the counter is adjusted exactly once.
        """
        if observed_cost is None:
            logger.debug("no x-requests-last header; reservation kept at its estimate")
            return
        observed = max(0, int(observed_cost))

        with session_scope(self._settings) as session:
            snapshot = self._snapshot(session, reservation_id)
            if snapshot is None:
                return
            provider, day, reserved, _previous = snapshot
            claimed = session.execute(
                update(ProviderBudgetLedgerRow)
                .where(
                    ProviderBudgetLedgerRow.id == reservation_id,
                    ProviderBudgetLedgerRow.observed_cost.is_(None),
                    ProviderBudgetLedgerRow.released.is_(False),
                )
                .values(observed_cost=observed)
            )
            if claimed.rowcount != 1:  # type: ignore[attr-defined]
                return
            self._adjust(
                session,
                provider,
                day,
                delta=observed - reserved,
                observed_delta=observed,
            )

    def release(self, reservation_id: int) -> None:
        """The request demonstrably never arrived, so no credit was consumed."""
        with session_scope(self._settings) as session:
            snapshot = self._snapshot(session, reservation_id)
            if snapshot is None:
                return
            provider, day, reserved, previous = snapshot
            claimed = session.execute(
                update(ProviderBudgetLedgerRow)
                .where(
                    ProviderBudgetLedgerRow.id == reservation_id,
                    ProviderBudgetLedgerRow.released.is_(False),
                )
                .values(observed_cost=0, released=True)
            )
            if claimed.rowcount != 1:  # type: ignore[attr-defined]
                return
            # Whatever this attempt currently counts for, take exactly that back.
            already = previous if previous is not None else reserved
            self._adjust(
                session,
                provider,
                day,
                delta=-already,
                observed_delta=-(previous or 0),
            )

    # -- inspection ---------------------------------------------------------
    def spent_today(self, provider: str, now: datetime) -> int:
        with session_scope(self._settings) as session:
            return self._counter(session, provider, day_key(now))

    def remaining_today(self, provider: str, now: datetime) -> int | None:
        """``None`` when no daily ceiling is configured."""
        ceiling = self._settings.provider_budget_per_day
        if not ceiling:
            return None
        return max(0, ceiling - self.spent_today(provider, now))

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

    def verify_invariant(self, provider: str, now: datetime) -> BudgetInvariant:
        """The counter must equal the sum of what the detail rows still owe.

        Exposed so an operator (and the test suite) can assert consistency rather
        than trust it. ``betmaxxing budget audit`` prints it.
        """
        day = day_key(now)
        with session_scope(self._settings) as session:
            counter = self._counter(session, provider, day)
            detail = int(
                session.scalar(
                    select(
                        func.coalesce(
                            func.sum(
                                func.coalesce(
                                    ProviderBudgetLedgerRow.observed_cost,
                                    ProviderBudgetLedgerRow.reserved_cost,
                                )
                            ),
                            0,
                        )
                    ).where(
                        ProviderBudgetLedgerRow.provider == provider,
                        ProviderBudgetLedgerRow.day_utc == day,
                        ProviderBudgetLedgerRow.released.is_(False),
                    )
                )
                or 0
            )
        return BudgetInvariant(
            provider=provider,
            day_utc=day,
            counter=counter,
            detail=detail,
            ok=counter == detail,
        )

    def days_with_activity(self, provider: str | None = None) -> list[tuple[str, str]]:
        with session_scope(self._settings) as session:
            statement = select(ProviderBudgetDayRow.provider, ProviderBudgetDayRow.day_utc)
            if provider:
                statement = statement.where(ProviderBudgetDayRow.provider == provider)
            return [
                (str(p), str(d))
                for p, d in session.execute(statement.order_by(ProviderBudgetDayRow.day_utc)).all()
            ]

    # -- the atomic primitive ------------------------------------------------
    @staticmethod
    def _snapshot(session: Session, reservation_id: int) -> tuple[str, str, int, int | None] | None:
        """Read the detail row's state **before** any UPDATE touches it.

        SQLAlchemy synchronises matching in-session objects when an UPDATE runs,
        so reading attributes afterwards returns post-update values. Reading
        ``observed_cost`` after setting it to 0 made the release subtract 0 and
        leave the day's counter charged — the same trap the scheduler's claim
        loop documents.
        """
        row = session.execute(
            select(
                ProviderBudgetLedgerRow.provider,
                ProviderBudgetLedgerRow.day_utc,
                ProviderBudgetLedgerRow.reserved_cost,
                ProviderBudgetLedgerRow.observed_cost,
            ).where(ProviderBudgetLedgerRow.id == reservation_id)
        ).one_or_none()
        if row is None:
            return None
        return str(row[0]), str(row[1]), int(row[2]), (None if row[3] is None else int(row[3]))

    @staticmethod
    def _ensure_day_row(session: Session, provider: str, day: str, moment: datetime) -> None:
        """Create the bucket if it does not exist, tolerating a concurrent creator."""
        if session.get(ProviderBudgetDayRow, (provider, day)) is not None:
            return
        savepoint = session.begin_nested()
        try:
            session.add(
                ProviderBudgetDayRow(
                    provider=provider,
                    day_utc=day,
                    reserved_total=0,
                    observed_total=0,
                    updated_at=moment,
                )
            )
            savepoint.commit()
        except IntegrityError:
            # Another worker created it between the read and the insert. Its row
            # is as good as ours would have been.
            savepoint.rollback()

    @staticmethod
    def _charge(
        session: Session,
        provider: str,
        day: str,
        cost: int,
        ceiling: int | None,
        moment: datetime,
    ) -> bool:
        """Conditional increment. ``False`` means the ceiling refused it.

        This is the whole synchronisation story: one row, one UPDATE, predicate
        re-evaluated under the row lock.
        """
        statement = (
            update(ProviderBudgetDayRow)
            .where(
                ProviderBudgetDayRow.provider == provider,
                ProviderBudgetDayRow.day_utc == day,
            )
            .values(
                reserved_total=ProviderBudgetDayRow.reserved_total + cost,
                updated_at=moment,
            )
        )
        if ceiling is not None:
            statement = statement.where(ProviderBudgetDayRow.reserved_total + cost <= ceiling)
        result = session.execute(statement)
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    @staticmethod
    def _adjust(
        session: Session,
        provider: str,
        day: str,
        *,
        delta: int,
        observed_delta: int,
    ) -> None:
        """Move the counter by ``delta``, clamped at zero.

        A release of an already-reconciled row, or a double release, must not
        push the day's spend negative — a negative budget is a budget that
        authorises everything.
        """
        session.execute(
            text(
                "UPDATE provider_budget_days"
                " SET reserved_total = CASE WHEN reserved_total + :delta > 0"
                "                          THEN reserved_total + :delta ELSE 0 END,"
                "     observed_total = CASE WHEN observed_total + :obs > 0"
                "                          THEN observed_total + :obs ELSE 0 END"
                " WHERE provider = :provider AND day_utc = :day"
            ),
            {"delta": delta, "obs": observed_delta, "provider": provider, "day": day},
        )

    @staticmethod
    def _counter(session: Session, provider: str, day: str) -> int:
        row = session.get(ProviderBudgetDayRow, (provider, day))
        return int(row.reserved_total) if row is not None else 0


__all__ = ["BudgetEntry", "BudgetInvariant", "ProviderBudgetLedger", "day_key"]


def utc_today() -> str:  # pragma: no cover - convenience for the CLI
    return day_key(utc_now())
