"""Provider spend, response taxonomy, discovery and additional markets.

No test here touches the network: every response comes from an
``httpx.MockTransport``. What is being pinned is what the adapter *asks for* and
what it *concludes*, both of which the audit found overstated:

* the budget lived in a per-client integer, so a retry after a failed attempt
  spent again from zero and two workers each had their own private allowance —
  the configured daily ceiling was never enforced anywhere;
* every league failing produced ``COVERAGE_MISSING``, i.e. "the bookmaker was
  not there", when in fact nothing had been observed at all;
* five additional markets were mapped in ``MARKET_MAP`` and never requested, so
  a passing ``map_market()`` test proved nothing about collection;
* ``/sports`` discovery did not exist, so an out-of-season key was still polled.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import CollectionStatus, MarketType, Period, Sport
from betmaxxing.providers.the_odds_api import TheOddsApiProvider

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
WINDOW = (NOW, NOW + timedelta(hours=24))
SPORTS = [Sport.FOOTBALL, Sport.TENNIS]
SECRET = "abcdef0123456789abcdef0123456789"

QUOTA_HEADERS = {
    "x-requests-remaining": "487",
    "x-requests-used": "13",
    "x-requests-last": "2",
}

FOOTBALL_KEY = "soccer_france_ligue_one"
TENNIS_KEY = "tennis_atp_aus_open_singles"


def budget_settings(db_settings: Settings, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "mode": RunMode.PAPER,
        "database_url": db_settings.database_url,
        "odds_provider": "the_odds_api",
        "the_odds_api_key": SECRET,
        "bookmakers": "winamax_fr",
        "the_odds_api_regions": "eu",
        "the_odds_api_sport_keys": f"{FOOTBALL_KEY},{TENNIS_KEY}",
        "provider_budget_per_scan": 50,
        "provider_budget_per_day": 60,
        "provider_max_retries": 2,
        "notifications_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Fixture payloads
# ---------------------------------------------------------------------------
def football_event(*, markets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": "evt-fb-1",
        "sport_key": FOOTBALL_KEY,
        "sport_title": "Ligue 1",
        "commence_time": (NOW + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": "Olympique Lyonnais",
        "away_team": "Stade Rennais",
        "bookmakers": [
            {
                "key": "winamax_fr",
                "title": "Winamax",
                "last_update": (NOW - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "markets": markets
                if markets is not None
                else [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Olympique Lyonnais", "price": 1.63},
                            {"name": "Stade Rennais", "price": 5.00},
                            {"name": "Draw", "price": 4.20},
                        ],
                    }
                ],
            }
        ],
    }


ADDITIONAL_MARKET_BLOCKS = [
    {
        "key": "draw_no_bet",
        "outcomes": [
            {"name": "Olympique Lyonnais", "price": 1.30},
            {"name": "Stade Rennais", "price": 3.40},
        ],
    },
    {
        "key": "double_chance",
        "outcomes": [
            {"name": "Olympique Lyonnais or Draw", "price": 1.15},
            {"name": "Draw or Stade Rennais", "price": 1.55},
            {"name": "Olympique Lyonnais or Stade Rennais", "price": 1.28},
        ],
    },
    {
        "key": "h2h_3_way_h1",
        "outcomes": [
            {"name": "Olympique Lyonnais", "price": 2.30},
            {"name": "Stade Rennais", "price": 6.50},
            {"name": "Draw", "price": 2.05},
        ],
    },
    {
        "key": "totals_h1",
        "outcomes": [
            {"name": "Over", "price": 2.40, "point": 1.5},
            {"name": "Under", "price": 1.55, "point": 1.5},
        ],
    },
]

SPORTS_PAYLOAD = [
    {"key": FOOTBALL_KEY, "group": "Soccer", "title": "Ligue 1", "active": True},
    {"key": TENNIS_KEY, "group": "Tennis", "title": "ATP", "active": False},
    {"key": "soccer_epl", "group": "Soccer", "title": "EPL", "active": True},
]


class RecordingTransport:
    """Records every request path + query, and replies from a routing table."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = urlparse(str(request.url)).path
        for suffix, reply in self.routes.items():
            if path.endswith(suffix):
                if callable(reply):
                    return reply(request)
                return httpx.Response(200, json=reply, headers=QUOTA_HEADERS)
        return httpx.Response(200, json=[], headers=QUOTA_HEADERS)

    @property
    def paths(self) -> list[str]:
        return [urlparse(str(r.url)).path for r in self.requests]

    def queries_for(self, suffix: str) -> list[dict[str, list[str]]]:
        return [
            parse_qs(urlparse(str(r.url)).query)
            for r in self.requests
            if urlparse(str(r.url)).path.endswith(suffix)
        ]

    def markets_requested(self) -> set[str]:
        out: set[str] = set()
        for request in self.requests:
            for value in parse_qs(urlparse(str(request.url)).query).get("markets", []):
                out.update(part for part in value.split(",") if part)
        return out


