"""Three costs, kept apart, and an unknown one that never becomes zero.

``_check_observed_cost(None, …)`` returned ``0``. That is the one substitution a
spending record may not make: an absent ``x-requests-last`` means *we do not know
what this call cost*, and the client already handles it correctly — it charges the
estimate, because under-counting is the direction a budget must never err in
(D-041). The receipt then contradicted the ledger by reporting nought.

Two consequences, both wrong in the same way:

* a free endpoint that answers without the header was declared
  ``DISCOVERY_VERIFIED`` with "observed 0 credits" as its proof. It proved
  nothing;
* a billed call without the header was recorded at zero credits while the ledger
  had just charged it one.

So one integer is replaced by three, and they are never conflated:

``estimated_credits``
    the pre-call bound, ``markets x effective region units``.
``observed_credits``
    the integer from ``x-requests-last``, or ``null`` when it is missing or
    unusable. Never a stand-in.
``accounted_credits``
    what the spend record keeps: the observation when there is one, the estimate
    otherwise. Conservative by construction.

A missing observation is not a failure of the provider, but it *is* a failure to
verify — status ``COST_UNVERIFIED`` — and an unverified step may not authorise
the next one.

No network: every response here comes from an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from helpers_activation import (
    BOOKMAKER,
    NOW,
    SPORT,
    Recorder,
    core_args,
    events_payload,
    install,
    odds_payload,
    receipts_in,
    run,
    sports_payload,
)


# ---------------------------------------------------------------------------
# The primitive
# ---------------------------------------------------------------------------
class TestAnUnknownCostStaysUnknown:
    def test_a_missing_header_is_none_not_zero(self) -> None:
        from betmaxxing.providers.the_odds_api.activation import observed_credits_of

        assert observed_credits_of({}) is None

    @pytest.mark.parametrize(
        "raw",
        ["", "many", "1.5", "-1", "None", " "],
        ids=["empty", "text", "float", "negative", "null-text", "blank"],
    )
    def test_an_unusable_header_is_none_not_zero(self, raw: str) -> None:
        """A negative or non-integer charge is not a charge of zero."""
        from betmaxxing.providers.the_odds_api.activation import observed_credits_of

        assert observed_credits_of({"x-requests-last": raw}) is None

    @pytest.mark.parametrize(("raw", "expected"), [("0", 0), ("1", 1), ("5", 5), ("42", 42)])
    def test_a_usable_header_is_read_verbatim(self, raw: str, expected: int) -> None:
        from betmaxxing.providers.the_odds_api.activation import observed_credits_of

        assert observed_credits_of({"x-requests-last": raw}) == expected


class TestAccountedCredits:
    """What the spend record keeps when the provider did not say."""

    def test_the_observation_wins_when_present(self) -> None:
        from betmaxxing.providers.the_odds_api.activation import accounted_credits_of

        assert accounted_credits_of(estimated=5, observed=2) == 2

    def test_zero_observed_is_honoured_not_treated_as_missing(self) -> None:
        """v4: an empty response is not charged. Nought is a real answer."""
        from betmaxxing.providers.the_odds_api.activation import accounted_credits_of

        assert accounted_credits_of(estimated=5, observed=0) == 0

    def test_the_estimate_is_kept_when_the_observation_is_missing(self) -> None:
        from betmaxxing.providers.the_odds_api.activation import accounted_credits_of

        assert accounted_credits_of(estimated=5, observed=None) == 5

    def test_it_never_returns_zero_for_an_unknown_billed_call(self) -> None:
        from betmaxxing.providers.the_odds_api.activation import accounted_credits_of

        assert accounted_credits_of(estimated=1, observed=None) == 1


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------
def _discover(monkeypatch: pytest.MonkeyPatch, recorder: Recorder, *extra: str) -> Any:
    install(monkeypatch, recorder)
    return run("discover", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--allow-network", *extra)


def _headers(**extra: str) -> dict[str, str]:
    return {"x-requests-remaining": "480", "x-requests-used": "20", **extra}


def _free_routes(last: str | None) -> dict[str, Any]:
    headers = _headers() if last is None else _headers(**{"x-requests-last": last})

    def sports(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sports_payload(), headers=headers)

    def events(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=events_payload(), headers=headers)

    return {"/sports/": events, "/sports": sports}


class TestDiscoverRefusesToProveACostItDidNotSee:
    def test_a_missing_header_is_cost_unverified(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = _discover(monkeypatch, Recorder(_free_routes(None)), "--json")
        payload = json.loads(result.stdout)
        assert payload["status"] == "COST_UNVERIFIED", (
            "a free endpoint that never reported its cost was accepted as proof of costing nothing"
        )

    def test_a_missing_header_does_not_report_zero_observed(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = _discover(monkeypatch, Recorder(_free_routes(None)), "--json")
        payload = json.loads(result.stdout)
        assert payload["observed_credits"] is None
        assert payload["estimated_credits"] == 0
        assert payload["accounted_credits"] == 0

    def test_a_missing_header_fails_the_command(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = _discover(monkeypatch, Recorder(_free_routes(None)))
        assert result.exit_code != 0

    def test_an_explicit_zero_is_discovery_verified(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = _discover(monkeypatch, Recorder(_free_routes("0")), "--json")
        payload = json.loads(result.stdout)
        assert payload["status"] == "DISCOVERY_VERIFIED"
        assert payload["observed_credits"] == 0
        assert payload["accounted_credits"] == 0

    @pytest.mark.parametrize("last", ["1", "3"], ids=["one", "three"])
    def test_a_charged_free_endpoint_is_a_cost_mismatch(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None, last: str
    ) -> None:
        result = _discover(monkeypatch, Recorder(_free_routes(last)))
        assert result.exit_code != 0
        assert "COST_MISMATCH" in result.stdout

    def test_an_unverified_discovery_cannot_authorise_core(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """The whole point of the chain: an unproven step authorises nothing."""
        _discover(monkeypatch, Recorder(_free_routes(None)))
        receipts = receipts_in(keyed)
        assert receipts, "discover wrote no receipt at all"
        unverified = [r for r in receipts if r["status"] == "COST_UNVERIFIED"]
        assert unverified, f"no COST_UNVERIFIED receipt among {[r['status'] for r in receipts]}"

        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        path = keyed / unverified[-1]["_filename"]
        result = run(*core_args(discovery_receipt=str(path)))
        assert result.exit_code != 0
        assert recorder.requests == [], "core called the provider on an unverified discovery"


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------
class TestCoreKeepsTheThreeCostsApart:
    def _run(self, monkeypatch: pytest.MonkeyPatch, keyed: Path, last: str | None) -> Any:
        headers = _headers() if last is None else _headers(**{"x-requests-last": last})
        discovery = _discover(monkeypatch, Recorder(_free_routes("0")))
        assert discovery.exit_code == 0, discovery.stdout
        receipt = keyed / receipts_in(keyed)[-1]["_filename"]

        recorder = Recorder(
            {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=headers)}
        )
        install(monkeypatch, recorder)
        return run(*core_args(discovery_receipt=str(receipt), extra=("--json",)))

    def test_an_observed_one_is_core_live_verified(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        payload = json.loads(self._run(monkeypatch, keyed, "1").stdout)
        assert payload["status"] == "CORE_LIVE_VERIFIED"
        assert (payload["estimated_credits"], payload["observed_credits"]) == (1, 1)
        assert payload["accounted_credits"] == 1

    def test_an_observed_zero_is_honoured(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        payload = json.loads(self._run(monkeypatch, keyed, "0").stdout)
        assert payload["observed_credits"] == 0
        assert payload["accounted_credits"] == 0
        assert payload["status"] == "CORE_LIVE_VERIFIED"

    def test_a_missing_header_keeps_the_estimate_and_refuses_to_verify(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        payload = json.loads(self._run(monkeypatch, keyed, None).stdout)
        assert payload["status"] == "COST_UNVERIFIED"
        assert payload["observed_credits"] is None
        assert payload["accounted_credits"] == 1, (
            "a billed call whose cost the provider did not report was recorded at zero"
        )

    @pytest.mark.parametrize("last", ["-2", "oops"], ids=["negative", "garbage"])
    def test_an_unusable_header_is_treated_as_missing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None, last: str
    ) -> None:
        payload = json.loads(self._run(monkeypatch, keyed, last).stdout)
        assert payload["observed_credits"] is None
        assert payload["accounted_credits"] == 1

    @pytest.mark.parametrize("last", ["2", "5"], ids=["two", "five"])
    def test_an_observation_above_the_ceiling_is_a_mismatch(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None, last: str
    ) -> None:
        result = self._run(monkeypatch, keyed, last)
        assert result.exit_code != 0
        assert json.loads(result.stdout)["status"] == "COST_MISMATCH"

    def test_a_low_observation_does_not_rewrite_the_attempt_count(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """Being charged 0 does not mean the request was not made."""
        payload = json.loads(self._run(monkeypatch, keyed, "0").stdout)
        assert payload["attempts"] == 1
        assert payload["network_attempted"] is True

    def test_an_unverified_core_cannot_authorise_additional(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from helpers_activation import additional_args

        self._run(monkeypatch, keyed, None)
        unverified = [r for r in receipts_in(keyed) if r["command"] == "core"]
        assert unverified and unverified[-1]["status"] == "COST_UNVERIFIED"

        recorder = Recorder({"/events/": {}})
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=str(keyed / unverified[-1]["_filename"])))
        assert result.exit_code != 0
        assert recorder.requests == []


class TestTheDurableLedgerStaysTheAuthority:
    """The receipt reports; the ledger of 02 ter accounts. Neither replaces the other."""

    def test_a_billed_call_without_a_header_still_charges_the_ledger(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.config import get_settings
        from betmaxxing.providers.budget import ProviderBudgetLedger

        discovery = _discover(monkeypatch, Recorder(_free_routes("0")))
        assert discovery.exit_code == 0
        receipt = keyed / receipts_in(keyed)[-1]["_filename"]

        recorder = Recorder(
            {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=_headers())}
        )
        install(monkeypatch, recorder)
        run(*core_args(discovery_receipt=str(receipt)))

        spent = ProviderBudgetLedger(get_settings()).spent_today("the_odds_api", NOW)
        assert spent == 1, f"the ledger recorded {spent} for a call of unknown cost"

    def test_the_free_step_never_charges_the_ledger(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.config import get_settings
        from betmaxxing.providers.budget import ProviderBudgetLedger

        _discover(monkeypatch, Recorder(_free_routes("0")))
        assert ProviderBudgetLedger(get_settings()).spent_today("the_odds_api", NOW) == 0


class TestTheReceiptAgreesWithTheLedger:
    def test_accounted_credits_match_what_was_charged(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.config import get_settings
        from betmaxxing.providers.budget import ProviderBudgetLedger

        discovery = _discover(monkeypatch, Recorder(_free_routes("0")))
        assert discovery.exit_code == 0
        receipt = keyed / receipts_in(keyed)[-1]["_filename"]
        recorder = Recorder(
            {
                "/odds": lambda _r: httpx.Response(
                    200, json=odds_payload(), headers=_headers(**{"x-requests-last": "1"})
                )
            }
        )
        install(monkeypatch, recorder)
        run(*core_args(discovery_receipt=str(receipt)))

        core = [r for r in receipts_in(keyed) if r["command"] == "core"][-1]
        spent = ProviderBudgetLedger(get_settings()).spent_today("the_odds_api", NOW)
        assert core["accounted_credits"] == spent == 1
