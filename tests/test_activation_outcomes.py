"""Every network attempt leaves a trace, and absence is never success.

Two failures of accounting, and one of vocabulary.

**A billed call could vanish.** Receipts were written only after
``run_core()`` / ``run_additional()`` *returned*. A response that arrived, was
charged, and then failed validation — empty, wrong shape, cost above the ceiling,
401, 500, a read timeout the provider may well have billed — produced no receipt
at all. The credit was spent and the audit trail was silent, which is the exact
inverse of what an audit trail is for.

The rule now: once a request has been attempted, a sanitised receipt is written
whatever the terminal status. A refusal *before* the network still writes nothing
— inventing a consumption record for a call that never happened would be the same
error pointing the other way.

**Absence could pass for coverage.** ``run_additional()`` built an
``ADDITIONAL_LIVE_VERIFIED`` receipt as soon as the bookmaker appeared, without
requiring a single one of the five requested markets, let alone a mapped
selection. A response containing the bookmaker and none of the markets proves
neither coverage nor market-level timestamp parsing — it proves the endpoint
answered. Each market now carries an explicit state, and the step's status
follows from them.

**"Hard ceiling" claimed too much.** What the program bounds locally is the number
of attempts, the endpoints, the scope and the *estimated* cost under the published
contract. It cannot stop an external provider from repricing a request it has
already served; it can only notice the discrepancy in the headers. The four cost
words are kept distinct, and the documentation says which is which.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from helpers_activation import (
    ADDITIONAL_MARKET_KEYS,
    BOOKMAKER,
    EVENT_ID,
    SPORT,
    Recorder,
    additional_args,
    core_args,
    discover_args,
    event_odds_payload,
    events_payload,
    install,
    odds_payload,
    receipt_path,
    receipts_in,
    run,
    spend_the_second_core,
    sports_payload,
)

FREE_HEADERS = {"x-requests-last": "0", "x-requests-remaining": "480"}


def free_routes() -> dict[str, Any]:
    return {
        "/sports/": lambda _r: httpx.Response(200, json=events_payload(), headers=FREE_HEADERS),
        "/sports": lambda _r: httpx.Response(200, json=sports_payload(), headers=FREE_HEADERS),
    }


def chain(monkeypatch: pytest.MonkeyPatch, receipts: Path) -> Path:
    """Walk discover → core with clean responses, and return the core receipt."""
    install(monkeypatch, Recorder(free_routes()))
    assert run(*discover_args()).exit_code == 0

    install(
        monkeypatch,
        Recorder(
            {
                "/odds": lambda _r: httpx.Response(
                    200, json=odds_payload(), headers={"x-requests-last": "1"}
                )
            }
        ),
    )
    result = run(*core_args(discovery_receipt=str(receipt_path(receipts, "discover"))))
    assert result.exit_code == 0, result.stdout
    return receipt_path(receipts, "core")


def chain_to_additional(monkeypatch: pytest.MonkeyPatch, receipts: Path) -> Path:
    """The same walk, carried to the step the register puts `additional` after.

    `soccer_epl` spends two `core` before its five-market step, so the parent this
    returns is the **second** of them and the event is rank 2 of the discovery.
    """
    chain(monkeypatch, receipts)
    return Path(
        spend_the_second_core(
            monkeypatch,
            receipts,
            str(receipt_path(receipts, "discover")),
            headers={"x-requests-last": "1"},
        )
    )


# ---------------------------------------------------------------------------
# A receipt for every attempt
# ---------------------------------------------------------------------------
#: (label, route for `/odds`, expected terminal status)
CORE_FAILURES: list[tuple[str, Any, str]] = [
    (
        "empty-but-billed",
        lambda _r: httpx.Response(200, json=[], headers={"x-requests-last": "1"}),
        "COVERAGE_MISSING",
    ),
    (
        "bookmaker-absent",
        lambda _r: httpx.Response(
            200,
            json=[{**odds_payload()[0], "bookmakers": []}],
            headers={"x-requests-last": "1"},
        ),
        "COVERAGE_MISSING",
    ),
    (
        "wrong-shape",
        lambda _r: httpx.Response(
            200, json=[{"unexpected": True}], headers={"x-requests-last": "1"}
        ),
        "SCHEMA_MISMATCH",
    ),
    (
        "cost-above-ceiling",
        lambda _r: httpx.Response(200, json=odds_payload(), headers={"x-requests-last": "4"}),
        "COST_MISMATCH",
    ),
    (
        "cost-absent",
        lambda _r: httpx.Response(200, json=odds_payload(), headers={}),
        "COST_UNVERIFIED",
    ),
    ("unauthorised", lambda _r: httpx.Response(401, json={"message": "no"}), "AUTH_FAILED"),
    ("forbidden", lambda _r: httpx.Response(403, json={"message": "no"}), "AUTH_FAILED"),
    ("server-error", lambda _r: httpx.Response(500, json={}), "PROVIDER_UNAVAILABLE"),
    ("rate-limited", lambda _r: httpx.Response(429, json={}), "PROVIDER_UNAVAILABLE"),
    ("invalid-json", lambda _r: httpx.Response(200, content=b"<html>"), "PROVIDER_UNAVAILABLE"),
]


def _raise(exc: type[Exception], message: str = "boom") -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc(message, request=request)

    return handler


CORE_TRANSPORT_FAILURES: list[tuple[str, Any, bool]] = [
    # (label, route, whether the request could have reached the provider)
    ("connect-timeout", _raise(httpx.ConnectTimeout), False),
    ("connect-error", _raise(httpx.ConnectError), False),
    ("read-timeout", _raise(httpx.ReadTimeout), True),
    ("write-error", _raise(httpx.WriteError), True),
]


class TestEveryCoreAttemptWritesAReceipt:
    @pytest.mark.parametrize(
        ("route", "status"),
        [(route, status) for _label, route, status in CORE_FAILURES],
        ids=[label for label, _r, _s in CORE_FAILURES],
    )
    def test_a_failed_paid_call_is_still_recorded(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        route: Any,
        status: str,
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        assert run(*discover_args()).exit_code == 0
        discovery = receipt_path(keyed, "discover")

        install(monkeypatch, Recorder({"/odds": route}))
        result = run(*core_args(discovery_receipt=str(discovery)))
        assert result.exit_code != 0

        core = [r for r in receipts_in(keyed) if r["command"] == "core"]
        assert core, f"a billed attempt ending in {status} left no receipt"
        assert core[-1]["status"] == status
        assert core[-1]["network_attempted"] is True
        assert core[-1]["attempts"] == 1

    @pytest.mark.parametrize(
        ("route", "reached"),
        [(route, reached) for _label, route, reached in CORE_TRANSPORT_FAILURES],
        ids=[label for label, _r, _x in CORE_TRANSPORT_FAILURES],
    )
    def test_a_transport_failure_is_still_recorded(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        route: Any,
        reached: bool,
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        assert run(*discover_args()).exit_code == 0
        discovery = receipt_path(keyed, "discover")

        install(monkeypatch, Recorder({"/odds": route}))
        result = run(*core_args(discovery_receipt=str(discovery)))
        assert result.exit_code != 0

        core = [r for r in receipts_in(keyed) if r["command"] == "core"]
        assert core, "a transport failure on a paid endpoint left no receipt"
        assert core[-1]["status"] == "PROVIDER_UNAVAILABLE"
        assert core[-1]["network_attempted"] is True
        assert core[-1]["may_have_reached_provider"] is reached

    def test_a_possibly_billed_timeout_keeps_its_estimate(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """D-041, restated in the receipt: a read timeout is not free."""
        install(monkeypatch, Recorder(free_routes()))
        assert run(*discover_args()).exit_code == 0
        install(monkeypatch, Recorder({"/odds": _raise(httpx.ReadTimeout)}))
        run(*core_args(discovery_receipt=str(receipt_path(keyed, "discover"))))

        core = [r for r in receipts_in(keyed) if r["command"] == "core"][-1]
        assert core["observed_credits"] is None
        assert core["accounted_credits"] == 1

    def test_a_never_sent_failure_accounts_nothing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        assert run(*discover_args()).exit_code == 0
        install(monkeypatch, Recorder({"/odds": _raise(httpx.ConnectError)}))
        run(*core_args(discovery_receipt=str(receipt_path(keyed, "discover"))))

        core = [r for r in receipts_in(keyed) if r["command"] == "core"][-1]
        assert core["accounted_credits"] == 0
        assert core["may_have_reached_provider"] is False


class TestEveryDiscoverAttemptWritesAReceipt:
    @pytest.mark.parametrize(
        ("route", "status"),
        [
            (lambda _r: httpx.Response(200, json=[], headers=FREE_HEADERS), "COVERAGE_MISSING"),
            (
                lambda _r: httpx.Response(
                    200, json=sports_payload(active=False), headers=FREE_HEADERS
                ),
                "COVERAGE_MISSING",
            ),
            (lambda _r: httpx.Response(401, json={}), "AUTH_FAILED"),
            (lambda _r: httpx.Response(503, json={}), "PROVIDER_UNAVAILABLE"),
            (
                lambda _r: httpx.Response(200, json=sports_payload(), headers={}),
                "COST_UNVERIFIED",
            ),
        ],
        ids=["no-sport", "inactive", "unauthorised", "unavailable", "cost-absent"],
    )
    def test_a_failed_free_call_is_still_recorded(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        route: Any,
        status: str,
    ) -> None:
        install(monkeypatch, Recorder({"/sports": route}))
        result = run(*discover_args())
        assert result.exit_code != 0

        receipts = [r for r in receipts_in(keyed) if r["command"] == "discover"]
        assert receipts, f"a discovery attempt ending in {status} left no receipt"
        assert receipts[-1]["status"] == status
        assert receipts[-1]["network_attempted"] is True


class TestALocalRefusalWritesNothing:
    """No consumption record for a call that never happened."""

    @pytest.mark.parametrize(
        "args",
        [
            ("discover", "--sport", SPORT, "--bookmaker", BOOKMAKER),
            ("discover", "--sport", f"{SPORT},x", "--bookmaker", BOOKMAKER, "--allow-network"),
            ("discover", "--sport", SPORT, "--bookmaker", "a,b", "--allow-network"),
            (
                "discover",
                "--sport",
                SPORT,
                "--bookmaker",
                BOOKMAKER,
                "--window-hours",
                "48",
                "--allow-network",
            ),
        ],
        ids=["no-allow-network", "two-sports", "two-bookmakers", "window-too-wide"],
    )
    def test_discover_refused_locally_leaves_no_receipt(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        args: tuple[str, ...],
    ) -> None:
        recorder = Recorder(free_routes())
        install(monkeypatch, recorder)
        result = run(*args)
        assert result.exit_code != 0
        assert recorder.requests == []
        assert receipts_in(keyed) == []

    @pytest.mark.parametrize(
        ("max_credits", "ack"),
        [("1", "2"), ("2", "2"), ("0", "0"), ("1", None)],
        ids=["mismatched", "wrong-ceiling", "zero", "no-acknowledgement"],
    )
    def test_core_refused_locally_leaves_no_receipt(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        max_credits: str,
        ack: str | None,
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        assert run(*discover_args()).exit_code == 0
        before = len(receipts_in(keyed))

        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(
            *core_args(
                discovery_receipt=str(receipt_path(keyed, "discover")),
                max_credits=max_credits,
                acknowledge=ack,
            )
        )
        assert result.exit_code != 0
        assert recorder.requests == []
        assert len(receipts_in(keyed)) == before

    def test_a_local_refusal_reserves_no_credit(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.config import get_settings
        from betmaxxing.providers.budget import ProviderBudgetLedger
        from helpers_activation import NOW

        install(monkeypatch, Recorder(free_routes()))
        assert run(*discover_args()).exit_code == 0
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        run(
            *core_args(
                discovery_receipt=str(receipt_path(keyed, "discover")),
                max_credits="2",
                acknowledge="2",
            )
        )
        assert ProviderBudgetLedger(get_settings()).spent_today("the_odds_api", NOW) == 0

    def test_plan_writes_no_receipt_and_reads_no_secret(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from betmaxxing import config
        from betmaxxing.providers.the_odds_api import activation

        reads: list[str] = []
        original = config.Settings.resolved_the_odds_api_key.fget  # type: ignore[attr-defined]
        monkeypatch.setattr(
            config.Settings,
            "resolved_the_odds_api_key",
            property(lambda self: (reads.append("key"), original(self))[1]),
            raising=False,
        )
        secrets: list[str] = []
        real_secret = activation.receipt_secret
        monkeypatch.setattr(
            activation,
            "receipt_secret",
            lambda: (secrets.append("secret"), real_secret())[1],
        )

        result = run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")
        assert result.exit_code == 0, result.stdout
        assert reads == [], "plan read the API key"
        assert secrets == [], "plan read the receipt signing secret"
        assert receipts_in(keyed) == []


# ---------------------------------------------------------------------------
# Per-market classification
# ---------------------------------------------------------------------------
def _additional(
    monkeypatch: pytest.MonkeyPatch,
    core_receipt: Path,
    payload: Any,
    *,
    last: str = "5",
    extra: tuple[str, ...] = ("--json",),
) -> Any:
    install(
        monkeypatch,
        Recorder(
            {
                "/events/": lambda _r: httpx.Response(
                    200, json=payload, headers={"x-requests-last": last}
                )
            }
        ),
    )
    return run(*additional_args(core_receipt=str(core_receipt), extra=extra))


class TestAdditionalCoverageIsClassifiedPerMarket:
    def test_all_five_present_is_fully_verified(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        result = _additional(monkeypatch, core, event_odds_payload())
        payload = json.loads(result.stdout)
        assert payload["status"] == "ADDITIONAL_LIVE_VERIFIED"
        assert result.exit_code == 0
        assert payload["market_states"] == dict.fromkeys(ADDITIONAL_MARKET_KEYS, "OBSERVED_MAPPED")

    def test_none_returned_is_coverage_missing_not_success(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """The bookmaker is quoted, and not one requested market came back."""
        core = chain_to_additional(monkeypatch, keyed)
        payload = event_odds_payload(markets=())
        result = _additional(monkeypatch, core, payload)
        document = json.loads(result.stdout)
        assert document["status"] == "COVERAGE_MISSING", (
            "a response with the bookmaker and none of the five markets was reported "
            "as a verified activation"
        )
        assert result.exit_code != 0
        assert set(document["market_states"].values()) == {"NOT_RETURNED"}

    def test_a_partial_set_is_reported_as_partial(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        result = _additional(
            monkeypatch, core, event_odds_payload(markets=("draw_no_bet", "double_chance"))
        )
        document = json.loads(result.stdout)
        assert document["status"] == "ADDITIONAL_PARTIAL_COVERAGE"
        assert document["market_states"] == {
            "draw_no_bet": "OBSERVED_MAPPED",
            "double_chance": "OBSERVED_MAPPED",
            "h2h_3_way_h1": "NOT_RETURNED",
            "totals_h1": "NOT_RETURNED",
            "double_chance_h1": "NOT_RETURNED",
        }

    def test_a_returned_but_unmappable_market_is_rejected_not_missing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        result = _additional(
            monkeypatch,
            core,
            event_odds_payload(markets=("draw_no_bet", "double_chance"), broken=("double_chance",)),
        )
        document = json.loads(result.stdout)
        assert document["market_states"]["double_chance"] == "OBSERVED_REJECTED"
        assert document["market_states"]["draw_no_bet"] == "OBSERVED_MAPPED"

    def test_every_market_returned_but_none_mapped_is_not_a_success(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        result = _additional(monkeypatch, core, event_odds_payload(broken=ADDITIONAL_MARKET_KEYS))
        document = json.loads(result.stdout)
        assert document["status"] == "SCHEMA_MISMATCH"
        assert result.exit_code != 0
        assert set(document["market_states"].values()) == {"OBSERVED_REJECTED"}

    def test_a_market_without_a_timestamp_is_not_mapped(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """No timestamp means no provable freshness, so nothing is retained."""
        core = chain_to_additional(monkeypatch, keyed)
        result = _additional(monkeypatch, core, event_odds_payload(stamped=False))
        document = json.loads(result.stdout)
        assert document["status"] != "ADDITIONAL_LIVE_VERIFIED"
        assert "OBSERVED_MAPPED" not in set(document["market_states"].values())

    def test_the_receipt_keeps_the_per_market_granularity(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        _additional(monkeypatch, core, event_odds_payload(markets=("draw_no_bet",)), extra=())
        receipt = [r for r in receipts_in(keyed) if r["command"] == "additional"][-1]
        assert receipt["market_states"]["draw_no_bet"] == "OBSERVED_MAPPED"
        assert receipt["market_states"]["totals_h1"] == "NOT_RETURNED"

    def test_nothing_is_substituted_for_an_absent_market(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        recorder = Recorder(
            {
                "/events/": lambda _r: httpx.Response(
                    200,
                    json=event_odds_payload(markets=("draw_no_bet",)),
                    headers={"x-requests-last": "5"},
                )
            }
        )
        install(monkeypatch, recorder)
        run(*additional_args(core_receipt=str(core)))
        assert len(recorder.requests) == 1, "the harness retried or widened its request"
        assert all(BOOKMAKER in str(r.url) for r in recorder.requests)


class TestFreshnessStaysPerMarket:
    """D-048 again, this time end to end through the harness."""

    def test_five_markets_yield_five_distinct_ages(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        document = json.loads(_additional(monkeypatch, core, event_odds_payload()).stdout)
        assert len(set(document["freshness"].values())) == 5

    def test_the_reception_time_is_never_used_as_the_age(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        document = json.loads(_additional(monkeypatch, core, event_odds_payload()).stdout)
        assert all(age > 0 for age in document["freshness"].values())


# ---------------------------------------------------------------------------
# What the ceilings actually are
# ---------------------------------------------------------------------------
class TestTheCeilingVocabularyIsHonest:
    """A local program cannot bind an external company's invoice.

    It bounds what it *does* — how many requests, to which endpoints, over what
    scope — and it computes the cost those requests should carry under the
    published rule. If the provider charges otherwise, the harness can notice it
    in the headers and stop; it cannot prevent it. Calling that a "hard ceiling"
    overstates the guarantee, and an overstated guarantee is the kind that gets
    relied on.
    """

    def test_the_module_does_not_promise_a_hard_ceiling(self) -> None:
        from betmaxxing.providers.the_odds_api import activation

        assert "hard ceiling" not in (activation.__doc__ or "").lower()

    def test_the_bounds_are_named_separately(self) -> None:
        from betmaxxing.providers.the_odds_api.activation import LOCAL_BOUNDS, STEP_CEILINGS

        assert set(STEP_CEILINGS) == {"plan", "discover", "core", "additional"}
        # What the program itself enforces, per paid step.
        assert LOCAL_BOUNDS["core"]["max_requests"] == 1
        assert LOCAL_BOUNDS["core"]["max_events"] == 1
        assert LOCAL_BOUNDS["core"]["max_bookmakers"] == 1
        assert LOCAL_BOUNDS["core"]["max_markets"] == 1
        assert LOCAL_BOUNDS["additional"]["max_requests"] == 1
        assert LOCAL_BOUNDS["additional"]["max_markets"] == 5

    def test_the_plan_distinguishes_the_four_cost_words(self, workspace: Path) -> None:
        result = run(
            "plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6", "--json"
        )
        document = json.loads(result.stdout)
        assert document["cost_model"]["local_bound"]
        assert document["cost_model"]["estimated_contractual_ceiling"] == 6
        assert "observed" in document["cost_model"]
        assert "accounted" in document["cost_model"]

    def test_the_plan_says_the_provider_could_price_differently(self, workspace: Path) -> None:
        result = run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")
        assert "tarification" in result.stdout.lower() or "facturer" in result.stdout.lower()


class TestNoGlobalPromotion:
    """One event, at one instant, is a limited proof — not a verified adapter."""

    def test_the_runbook_does_not_offer_a_global_verified_status(self) -> None:
        text = Path("docs/provider-activation.md").read_text(encoding="utf-8")
        assert "`VERIFIED`" not in text, (
            "the runbook still tells the operator to promote the adapter globally "
            "on the strength of a single event"
        )

    def test_a_successful_run_says_the_adapter_stays_unverified(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        document = json.loads(_additional(monkeypatch, core, event_odds_payload()).stdout)
        assert document["adapter_status"] == "IMPLEMENTED_UNVERIFIED"
        assert document["model_impact"].startswith("aucun")

    def test_the_receipt_records_the_exact_scope_of_the_proof(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = chain_to_additional(monkeypatch, keyed)
        _additional(monkeypatch, core, event_odds_payload(), extra=())
        receipt = [r for r in receipts_in(keyed) if r["command"] == "additional"][-1]
        for field in ("endpoint", "sport_key", "bookmaker", "event_tag", "recorded_at"):
            assert receipt[field], f"{field} missing from the proof's scope"
        assert EVENT_ID not in json.dumps(receipt)
