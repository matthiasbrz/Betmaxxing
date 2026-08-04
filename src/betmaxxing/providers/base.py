"""Provider-agnostic interfaces.

Everything that touches the outside world sits behind one of these protocols, so
the engine, the backtester and the tests never depend on a vendor. A provider
that cannot serve a request raises :class:`ProviderUnavailable`; the scan turns
that into ``DATA_UNAVAILABLE`` or a degraded mode with an explicit warning — it
never falls back to another source silently, and never to stale data without
saying so.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from betmaxxing.domain.enums import ProviderHealth, Sport
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
