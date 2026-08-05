"""The Odds API adapter — contract tests against local fixtures.

**No test here touches the network.** Every response is served by an
``httpx.MockTransport`` built from synthetic payloads shaped like the documented
v4 contract. That is what keeps CI deterministic and free of provider credits.

The fixtures are hand-written and anonymised; they are not captured production
responses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import CollectionStatus, MarketType, Period, Sport
from betmaxxing.providers.base import BudgetExceeded, ProviderQuotaExceeded
from betmaxxing.providers.the_odds_api import (
    UNSUPPORTED_BY_PROVIDER,
    MappingRejected,
    TheOddsApiAuthError,
    TheOddsApiClient,
    TheOddsApiError,
    TheOddsApiProvider,
    classify_sport,
    estimate_cost,
    map_market,
    parse_quota,
    redact,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
WINDOW = (NOW, NOW + timedelta(hours=24))
SECRET = "abcdef0123456789abcdef0123456789"

QUOTA_HEADERS = {
    "x-requests-remaining": "487",
    "x-requests-used": "13",
    "x-requests-last": "2",
}


def football_event(
    *, bookmaker: str = "winamax_fr", start: datetime | None = None
) -> dict[str, Any]:
    commence = (start or NOW + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": "evt-fb-1",
        "sport_key": "soccer_france_ligue_one",
        "sport_title": "Ligue 1",
        "commence_time": commence,
        "home_team": "Olympique Lyonnais",
        "away_team": "Stade Rennais",
        "bookmakers": [
            {
                "key": bookmaker,
                "title": bookmaker.title(),
                "last_update": (NOW - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Olympique Lyonnais", "price": 1.63},
                            {"name": "Stade Rennais", "price": 5.00},
                            {"name": "Draw", "price": 4.20},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.86, "point": 2.5},
                            {"name": "Under", "price": 1.98, "point": 2.5},
                        ],
                    },
                ],
            }
        ],
    }


def tennis_event() -> dict[str, Any]:
    return {
        "id": "evt-tn-1",
        "sport_key": "tennis_atp_aus_open_singles",
        "sport_title": "ATP",
        "commence_time": (NOW + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": "Alejandro Tabilo",
        "away_team": "Rafael Jodar",
        "bookmakers": [
            {
                "key": "winamax_fr",
                "title": "Winamax",
                "last_update": (NOW - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Alejandro Tabilo", "price": 1.76},
                            {"name": "Rafael Jodar", "price": 2.07},
                        ],
                    }
                ],
            }
        ],
    }


#: Per-test SQLite file, installed by the autouse fixture below. The provider
#: now records every credit reservation durably, so it needs a database even in
#: a contract test that makes no real call.
_DATABASE_URL = ""


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path: Any) -> Any:
    from betmaxxing.storage.db import reset_engine

    global _DATABASE_URL
    reset_engine()
    _DATABASE_URL = f"sqlite+pysqlite:///{tmp_path / 'odds.db'}"
    yield
    _DATABASE_URL = ""
    reset_engine()


def provider_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": _DATABASE_URL or "sqlite+pysqlite:///:memory:",
        "mode": RunMode.PAPER,
        "odds_provider": "the_odds_api",
        "the_odds_api_key": SECRET,
        "bookmakers": "winamax_fr",
        "the_odds_api_regions": "eu,fr",
        "the_odds_api_sport_keys": "soccer_france_ligue_one,tennis_atp_aus_open_singles",
        "provider_budget_per_scan": 50,
    }
    base.update(overrides)
    return Settings(**base)


def make_client(handler: Any, settings: Settings | None = None, **kwargs: Any) -> TheOddsApiClient:
    settings = settings or provider_settings()
    return TheOddsApiClient(
        api_key=settings.resolved_the_odds_api_key,
        base_url=settings.the_odds_api_base_url,
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
        budget_per_scan=settings.provider_budget_per_scan,
        **kwargs,
    )


def responder(payload: Any, status: int = 200, headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, headers={**QUOTA_HEADERS, **(headers or {})})

    return handler


# ---------------------------------------------------------------------------
# Secret handling
# ---------------------------------------------------------------------------


class TestKeyNeverLeaks:
    def test_redact_masks_the_query_parameter(self) -> None:
        url = f"https://api.the-odds-api.com/v4/sports?apiKey={SECRET}&regions=eu"
        assert SECRET not in redact(url)
        assert "***REDACTED***" in redact(url)

    def test_auth_error_message_carries_no_key(self) -> None:
        client = make_client(responder({"message": "bad key"}, status=401))
        with pytest.raises(TheOddsApiAuthError) as exc:
            client.get("sports/soccer_france_ligue_one/odds")
        assert SECRET not in str(exc.value)

    def test_transport_error_message_carries_no_key(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns failure", request=request)

        client = make_client(boom, max_retries=0)
        with pytest.raises(TheOddsApiError) as exc:
            client.get("sports/x/odds")
        assert SECRET not in str(exc.value)

    def test_invalid_json_message_carries_no_key(self) -> None:
        def bad_json(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json", headers=QUOTA_HEADERS)

        client = make_client(bad_json)
        with pytest.raises(TheOddsApiError) as exc:
            client.get("sports/x/odds")
        assert SECRET not in str(exc.value)

    def test_settings_redaction_hides_the_key(self) -> None:
        assert provider_settings().redacted()["the_odds_api_key"] == "***set***"

    def test_provider_health_carries_no_key(self) -> None:
        status = TheOddsApiProvider(provider_settings(), client=make_client(responder([]))).health()
        assert SECRET not in status.model_dump_json()

    def test_no_fixture_in_this_module_contains_a_realistic_key(self) -> None:
        blob = json.dumps([football_event(), tennis_event()])
        assert "apiKey" not in blob


# ---------------------------------------------------------------------------
# HTTP behaviour
# ---------------------------------------------------------------------------


class TestErrorTaxonomy:
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failures_raise_auth_error(self, status: int) -> None:
        client = make_client(responder({}, status=status))
        with pytest.raises(TheOddsApiAuthError):
            client.get("sports/x/odds")

    def test_404_is_not_retried(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(404, json={}, headers=QUOTA_HEADERS)

        with pytest.raises(TheOddsApiError, match="introuvable"):
            make_client(handler).get("sports/x/odds")
        assert calls["n"] == 1

    def test_422_reports_an_unsupported_parameter(self) -> None:
        client = make_client(responder({}, status=422))
        with pytest.raises(TheOddsApiError, match="422"):
            client.get("sports/x/odds")

    def test_429_is_retried_then_reported_as_quota(self) -> None:
        client = make_client(responder({}, status=429), max_retries=2)
        with pytest.raises(ProviderQuotaExceeded):
            client.get("sports/x/odds")

    def test_retry_after_is_honoured(self) -> None:
        waits: list[float] = []
        client = TheOddsApiClient(
            api_key=SECRET,
            base_url="https://api.the-odds-api.com/v4",
            transport=httpx.MockTransport(responder({}, status=429, headers={"Retry-After": "7"})),
            sleep=waits.append,
            max_retries=1,
            budget_per_scan=100,
        )
        with pytest.raises(ProviderQuotaExceeded):
            client.get("sports/x/odds")
        assert 7.0 in waits

    def test_5xx_is_retried_then_raises(self) -> None:
        client = make_client(responder({}, status=503), max_retries=1)
        with pytest.raises(TheOddsApiError, match="503"):
            client.get("sports/x/odds")

    def test_a_transient_5xx_then_success_returns_data(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, json={}, headers=QUOTA_HEADERS)
            return httpx.Response(200, json=[football_event()], headers=QUOTA_HEADERS)

        response = make_client(handler, max_retries=2).get("sports/x/odds")
        assert len(response.payload) == 1

    def test_timeout_is_retried_then_raises(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        with pytest.raises(TheOddsApiError, match="timeout"):
            make_client(timeout, max_retries=1).get("sports/x/odds")


class TestQuotaAndBudget:
    def test_quota_headers_are_read(self) -> None:
        response = make_client(responder([])).get("sports/x/odds")
        assert response.quota.remaining == 487
        assert response.quota.used == 13
        assert response.quota.last_cost == 2

    def test_missing_quota_headers_are_tolerated(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        assert make_client(handler).get("sports/x/odds").quota.remaining is None

    def test_unparseable_quota_header_is_ignored(self) -> None:
        assert parse_quota({"x-requests-remaining": "many"}).remaining is None

    def test_cost_estimate_multiplies_markets_by_regions(self) -> None:
        assert estimate_cost(markets=2, regions=2) == 4
        assert estimate_cost(markets=1, regions=1) == 1

    def test_a_call_over_budget_is_refused_before_it_runs(self) -> None:
        """The guard fires before the request, so quota cannot be spent by mistake."""
        called = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            return httpx.Response(200, json=[], headers=QUOTA_HEADERS)

        client = make_client(handler, settings=provider_settings(provider_budget_per_scan=1))
        with pytest.raises(BudgetExceeded):
            client.get("sports/x/odds", cost=5)
        assert called["n"] == 0

    def test_spend_accumulates_from_reported_cost(self) -> None:
        client = make_client(responder([]))
        client.get("sports/x/odds", cost=1)
        assert client.credits_spent == 2  # x-requests-last wins over the estimate


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


class TestSportClassification:
    def test_known_prefixes(self) -> None:
        assert classify_sport("soccer_france_ligue_one") is Sport.FOOTBALL
        assert classify_sport("tennis_atp_aus_open_singles") is Sport.TENNIS

    def test_unknown_prefix_is_none(self) -> None:
        assert classify_sport("basketball_nba") is None


class TestMarketMapping:
    def test_football_h2h_maps_to_1x2(self) -> None:
        mapped = map_market(
            provider_market_key="h2h",
            sport=Sport.FOOTBALL,
            outcomes=[
                {"name": "Olympique Lyonnais", "price": 1.63},
                {"name": "Draw", "price": 4.20},
                {"name": "Stade Rennais", "price": 5.00},
            ],
            home_team="Olympique Lyonnais",
            away_team="Stade Rennais",
        )
        assert [m.selection.code for m in mapped] == ["home", "draw", "away"]
        assert all(m.selection.market is MarketType.MATCH_RESULT_1X2 for m in mapped)
        assert all(m.selection.period is Period.FULL_TIME for m in mapped)

    def test_totals_carry_an_exact_line(self) -> None:
        mapped = map_market(
            provider_market_key="totals",
            sport=Sport.FOOTBALL,
            outcomes=[
                {"name": "Over", "price": 1.86, "point": 2.5},
                {"name": "Under", "price": 1.98, "point": 2.5},
            ],
            home_team="A",
            away_team="B",
        )
        assert mapped[0].selection.line_canonical == "2.5"

    def test_equivalent_line_spellings_collapse(self) -> None:
        for spelling in ("2.5", "2.50", 2.5):
            mapped = map_market(
                provider_market_key="totals",
                sport=Sport.FOOTBALL,
                outcomes=[{"name": "Over", "price": 1.86, "point": spelling}],
                home_team="A",
                away_team="B",
            )
            assert mapped[0].selection.line_canonical == "2.5"

    def test_first_half_markets_map_to_the_right_period(self) -> None:
        mapped = map_market(
            provider_market_key="h2h_3_way_h1",
            sport=Sport.FOOTBALL,
            outcomes=[
                {"name": "A", "price": 2.0},
                {"name": "Draw", "price": 2.1},
                {"name": "B", "price": 5.0},
            ],
            home_team="A",
            away_team="B",
        )
        assert all(m.selection.period is Period.FIRST_HALF for m in mapped)

    def test_tennis_h2h_maps_to_match_winner(self) -> None:
        mapped = map_market(
            provider_market_key="h2h",
            sport=Sport.TENNIS,
            outcomes=[{"name": "A", "price": 1.76}, {"name": "B", "price": 2.07}],
            home_team="A",
            away_team="B",
        )
        assert all(m.selection.market is MarketType.MATCH_WINNER for m in mapped)


class TestMappingRefusals:
    def test_h2h_s1_is_never_mapped_to_wins_a_set(self) -> None:
        """`h2h_s1` is *winner of set 1*. Treating it as "wins a set" would price
        a different bet with a very different probability."""
        assert "h2h_s1" in UNSUPPORTED_BY_PROVIDER
        with pytest.raises(MappingRejected, match="1er set"):
            map_market(
                provider_market_key="h2h_s1",
                sport=Sport.TENNIS,
                outcomes=[{"name": "A", "price": 1.9}],
                home_team="A",
                away_team="B",
            )

    def test_wins_a_set_has_no_source_key(self) -> None:
        with pytest.raises(MappingRejected, match="UNSUPPORTED_BY_PROVIDER"):
            map_market(
                provider_market_key="player_wins_a_set",
                sport=Sport.TENNIS,
                outcomes=[{"name": "A", "price": 1.4}],
                home_team="A",
                away_team="B",
            )

    def test_unknown_market_is_rejected_not_guessed(self) -> None:
        with pytest.raises(MappingRejected, match="non reconnu"):
            map_market(
                provider_market_key="correct_score",
                sport=Sport.FOOTBALL,
                outcomes=[{"name": "1-0", "price": 8.0}],
                home_team="A",
                away_team="B",
            )

    def test_tennis_totals_is_disabled_until_semantics_are_confirmed(self) -> None:
        with pytest.raises(MappingRejected, match="jeux vs sets"):
            map_market(
                provider_market_key="totals",
                sport=Sport.TENNIS,
                outcomes=[{"name": "Over", "price": 1.9, "point": 22.5}],
                home_team="A",
                away_team="B",
            )

    def test_tennis_totals_maps_when_explicitly_allowed(self) -> None:
        mapped = map_market(
            provider_market_key="totals",
            sport=Sport.TENNIS,
            outcomes=[{"name": "Over", "price": 1.9, "point": 22.5}],
            home_team="A",
            away_team="B",
            allow_tennis_totals=True,
        )
        assert mapped[0].selection.market is MarketType.TOTAL_GAMES

    def test_an_unknown_participant_is_rejected(self) -> None:
        """Never match by position: a mismatched side inverts the bet."""
        with pytest.raises(MappingRejected, match="absent de l'événement"):
            map_market(
                provider_market_key="h2h",
                sport=Sport.FOOTBALL,
                outcomes=[{"name": "Someone Else", "price": 2.0}],
                home_team="A",
                away_team="B",
            )

    def test_over_under_without_a_line_is_rejected(self) -> None:
        with pytest.raises(MappingRejected, match="sans ligne"):
            map_market(
                provider_market_key="totals",
                sport=Sport.FOOTBALL,
                outcomes=[{"name": "Over", "price": 1.9}],
                home_team="A",
                away_team="B",
            )

    def test_invalid_price_is_rejected(self) -> None:
        with pytest.raises(MappingRejected):
            map_market(
                provider_market_key="h2h",
                sport=Sport.FOOTBALL,
                outcomes=[{"name": "A", "price": 0.5}],
                home_team="A",
                away_team="B",
            )

    def test_naive_timestamp_is_rejected(self) -> None:
        from betmaxxing.providers.the_odds_api.mapping import parse_iso

        with pytest.raises(MappingRejected, match="sans décalage"):
            parse_iso("2026-08-04T12:00:00", "commence_time")


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


class TestCollection:
    def _provider(self, payload: Any, settings: Settings | None = None) -> TheOddsApiProvider:
        settings = settings or provider_settings()
        return TheOddsApiProvider(
            settings, client=make_client(responder(payload), settings), now=NOW
        )

    def test_collects_football_and_tennis(self) -> None:
        provider = self._provider([football_event(), tennis_event()])
        batch = provider.collect([Sport.FOOTBALL, Sport.TENNIS], WINDOW)
        assert batch.snapshots
        assert batch.coverage is CollectionStatus.OK

    def test_snapshots_keep_source_and_local_times_distinct(self) -> None:
        batch = self._provider([football_event()]).collect([Sport.FOOTBALL], WINDOW)
        snapshot = batch.snapshots[0]
        assert snapshot.observed_at == snapshot.provider_updated_at
        assert snapshot.received_at >= snapshot.observed_at
        assert snapshot.observed_at != snapshot.received_at

    def test_missing_bookmaker_is_coverage_not_failure(self) -> None:
        """A correct response that lacks our book must not look like an outage,
        and must never trigger the demo pack."""
        batch = self._provider([football_event(bookmaker="other_book")]).collect(
            [Sport.FOOTBALL], WINDOW
        )
        assert batch.snapshots == []
        assert batch.coverage is CollectionStatus.COVERAGE_MISSING

    def test_an_already_started_event_is_dropped(self) -> None:
        started = football_event(start=NOW - timedelta(minutes=30))
        batch = self._provider([started]).collect([Sport.FOOTBALL], WINDOW)
        assert batch.events == []

    def test_an_event_beyond_the_window_is_dropped(self) -> None:
        far = football_event(start=NOW + timedelta(hours=48))
        batch = self._provider([far]).collect([Sport.FOOTBALL], WINDOW)
        assert batch.events == []

    def test_an_unknown_market_is_reported_not_fatal(self) -> None:
        payload = football_event()
        payload["bookmakers"][0]["markets"].append(
            {"key": "correct_score", "outcomes": [{"name": "1-0", "price": 9.0}]}
        )
        batch = self._provider([payload]).collect([Sport.FOOTBALL], WINDOW)
        assert batch.snapshots  # the good markets survived
        assert any("correct_score" in err for err in batch.partial_errors)

    def test_multiple_lines_are_kept_separate(self) -> None:
        payload = football_event()
        payload["bookmakers"][0]["markets"].append(
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": 2.6, "point": 3.5},
                    {"name": "Under", "price": 1.5, "point": 3.5},
                ],
            }
        )
        batch = self._provider([payload]).collect([Sport.FOOTBALL], WINDOW)
        lines = {
            s.selection.line_canonical
            for s in batch.snapshots
            if s.selection.market is MarketType.TOTAL_GOALS
        }
        assert lines == {"2.5", "3.5"}

    def test_quota_is_reported_on_the_batch(self) -> None:
        batch = self._provider([football_event()]).collect([Sport.FOOTBALL], WINDOW)
        assert batch.quota.remaining == 487

    def test_snapshots_deduplicate_on_reingest(self) -> None:
        provider = self._provider([football_event()])
        first = provider.collect([Sport.FOOTBALL], WINDOW)
        second = provider.collect([Sport.FOOTBALL], WINDOW)
        assert {s.fingerprint for s in first.snapshots} == {s.fingerprint for s in second.snapshots}

    def test_a_partial_failure_keeps_the_other_sport(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "tennis" in str(request.url):
                return httpx.Response(503, json={}, headers=QUOTA_HEADERS)
            return httpx.Response(200, json=[football_event()], headers=QUOTA_HEADERS)

        settings = provider_settings()
        provider = TheOddsApiProvider(
            settings,
            client=make_client(handler, settings, max_retries=0),
            now=NOW,
        )
        batch = provider.collect([Sport.FOOTBALL, Sport.TENNIS], WINDOW)
        assert batch.snapshots
        assert batch.partial_errors

    def test_health_reports_implemented_unverified(self) -> None:
        status = self._provider([]).health()
        assert "IMPLEMENTED_UNVERIFIED" in status.detail


class TestConfigurationGuards:
    def test_client_refuses_to_construct_without_a_key(self) -> None:
        with pytest.raises(TheOddsApiAuthError):
            TheOddsApiClient(api_key="", base_url="https://example.invalid")

    def test_deprecated_generic_key_is_honoured_with_a_warning(self) -> None:
        settings = Settings(mode=RunMode.PAPER, odds_provider="the_odds_api", odds_api_key=SECRET)
        assert settings.resolved_the_odds_api_key == SECRET
        warnings = settings.deprecation_warnings()
        assert warnings
        assert SECRET not in " ".join(warnings)

    def test_specific_key_wins_over_the_deprecated_one(self) -> None:
        settings = Settings(
            mode=RunMode.PAPER,
            odds_api_key="old-value-should-lose",
            the_odds_api_key=SECRET,
        )
        assert settings.resolved_the_odds_api_key == SECRET
        assert settings.deprecation_warnings() == []
