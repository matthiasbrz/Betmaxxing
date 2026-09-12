"""Absent bookmaker and absent market are two different findings.

Two real `core` calls were made against a live provider. Both returned a valid
response for the right event, with no `winamax_fr` block at all. Both were
correctly reported as ``COVERAGE_MISSING``. But the detailed evidence read:

    markets_requested = ["h2h"]
    market_states     = {}
    markets_absent    = []
    selections_mapped = 0

Nothing there distinguishes *"the bookmaker was not quoted"* from *"the
bookmaker was quoted but did not offer h2h"*. Those are entirely different
facts: the first says nothing about the market, the second says the market is
missing. And ``markets_absent = []`` alongside ``markets_requested = ["h2h"]``
actively invites the wrong reading — that nothing was missing.

The credits were spent; the evidence has to be worth them. So:

* the bookmaker gets its own explicit state, ``OBSERVED`` or ``NOT_RETURNED``;
* every requested market gets exactly one terminal state, including
  ``NOT_EVALUATED_BOOKMAKER_ABSENT`` when there was no block to look in;
* the market map is **total** — ``set(market_states) == set(markets_requested)``
  for any receipt written after a network attempt whose market scope was known;
* ``markets_absent`` stays, but strictly derived, and can no longer contradict
  ``market_states``;
* the human and JSON output say it in words: bookmaker not returned, market not
  evaluated.

Everything here is synthetic. No payload, event id, participant or receipt from
the real 03B operations appears in this file or in the fixtures it uses.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from helpers_activation import (
    BOOKMAKER,
    EVENT_ID,
    FAKE_RECEIPT_SECRET,
    NOW,
    OTHER_BOOKMAKER,
    Recorder,
    core_args,
    discover_args,
    events_payload,
    install,
    iso_z,
    odds_payload,
    receipt_path,
    receipts_in,
    run,
    sports_payload,
)

FREE_HEADERS = {"x-requests-last": "0", "x-requests-remaining": "480"}
PAID_HEADERS = {"x-requests-last": "1", "x-requests-remaining": "479"}


def free_routes() -> dict[str, Any]:
    return {
        "/sports/": lambda _r: httpx.Response(200, json=events_payload(), headers=FREE_HEADERS),
        "/sports": lambda _r: httpx.Response(200, json=sports_payload(), headers=FREE_HEADERS),
    }


def approved(monkeypatch: pytest.MonkeyPatch, receipts: Path) -> str:
    install(monkeypatch, Recorder(free_routes()))
    result = run(*discover_args())
    assert result.exit_code == 0, result.stdout
    return str(receipt_path(receipts, "discover"))


def run_core_against(
    monkeypatch: pytest.MonkeyPatch, receipts: Path, payload: Any, *extra: str
) -> Any:
    """One `core` invocation against a synthetic grouped-odds response."""
    discovery = approved(monkeypatch, receipts)
    install(
        monkeypatch,
        Recorder({"/odds": lambda _r: httpx.Response(200, json=payload, headers=PAID_HEADERS)}),
    )
    return run(*core_args(discovery_receipt=discovery, extra=extra))


def core_receipt(receipts: Path) -> dict[str, Any]:
    matching = [r for r in receipts_in(receipts) if r["command"] == "core"]
    assert matching, "no core receipt was written"
    return matching[-1]


# ---------------------------------------------------------------------------
# Synthetic payload builders — never derived from a real response
# ---------------------------------------------------------------------------
def _no_bookmaker() -> list[dict[str, Any]]:
    """A valid event, quoted by nobody we asked for. The real 03B shape."""
    payload = odds_payload()
    payload[0]["bookmakers"] = []
    return payload


def _other_bookmaker_only() -> list[dict[str, Any]]:
    payload = odds_payload(bookmaker=OTHER_BOOKMAKER)
    return payload


def _bookmaker_without_h2h() -> list[dict[str, Any]]:
    """Bookmaker present, quoting a market we did not ask for."""
    payload = odds_payload()
    payload[0]["bookmakers"][0]["markets"] = [
        {
            "key": "totals",
            "outcomes": [
                {"name": "Over", "price": 1.90, "point": 2.5},
                {"name": "Under", "price": 1.90, "point": 2.5},
            ],
        }
    ]
    return payload


def _bookmaker_with_unusable_h2h() -> list[dict[str, Any]]:
    """h2h present but structurally unusable — one nameless outcome."""
    payload = odds_payload()
    payload[0]["bookmakers"][0]["markets"] = [{"key": "h2h", "outcomes": [{"price": 1.5}]}]
    return payload


# ---------------------------------------------------------------------------
# E1 — the bookmaker's own state
# ---------------------------------------------------------------------------
class TestTheBookmakerHasItsOwnState:
    def test_an_absent_bookmaker_is_stated_explicitly(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_core_against(monkeypatch, keyed, _no_bookmaker())
        receipt = core_receipt(keyed)
        assert receipt["bookmaker_state"] == "NOT_RETURNED"

    def test_a_response_quoting_only_another_bookmaker_is_still_not_returned(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """A response full of other bookmakers is not partial coverage of ours."""
        run_core_against(monkeypatch, keyed, _other_bookmaker_only())
        assert core_receipt(keyed)["bookmaker_state"] == "NOT_RETURNED"

    def test_a_present_bookmaker_is_observed(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_core_against(monkeypatch, keyed, odds_payload())
        assert core_receipt(keyed)["bookmaker_state"] == "OBSERVED"

    def test_it_is_observed_even_when_the_market_is_missing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """The two dimensions are independent; this is the case that proves it."""
        run_core_against(monkeypatch, keyed, _bookmaker_without_h2h())
        receipt = core_receipt(keyed)
        assert receipt["bookmaker_state"] == "OBSERVED"
        assert receipt["market_states"]["h2h"] == "NOT_RETURNED"

    def test_the_two_states_are_never_the_same_field(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_core_against(monkeypatch, keyed, _no_bookmaker())
        receipt = core_receipt(keyed)
        assert "bookmaker_state" in receipt
        assert "market_states" in receipt
        assert receipt["bookmaker_state"] not in receipt["market_states"].values()


# ---------------------------------------------------------------------------
# E1 — every requested market has exactly one terminal state
# ---------------------------------------------------------------------------
class TestTheMarketMapIsTotal:
    @pytest.mark.parametrize(
        ("label", "payload_factory", "expected"),
        [
            ("bookmaker-absent", _no_bookmaker, "NOT_EVALUATED_BOOKMAKER_ABSENT"),
            ("market-absent", _bookmaker_without_h2h, "NOT_RETURNED"),
            ("market-unusable", _bookmaker_with_unusable_h2h, "OBSERVED_REJECTED"),
            ("market-usable", odds_payload, "OBSERVED_MAPPED"),
        ],
    )
    def test_h2h_always_gets_exactly_one_state(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        label: str,
        payload_factory: Any,
        expected: str,
    ) -> None:
        run_core_against(monkeypatch, keyed, payload_factory())
        receipt = core_receipt(keyed)
        assert receipt["market_states"] == {"h2h": expected}, (
            f"{label}: h2h was not classified as {expected}"
        )

    @pytest.mark.parametrize(
        "payload_factory",
        [
            _no_bookmaker,
            _other_bookmaker_only,
            _bookmaker_without_h2h,
            _bookmaker_with_unusable_h2h,
            odds_payload,
        ],
    )
    def test_the_state_keys_equal_the_requested_markets(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        payload_factory: Any,
    ) -> None:
        """The invariant the two real receipts broke."""
        run_core_against(monkeypatch, keyed, payload_factory())
        receipt = core_receipt(keyed)
        assert set(receipt["market_states"]) == set(receipt["markets_requested"])

    def test_a_bookmaker_absent_market_is_not_reported_as_absent(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """We did not observe the market missing; we never got to look."""
        run_core_against(monkeypatch, keyed, _no_bookmaker())
        receipt = core_receipt(keyed)
        assert receipt["markets_absent"] == []
        assert receipt["markets_not_evaluated"] == ["h2h"]
        assert receipt["markets_observed"] == []

    def test_a_genuinely_absent_market_is_reported_as_absent(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_core_against(monkeypatch, keyed, _bookmaker_without_h2h())
        receipt = core_receipt(keyed)
        assert receipt["markets_absent"] == ["h2h"]
        assert receipt["markets_not_evaluated"] == []


class TestTheDerivedListsCannotContradictTheStates:
    """Every derived list is exactly a projection of `market_states`."""

    @pytest.mark.parametrize(
        "payload_factory",
        [_no_bookmaker, _bookmaker_without_h2h, _bookmaker_with_unusable_h2h, odds_payload],
    )
    def test_the_projections_partition_the_requested_markets(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        payload_factory: Any,
    ) -> None:
        run_core_against(monkeypatch, keyed, payload_factory())
        r = core_receipt(keyed)
        buckets = (
            r["markets_mapped"],
            r["markets_rejected"],
            r["markets_absent"],
            r["markets_not_evaluated"],
        )
        flat = [m for bucket in buckets for m in bucket]
        assert sorted(flat) == sorted(r["markets_requested"]), (
            "the derived lists do not partition the requested markets exactly once"
        )

    @pytest.mark.parametrize(
        "payload_factory", [_no_bookmaker, _bookmaker_without_h2h, odds_payload]
    )
    def test_markets_observed_is_exactly_what_was_looked_at(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        payload_factory: Any,
    ) -> None:
        run_core_against(monkeypatch, keyed, payload_factory())
        r = core_receipt(keyed)
        assert sorted(r["markets_observed"]) == sorted(r["markets_mapped"] + r["markets_rejected"])


# ---------------------------------------------------------------------------
# E1 — the rendering has to say it
# ---------------------------------------------------------------------------
class TestTheOutputSaysBookmakerNotReturnedMarketNotEvaluated:
    def test_the_human_output_states_both(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = run_core_against(monkeypatch, keyed, _no_bookmaker())
        text = result.stdout.lower()
        assert "non retourné" in text, "the output does not say the bookmaker was not returned"
        assert "non évalué" in text, "the output does not say the market was not evaluated"

    def test_the_human_output_never_implies_the_market_was_checked(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = run_core_against(monkeypatch, keyed, _no_bookmaker())
        assert "NOT_EVALUATED_BOOKMAKER_ABSENT" in result.stdout

    def test_the_json_output_carries_both_fields(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = run_core_against(monkeypatch, keyed, _no_bookmaker(), "--json")
        payload = json.loads(result.stdout)
        assert payload["bookmaker_state"] == "NOT_RETURNED"
        assert payload["market_states"] == {"h2h": "NOT_EVALUATED_BOOKMAKER_ABSENT"}

    def test_a_missing_market_reads_differently_from_an_absent_bookmaker(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        absent_book = run_core_against(monkeypatch, keyed, _no_bookmaker()).stdout
        for path in keyed.glob("*.json"):
            path.unlink()
        absent_market = run_core_against(monkeypatch, keyed, _bookmaker_without_h2h()).stdout
        assert absent_book != absent_market


# ---------------------------------------------------------------------------
# E4 — the success path, proved offline, promoting nothing
# ---------------------------------------------------------------------------
#: Built here, by hand, from the documented shape. It is not a recording: no
#: byte of it comes from the two real 03B calls, and the ids and names are
#: obviously synthetic so a reader cannot mistake it for evidence.
SYNTHETIC_EVENT_ID = "synthetic-fixture-event-0001"
SYNTHETIC_HOME = "Synthetic Home FC"
SYNTHETIC_AWAY = "Synthetic Away United"
SYNTHETIC_BOOKMAKER_STAMP = iso_z(NOW - timedelta(minutes=10))
SYNTHETIC_MARKET_STAMP = iso_z(NOW - timedelta(minutes=29))


def synthetic_grouped_odds(
    *,
    outcome_order: tuple[str, ...] = ("home", "draw", "away"),
    bookmakers_first: bool = True,
    market_level_stamp: bool = False,
) -> list[dict[str, Any]]:
    """A wholly synthetic grouped `/odds` response, contract-shaped.

    ``GROUPED_ODDS`` carries ``last_update`` on the **bookmaker** — the v4 guide
    is explicit that the market-level field belongs to the per-event endpoint
    (D-048). ``market_level_stamp`` adds one anyway, to prove the grouped parser
    ignores it rather than quietly preferring it.

    Order is a parameter because a real provider guarantees none: bookmakers,
    markets and outcomes may arrive in any sequence.
    """
    prices = {"home": 1.95, "draw": 3.40, "away": 3.80}
    names = {"home": SYNTHETIC_HOME, "draw": "Draw", "away": SYNTHETIC_AWAY}
    h2h: dict[str, Any] = {
        "key": "h2h",
        "outcomes": [{"name": names[k], "price": prices[k]} for k in outcome_order],
    }
    if market_level_stamp:
        h2h["last_update"] = SYNTHETIC_MARKET_STAMP

    ours: dict[str, Any] = {
        "key": BOOKMAKER,
        "title": "Synthetic Book (FR)",
        "last_update": SYNTHETIC_BOOKMAKER_STAMP,
        "markets": [h2h],
    }
    theirs: dict[str, Any] = {
        "key": OTHER_BOOKMAKER,
        "title": "Synthetic Other",
        "last_update": SYNTHETIC_BOOKMAKER_STAMP,
        "markets": [{"key": "h2h", "outcomes": [{"name": names["home"], "price": 2.0}]}],
    }
    books = [ours, theirs] if bookmakers_first else [theirs, ours]
    return [
        {
            "id": EVENT_ID,
            "sport_key": "soccer_france_ligue_one",
            "sport_title": "Synthetic League",
            "commence_time": iso_z(NOW + timedelta(hours=6)),
            "home_team": SYNTHETIC_HOME,
            "away_team": SYNTHETIC_AWAY,
            "bookmakers": books,
        }
    ]


class TestTheSyntheticCoreSuccessPath:
    """Response → shape check → ingestion → mapping → freshness → signed receipt.

    The contractual unit tests prove each link. This proves the chain, on a
    scenario whose bookmaker and market are both present — which the two real
    calls never reached, and which therefore had never been exercised end to end
    through the harness itself.
    """

    def test_it_reaches_core_live_verified(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = run_core_against(monkeypatch, keyed, synthetic_grouped_odds())
        assert result.exit_code == 0, result.stdout
        assert core_receipt(keyed)["status"] == "CORE_LIVE_VERIFIED"

    def test_the_bookmaker_and_the_market_are_both_positive(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_core_against(monkeypatch, keyed, synthetic_grouped_odds())
        r = core_receipt(keyed)
        assert r["bookmaker_state"] == "OBSERVED"
        assert r["market_states"] == {"h2h": "OBSERVED_MAPPED"}

    def test_three_football_outcomes_are_mapped(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_core_against(monkeypatch, keyed, synthetic_grouped_odds())
        assert core_receipt(keyed)["selections_mapped"] == 3

    def test_the_freshness_is_derived_per_market(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """Reported per market even in the grouped shape, and never as `now`."""
        run_core_against(monkeypatch, keyed, synthetic_grouped_odds())
        freshness = core_receipt(keyed)["freshness"]
        assert set(freshness) == {"h2h"}
        assert freshness["h2h"] == 600, "the bookmaker-level stamp was not used"

    def test_a_market_level_stamp_is_ignored_in_the_grouped_shape(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """D-048: the grouped endpoint's timestamp is the bookmaker's, full stop."""
        run_core_against(monkeypatch, keyed, synthetic_grouped_odds(market_level_stamp=True))
        assert core_receipt(keyed)["freshness"]["h2h"] == 600

    @pytest.mark.parametrize(
        "order",
        [("home", "draw", "away"), ("away", "home", "draw"), ("draw", "away", "home")],
        ids=["hda", "ahd", "dah"],
    )
    def test_the_outcome_order_is_not_assumed(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        order: tuple[str, ...],
    ) -> None:
        run_core_against(monkeypatch, keyed, synthetic_grouped_odds(outcome_order=order))
        r = core_receipt(keyed)
        assert r["status"] == "CORE_LIVE_VERIFIED"
        assert r["selections_mapped"] == 3

    @pytest.mark.parametrize("first", [True, False], ids=["ours-first", "ours-second"])
    def test_the_bookmaker_order_is_not_assumed(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None, first: bool
    ) -> None:
        run_core_against(monkeypatch, keyed, synthetic_grouped_odds(bookmakers_first=first))
        assert core_receipt(keyed)["status"] == "CORE_LIVE_VERIFIED"

    def test_the_receipt_is_signed_and_sanitised(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation as A

        run_core_against(monkeypatch, keyed, synthetic_grouped_odds())
        r = core_receipt(keyed)
        assert A.verify_receipt(
            {k: v for k, v in r.items() if k != "_filename"}, FAKE_RECEIPT_SECRET
        )
        blob = json.dumps(r)
        for forbidden in (
            SYNTHETIC_HOME,
            SYNTHETIC_AWAY,
            EVENT_ID,
            "outcomes",
            "price",
            "1.95",
            "3.40",
        ):
            assert forbidden not in blob, f"{forbidden!r} leaked into the receipt"

    def test_it_promotes_nothing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """A fixture cannot make a real adapter verified."""
        run_core_against(monkeypatch, keyed, synthetic_grouped_odds())
        r = core_receipt(keyed)
        assert r["adapter_status"] == "IMPLEMENTED_UNVERIFIED"
        assert r["model_impact"].startswith("aucun")

    def test_the_offline_proof_is_labelled_as_such(self) -> None:
        """This scenario's proof label may never claim a live verification."""
        from betmaxxing.providers.the_odds_api.activation import MappingProof

        assert MappingProof.OFFLINE_CONTRACT_VERIFIED.value == "OFFLINE_CONTRACT_VERIFIED"
        assert "LIVE" not in MappingProof.OFFLINE_CONTRACT_VERIFIED.value


class TestADiscoveryReportsNoBookmakerFinding:
    """`/events` carries no bookmaker information, so there is nothing to report.

    Defaulting the field to `NOT_RETURNED` on a discovery receipt would read as a
    finding about the bookmaker when nothing was ever asked about it — the same
    class of error as an empty market map meaning "nothing was missing".
    """

    def test_the_discovery_receipt_omits_the_bookmaker_state(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        assert run(*discover_args()).exit_code == 0
        discovery = [r for r in receipts_in(keyed) if r["command"] == "discover"][-1]
        assert "bookmaker_state" not in discovery

    def test_it_still_names_the_bookmaker_the_operator_asked_about(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """The scope is recorded; only the *finding* is absent."""
        install(monkeypatch, Recorder(free_routes()))
        run(*discover_args())
        discovery = [r for r in receipts_in(keyed) if r["command"] == "discover"][-1]
        assert discovery["bookmaker"] == BOOKMAKER

    def test_a_core_receipt_always_carries_one(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_core_against(monkeypatch, keyed, odds_payload())
        assert core_receipt(keyed)["bookmaker_state"] == "OBSERVED"
