"""What a request is allowed to cost, before it is made.

Official rule, re-read at <https://the-odds-api.com/liveapi/guides/v4/> on
2026-08-05:

    cost = [number of markets specified] x [number of regions specified]

    When both `bookmakers` and `regions` are specified, `bookmakers` takes
    priority. Every group of 10 bookmakers is the equivalent of 1 region.

The adapter counted the *configured regions* even when it sent
``bookmakers=winamax_fr``, so a single-bookmaker call with ``regions=eu,fr``
reserved two regional units instead of one. That never overspends — the
reservation is an upper bound — but it refuses calls that the budget could
have afforded, which is its own kind of wrong: a guard that fires on correct
requests gets widened, and then it guards nothing.

The reservation stays conservative on purpose. ``x-requests-last`` remains the
authority once the response is in hand.
"""

from __future__ import annotations

import pytest


def units(bookmakers: object, regions: object) -> int:
    """Call-time import: introduced by this tranche."""
    from betmaxxing.providers.the_odds_api.client import effective_region_units

    return effective_region_units(bookmakers=bookmakers, regions=regions)


def cost(*, markets: int, bookmakers: object, regions: object) -> int:
    from betmaxxing.providers.the_odds_api.client import estimate_cost

    return estimate_cost(markets=markets, region_units=units(bookmakers, regions))


# ---------------------------------------------------------------------------
# Effective regional units
# ---------------------------------------------------------------------------
class TestBookmakersTakePriority:
    def test_one_bookmaker_with_two_regions_is_one_unit(self) -> None:
        assert units(["winamax_fr"], ["eu", "fr"]) == 1

    def test_ten_bookmakers_are_one_unit(self) -> None:
        assert units([f"book_{i}" for i in range(10)], ["eu", "fr"]) == 1

    def test_eleven_bookmakers_are_two_units(self) -> None:
        assert units([f"book_{i}" for i in range(11)], ["eu"]) == 2

    def test_twenty_bookmakers_are_two_units(self) -> None:
        assert units([f"book_{i}" for i in range(20)], ["eu"]) == 2

    def test_twenty_one_bookmakers_are_three_units(self) -> None:
        assert units([f"book_{i}" for i in range(21)], ["eu"]) == 3

    def test_regions_are_ignored_entirely_when_bookmakers_are_given(self) -> None:
        few = units(["winamax_fr"], ["eu"])
        many = units(["winamax_fr"], ["eu", "fr", "uk", "us", "au"])
        assert few == many == 1


class TestRegionFallback:
    def test_two_regions_without_bookmakers_are_two_units(self) -> None:
        assert units([], ["eu", "fr"]) == 2

    def test_one_region_without_bookmakers_is_one_unit(self) -> None:
        assert units([], ["eu"]) == 1

    def test_five_regions_without_bookmakers_are_five_units(self) -> None:
        assert units(None, ["us", "uk", "eu", "au", "fr"]) == 5


class TestNormalisationIsDeterministic:
    @pytest.mark.parametrize(
        "raw",
        [
            ["  winamax_fr  "],
            ["winamax_fr", "winamax_fr"],
            ["winamax_fr", ""],
            ["winamax_fr", "   "],
            ["WINAMAX_FR", "winamax_fr"],
            "winamax_fr",
            " winamax_fr , winamax_fr ",
        ],
        ids=["padded", "duplicate", "empty", "blank", "case", "string", "csv-string"],
    )
    def test_one_effective_bookmaker_however_it_is_written(self, raw: object) -> None:
        assert units(raw, ["eu", "fr"]) == 1

    @pytest.mark.parametrize(
        "raw",
        [["eu", "eu"], [" eu ", "eu"], ["EU", "eu"], "eu", "eu,eu", ["eu", ""]],
        ids=["duplicate", "padded", "case", "string", "csv-duplicate", "empty"],
    )
    def test_one_effective_region_however_it_is_written(self, raw: object) -> None:
        assert units([], raw) == 1

    def test_an_empty_configuration_never_yields_zero(self) -> None:
        """A billable request costs at least one unit; the bound must not vanish."""
        assert units([], []) == 1
        assert units(None, None) == 1


# ---------------------------------------------------------------------------
# The bound itself
# ---------------------------------------------------------------------------
class TestEstimatedCost:
    def test_one_market_one_bookmaker_costs_one(self) -> None:
        assert cost(markets=1, bookmakers=["winamax_fr"], regions=["eu", "fr"]) == 1

    def test_five_markets_one_bookmaker_cost_five(self) -> None:
        assert cost(markets=5, bookmakers=["winamax_fr"], regions=["eu", "fr"]) == 5

    def test_two_markets_two_regions_cost_four(self) -> None:
        assert cost(markets=2, bookmakers=[], regions=["eu", "fr"]) == 4

    def test_two_markets_eleven_bookmakers_cost_four(self) -> None:
        assert cost(markets=2, bookmakers=[f"b{i}" for i in range(11)], regions=["eu"]) == 4

    def test_the_bound_is_never_below_one(self) -> None:
        assert cost(markets=0, bookmakers=["winamax_fr"], regions=["eu"]) == 1


