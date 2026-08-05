"""The Odds API v4 odds provider.

**Status: IMPLEMENTED_UNVERIFIED.** Every behaviour below is exercised against
recorded local fixtures; none of it has been run against the live service. The
opt-in smoke test (``scripts/smoke_the_odds_api.py``) is the only thing that can
change that, and it requires the user's own key and explicit action.

Behaviour worth stating plainly:

* A valid response that simply does not include the configured bookmaker is
  ``COVERAGE_MISSING``, **not** a provider failure — and it never falls back to
  demo data.
* Events that have already started are dropped even if the API returns them.
* Source time, bookmaker ``last_update``, and local ``received_at`` are kept
  distinct; conflating them is how stale prices get treated as fresh.
* Requests are budget-checked before they are made.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from betmaxxing.config import Settings
from betmaxxing.domain.enums import CollectionStatus, EventStatus, ProviderHealth, Sport
from betmaxxing.domain.ids import participant_id
from betmaxxing.domain.models import (
    CanonicalEvent,
    OddsSnapshot,
    Participant,
    ProviderStatus,
)
from betmaxxing.domain.timeutil import ensure_utc, utc_now
from betmaxxing.providers.base import (
    BudgetExceeded,
    CollectionBatch,
    ProviderError,
    QuotaInfo,
)
from betmaxxing.providers.budget import ProviderBudgetLedger
from betmaxxing.providers.the_odds_api.client import (
    TheOddsApiAuthError,
    TheOddsApiClient,
    estimate_cost,
    redact,
)
from betmaxxing.providers.the_odds_api.mapping import (
    MappingRejected,
    classify_sport,
    map_market,
    parse_iso,
)

logger = logging.getLogger("betmaxxing.the_odds_api")

PROVIDER_NAME = "the_odds_api"

#: Markets requested in the grouped, one-call-per-league request, **per sport**.
#:
#: A single global tuple was wrong: it asked for tennis ``totals``, which the
#: project documents as disabled until the games-versus-sets semantics is
#: confirmed. Every market in that call is billed, so we were paying for a price
#: the mapper then refused — the worst of both worlds. What is not requested is
#: not billed, and the request is the only place that can enforce it.
CORE_MARKETS_BY_SPORT: dict[Sport, tuple[str, ...]] = {
    Sport.FOOTBALL: ("h2h", "totals"),
    Sport.TENNIS: ("h2h",),
}

#: Additional markets, per sport. v4 exposes these on the **per-event** endpoint
#: only, so they cost one request per event and are attempted after the core
#: call, under the same budget gate. Declaring a key in ``MARKET_MAP`` is not the
#: same as collecting it — the previous version did only the former.
ADDITIONAL_MARKETS_BY_SPORT: dict[Sport, tuple[str, ...]] = {
    Sport.FOOTBALL: (
        "draw_no_bet",
        "double_chance",
        "h2h_3_way_h1",
        "totals_h1",
        "double_chance_h1",
    ),
    Sport.TENNIS: (),
}

#: Kept for callers that still import it; football's grouped set.
CORE_MARKETS = CORE_MARKETS_BY_SPORT[Sport.FOOTBALL]
ADDITIONAL_FOOTBALL_MARKETS = ADDITIONAL_MARKETS_BY_SPORT[Sport.FOOTBALL]

#: Credits of daily headroom required before the optional markets are attempted.
#: Below it the core prices are kept and the extras are skipped: an incomplete
#: market set is a normal, reportable outcome.
ADDITIONAL_MARKET_MIN_HEADROOM = 4


def core_markets_for(sport: Sport) -> tuple[str, ...]:
    """Grouped markets to request for one sport. Never a global default."""
    return CORE_MARKETS_BY_SPORT.get(sport, ())


def additional_markets_for(sport: Sport) -> tuple[str, ...]:
    """Per-event markets to attempt for one sport, budget permitting."""
    return ADDITIONAL_MARKETS_BY_SPORT.get(sport, ())


class TheOddsApiProvider:
    """Odds provider backed by The Odds API v4."""

    name = PROVIDER_NAME

    def __init__(
        self,
        settings: Settings,
        client: TheOddsApiClient | None = None,
        *,
        now: datetime | None = None,
    ) -> None:
        self._settings = settings
        self._now = now or utc_now()
        self._bookmakers = settings.bookmaker_list
        self.bookmaker = self._bookmakers[0] if self._bookmakers else "unknown"
        self._budget = ProviderBudgetLedger(settings)
        self._client = client or TheOddsApiClient(
            api_key=settings.resolved_the_odds_api_key,
            base_url=settings.the_odds_api_base_url,
            timeout=settings.provider_timeout_seconds,
            max_retries=settings.provider_max_retries,
            budget_per_scan=settings.provider_budget_per_scan,
            budget_ledger=self._budget,
            provider_name=PROVIDER_NAME,
            now=self._now,
        )
        # An injected client (tests, or a caller wiring its own transport) still
        # gets the durable ceiling: the budget is a property of the deployment,
        # not of who constructed the HTTP layer.
        if getattr(self._client, "_ledger", None) is None:
            self._client._ledger = self._budget
            self._client._provider_name = PROVIDER_NAME
            self._client._now = self._now
        self._last_quota = QuotaInfo()
        self._coverage = CollectionStatus.OK

    # -- health -------------------------------------------------------------
    def health(self) -> ProviderStatus:
        configured = bool(self._settings.resolved_the_odds_api_key)
        return ProviderStatus(
            name=self.name,
            kind="odds",
            health=ProviderHealth.OK if configured else ProviderHealth.NOT_CONFIGURED,
            detail=(
                "The Odds API v4 — statut IMPLEMENTED_UNVERIFIED : aucun appel réel "
                f"n'a encore validé la couverture de {', '.join(self._bookmakers)}."
                if configured
                else "BETMAXXING_THE_ODDS_API_KEY absent."
            ),
            quota_remaining=self._last_quota.remaining,
            quota_used=self._last_quota.used,
            last_request_cost=self._last_quota.last_cost,
        )

    # -- collection ---------------------------------------------------------
    def collect(self, sports: list[Sport], window: tuple[datetime, datetime]) -> CollectionBatch:
        """Fetch pre-match odds for the configured bookmakers inside the window.

        The collection instant is pinned at construction so one scan sees a
        single coherent "now" — the same reason the demo provider does it.
        """
        received_at = self._now
        batch = CollectionBatch(
            provider=self.name,
            collected_at=received_at,
            bookmakers=list(self._bookmakers),
        )
        wanted = set(sports)
        regions = len([r for r in self._settings.the_odds_api_regions.split(",") if r.strip()])

        keys = self._sport_keys_to_poll(wanted, batch)

        attempted = 0
        failed = 0
        any_event_seen = False
        any_bookmaker_seen = False

        for sport_key in keys:
            sport = classify_sport(sport_key)
            if sport is None:
                continue
            markets = core_markets_for(sport)
            if not markets:
                batch.partial_errors.append(
                    f"{sport_key} : aucun marché autorisé pour {sport} — non interrogé."
                )
                continue
            attempted += 1
            try:
                cost = estimate_cost(markets=len(markets), regions=regions)
                response = self._client.get(
                    f"sports/{sport_key}/odds",
                    params={
                        "regions": self._settings.the_odds_api_regions,
                        "markets": ",".join(markets),
                        "oddsFormat": "decimal",
                        "dateFormat": "iso",
                        "bookmakers": ",".join(self._bookmakers),
                        "commenceTimeFrom": _iso_z(window[0]),
                        "commenceTimeTo": _iso_z(window[1]),
                    },
                    cost=cost,
                )
            except BudgetExceeded as exc:
                failed += 1
                batch.partial_errors.append(f"{sport_key}: {exc}")
                continue
            except TheOddsApiAuthError:
                raise
            except ProviderError as exc:
                # Partial failure on one sport must not discard the others.
                failed += 1
                batch.partial_errors.append(f"{sport_key}: {redact(str(exc))}")
                continue

            self._last_quota = response.quota
            batch.quota = response.quota

            for raw_event in response.payload or []:
                any_event_seen = True
                seen = self._ingest_event(raw_event, sport, window, received_at, batch)
                any_bookmaker_seen = any_bookmaker_seen or seen
                if seen and additional_markets_for(sport):
                    self._collect_additional_markets(
                        sport_key, raw_event, sport, window, received_at, batch, regions
                    )

        batch.coverage = self._classify_coverage(
            attempted=attempted,
            failed=failed,
            any_event_seen=any_event_seen,
            any_bookmaker_seen=any_bookmaker_seen,
            batch=batch,
        )
        self._coverage = batch.coverage
        return batch

    # -- taxonomy -----------------------------------------------------------
    def _classify_coverage(
        self,
        *,
        attempted: int,
        failed: int,
        any_event_seen: bool,
        any_bookmaker_seen: bool,
        batch: CollectionBatch,
    ) -> CollectionStatus:
        """Say precisely what happened. These are six different situations.

        The previous version collapsed the first four into ``COVERAGE_MISSING``,
        so "every league returned 500" was reported as "Winamax was not in the
        response" — a fault presented as a normal absence.
        """
        if attempted and failed == attempted:
            return CollectionStatus.PROVIDER_ERROR
        if batch.snapshots:
            return CollectionStatus.OK
        if any_bookmaker_seen:
            # The bookmaker was quoted, but nothing survived mapping.
            return CollectionStatus.NO_CANDIDATE
        if any_event_seen:
            # Events exist in the window; our bookmaker is simply not among them.
            return CollectionStatus.COVERAGE_MISSING
        # A valid, empty response: nothing is playing in the window.
        return CollectionStatus.NO_CANDIDATE

    # -- discovery ----------------------------------------------------------
    def _sport_keys_to_poll(self, wanted: set[Sport], batch: CollectionBatch) -> list[str]:
        """Intersect the configured allowlist with the sports actually active.

        Polling an out-of-season key costs a credit and returns nothing, so the
        allowlist alone is not a plan. Discovery failing is not fatal: we fall
        back to the allowlist and say so.
        """
        allowlist = [
            key
            for key in self._settings.the_odds_api_sport_key_list
            if (sport := classify_sport(key)) is not None and sport in wanted
        ]
        if not allowlist:
            return []

        try:
            response = self._client.get("sports", params={"all": "false"}, cost=0, billable=False)
        except TheOddsApiAuthError:
            raise
        except ProviderError as exc:
            batch.partial_errors.append(
                f"découverte /sports indisponible ({redact(str(exc))}) — "
                "l'allowlist configurée est utilisée telle quelle."
            )
            return allowlist

        payload = response.payload
        if not isinstance(payload, list):
            batch.partial_errors.append(
                "découverte /sports : réponse inattendue — l'allowlist configurée "
                "est utilisée telle quelle."
            )
            return allowlist

        descriptors = [e for e in payload if isinstance(e, dict) and "key" in e]
        if payload and not descriptors:
            # A non-empty response that is not a sports listing is a *failed*
            # discovery, not "nothing is in season". Treating it as the latter
            # would silently cancel the whole collection.
            batch.partial_errors.append(
                "découverte /sports : réponse non reconnue comme un catalogue de "
                "compétitions — l'allowlist configurée est utilisée telle quelle."
            )
            return allowlist

        active = {str(e["key"]) for e in descriptors if e.get("active", True)}
        if not active:
            batch.partial_errors.append("découverte /sports : aucune compétition active retournée.")
            return []

        selected = [key for key in allowlist if key in active]
        for key in allowlist:
            if key not in active:
                batch.partial_errors.append(f"{key} : compétition inactive, non interrogée.")
        return selected

    # -- additional markets -------------------------------------------------
    def _collect_additional_markets(
        self,
        sport_key: str,
        raw_event: dict[str, Any],
        sport: Sport,
        window: tuple[datetime, datetime],
        received_at: datetime,
        batch: CollectionBatch,
        regions: int,
    ) -> None:
        """Fetch the optional markets for one event, if the budget allows.

        These live on the per-event endpoint, so each one is a separate request.
        They are genuinely optional: a refusal here leaves the core prices in
        place and is reported, never silently swallowed.
        """
        event_id = str(raw_event.get("id") or "")
        extra = additional_markets_for(sport)
        if not event_id or not extra:
            return
        remaining = self._budget.remaining_today(self.name, self._now)
        if remaining is not None and remaining < ADDITIONAL_MARKET_MIN_HEADROOM:
            batch.partial_errors.append(
                f"{event_id} : marchés additionnels ignorés, budget journalier "
                f"restant insuffisant ({remaining})."
            )
            return

        try:
            response = self._client.get(
                f"sports/{sport_key}/events/{event_id}/odds",
                params={
                    "regions": self._settings.the_odds_api_regions,
                    "markets": ",".join(extra),
                    "oddsFormat": "decimal",
                    "dateFormat": "iso",
                    "bookmakers": ",".join(self._bookmakers),
                },
                cost=estimate_cost(markets=len(extra), regions=regions),
            )
        except BudgetExceeded as exc:
            batch.partial_errors.append(f"{event_id} : marchés additionnels ignorés — {exc}")
            return
        except TheOddsApiAuthError:
            raise
        except ProviderError as exc:
            batch.partial_errors.append(
                f"{event_id} : marchés additionnels indisponibles ({redact(str(exc))})."
            )
            return

        self._last_quota = response.quota
        batch.quota = response.quota
        payload = response.payload
        if isinstance(payload, list):
            payload = payload[0] if payload else None
        if not isinstance(payload, dict):
            return
        self._ingest_event(payload, sport, window, received_at, batch)

    def _ingest_event(
        self,
        raw_event: dict[str, Any],
        sport: Sport,
        window: tuple[datetime, datetime],
        received_at: datetime,
        batch: CollectionBatch,
    ) -> bool:
        """Map one event. Returns whether a configured bookmaker appeared."""
        try:
            event_id = str(raw_event["id"])
            home = str(raw_event["home_team"])
            away = str(raw_event["away_team"])
            start = parse_iso(str(raw_event["commence_time"]), "commence_time")
        except (KeyError, MappingRejected) as exc:
            batch.partial_errors.append(f"événement ignoré : {exc}")
            return False

        # Never price something already under way, whatever the API returns.
        if start <= received_at:
            return False
        if not (window[0] < start <= window[1]):
            return False

        event = CanonicalEvent(
            internal_id=f"{PROVIDER_NAME}:{event_id}",
            sport=sport,
            competition=str(raw_event.get("sport_title") or raw_event.get("sport_key") or ""),
            home=Participant(canonical_id=participant_id(str(sport), home), name=home),
            away=Participant(canonical_id=participant_id(str(sport), away), name=away),
            start_time_utc=start,
            status=EventStatus.SCHEDULED,
            source_ids={PROVIDER_NAME: event_id},
        )

        bookmakers = raw_event.get("bookmakers") or []
        matched = False
        snapshots: list[OddsSnapshot] = []
        for book in bookmakers:
            key = str(book.get("key", ""))
            if self._bookmakers and key not in self._bookmakers:
                continue
            matched = True
            try:
                last_update = parse_iso(str(book["last_update"]), "last_update")
            except (KeyError, MappingRejected) as exc:
                batch.partial_errors.append(f"{key}: {exc}")
                continue

            for market_block in book.get("markets") or []:
                market_key = str(market_block.get("key", ""))
                try:
                    mapped = map_market(
                        provider_market_key=market_key,
                        sport=sport,
                        outcomes=list(market_block.get("outcomes") or []),
                        home_team=home,
                        away_team=away,
                    )
                except MappingRejected as exc:
                    batch.partial_errors.append(f"{key}/{market_key}: {exc}")
                    continue

                for item in mapped:
                    snapshots.append(
                        OddsSnapshot(
                            provider=PROVIDER_NAME,
                            bookmaker=key,
                            event_internal_id=event.internal_id,
                            event_source_id=event_id,
                            selection=item.selection,
                            decimal_odds=item.decimal_odds,
                            currency="EUR",
                            event_status=EventStatus.SCHEDULED,
                            # Distinct on purpose: the bookmaker's own update
                            # time is when the price was true; received_at is
                            # when we saw it.
                            provider_updated_at=last_update,
                            observed_at=last_update,
                            received_at=received_at,
                            source_meta={
                                "sport_key": str(raw_event.get("sport_key", "")),
                                "market": market_key,
                            },
                        )
                    )

        if snapshots:
            # The additional-markets pass revisits the same event, so the batch
            # must not accumulate duplicates of it.
            if all(existing.internal_id != event.internal_id for existing in batch.events):
                batch.events.append(event)
            known = {s.fingerprint for s in batch.snapshots}
            batch.snapshots.extend(s for s in snapshots if s.fingerprint not in known)
        return matched

    # -- legacy listing API -------------------------------------------------
    def list_events(
        self, sports: list[Sport], window: tuple[datetime, datetime]
    ) -> list[CanonicalEvent]:
        return self.collect(sports, window).events

    def fetch_odds(self, events: list[CanonicalEvent]) -> list[OddsSnapshot]:
        if not events:
            return []
        window = (self._now, max(e.start_time_utc for e in events))
        wanted = {e.internal_id for e in events}
        return [
            s
            for s in self.collect([Sport.FOOTBALL, Sport.TENNIS], window).snapshots
            if s.event_internal_id in wanted
        ]

    @property
    def coverage(self) -> CollectionStatus:
        return self._coverage


def _iso_z(moment: datetime) -> str:
    """The API expects ``YYYY-MM-DDTHH:MM:SSZ`` without sub-second precision."""
    return ensure_utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")
