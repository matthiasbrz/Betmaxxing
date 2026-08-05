"""Provider-agnostic interfaces.

Everything that touches the outside world sits behind one of these protocols, so
the engine, the backtester and the tests never depend on a vendor. A provider
that cannot serve a request raises :class:`ProviderUnavailable`; the scan turns
that into ``DATA_UNAVAILABLE`` or a degraded mode with an explicit warning — it
never falls back to another source silently, and never to stale data without
saying so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from betmaxxing.domain.enums import CollectionStatus, ProviderHealth, Sport
from betmaxxing.domain.models import (
    CanonicalEvent,
    EvidenceItem,
    OddsSnapshot,
    ProviderStatus,
    SettlementResult,
)


class ProviderError(RuntimeError):
    """Base class for provider failures."""


class ProviderUnavailable(ProviderError):
    """The provider is not configured, not reachable, or out of quota."""


class ProviderQuotaExceeded(ProviderUnavailable):
    """The provider refused the call because the quota is spent."""


class BudgetExceeded(ProviderError):
    """The request would cost more credits than the configured budget allows.

    Raised *before* the call, so a misconfiguration cannot silently spend quota.
    """


@dataclass(frozen=True, slots=True)
class QuotaInfo:
    """Provider quota as reported by response headers, when it reports any."""

    remaining: int | None = None
    used: int | None = None
    last_cost: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        return {"remaining": self.remaining, "used": self.used, "last_cost": self.last_cost}


@dataclass(slots=True)
class CollectionBatch:
    """One provider collection: what was seen, what failed, what it cost.

    Returned whole so the caller can persist the source data **before** deciding
    whether any model can price it. A batch with zero candidates is still a
    valuable, storable result; a batch that vanishes because no model existed is
    data loss.
    """

    provider: str
    collected_at: datetime
    events: list[CanonicalEvent] = field(default_factory=list)
    snapshots: list[OddsSnapshot] = field(default_factory=list)
    bookmakers: list[str] = field(default_factory=list)
    #: Non-fatal failures. Their presence must never discard the valid data.
    partial_errors: list[str] = field(default_factory=list)
    quota: QuotaInfo = field(default_factory=QuotaInfo)
    coverage: CollectionStatus = CollectionStatus.OK
    batch_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    @property
    def is_empty(self) -> bool:
        return not self.snapshots


@runtime_checkable
class OddsProvider(Protocol):
    """Events, markets and immutable odds snapshots."""

    name: str
    bookmaker: str

    def health(self) -> ProviderStatus: ...

    def list_events(
        self, sports: list[Sport], window: tuple[datetime, datetime]
    ) -> list[CanonicalEvent]: ...

    def fetch_odds(self, events: list[CanonicalEvent]) -> list[OddsSnapshot]: ...

    def collect(
        self, sports: list[Sport], window: tuple[datetime, datetime]
    ) -> CollectionBatch: ...


@runtime_checkable
class SportsDataProvider(Protocol):
    """Schedules, results and the statistics that feed model features."""

    name: str

    def health(self) -> ProviderStatus: ...

    def team_features(self, event: CanonicalEvent) -> dict[str, float]: ...


@runtime_checkable
class ContextProvider(Protocol):
    """Verifiable side information: injuries, line-ups, withdrawals.

    Returns evidence items that already carry a source and a timestamp; anything
    without provenance must not be returned at all.
    """

    name: str

    def health(self) -> ProviderStatus: ...

    def context_for(self, event: CanonicalEvent) -> list[EvidenceItem]: ...


@runtime_checkable
class ResultsProvider(Protocol):
    """Settlement of finished events."""

    name: str

    def health(self) -> ProviderStatus: ...

    def settle(self, event: CanonicalEvent, selection_key: str) -> SettlementResult | None: ...


@runtime_checkable
class NotificationProvider(Protocol):
    """Outbound alerting. ``send`` must be a no-op when not enabled."""

    name: str

    def health(self) -> ProviderStatus: ...

    def send(self, subject: str, body: str) -> bool: ...


def not_configured(name: str, kind: str, detail: str) -> ProviderStatus:
    """Helper for reporting a provider that has no credentials."""
    return ProviderStatus(
        name=name,
        kind=kind,
        health=ProviderHealth.NOT_CONFIGURED,
        detail=detail,
    )


def collect_via_listing(
    provider: object,
    sports: list[Sport],
    window: tuple[datetime, datetime],
    now: datetime,
) -> CollectionBatch:
    """Build a batch from a provider that only implements list/fetch.

    Lets simple adapters (demo, manual CSV) satisfy the batch contract without
    each reimplementing it, so the acquisition path is genuinely single.
    """
    name = getattr(provider, "name", "unknown")
    bookmaker = getattr(provider, "bookmaker", "")
    events = list(provider.list_events(sports, window))  # type: ignore[attr-defined]
    snapshots = list(provider.fetch_odds(events)) if events else []  # type: ignore[attr-defined]
    return CollectionBatch(
        provider=name,
        collected_at=now,
        events=events,
        snapshots=snapshots,
        bookmakers=[bookmaker] if bookmaker else [],
        coverage=CollectionStatus.OK if snapshots else CollectionStatus.COVERAGE_MISSING,
    )
