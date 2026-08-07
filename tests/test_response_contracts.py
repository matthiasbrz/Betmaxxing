"""The two v4 odds response shapes are different contracts.

Verified against <https://the-odds-api.com/liveapi/guides/v4/> on 2026-08-05:

* ``GET /v4/sports/{sport}/odds`` carries ``last_update`` **on the bookmaker**;
* ``GET /v4/sports/{sport}/events/{eventId}/odds`` carries it **on each market**,
  and the guide states plainly: *"The `last_update` field is only available on
  the market level in the response and not on the bookmaker level."*

The adapter read ``book["last_update"]`` for both. Local fixtures were green
because they were written to match the code, not the contract — so the first
real per-event response would have had every bookmaker rejected for a missing
timestamp, and the additional markets would have collected nothing.

Two markets of one bookmaker can also be refreshed at different instants. The
event endpoint says so per market; flattening them onto one instant would make a
five-minute-old price and a five-hour-old price indistinguishable, which is
exactly the staleness check's input.

No network: every payload here is a small hand-written fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import MarketType, Period, Sport

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
WINDOW = (NOW, NOW + timedelta(hours=24))
SPORTS = [Sport.FOOTBALL]
SECRET = "abcdef0123456789abcdef0123456789"
FOOTBALL_KEY = "soccer_france_ligue_one"

QUOTA_HEADERS = {
    "x-requests-remaining": "487",
    "x-requests-used": "13",
    "x-requests-last": "1",
}

HOME = "Olympique Lyonnais"
AWAY = "Stade Rennais"

#: Three distinct instants, so a flattening bug cannot hide behind equality.
BOOKMAKER_STAMP = "2026-08-04T11:50:00Z"
H2H_STAMP = "2026-08-04T11:58:00Z"
TOTALS_STAMP = "2026-08-04T11:31:00Z"


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def h2h_block(*, last_update: str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {
        "key": "h2h",
        "outcomes": [
            {"name": HOME, "price": 1.63},
            {"name": AWAY, "price": 5.00},
            {"name": "Draw", "price": 4.20},
        ],
    }
    if last_update is not None:
        block["last_update"] = last_update
    return block


def totals_block(*, last_update: str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {
        "key": "totals",
        "outcomes": [
            {"name": "Over", "price": 1.86, "point": 2.5},
            {"name": "Under", "price": 1.98, "point": 2.5},
        ],
    }
    if last_update is not None:
        block["last_update"] = last_update
    return block


def event_payload(bookmakers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "evt-fb-1",
        "sport_key": FOOTBALL_KEY,
        "sport_title": "Ligue 1",
        "commence_time": (NOW + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": HOME,
        "away_team": AWAY,
        "bookmakers": bookmakers,
    }


#: Shape 1 — grouped `/odds`: timestamp on the bookmaker, absent from markets.
GROUPED_PAYLOAD = event_payload(
    [
        {
            "key": "winamax_fr",
            "title": "Winamax (FR)",
            "last_update": BOOKMAKER_STAMP,
            "markets": [h2h_block(), totals_block()],
        }
    ]
)

#: Shape 2 — `/events/{id}/odds`: no bookmaker timestamp, one per market.
EVENT_PAYLOAD = event_payload(
    [
        {
            "key": "winamax_fr",
            "title": "Winamax (FR)",
            "markets": [
                h2h_block(last_update=H2H_STAMP),
                totals_block(last_update=TOTALS_STAMP),
            ],
        }
    ]
)

#: Shape 2, but one market has no timestamp at all.
EVENT_PAYLOAD_MISSING_STAMP = event_payload(
    [
        {
            "key": "winamax_fr",
            "title": "Winamax (FR)",
            "markets": [h2h_block(last_update=H2H_STAMP), totals_block()],
        }
    ]
)

#: Shape 2, one market's timestamp is unparseable.
EVENT_PAYLOAD_INVALID_STAMP = event_payload(
    [
        {
            "key": "winamax_fr",
            "title": "Winamax (FR)",
            "markets": [
                h2h_block(last_update=H2H_STAMP),
                totals_block(last_update="not-a-timestamp"),
            ],
        }
    ]
)

#: Shape 1, but the bookmaker timestamp is missing.
GROUPED_PAYLOAD_MISSING_STAMP = event_payload(
    [
        {
            "key": "winamax_fr",
            "title": "Winamax (FR)",
            "markets": [h2h_block(), totals_block()],
        }
    ]
)


def contract_settings(db_settings: Settings, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "mode": RunMode.PAPER,
        "database_url": db_settings.database_url,
        "odds_provider": "the_odds_api",
        "the_odds_api_key": SECRET,
        "bookmakers": "winamax_fr",
        "the_odds_api_regions": "eu",
        "the_odds_api_sport_keys": FOOTBALL_KEY,
        "provider_budget_per_scan": 200,
        "provider_budget_per_day": 400,
        "notifications_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def parse(payload: dict[str, Any], *, shape: str, settings: Settings) -> Any:
    """Parse one raw event under an explicitly named endpoint contract.

    Imported at call time: ``ResponseShape`` and the shape-aware ``_ingest_event``
    are introduced by this tranche, and a module-level import would collapse
    every test here into one collection error.
    """
    from betmaxxing.providers.base import CollectionBatch
    from betmaxxing.providers.the_odds_api.client import TheOddsApiClient
    from betmaxxing.providers.the_odds_api.provider import ResponseShape, TheOddsApiProvider

    client = TheOddsApiClient(
        api_key=settings.resolved_the_odds_api_key,
        base_url=settings.the_odds_api_base_url,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[], headers=QUOTA_HEADERS)
        ),
        sleep=lambda _s: None,
        max_retries=0,
    )
    provider = TheOddsApiProvider(settings, client=client, now=NOW)
    batch = CollectionBatch(provider="the_odds_api", collected_at=NOW, bookmakers=["winamax_fr"])
    provider._ingest_event(
        payload,
        Sport.FOOTBALL,
        WINDOW,
        NOW,
        batch,
        shape=ResponseShape.GROUPED_ODDS if shape == "grouped" else ResponseShape.EVENT_ODDS,
    )
    return batch


def stamps(batch: Any) -> dict[str, datetime]:
    return {str(s.selection.market): s.provider_updated_at for s in batch.snapshots}


# ---------------------------------------------------------------------------
# Shape 1 — grouped /odds
# ---------------------------------------------------------------------------
class TestGroupedResponse:
    def test_the_bookmaker_timestamp_is_used(self, db_settings: Settings) -> None:
        batch = parse(GROUPED_PAYLOAD, shape="grouped", settings=contract_settings(db_settings))
        assert batch.snapshots
        assert {s.provider_updated_at for s in batch.snapshots} == {instant(BOOKMAKER_STAMP)}

    def test_the_local_reception_time_stays_distinct(self, db_settings: Settings) -> None:
        batch = parse(GROUPED_PAYLOAD, shape="grouped", settings=contract_settings(db_settings))
        for snapshot in batch.snapshots:
            assert snapshot.received_at == NOW
            assert snapshot.provider_updated_at != snapshot.received_at

    def test_both_core_markets_are_mapped(self, db_settings: Settings) -> None:
        batch = parse(GROUPED_PAYLOAD, shape="grouped", settings=contract_settings(db_settings))
        assert {s.selection.market for s in batch.snapshots} == {
            MarketType.MATCH_RESULT_1X2,
            MarketType.TOTAL_GOALS,
        }

    def test_a_missing_bookmaker_timestamp_rejects_that_bookmaker(
        self, db_settings: Settings
    ) -> None:
        batch = parse(
            GROUPED_PAYLOAD_MISSING_STAMP, shape="grouped", settings=contract_settings(db_settings)
        )
        assert batch.snapshots == []
        assert batch.partial_errors
        assert any("last_update" in error for error in batch.partial_errors)

    def test_no_timestamp_is_fabricated_from_the_reception_time(
        self, db_settings: Settings
    ) -> None:
        batch = parse(
            GROUPED_PAYLOAD_MISSING_STAMP, shape="grouped", settings=contract_settings(db_settings)
        )
        assert not any(s.provider_updated_at == NOW for s in batch.snapshots)


# ---------------------------------------------------------------------------
# Shape 2 — /events/{eventId}/odds
# ---------------------------------------------------------------------------
class TestEventResponse:
    def test_it_parses_without_a_bookmaker_timestamp(self, db_settings: Settings) -> None:
        """The contract says the field is absent here. Requiring it rejects everything."""
        batch = parse(EVENT_PAYLOAD, shape="event", settings=contract_settings(db_settings))
        assert batch.snapshots, (
            "an event-odds response was rejected for lacking a bookmaker-level "
            "last_update, which the official contract says it does not carry"
        )

    def test_each_market_keeps_its_own_timestamp(self, db_settings: Settings) -> None:
        batch = parse(EVENT_PAYLOAD, shape="event", settings=contract_settings(db_settings))
        by_market = stamps(batch)
        assert by_market[str(MarketType.MATCH_RESULT_1X2)] == instant(H2H_STAMP)
        assert by_market[str(MarketType.TOTAL_GOALS)] == instant(TOTALS_STAMP)

    def test_two_markets_are_not_flattened_onto_one_instant(self, db_settings: Settings) -> None:
        batch = parse(EVENT_PAYLOAD, shape="event", settings=contract_settings(db_settings))
        observed = {s.provider_updated_at for s in batch.snapshots}
        assert len(observed) == 2, f"27 minutes of difference collapsed into {observed}"

    def test_the_local_reception_time_stays_distinct(self, db_settings: Settings) -> None:
        batch = parse(EVENT_PAYLOAD, shape="event", settings=contract_settings(db_settings))
        for snapshot in batch.snapshots:
            assert snapshot.received_at == NOW
            assert snapshot.provider_updated_at != NOW

    def test_a_market_without_a_timestamp_is_rejected_alone(self, db_settings: Settings) -> None:
        """One unusable market must not discard the one next to it."""
        batch = parse(
            EVENT_PAYLOAD_MISSING_STAMP, shape="event", settings=contract_settings(db_settings)
        )
        markets = {s.selection.market for s in batch.snapshots}
        assert MarketType.MATCH_RESULT_1X2 in markets
        assert MarketType.TOTAL_GOALS not in markets
        assert any("last_update" in error for error in batch.partial_errors)

    def test_an_invalid_timestamp_is_rejected_explicitly(self, db_settings: Settings) -> None:
        batch = parse(
            EVENT_PAYLOAD_INVALID_STAMP, shape="event", settings=contract_settings(db_settings)
        )
        assert {s.selection.market for s in batch.snapshots} == {MarketType.MATCH_RESULT_1X2}
        assert batch.partial_errors

    def test_the_reception_time_is_never_used_as_the_provider_time(
        self, db_settings: Settings
    ) -> None:
        batch = parse(
            EVENT_PAYLOAD_MISSING_STAMP, shape="event", settings=contract_settings(db_settings)
        )
        assert all(s.provider_updated_at != s.received_at for s in batch.snapshots)

    def test_observed_at_follows_the_market_timestamp(self, db_settings: Settings) -> None:
        """`observed_at` is what the staleness check reads; it must not be `now`."""
        batch = parse(EVENT_PAYLOAD, shape="event", settings=contract_settings(db_settings))
        for snapshot in batch.snapshots:
            assert snapshot.observed_at == snapshot.provider_updated_at


class TestTheShapeIsExplicit:
    def test_the_two_shapes_are_named_not_guessed(self) -> None:
        from betmaxxing.providers.the_odds_api.provider import ResponseShape

        assert {value.name for value in ResponseShape} >= {"GROUPED_ODDS", "EVENT_ODDS"}

    def test_the_same_payload_yields_different_timestamps_under_each_shape(
        self, db_settings: Settings
    ) -> None:
        """Proof the parser branches on the declared contract, not on the data."""
        settings = contract_settings(db_settings)
        both = event_payload(
            [
                {
                    "key": "winamax_fr",
                    "title": "Winamax (FR)",
                    "last_update": BOOKMAKER_STAMP,
                    "markets": [h2h_block(last_update=H2H_STAMP)],
                }
            ]
        )
        grouped = parse(both, shape="grouped", settings=settings)
        event = parse(both, shape="event", settings=settings)
        assert {s.provider_updated_at for s in grouped.snapshots} == {instant(BOOKMAKER_STAMP)}
        assert {s.provider_updated_at for s in event.snapshots} == {instant(H2H_STAMP)}


class TestTheCollectorUsesTheRightShapePerEndpoint:
    """End to end: the grouped call and the per-event call must not share a shape."""

    def test_additional_markets_keep_their_per_market_timestamps(
        self, db_settings: Settings
    ) -> None:
        from urllib.parse import urlparse

        from betmaxxing.providers.the_odds_api import TheOddsApiProvider
        from betmaxxing.providers.the_odds_api.client import TheOddsApiClient

        settings = contract_settings(db_settings)
        dnb_stamp = "2026-08-04T11:05:00Z"

        def handler(request: httpx.Request) -> httpx.Response:
            path = urlparse(str(request.url)).path
            if path.endswith("/sports"):
                return httpx.Response(
                    200,
                    json=[{"key": FOOTBALL_KEY, "active": True, "group": "Soccer"}],
                    headers=QUOTA_HEADERS,
                )
            if "/events/" in path:
                # Event-odds shape: no bookmaker timestamp, one per market.
                payload = event_payload(
                    [
                        {
                            "key": "winamax_fr",
                            "title": "Winamax (FR)",
                            "markets": [
                                {
                                    "key": "draw_no_bet",
                                    "last_update": dnb_stamp,
                                    "outcomes": [
                                        {"name": HOME, "price": 1.30},
                                        {"name": AWAY, "price": 3.40},
                                    ],
                                }
                            ],
                        }
                    ]
                )
                return httpx.Response(200, json=payload, headers=QUOTA_HEADERS)
            return httpx.Response(200, json=[GROUPED_PAYLOAD], headers=QUOTA_HEADERS)

        client = TheOddsApiClient(
            api_key=settings.resolved_the_odds_api_key,
            base_url=settings.the_odds_api_base_url,
            transport=httpx.MockTransport(handler),
            sleep=lambda _s: None,
            max_retries=0,
        )
        batch = TheOddsApiProvider(settings, client=client, now=NOW).collect(SPORTS, WINDOW)

        by_market = stamps(batch)
        assert by_market[str(MarketType.MATCH_RESULT_1X2)] == instant(BOOKMAKER_STAMP)
        assert by_market[str(MarketType.DRAW_NO_BET)] == instant(dnb_stamp)

    def test_a_real_shaped_event_response_is_not_silently_dropped(
        self, db_settings: Settings
    ) -> None:
        """The whole point: the additional markets must actually arrive."""
        from urllib.parse import urlparse

        from betmaxxing.providers.the_odds_api import TheOddsApiProvider
        from betmaxxing.providers.the_odds_api.client import TheOddsApiClient

        settings = contract_settings(db_settings)

        def handler(request: httpx.Request) -> httpx.Response:
            path = urlparse(str(request.url)).path
            if path.endswith("/sports"):
                return httpx.Response(
                    200,
                    json=[{"key": FOOTBALL_KEY, "active": True, "group": "Soccer"}],
                    headers=QUOTA_HEADERS,
                )
            if "/events/" in path:
                return httpx.Response(200, json=EVENT_PAYLOAD, headers=QUOTA_HEADERS)
            return httpx.Response(200, json=[GROUPED_PAYLOAD], headers=QUOTA_HEADERS)

        client = TheOddsApiClient(
            api_key=settings.resolved_the_odds_api_key,
            base_url=settings.the_odds_api_base_url,
            transport=httpx.MockTransport(handler),
            sleep=lambda _s: None,
            max_retries=0,
        )
        batch = TheOddsApiProvider(settings, client=client, now=NOW).collect(SPORTS, WINDOW)
        assert not any("last_update" in error for error in batch.partial_errors), (
            f"the event-odds response was rejected: {batch.partial_errors}"
        )


class TestPeriodsAreUnaffected:
    """Non-regression: the timestamp change must not disturb market mapping."""

    def test_full_time_periods_survive(self, db_settings: Settings) -> None:
        batch = parse(GROUPED_PAYLOAD, shape="grouped", settings=contract_settings(db_settings))
        assert all(s.selection.period is Period.FULL_TIME for s in batch.snapshots)

    @pytest.mark.parametrize("shape", ["grouped", "event"])
    def test_the_bookmaker_key_is_preserved(self, db_settings: Settings, shape: str) -> None:
        payload = GROUPED_PAYLOAD if shape == "grouped" else EVENT_PAYLOAD
        batch = parse(payload, shape=shape, settings=contract_settings(db_settings))
        assert {s.bookmaker for s in batch.snapshots} == {"winamax_fr"}
