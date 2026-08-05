"""What a failed request costs, and what we are allowed to assume about it.

The previous tranche released the reservation for **every** ``TimeoutException``
and every ``TransportError``, and documented that as "no response arrived, so no
credit was consumed". That is only true when the request demonstrably never left
the client. A read timeout means the request was sent and the *answer* did not
come back in time — the provider may well have served and billed it. Treating
that as free under-counts spend, which is the one direction a budget must never
err in.

The rule these tests pin: **release only when the request cannot have been
received.** Everything uncertain stays charged at its estimate.

No provider is contacted; every failure is injected through an
``httpx.MockTransport``.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.providers.base import ProviderError
from betmaxxing.providers.budget import ProviderBudgetLedger
from betmaxxing.providers.the_odds_api.client import TheOddsApiClient

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
SECRET = "abcdef0123456789abcdef0123456789"

QUOTA_HEADERS = {
    "x-requests-remaining": "487",
    "x-requests-used": "13",
    "x-requests-last": "2",
}


def accounting_settings(db_settings: Settings, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "mode": RunMode.PAPER,
        "database_url": db_settings.database_url,
        "odds_provider": "the_odds_api",
        "the_odds_api_key": SECRET,
        "bookmakers": "winamax_fr",
        "the_odds_api_regions": "eu",
        "provider_budget_per_scan": 50,
        "provider_budget_per_day": 100,
        "notifications_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def make_client(
    settings: Settings, handler: Any, *, max_retries: int = 0
) -> tuple[TheOddsApiClient, ProviderBudgetLedger]:
    budget = ProviderBudgetLedger(settings)
    client = TheOddsApiClient(
        api_key=settings.resolved_the_odds_api_key,
        base_url=settings.the_odds_api_base_url,
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        budget_per_scan=settings.provider_budget_per_scan,
        max_retries=max_retries,
        budget_ledger=budget,
        now=NOW,
    )
    return client, budget


def raiser(exception: BaseException) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    return handler


# ---------------------------------------------------------------------------
# 1. Errors that prove the request was never received
# ---------------------------------------------------------------------------
class TestRequestDemonstrablyNeverSent:
    @pytest.mark.parametrize(
        "exception",
        [
            httpx.ConnectError("dns failure"),
            httpx.ConnectTimeout("handshake timed out"),
            httpx.PoolTimeout("no connection available"),
        ],
        ids=["connect-error", "connect-timeout", "pool-timeout"],
    )
    def test_the_reservation_is_released(
        self, db_settings: Settings, exception: BaseException
    ) -> None:
        settings = accounting_settings(db_settings)
        client, budget = make_client(settings, raiser(exception))
        with pytest.raises(ProviderError):
            client.get("sports/x/odds", cost=2)

        assert budget.spent_today("the_odds_api", NOW) == 0
        entries = budget.entries_for_day(NOW, "the_odds_api")
        assert entries and all(entry.released for entry in entries)


# ---------------------------------------------------------------------------
# 2. Errors where billing is uncertain
# ---------------------------------------------------------------------------
class TestBillingUncertain:
    @pytest.mark.parametrize(
        "exception",
        [
            httpx.ReadTimeout("no answer in time"),
            httpx.WriteTimeout("stalled mid-send"),
            httpx.ReadError("connection reset while reading"),
            httpx.WriteError("connection reset while sending"),
            httpx.RemoteProtocolError("server disconnected mid-response"),
        ],
        ids=["read-timeout", "write-timeout", "read-error", "write-error", "protocol-error"],
    )
    def test_the_estimate_stays_charged(
        self, db_settings: Settings, exception: BaseException
    ) -> None:
        """The provider may have served and billed this request."""
        settings = accounting_settings(db_settings)
        client, budget = make_client(settings, raiser(exception))
        with pytest.raises(ProviderError):
            client.get("sports/x/odds", cost=2)

        assert budget.spent_today("the_odds_api", NOW) == 2, (
            "a request that may have been received was accounted as free"
        )
        entries = budget.entries_for_day(NOW, "the_odds_api")
        assert entries and not any(entry.released for entry in entries)

    def test_a_read_timeout_is_not_reported_as_costless(self, db_settings: Settings) -> None:
        settings = accounting_settings(db_settings)
        client, budget = make_client(settings, raiser(httpx.ReadTimeout("late")))
        with pytest.raises(ProviderError):
            client.get("sports/x/odds", cost=3)
        entry = budget.entries_for_day(NOW, "the_odds_api")[0]
        assert entry.effective_cost == 3


# ---------------------------------------------------------------------------
# 3. Responses, with and without the cost header
# ---------------------------------------------------------------------------
class TestResponsesAndHeaders:
    def test_the_reported_cost_replaces_the_estimate(self, db_settings: Settings) -> None:
        settings = accounting_settings(db_settings)
        client, budget = make_client(
            settings,
            lambda r: httpx.Response(200, json=[], headers=QUOTA_HEADERS),
        )
        client.get("sports/x/odds", cost=6)
        assert budget.spent_today("the_odds_api", NOW) == 2

    def test_a_missing_header_keeps_the_estimate(self, db_settings: Settings) -> None:
        settings = accounting_settings(db_settings)
        client, budget = make_client(settings, lambda r: httpx.Response(200, json=[]))
        client.get("sports/x/odds", cost=6)
        assert budget.spent_today("the_odds_api", NOW) == 6, "an unknown cost was treated as zero"

    def test_an_error_response_is_still_charged(self, db_settings: Settings) -> None:
        """A 500 was served by the provider; it reached them."""
        settings = accounting_settings(db_settings)
        client, budget = make_client(
            settings, lambda r: httpx.Response(500, json={}, headers=QUOTA_HEADERS)
        )
        with pytest.raises(ProviderError):
            client.get("sports/x/odds", cost=4)
        assert budget.spent_today("the_odds_api", NOW) >= 2


# ---------------------------------------------------------------------------
# 4. Retries cannot outrun either ceiling
# ---------------------------------------------------------------------------
class TestRetriesRespectBothCeilings:
    def test_read_timeouts_stop_at_the_scan_ceiling(self, db_settings: Settings) -> None:
        settings = accounting_settings(
            db_settings, provider_budget_per_scan=5, provider_budget_per_day=1000
        )
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            raise httpx.ReadTimeout("late")

        client, budget = make_client(settings, handler, max_retries=20)
        with pytest.raises(ProviderError):
            client.get("sports/x/odds", cost=2)

        assert attempts["n"] <= 2, f"{attempts['n']} attempts at 2 credits under a ceiling of 5"
        assert budget.spent_today("the_odds_api", NOW) <= 5

    def test_read_timeouts_stop_at_the_daily_ceiling(self, db_settings: Settings) -> None:
        settings = accounting_settings(
            db_settings, provider_budget_per_scan=1000, provider_budget_per_day=5
        )
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            raise httpx.ReadTimeout("late")

        client, budget = make_client(settings, handler, max_retries=20)
        with pytest.raises(ProviderError):
            client.get("sports/x/odds", cost=2)

        assert attempts["n"] <= 2
        assert budget.spent_today("the_odds_api", NOW) <= 5

    def test_connect_errors_do_not_consume_the_budget(self, db_settings: Settings) -> None:
        """Released reservations must not accumulate into a false ceiling."""
        settings = accounting_settings(
            db_settings, provider_budget_per_scan=4, provider_budget_per_day=6
        )
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            raise httpx.ConnectError("dns")

        client, budget = make_client(settings, handler, max_retries=5)
        with pytest.raises(ProviderError):
            client.get("sports/x/odds", cost=2)

        assert attempts["n"] == 6, "a demonstrably unsent request must not eat the budget"
        assert budget.spent_today("the_odds_api", NOW) == 0

    def test_a_mixed_sequence_never_exceeds_the_ceiling(self, db_settings: Settings) -> None:
        settings = accounting_settings(
            db_settings, provider_budget_per_scan=6, provider_budget_per_day=6
        )
        sequence = [
            httpx.ConnectError("dns"),
            httpx.ReadTimeout("late"),
            httpx.ReadTimeout("late"),
            httpx.ReadTimeout("late"),
            httpx.ReadTimeout("late"),
        ]
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            index = calls["n"]
            calls["n"] += 1
            if index < len(sequence):
                raise sequence[index]
            return httpx.Response(200, json=[], headers=QUOTA_HEADERS)

        client, budget = make_client(settings, handler, max_retries=20)
        with contextlib.suppress(ProviderError):
            client.get("sports/x/odds", cost=2)
        assert budget.spent_today("the_odds_api", NOW) <= 6
        assert budget.verify_invariant("the_odds_api", NOW)


# ---------------------------------------------------------------------------
# 5. The taxonomy is declared, not inferred at each call site
# ---------------------------------------------------------------------------
class TestTheTaxonomyIsExplicit:
    @pytest.mark.parametrize(
        ("exception", "expected"),
        [
            (httpx.ConnectError("x"), False),
            (httpx.ConnectTimeout("x"), False),
            (httpx.PoolTimeout("x"), False),
            (httpx.ReadTimeout("x"), True),
            (httpx.WriteTimeout("x"), True),
            (httpx.ReadError("x"), True),
            (httpx.WriteError("x"), True),
            (httpx.RemoteProtocolError("x"), True),
        ],
    )
    def test_may_have_been_billed(self, exception: BaseException, expected: bool) -> None:
        from betmaxxing.providers.the_odds_api.client import may_have_been_billed

        assert may_have_been_billed(exception) is expected