def make_provider(settings: Settings, transport: RecordingTransport) -> TheOddsApiProvider:
    from betmaxxing.providers.the_odds_api.client import TheOddsApiClient

    client = TheOddsApiClient(
        api_key=settings.resolved_the_odds_api_key,
        base_url=settings.the_odds_api_base_url,
        transport=httpx.MockTransport(transport.handler),
        sleep=lambda _s: None,
        budget_per_scan=settings.provider_budget_per_scan,
        max_retries=settings.provider_max_retries,
    )
    return TheOddsApiProvider(settings, client=client, now=NOW)


# ---------------------------------------------------------------------------
# 1. Budget: retries, per-scan and per-day
# ---------------------------------------------------------------------------
class TestBudget:
    def test_a_retry_never_spends_beyond_the_scan_budget(self, db_settings: Settings) -> None:
        """Each attempt costs credits; three attempts of a 2-credit call is 6."""
        settings = budget_settings(db_settings, provider_budget_per_scan=3, provider_max_retries=5)
        calls = {"n": 0}

        def flaky(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503, json={}, headers=QUOTA_HEADERS)

        transport = RecordingTransport({"/odds": flaky, "/sports": SPORTS_PAYLOAD})
        provider = make_provider(settings, transport)
        provider.collect(SPORTS, WINDOW)

        odds_calls = len([p for p in transport.paths if p.endswith("/odds")])
        assert odds_calls <= 2, (
            f"{odds_calls} attempts were made against a 3-credit budget at 2 credits each"
        )

    def test_two_scans_cannot_exceed_the_daily_budget(self, db_settings: Settings) -> None:
        """A per-client counter resets with the client; the ceiling must not."""
        settings = budget_settings(
            db_settings, provider_budget_per_scan=50, provider_budget_per_day=3
        )
        transport = RecordingTransport({"/odds": [football_event()], "/sports": SPORTS_PAYLOAD})

        make_provider(settings, transport).collect(SPORTS, WINDOW)
        make_provider(settings, transport).collect(SPORTS, WINDOW)

        spent = 2 * len([p for p in transport.paths if p.endswith("/odds")])
        assert spent <= 3, f"{spent} credits were spent against a daily ceiling of 3"

    def test_the_daily_ledger_records_reservation_and_observed_cost(
        self, db_settings: Settings
    ) -> None:
        from betmaxxing.providers.budget import ProviderBudgetLedger

        settings = budget_settings(db_settings)
        transport = RecordingTransport({"/odds": [football_event()], "/sports": SPORTS_PAYLOAD})
        make_provider(settings, transport).collect(SPORTS, WINDOW)

        entries = ProviderBudgetLedger(settings).entries_for_day(NOW)
        assert entries, "no reservation was recorded"
        assert all(entry.reserved_cost > 0 for entry in entries)
        # x-requests-last says 2; the reservation must be reconciled against it.
        assert any(entry.observed_cost == 2 for entry in entries)

    def test_a_transport_error_releases_its_reservation(self, db_settings: Settings) -> None:
        from betmaxxing.providers.budget import ProviderBudgetLedger

        settings = budget_settings(db_settings, provider_max_retries=0)

        def dead(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns failure", request=request)

        transport = RecordingTransport({"/odds": dead, "/sports": SPORTS_PAYLOAD})
        make_provider(settings, transport).collect(SPORTS, WINDOW)

        ledger = ProviderBudgetLedger(settings)
        released = [e for e in ledger.entries_for_day(NOW) if e.request.endswith("/odds")]
        assert released, "the attempt was not recorded at all"
        assert all(entry.observed_cost == 0 for entry in released)
        assert all(entry.released for entry in released)

    def test_no_key_appears_in_a_budget_refusal(self, db_settings: Settings) -> None:
        settings = budget_settings(db_settings, provider_budget_per_scan=0)
        transport = RecordingTransport({"/odds": [football_event()], "/sports": SPORTS_PAYLOAD})
        batch = make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert SECRET not in json.dumps(batch.partial_errors)


# ---------------------------------------------------------------------------
# 2. Response taxonomy
# ---------------------------------------------------------------------------
class TestResponseTaxonomy:
    def test_every_league_failing_is_a_provider_error(self, db_settings: Settings) -> None:
        settings = budget_settings(db_settings, provider_max_retries=0)
        transport = RecordingTransport(
            {
                "/odds": lambda r: httpx.Response(500, json={}, headers=QUOTA_HEADERS),
                "/sports": SPORTS_PAYLOAD,
            }
        )
        batch = make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert batch.coverage is CollectionStatus.PROVIDER_ERROR, (
            "a total collection failure was reported as missing bookmaker coverage"
        )

    def test_an_empty_but_valid_response_is_not_a_failure(self, db_settings: Settings) -> None:
        settings = budget_settings(db_settings)
        transport = RecordingTransport({"/odds": [], "/sports": SPORTS_PAYLOAD})
        batch = make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert batch.coverage is CollectionStatus.NO_CANDIDATE
        assert batch.events == []

    def test_events_without_the_configured_bookmaker_are_coverage_missing(
        self, db_settings: Settings
    ) -> None:
        settings = budget_settings(db_settings)
        payload = football_event()
        payload["bookmakers"][0]["key"] = "someone_else"
        transport = RecordingTransport({"/odds": [payload], "/sports": SPORTS_PAYLOAD})
        batch = make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert batch.coverage is CollectionStatus.COVERAGE_MISSING

    def test_an_empty_response_and_a_missing_bookmaker_are_distinguishable(
        self, db_settings: Settings
    ) -> None:
        settings = budget_settings(db_settings)
        empty = make_provider(
            settings, RecordingTransport({"/odds": [], "/sports": SPORTS_PAYLOAD})
        ).collect(SPORTS, WINDOW)

        payload = football_event()
        payload["bookmakers"][0]["key"] = "someone_else"
        uncovered = make_provider(
            settings, RecordingTransport({"/odds": [payload], "/sports": SPORTS_PAYLOAD})
        ).collect(SPORTS, WINDOW)

        assert empty.coverage is not uncovered.coverage

    def test_a_partial_failure_keeps_the_leagues_that_worked(self, db_settings: Settings) -> None:
        settings = budget_settings(
            db_settings,
            the_odds_api_sport_keys=f"{FOOTBALL_KEY},soccer_epl",
            provider_max_retries=0,
        )

        def route(request: httpx.Request) -> httpx.Response:
            if "soccer_epl" in str(request.url):
                return httpx.Response(500, json={}, headers=QUOTA_HEADERS)
            return httpx.Response(200, json=[football_event()], headers=QUOTA_HEADERS)

        transport = RecordingTransport({"/odds": route, "/sports": SPORTS_PAYLOAD})
        batch = make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert batch.snapshots
        assert batch.partial_errors
        assert batch.coverage is CollectionStatus.OK


# ---------------------------------------------------------------------------
# 3. Sport discovery
# ---------------------------------------------------------------------------
class TestSportDiscovery:
    def test_the_active_sports_endpoint_is_consulted(self, db_settings: Settings) -> None:
        settings = budget_settings(db_settings)
        transport = RecordingTransport({"/odds": [football_event()], "/sports": SPORTS_PAYLOAD})
        make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert any(p.endswith("/sports") for p in transport.paths), "/sports was never called"

    def test_an_inactive_sport_is_not_polled(self, db_settings: Settings) -> None:
        settings = budget_settings(db_settings)
        transport = RecordingTransport({"/odds": [football_event()], "/sports": SPORTS_PAYLOAD})
        make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert not any(TENNIS_KEY in p for p in transport.paths)

    def test_an_active_sport_outside_the_allowlist_is_not_polled(
        self, db_settings: Settings
    ) -> None:
        settings = budget_settings(db_settings)
        transport = RecordingTransport({"/odds": [football_event()], "/sports": SPORTS_PAYLOAD})
        make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert not any("soccer_epl" in p for p in transport.paths)


# ---------------------------------------------------------------------------
# 4. Additional markets are actually requested, not merely mapped
# ---------------------------------------------------------------------------
class TestAdditionalMarketsAreCollected:
    def _run(self, settings: Settings) -> tuple[RecordingTransport, Any]:
        def route(request: httpx.Request) -> httpx.Response:
            query = parse_qs(urlparse(str(request.url)).query)
            wanted = set(",".join(query.get("markets", [])).split(","))
            blocks = [b for b in ADDITIONAL_MARKET_BLOCKS if b["key"] in wanted]
            if "h2h" in wanted:
                blocks = [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Olympique Lyonnais", "price": 1.63},
                            {"name": "Stade Rennais", "price": 5.00},
                            {"name": "Draw", "price": 4.20},
                        ],
                    },
                    *blocks,
                ]
            payload = football_event(markets=blocks)
            if "/events/" in str(request.url):
                return httpx.Response(200, json=payload, headers=QUOTA_HEADERS)
            return httpx.Response(200, json=[payload], headers=QUOTA_HEADERS)

        transport = RecordingTransport({"/odds": route, "/sports": SPORTS_PAYLOAD})
        batch = make_provider(settings, transport).collect(SPORTS, WINDOW)
        return transport, batch

    @pytest.mark.parametrize(
        "market_key", ["draw_no_bet", "double_chance", "h2h_3_way_h1", "totals_h1"]
    )
    def test_the_market_is_present_in_a_real_request(
        self, db_settings: Settings, market_key: str
    ) -> None:
        transport, _ = self._run(budget_settings(db_settings))
        assert market_key in transport.markets_requested(), (
            f"{market_key} is mapped but never requested — mapping is not collection"
        )

    def test_draw_no_bet_snapshots_are_produced(self, db_settings: Settings) -> None:
        _, batch = self._run(budget_settings(db_settings))
        assert any(s.selection.market is MarketType.DRAW_NO_BET for s in batch.snapshots)

    def test_double_chance_snapshots_are_produced(self, db_settings: Settings) -> None:
        _, batch = self._run(budget_settings(db_settings))
        assert any(s.selection.market is MarketType.DOUBLE_CHANCE for s in batch.snapshots)

    def test_first_half_snapshots_are_produced(self, db_settings: Settings) -> None:
        _, batch = self._run(budget_settings(db_settings))
        assert any(s.selection.period is Period.FIRST_HALF for s in batch.snapshots)

    def test_additional_markets_are_skipped_when_the_budget_is_tight(
        self, db_settings: Settings
    ) -> None:
        """Extra markets are optional; the core call is not."""
        transport, _ = self._run(budget_settings(db_settings, provider_budget_per_scan=2))
        assert any(p.endswith("/odds") for p in transport.paths)
        assert "draw_no_bet" not in transport.markets_requested()