class TestTheCollectorAppliesIt:
    """The adapter must reserve what the contract says, not what it configured."""

    def test_a_single_bookmaker_scan_reserves_one_unit_per_market(
        self, db_settings: object
    ) -> None:
        from datetime import UTC, datetime, timedelta
        from urllib.parse import urlparse

        import httpx

        from betmaxxing.config import RunMode, Settings
        from betmaxxing.domain.enums import Sport
        from betmaxxing.providers.budget import ProviderBudgetLedger
        from betmaxxing.providers.the_odds_api import TheOddsApiProvider
        from betmaxxing.providers.the_odds_api.client import TheOddsApiClient

        moment = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
        settings = Settings(
            mode=RunMode.PAPER,
            database_url=db_settings.database_url,  # type: ignore[attr-defined]
            odds_provider="the_odds_api",
            the_odds_api_key="abcdef0123456789abcdef0123456789",
            bookmakers="winamax_fr",
            # Two regions configured, one bookmaker sent: the contract says the
            # bookmaker wins, so this must cost one unit per market, not two.
            the_odds_api_regions="eu,fr",
            the_odds_api_sport_keys="soccer_france_ligue_one",
            provider_budget_per_scan=200,
            provider_budget_per_day=400,
            notifications_enabled=False,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            path = urlparse(str(request.url)).path
            headers = {"x-requests-remaining": "9", "x-requests-used": "1"}
            if path.endswith("/sports"):
                return httpx.Response(
                    200,
                    json=[{"key": "soccer_france_ligue_one", "active": True}],
                    headers=headers,
                )
            return httpx.Response(200, json=[], headers=headers)

        client = TheOddsApiClient(
            api_key=settings.resolved_the_odds_api_key,
            base_url=settings.the_odds_api_base_url,
            transport=httpx.MockTransport(handler),
            sleep=lambda _s: None,
            max_retries=0,
        )
        TheOddsApiProvider(settings, client=client, now=moment).collect(
            [Sport.FOOTBALL], (moment, moment + timedelta(hours=24))
        )

        entries = [
            entry
            for entry in ProviderBudgetLedger(settings).entries_for_day(moment, "the_odds_api")
            if entry.request.endswith("/odds")
        ]
        assert entries, "the grouped call was not recorded"
        # Two core football markets x 1 effective unit.
        assert entries[0].reserved_cost == 2, (
            f"reserved {entries[0].reserved_cost} credits for 2 markets and 1 effective "
            "regional unit; the configured regions were counted instead of the bookmaker"
        )


class TestReconciliationStillWins:
    """The estimate is a bound. What the provider says it charged is the truth."""

    def test_the_observed_cost_replaces_a_larger_estimate(self, db_settings: object) -> None:
        from datetime import UTC, datetime

        import httpx

        from betmaxxing.config import RunMode, Settings
        from betmaxxing.providers.budget import ProviderBudgetLedger
        from betmaxxing.providers.the_odds_api.client import TheOddsApiClient

        moment = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
        settings = Settings(
            mode=RunMode.PAPER,
            database_url=db_settings.database_url,  # type: ignore[attr-defined]
            the_odds_api_key="abcdef0123456789abcdef0123456789",
            provider_budget_per_scan=50,
            provider_budget_per_day=100,
            notifications_enabled=False,
        )
        ledger = ProviderBudgetLedger(settings)
        client = TheOddsApiClient(
            api_key=settings.resolved_the_odds_api_key,
            base_url=settings.the_odds_api_base_url,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json=[], headers={"x-requests-last": "2", "x-requests-remaining": "5"}
                )
            ),
            sleep=lambda _s: None,
            max_retries=0,
            budget_ledger=ledger,
            now=moment,
        )
        # Reserved as 5 markets x 1 unit; the provider says it charged 2.
        client.get("sports/x/odds", cost=5)
        assert ledger.spent_today("the_odds_api", moment) == 2

    def test_an_empty_response_charged_zero_is_reconciled_to_zero(
        self, db_settings: object
    ) -> None:
        """v4: "If no events are returned, the request will not count against
        the usage quota." The pre-call bound stays conservative regardless."""
        from datetime import UTC, datetime

        import httpx

        from betmaxxing.config import RunMode, Settings
        from betmaxxing.providers.budget import ProviderBudgetLedger
        from betmaxxing.providers.the_odds_api.client import TheOddsApiClient

        moment = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
        settings = Settings(
            mode=RunMode.PAPER,
            database_url=db_settings.database_url,  # type: ignore[attr-defined]
            the_odds_api_key="abcdef0123456789abcdef0123456789",
            provider_budget_per_scan=50,
            provider_budget_per_day=100,
            notifications_enabled=False,
        )
        ledger = ProviderBudgetLedger(settings)
        client = TheOddsApiClient(
            api_key=settings.resolved_the_odds_api_key,
            base_url=settings.the_odds_api_base_url,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json=[], headers={"x-requests-last": "0"})
            ),
            sleep=lambda _s: None,
            max_retries=0,
            budget_ledger=ledger,
            now=moment,
        )
        client.get("sports/x/odds", cost=5)
        assert ledger.spent_today("the_odds_api", moment) == 0
        entry = ledger.entries_for_day(moment, "the_odds_api")[0]
        assert entry.reserved_cost == 5, "the pre-call bound must stay conservative"
        assert entry.observed_cost == 0
