"""Which markets are requested, per sport.

Two defects this pins:

* ``CORE_MARKETS = ("h2h", "totals")`` was used for **every** sport. Tennis
  ``totals`` is documented as disabled until the games-versus-sets semantics is
  confirmed — and it was being requested and billed anyway. Paying for a market
  we then refuse to map is the worst of both worlds.
* ``double_chance_h1`` was listed among the additional markets and no fixture
  ever exercised it, so "requested, mapped and persisted" was true of four
  markets out of five while being claimed for all of them.

Every response here comes from an ``httpx.MockTransport``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import MarketType, Period, Sport
from betmaxxing.providers.the_odds_api import TheOddsApiProvider

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
WINDOW = (NOW, NOW + timedelta(hours=24))
SPORTS = [Sport.FOOTBALL, Sport.TENNIS]
SECRET = "abcdef0123456789abcdef0123456789"

FOOTBALL_KEY = "soccer_france_ligue_one"
TENNIS_KEY = "tennis_atp_aus_open_singles"

QUOTA_HEADERS = {
    "x-requests-remaining": "487",
    "x-requests-used": "13",
    "x-requests-last": "2",
}

HOME = "Olympique Lyonnais"
AWAY = "Stade Rennais"

#: Both sports active, so the tennis request is genuinely attempted.
SPORTS_PAYLOAD = [
    {"key": FOOTBALL_KEY, "group": "Soccer", "title": "Ligue 1", "active": True},
    {"key": TENNIS_KEY, "group": "Tennis", "title": "ATP", "active": True},
]

MARKET_BLOCKS: dict[str, dict[str, Any]] = {
    "h2h": {
        "key": "h2h",
        "outcomes": [
            {"name": HOME, "price": 1.63},
            {"name": AWAY, "price": 5.00},
            {"name": "Draw", "price": 4.20},
        ],
    },
    "totals": {
        "key": "totals",
        "outcomes": [
            {"name": "Over", "price": 1.86, "point": 2.5},
            {"name": "Under", "price": 1.98, "point": 2.5},
        ],
    },
    "draw_no_bet": {
        "key": "draw_no_bet",
        "outcomes": [{"name": HOME, "price": 1.30}, {"name": AWAY, "price": 3.40}],
    },
    "double_chance": {
        "key": "double_chance",
        "outcomes": [
            {"name": f"{HOME} or Draw", "price": 1.15},
            {"name": f"Draw or {AWAY}", "price": 1.55},
            {"name": f"{HOME} or {AWAY}", "price": 1.28},
        ],
    },
    "h2h_3_way_h1": {
        "key": "h2h_3_way_h1",
        "outcomes": [
            {"name": HOME, "price": 2.30},
            {"name": AWAY, "price": 6.50},
            {"name": "Draw", "price": 2.05},
        ],
    },
    "totals_h1": {
        "key": "totals_h1",
        "outcomes": [
            {"name": "Over", "price": 2.40, "point": 1.5},
            {"name": "Under", "price": 1.55, "point": 1.5},
        ],
    },
    "double_chance_h1": {
        "key": "double_chance_h1",
        "outcomes": [
            {"name": f"{HOME} or Draw", "price": 1.32},
            {"name": f"Draw or {AWAY}", "price": 1.18},
            {"name": f"{HOME} or {AWAY}", "price": 1.95},
        ],
    },
}

TENNIS_BLOCKS: dict[str, dict[str, Any]] = {
    "h2h": {
        "key": "h2h",
        "outcomes": [
            {"name": "Alejandro Tabilo", "price": 1.76},
            {"name": "Rafael Jodar", "price": 2.07},
        ],
    },
    "totals": {
        "key": "totals",
        "outcomes": [
            {"name": "Over", "price": 1.90, "point": 22.5},
            {"name": "Under", "price": 1.90, "point": 22.5},
        ],
    },
}


def market_settings(db_settings: Settings, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "mode": RunMode.PAPER,
        "database_url": db_settings.database_url,
        "odds_provider": "the_odds_api",
        "the_odds_api_key": SECRET,
        "bookmakers": "winamax_fr",
        "the_odds_api_regions": "eu",
        "the_odds_api_sport_keys": f"{FOOTBALL_KEY},{TENNIS_KEY}",
        "provider_budget_per_scan": 200,
        "provider_budget_per_day": 400,
        "notifications_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


class Recorder:
    """Serves per-market payloads and records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        path = urlparse(url).path
        wanted = self.markets_of(request)

        if path.endswith("/sports"):
            return httpx.Response(200, json=SPORTS_PAYLOAD, headers=QUOTA_HEADERS)

        # v4 puts `last_update` on the bookmaker for `/odds` and on each market
        # for `/events/{id}/odds`. Serving one shape for both endpoints made
        # these fixtures agree with the parser instead of with the API.
        per_event = "/events/" in path

        if TENNIS_KEY in path:
            blocks = [TENNIS_BLOCKS[k] for k in wanted if k in TENNIS_BLOCKS]
            payload = self._event(
                "evt-tn-1",
                TENNIS_KEY,
                "Alejandro Tabilo",
                "Rafael Jodar",
                blocks,
                per_event=per_event,
            )
        else:
            blocks = [MARKET_BLOCKS[k] for k in wanted if k in MARKET_BLOCKS]
            payload = self._event("evt-fb-1", FOOTBALL_KEY, HOME, AWAY, blocks, per_event=per_event)

        if per_event:
            return httpx.Response(200, json=payload, headers=QUOTA_HEADERS)
        return httpx.Response(200, json=[payload], headers=QUOTA_HEADERS)

    @staticmethod
    def markets_of(request: httpx.Request) -> list[str]:
        query = parse_qs(urlparse(str(request.url)).query)
        return [m for value in query.get("markets", []) for m in value.split(",") if m]

    @staticmethod
    def _event(
        event_id: str,
        sport_key: str,
        home: str,
        away: str,
        blocks: list[dict[str, Any]],
        *,
        per_event: bool,
    ) -> dict[str, Any]:
        stamp = (NOW - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        book: dict[str, Any] = {"key": "winamax_fr", "title": "Winamax"}
        if per_event:
            book["markets"] = [{**block, "last_update": stamp} for block in blocks]
        else:
            book["last_update"] = stamp
            book["markets"] = blocks
        return {
            "id": event_id,
            "sport_key": sport_key,
            "sport_title": sport_key,
            "commence_time": (NOW + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "home_team": home,
            "away_team": away,
            "bookmakers": [book],
        }

    # -- inspection ---------------------------------------------------------
    def markets_for_path(self, fragment: str) -> set[str]:
        out: set[str] = set()
        for request in self.requests:
            if fragment in urlparse(str(request.url)).path:
                out.update(self.markets_of(request))
        return out

    @property
    def paths(self) -> list[str]:
        return [urlparse(str(r.url)).path for r in self.requests]


@pytest.fixture
def collected(db_settings: Settings) -> tuple[Recorder, Any]:
    settings = market_settings(db_settings)
    recorder = Recorder()
    from betmaxxing.providers.the_odds_api.client import TheOddsApiClient

    client = TheOddsApiClient(
        api_key=settings.resolved_the_odds_api_key,
        base_url=settings.the_odds_api_base_url,
        transport=httpx.MockTransport(recorder.handler),
        sleep=lambda _s: None,
        budget_per_scan=settings.provider_budget_per_scan,
        max_retries=0,
    )
    provider = TheOddsApiProvider(settings, client=client, now=NOW)
    return recorder, provider.collect(SPORTS, WINDOW)


# ---------------------------------------------------------------------------
# Per-sport policy
# ---------------------------------------------------------------------------
class TestPolicyIsPerSport:
    def test_football_groups_h2h_and_totals(self) -> None:
        from betmaxxing.providers.the_odds_api.provider import core_markets_for

        assert core_markets_for(Sport.FOOTBALL) == ("h2h", "totals")

    def test_tennis_groups_h2h_only(self) -> None:
        from betmaxxing.providers.the_odds_api.provider import core_markets_for

        assert core_markets_for(Sport.TENNIS) == ("h2h",)

    def test_tennis_has_no_additional_markets(self) -> None:
        from betmaxxing.providers.the_odds_api.provider import additional_markets_for

        assert additional_markets_for(Sport.TENNIS) == ()

    def test_football_additional_markets_are_the_five_declared(self) -> None:
        from betmaxxing.providers.the_odds_api.provider import additional_markets_for

        assert set(additional_markets_for(Sport.FOOTBALL)) == {
            "draw_no_bet",
            "double_chance",
            "h2h_3_way_h1",
            "totals_h1",
            "double_chance_h1",
        }


class TestTennisTotalsIsNeitherRequestedNorBilled:
    def test_the_tennis_request_does_not_ask_for_totals(
        self, collected: tuple[Recorder, Any]
    ) -> None:
        recorder, _ = collected
        assert any(TENNIS_KEY in p for p in recorder.paths), "tennis was never polled"
        assert recorder.markets_for_path(TENNIS_KEY) == {"h2h"}, (
            "tennis `totals` is documented as disabled but was requested — and billed"
        )

    def test_no_tennis_total_games_snapshot_is_produced(
        self, collected: tuple[Recorder, Any]
    ) -> None:
        _, batch = collected
        assert not any(s.selection.market is MarketType.TOTAL_GAMES for s in batch.snapshots)

    def test_tennis_match_winner_is_still_collected(self, collected: tuple[Recorder, Any]) -> None:
        _, batch = collected
        assert any(s.selection.market is MarketType.MATCH_WINNER for s in batch.snapshots)

    def test_the_tennis_request_costs_one_market_not_two(
        self, db_settings: Settings, collected: tuple[Recorder, Any]
    ) -> None:
        from betmaxxing.providers.budget import ProviderBudgetLedger

        settings = market_settings(db_settings)
        entries = ProviderBudgetLedger(settings).entries_for_day(NOW, "the_odds_api")
        tennis = [e for e in entries if TENNIS_KEY in e.request]
        assert tennis, "the tennis request was not recorded in the budget ledger"
        assert all(e.reserved_cost == 1 for e in tennis), (
            f"tennis reserved {[e.reserved_cost for e in tennis]} credits for one market"
        )


# ---------------------------------------------------------------------------
# double_chance_h1, end to end
# ---------------------------------------------------------------------------
class TestDoubleChanceFirstHalf:
    def test_the_key_is_present_in_the_per_event_request(
        self, collected: tuple[Recorder, Any]
    ) -> None:
        recorder, _ = collected
        assert "double_chance_h1" in recorder.markets_for_path("/events/")

    def test_all_three_selections_are_mapped(self, collected: tuple[Recorder, Any]) -> None:
        _, batch = collected
        codes = {
            s.selection.code
            for s in batch.snapshots
            if s.selection.market is MarketType.DOUBLE_CHANCE
            and s.selection.period is Period.FIRST_HALF
        }
        assert codes == {"home_or_draw", "draw_or_away", "home_or_away"}

    def test_the_period_is_first_half(self, collected: tuple[Recorder, Any]) -> None:
        _, batch = collected
        first_half = [
            s
            for s in batch.snapshots
            if s.selection.market is MarketType.DOUBLE_CHANCE
            and s.selection.period is Period.FIRST_HALF
        ]
        assert first_half
        assert all(s.selection.period is Period.FIRST_HALF for s in first_half)

    def test_the_snapshots_are_persisted(self, db_settings: Settings) -> None:
        from betmaxxing.engine.acquisition import AcquisitionService
        from betmaxxing.providers.factory import ProviderBundle, build_providers
        from betmaxxing.providers.the_odds_api.client import TheOddsApiClient
        from betmaxxing.storage.db import session_scope
        from betmaxxing.storage.tables import OddsSnapshotRow

        settings = market_settings(db_settings)
        recorder = Recorder()
        client = TheOddsApiClient(
            api_key=settings.resolved_the_odds_api_key,
            base_url=settings.the_odds_api_base_url,
            transport=httpx.MockTransport(recorder.handler),
            sleep=lambda _s: None,
            budget_per_scan=settings.provider_budget_per_scan,
            max_retries=0,
        )
        demo: ProviderBundle = build_providers(
            Settings(mode=RunMode.DEMO, database_url=settings.database_url), NOW
        )
        demo.odds = TheOddsApiProvider(settings, client=client, now=NOW)

        AcquisitionService(settings).run(now=NOW, bundle=demo)

        with session_scope(settings) as session:
            rows = (
                session.query(OddsSnapshotRow)
                .filter(
                    OddsSnapshotRow.market == str(MarketType.DOUBLE_CHANCE),
                    OddsSnapshotRow.period == str(Period.FIRST_HALF),
                )
                .all()
            )
            codes = {row.selection_code for row in rows}
        assert codes == {"home_or_draw", "draw_or_away", "home_or_away"}

    def test_it_does_not_duplicate_the_core_markets(self, collected: tuple[Recorder, Any]) -> None:
        _, batch = collected
        fingerprints = [s.fingerprint for s in batch.snapshots]
        assert len(fingerprints) == len(set(fingerprints))

    def test_the_event_appears_once_in_the_batch(self, collected: tuple[Recorder, Any]) -> None:
        _, batch = collected
        ids = [e.internal_id for e in batch.events]
        assert len(ids) == len(set(ids))


class TestAllFiveAdditionalFootballMarkets:
    @pytest.mark.parametrize(
        "market_key",
        ["draw_no_bet", "double_chance", "h2h_3_way_h1", "totals_h1", "double_chance_h1"],
    )
    def test_requested(self, collected: tuple[Recorder, Any], market_key: str) -> None:
        recorder, _ = collected
        assert market_key in recorder.markets_for_path("/events/")

    @pytest.mark.parametrize(
        ("market", "period"),
        [
            (MarketType.DRAW_NO_BET, Period.FULL_TIME),
            (MarketType.DOUBLE_CHANCE, Period.FULL_TIME),
            (MarketType.MATCH_RESULT_1X2, Period.FIRST_HALF),
            (MarketType.TOTAL_GOALS, Period.FIRST_HALF),
            (MarketType.DOUBLE_CHANCE, Period.FIRST_HALF),
        ],
    )
    def test_mapped_and_present(
        self, collected: tuple[Recorder, Any], market: MarketType, period: Period
    ) -> None:
        _, batch = collected
        assert any(
            s.selection.market is market and s.selection.period is period for s in batch.snapshots
        )