# ---------------------------------------------------------------------------
# 5. Historical: interface and offline estimator only
# ---------------------------------------------------------------------------
class TestHistoricalIsEstimatedNotFetched:
    def _request(self, **overrides: Any) -> Any:
        from betmaxxing.providers.the_odds_api.historical import HistoricalOddsRequest

        base: dict[str, Any] = {
            "sport_keys": (FOOTBALL_KEY,),
            "markets": ("h2h", "totals"),
            "regions": ("eu",),
            "bookmakers": ("winamax_fr",),
            "start": NOW - timedelta(days=1),
            "end": NOW,
            "snapshot_interval": timedelta(hours=1),
        }
        base.update(overrides)
        return HistoricalOddsRequest(**base)

    def test_the_estimate_is_an_upper_bound_and_makes_no_call(self) -> None:
        from betmaxxing.providers.the_odds_api.historical import estimate_historical_cost

        estimate = estimate_historical_cost(self._request())
        assert estimate.snapshots == 25
        assert estimate.credits_upper_bound > 0
        assert "BORNE SUPÉRIEURE" in estimate.render()

    def test_a_finer_interval_costs_more(self) -> None:
        from betmaxxing.providers.the_odds_api.historical import estimate_historical_cost

        hourly = estimate_historical_cost(self._request())
        fine = estimate_historical_cost(self._request(snapshot_interval=timedelta(minutes=15)))
        assert fine.credits_upper_bound > hourly.credits_upper_bound

    def test_an_unsupported_interval_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"intervalle"):
            self._request(snapshot_interval=timedelta(minutes=1))

    def test_downloading_is_not_implemented(self) -> None:
        from betmaxxing.providers.the_odds_api.historical import (
            HistoricalNotEnabled,
            fetch_historical,
        )

        with pytest.raises(HistoricalNotEnabled):
            fetch_historical(self._request())

    def test_consent_defaults_to_absent(self) -> None:
        assert self._request().acknowledged_cost is False


