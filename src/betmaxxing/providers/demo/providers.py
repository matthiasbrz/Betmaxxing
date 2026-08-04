"""Demo implementations of every provider protocol. Synthetic, keyless, deterministic."""

from __future__ import annotations

from datetime import datetime, timedelta

from betmaxxing.domain.enums import BetOutcome, ProviderHealth, Sport
from betmaxxing.domain.models import (
    CanonicalEvent,
    EvidenceItem,
    OddsSnapshot,
    ProviderStatus,
    SettlementResult,
)
from betmaxxing.domain.timeutil import is_in_window, utc_now
from betmaxxing.providers.demo.world import (
    ALL_FIXTURES,
    DEMO_BOOKMAKER,
    DEMO_PROVIDER,
    build_event,
    build_snapshots,
)


class DemoOddsProvider:
    """Serves the synthetic book. Never contacts the network."""

    name = DEMO_PROVIDER
    bookmaker = DEMO_BOOKMAKER

    def __init__(self, now: datetime | None = None) -> None:
        # Pinned at construction so a single scan sees one coherent instant.
        self._now = now or utc_now()
        self._events: dict[str, CanonicalEvent] = {}

    def health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            kind="odds",
            health=ProviderHealth.OK,
            detail="Fournisseur de démonstration — données synthétiques, aucune cote réelle.",
            events_returned=len(self._events),
            quota_remaining=None,
        )

    def list_events(
        self, sports: list[Sport], window: tuple[datetime, datetime]
    ) -> list[CanonicalEvent]:
        """Returns every fixture for the requested sports.

        Window filtering is intentionally *not* applied here: the scan engine
        performs it and records an ``OUTSIDE_WINDOW`` rejection, so the exclusion
        is visible in the audit trail instead of vanishing at the provider.
        """
        wanted = set(sports)
        out: list[CanonicalEvent] = []
        for fixture in ALL_FIXTURES:
            if fixture.sport not in wanted:
                continue
            event = build_event(fixture, self._now)
            self._events[event.canonical_id] = event
            out.append(event)
        return out

    def fetch_odds(self, events: list[CanonicalEvent]) -> list[OddsSnapshot]:
        wanted = {e.canonical_id for e in events}
        out: list[OddsSnapshot] = []
        for fixture in ALL_FIXTURES:
            event = build_event(fixture, self._now)
            if event.canonical_id not in wanted:
                continue
            out.extend(build_snapshots(fixture, event, self._now))
        return out


class DemoSportsDataProvider:
    name = DEMO_PROVIDER

    def health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            kind="sports_data",
            health=ProviderHealth.OK,
            detail="Statistiques synthétiques de démonstration.",
        )

    def team_features(self, event: CanonicalEvent) -> dict[str, float]:
        # Model inputs are supplied directly by the demo world; nothing extra.
        return {}


class DemoContextProvider:
    """Returns sourced evidence items. Every item carries a source and a date."""

    name = DEMO_PROVIDER

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or utc_now()

    def health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            kind="context",
            health=ProviderHealth.OK,
            detail="Contexte synthétique de démonstration.",
        )

    def context_for(self, event: CanonicalEvent) -> list[EvidenceItem]:
        as_of = self._now - timedelta(hours=2)
        items = [
            EvidenceItem(
                text=(
                    f"Aucune absence confirmée publiée pour {event.home.name} "
                    f"ni {event.away.name} à cette heure."
                ),
                source="demo:context-feed",
                as_of=as_of,
                kind="fact",
            ),
            EvidenceItem(
                text="Composition officielle non encore disponible à l'heure du scan.",
                source="demo:context-feed",
                as_of=as_of,
                kind="uncertainty",
            ),
        ]
        if event.sport is Sport.TENNIS and event.surface:
            items.append(
                EvidenceItem(
                    text=f"Surface du tournoi : {event.surface}.",
                    source="demo:tournament-metadata",
                    as_of=as_of,
                    kind="fact",
                )
            )
        return items


class DemoResultsProvider:
    """Settles nothing: demo events never finish. Returns ``None`` honestly."""

    name = DEMO_PROVIDER

    def health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            kind="results",
            health=ProviderHealth.OK,
            detail="Aucun résultat en mode démo — les événements ne se terminent jamais.",
        )

    def settle(self, event: CanonicalEvent, selection_key: str) -> SettlementResult | None:
        if event.start_time_utc > utc_now():
            return None
        return SettlementResult(
            event_canonical_id=event.canonical_id,
            selection_key=selection_key,
            outcome=BetOutcome.PENDING,
            settled_at=utc_now(),
            proof="demo:no-settlement",
            detail="Le mode démo ne produit pas de résultat vérifié.",
        )


def demo_window_contains(event: CanonicalEvent, window: tuple[datetime, datetime]) -> bool:
    """Small helper kept for readability in tests."""
    return is_in_window(event.start_time_utc, window)