class TestDiscoveryFailureIsNotSilentCancellation:
    def test_an_unrecognisable_response_falls_back_to_the_allowlist(
        self, db_settings: Settings
    ) -> None:
        """A malformed catalogue must not read as "nothing is in season"."""
        settings = budget_settings(db_settings)
        transport = RecordingTransport(
            {"/odds": [football_event()], "/sports": [{"unexpected": True}]}
        )
        batch = make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert any("/odds" in p for p in transport.paths)
        assert batch.snapshots
        assert any("allowlist" in e for e in batch.partial_errors)

    def test_a_genuinely_empty_catalogue_polls_nothing(self, db_settings: Settings) -> None:
        settings = budget_settings(db_settings)
        transport = RecordingTransport({"/odds": [football_event()], "/sports": []})
        batch = make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert not any(p.endswith("/odds") for p in transport.paths)
        assert batch.snapshots == []

    def test_a_failed_discovery_call_falls_back_to_the_allowlist(
        self, db_settings: Settings
    ) -> None:
        settings = budget_settings(db_settings, provider_max_retries=0)
        transport = RecordingTransport(
            {
                "/odds": [football_event()],
                "/sports": lambda r: httpx.Response(500, json={}, headers=QUOTA_HEADERS),
            }
        )
        batch = make_provider(settings, transport).collect(SPORTS, WINDOW)
        assert batch.snapshots
        assert any("découverte /sports" in e for e in batch.partial_errors)
