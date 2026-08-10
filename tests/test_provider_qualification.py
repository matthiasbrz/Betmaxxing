"""The qualification evaluator: what it must refuse, and what it may conclude.

The protocol these tests enforce is written down first, in
``docs/provider-validation-protocol.md`` and D-071, and carries a version number.
That order matters: thresholds argued after the observations arrive are not
criteria, they are a description of whatever happened.

Every receipt here is synthetic and locally signed. Nothing opens a socket, no
real receipt is read, and the evaluator itself never touches the network — which
is why it can be tested purely.
"""

from __future__ import annotations

import json as jsonlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual

FOOTBALL = "soccer_france_ligue_one"
FOOTBALL_2 = "soccer_epl"
TENNIS = "tennis_atp_paris"
TENNIS_2 = "tennis_wta_madrid"
BOOK = "unibet"
#: After `QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC`: under protocol v2 a receipt
#: recorded before the protocol took effect is history, never qualification.
DAY_ONE = datetime(2026, 8, 10, 12, tzinfo=UTC)
DAY_TWO = datetime(2026, 8, 11, 12, tzinfo=UTC)
DAY_THREE = datetime(2026, 8, 12, 12, tzinfo=UTC)


def signed(**fields: Any) -> dict[str, Any]:
    """A signed synthetic receipt. Defaults describe an admissible core mapping."""
    moment: datetime = fields.pop("moment", DAY_ONE)
    document: dict[str, Any] = {
        "schema_version": 4,
        "qualification_protocol_version": qual.PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "provider_adapter_evidence_version": qual.PROVIDER_ADAPTER_EVIDENCE_VERSION,
        "receipt_id": fields.pop("receipt_id", "00" * 8),
        "command": "core",
        "status": str(act.ActivationStatus.CORE_LIVE_VERIFIED),
        "recorded_at": moment.isoformat(),
        "expires_at": (moment + act.RECEIPT_TTL).isoformat(),
        "sport_key": FOOTBALL,
        "bookmaker": BOOK,
        "network_attempted": True,
        "may_have_reached_provider": True,
        # Mandatory since protocol v4, and consistent with the network flag by
        # construction. The harness writes `attempts` on every receipt, so a fixture
        # that omitted it described a document the producer never emits; derived
        # rather than hard-coded so a case overriding the flag stays honest.
        "attempts": 1 if fields.get("network_attempted", True) is True else 0,
        "estimated_credits": 1,
        "observed_credits": 1,
        "accounted_credits": 1,
        "markets_requested": ["h2h"],
        "market_states": {"h2h": str(act.MarketState.OBSERVED_MAPPED)},
        "markets_mapped": ["h2h"],
        "selections_mapped": 3,
        "freshness": {"h2h": 600},
        "mapping_rejections": [],
        "event_tag": fields.pop("event_tag", "e" * 32),
        "bookmaker_state": str(act.BookmakerState.OBSERVED),
    }
    document.update(fields)
    document[act.SIGNATURE_FIELD] = act.sign_receipt(document)
    return document


def additional(**fields: Any) -> dict[str, Any]:
    """A signed synthetic `additional` receipt with all five markets mapped."""
    markets = list(act.ADDITIONAL_MARKETS)
    base: dict[str, Any] = {
        "command": "additional",
        "status": str(act.ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
        "estimated_credits": 5,
        "observed_credits": 5,
        "accounted_credits": 5,
        "markets_requested": markets,
        "market_states": {m: str(act.MarketState.OBSERVED_MAPPED) for m in markets},
        "markets_mapped": markets,
        "selections_mapped": 11,
        "freshness": dict.fromkeys(markets, 300),
    }
    base.update(fields)
    return signed(**base)


def core_set(
    *,
    sport_keys: tuple[str, ...],
    moments: tuple[datetime, ...],
    tags: tuple[str, ...],
) -> list[dict[str, Any]]:
    """One admissible core receipt per (sport_key, moment, tag) triple."""
    out: list[dict[str, Any]] = []
    for index, (key, moment, tag) in enumerate(
        zip(sport_keys, moments, tags, strict=True), start=1
    ):
        out.append(
            signed(
                receipt_id=f"{index:016x}",
                sport_key=key,
                moment=moment,
                event_tag=tag,
            )
        )
    return out


def football_core_passing() -> list[dict[str, Any]]:
    """Three events, two competitions, two UTC days — the football core threshold."""
    return core_set(
        sport_keys=(FOOTBALL, FOOTBALL_2, FOOTBALL),
        moments=(DAY_ONE, DAY_TWO, DAY_TWO),
        tags=("a" * 32, "b" * 32, "c" * 32),
    )


def tennis_core_passing() -> list[dict[str, Any]]:
    out = core_set(
        sport_keys=(TENNIS, TENNIS_2, TENNIS),
        moments=(DAY_ONE, DAY_TWO, DAY_THREE),
        tags=("d" * 32, "f" * 32, "0" * 32),
    )
    for index, receipt in enumerate(out, start=10):
        receipt["receipt_id"] = f"{index:016x}"
        receipt[act.SIGNATURE_FIELD] = act.sign_receipt(
            {k: v for k, v in receipt.items() if k != act.SIGNATURE_FIELD}
        )
    return out


def additional_football_passing() -> list[dict[str, Any]]:
    """Two events in two competitions, both with the five markets mapped."""
    return [
        additional(receipt_id="aa" * 8, sport_key=FOOTBALL, moment=DAY_ONE, event_tag="1" * 32),
        additional(receipt_id="bb" * 8, sport_key=FOOTBALL_2, moment=DAY_TWO, event_tag="2" * 32),
    ]


def result_for(document: dict[str, Any], criterion_id: str) -> dict[str, Any]:
    for entry in document["criteria_results"]:
        if entry["criterion_id"] == criterion_id:
            return entry
    raise AssertionError(f"no criterion {criterion_id} in {document['criteria_results']}")


def everything_passing() -> list[dict[str, Any]]:
    return football_core_passing() + tennis_core_passing() + additional_football_passing()


# ---------------------------------------------------------------------------
# 1-2. Nothing, and not-enough
# ---------------------------------------------------------------------------
class TestTheFloor:
    def test_no_receipt_at_all_is_insufficient_evidence(self) -> None:
        document = qual.evaluate([], 0)
        assert document["qualification_state"] == str(qual.QualificationState.INSUFFICIENT_EVIDENCE)
        assert document["eligible_for_human_promotion_review"] is False
        assert all(entry["passed"] is False for entry in document["criteria_results"])

    def test_one_successful_observation_does_not_qualify(self) -> None:
        document = qual.evaluate([signed()], 0)
        assert document["qualification_state"] == str(qual.QualificationState.INSUFFICIENT_EVIDENCE)
        core = result_for(document, "CORE_MAPPING_FOOTBALL")
        assert core["passed"] is False
        assert core["observed"]["events"] == 1
        assert core["required"]["events"] >= 2, "a single event must never be the threshold"
        assert core["missing"], "the reader must be told what is short"

    def test_the_protocol_version_is_reported(self) -> None:
        document = qual.evaluate([], 0)
        assert document["qualification_protocol_version"] == (
            qual.PROVIDER_VALIDATION_PROTOCOL_VERSION
        )


# ---------------------------------------------------------------------------
# 3-5. Duplication and diversity
# ---------------------------------------------------------------------------
class TestDeduplicationAndDiversity:
    def test_the_same_receipt_twice_counts_once(self) -> None:
        one = signed(receipt_id="cc" * 8)
        document = qual.evaluate([one, dict(one)], 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 1

    def test_two_receipts_for_the_same_event_are_not_two_events(self) -> None:
        first = signed(receipt_id="11" * 8, event_tag="z" * 32, moment=DAY_ONE)
        second = signed(receipt_id="22" * 8, event_tag="z" * 32, moment=DAY_TWO)
        observed = result_for(qual.evaluate([first, second], 0), "CORE_MAPPING_FOOTBALL")[
            "observed"
        ]
        assert observed["events"] == 1
        # The days still differ, and the evaluator says so without inflating events.
        assert observed["utc_days"] == 2

    def test_competitions_and_utc_days_are_counted_as_the_protocol_says(self) -> None:
        observed = result_for(qual.evaluate(football_core_passing(), 0), "CORE_MAPPING_FOOTBALL")[
            "observed"
        ]
        assert observed == {"events": 3, "competitions": 2, "utc_days": 2}


# ---------------------------------------------------------------------------
# 6-8. Evidence that proves nothing
# ---------------------------------------------------------------------------
class TestInadmissibleEvidence:
    def test_offline_contract_verified_is_never_live(self) -> None:
        offline = signed(receipt_id="dd" * 8, status="OFFLINE_CONTRACT_VERIFIED")
        document = qual.evaluate([offline], 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0

    def test_a_receipt_with_no_network_attempt_is_never_live(self) -> None:
        fixture = signed(receipt_id="ee" * 8, network_attempted=False)
        document = qual.evaluate([fixture], 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0

    def test_coverage_missing_proves_no_mapping(self) -> None:
        missing = signed(
            receipt_id="ff" * 8,
            status=str(act.ActivationStatus.COVERAGE_MISSING),
            bookmaker_state=str(act.BookmakerState.NOT_RETURNED),
            market_states={"h2h": str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)},
            markets_mapped=[],
            selections_mapped=0,
            freshness={},
        )
        document = qual.evaluate([missing], 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0

    def test_the_bookmaker_being_absent_proves_nothing_about_its_markets(self) -> None:
        absent = additional(
            receipt_id="ab" * 8,
            status=str(act.ActivationStatus.COVERAGE_MISSING),
            bookmaker_state=str(act.BookmakerState.NOT_RETURNED),
            market_states=dict.fromkeys(
                act.ADDITIONAL_MARKETS, str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)
            ),
            markets_mapped=[],
            selections_mapped=0,
            freshness={},
        )
        document = qual.evaluate([absent], 0)
        for market in act.ADDITIONAL_MARKETS:
            entry = result_for(document, f"ADDITIONAL_MAPPING_FOOTBALL_{market.upper()}")
            assert entry["observed"]["events"] == 0

    @pytest.mark.parametrize(
        "status",
        (
            act.ActivationStatus.COST_MISMATCH,
            act.ActivationStatus.COST_UNVERIFIED,
            act.ActivationStatus.AUTH_FAILED,
            act.ActivationStatus.PROVIDER_UNAVAILABLE,
        ),
    )
    def test_a_failure_status_never_satisfies_a_positive_criterion(
        self, status: act.ActivationStatus
    ) -> None:
        document = qual.evaluate([signed(receipt_id="ac" * 8, status=str(status))], 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0
        assert document["qualification_state"] != str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )


# ---------------------------------------------------------------------------
# 9. Freshness
# ---------------------------------------------------------------------------
class TestFreshness:
    def test_a_mapping_without_a_usable_timestamp_fails_the_freshness_criterion(self) -> None:
        stampless = [dict(r, freshness={}) for r in football_core_passing()]
        for receipt in stampless:
            receipt[act.SIGNATURE_FIELD] = act.sign_receipt(
                {k: v for k, v in receipt.items() if k != act.SIGNATURE_FIELD}
            )
        document = qual.evaluate(stampless, 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0

    def test_a_mapping_that_is_too_old_fails_the_freshness_criterion(self) -> None:
        old = [dict(r, freshness={"h2h": 99_999}) for r in football_core_passing()]
        for receipt in old:
            receipt[act.SIGNATURE_FIELD] = act.sign_receipt(
                {k: v for k, v in receipt.items() if k != act.SIGNATURE_FIELD}
            )
        document = qual.evaluate(old, 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0

    def test_the_threshold_is_a_protocol_literal(self) -> None:
        """Fixed, not anchored.

        This assertion used to compare the protocol threshold with the product's
        runtime `max_odds_age_seconds`. That identity held whatever the runtime
        value was — including 123 s from a `.env` — so it pinned the coupling
        instead of the protocol. Under v2 the threshold is a literal, and the fact
        that the product's default agrees today is recorded without being relied
        on.
        """
        from betmaxxing.config import Settings

        assert qual.PROTOCOL_MAX_ODDS_AGE_SECONDS == 900
        assert Settings.model_fields["max_odds_age_seconds"].default == 900


# ---------------------------------------------------------------------------
# 10-11. Markets and sports do not substitute for each other
# ---------------------------------------------------------------------------
class TestNoSubstitution:
    def test_the_five_additional_markets_are_evaluated_one_by_one(self) -> None:
        ids = {entry["criterion_id"] for entry in qual.evaluate([], 0)["criteria_results"]}
        for market in act.ADDITIONAL_MARKETS:
            assert f"ADDITIONAL_MAPPING_FOOTBALL_{market.upper()}" in ids

    def test_four_mapped_markets_do_not_carry_the_fifth(self) -> None:
        partial = list(act.ADDITIONAL_MARKETS)
        missing_one = partial[-1]
        states = {m: str(act.MarketState.OBSERVED_MAPPED) for m in partial}
        states[missing_one] = str(act.MarketState.NOT_RETURNED)
        receipts = [
            additional(
                receipt_id=f"a{index}" * 8,
                sport_key=key,
                moment=moment,
                event_tag=tag,
                status=str(act.ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE),
                market_states=states,
                markets_mapped=[m for m in partial if m != missing_one],
                freshness={m: 300 for m in partial if m != missing_one},
            )
            for index, (key, moment, tag) in enumerate(
                ((FOOTBALL, DAY_ONE, "3" * 32), (FOOTBALL_2, DAY_TWO, "4" * 32))
            )
        ]
        document = qual.evaluate(receipts, 0)
        for market in partial[:-1]:
            entry = result_for(document, f"ADDITIONAL_MAPPING_FOOTBALL_{market.upper()}")
            assert entry["passed"] is True, market
        last = result_for(document, f"ADDITIONAL_MAPPING_FOOTBALL_{missing_one.upper()}")
        assert last["passed"] is False

    def test_football_does_not_satisfy_the_tennis_criterion(self) -> None:
        document = qual.evaluate(football_core_passing(), 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["passed"] is True
        assert result_for(document, "CORE_MAPPING_TENNIS")["passed"] is False

    def test_tennis_does_not_satisfy_the_football_criterion(self) -> None:
        document = qual.evaluate(tennis_core_passing(), 0)
        assert result_for(document, "CORE_MAPPING_TENNIS")["passed"] is True
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["passed"] is False


# ---------------------------------------------------------------------------
# 12-15. Schema versions, signatures, expiry
# ---------------------------------------------------------------------------
class TestProvenance:
    def test_v2_is_readable_history_and_qualifies_nothing(self) -> None:
        """Reversed on purpose, and the reversal is the correction.

        Protocol v1 let v2 support the core criteria because `selections_mapped`
        means the same in both schemas. True, and beside the point: a v2 receipt
        cannot say which protocol judged it or which parser produced it, so it
        cannot be *current* evidence. It stays readable, honoured for chaining,
        and counted in the historical block.
        """
        receipts = [dict(r, schema_version=2) for r in football_core_passing()]
        for receipt in receipts:
            receipt[act.SIGNATURE_FIELD] = act.sign_receipt(
                {k: v for k, v in receipt.items() if k != act.SIGNATURE_FIELD}
            )
        document = qual.evaluate(receipts, 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["passed"] is False
        assert document["qualification_historical_nonqualifying_receipts"] == 3
        assert document["qualification_unverifiable_receipts"] == 0

    def test_v2_does_not_contribute_to_a_per_market_criterion(self) -> None:
        """v2's market map was partial, so it cannot establish one market's state."""
        receipts = [dict(r, schema_version=2) for r in additional_football_passing()]
        for receipt in receipts:
            receipt[act.SIGNATURE_FIELD] = act.sign_receipt(
                {k: v for k, v in receipt.items() if k != act.SIGNATURE_FIELD}
            )
        document = qual.evaluate(receipts, 0)
        for market in act.ADDITIONAL_MARKETS:
            entry = result_for(document, f"ADDITIONAL_MAPPING_FOOTBALL_{market.upper()}")
            assert entry["observed"]["events"] == 0, market

    @pytest.mark.parametrize("version", (1, 3, 5, 99, None, "3"))
    def test_v1_v3_and_unknown_schemas_never_contribute(self, version: object) -> None:
        receipts = [dict(r, schema_version=version) for r in football_core_passing()]
        document = qual.evaluate(receipts, 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0

    def test_an_invalid_signature_is_unverifiable_and_never_evidence(self) -> None:
        tampered = [dict(r, signature="00" * 32) for r in football_core_passing()]
        document = qual.evaluate(tampered, 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0

    def test_unverifiable_receipts_are_reported_and_never_used(self) -> None:
        document = qual.evaluate([], 7)
        assert document["qualification_unverifiable_receipts"] == 7
        assert document["qualification_admissible_receipts"] == 0

    def test_an_expired_receipt_remains_historical_evidence(self) -> None:
        """Expiry refuses a *parent*. It does not un-happen the call that was made."""
        expired = [
            dict(r, expires_at=(DAY_ONE - timedelta(hours=1)).isoformat())
            for r in football_core_passing()
        ]
        for receipt in expired:
            receipt[act.SIGNATURE_FIELD] = act.sign_receipt(
                {k: v for k, v in receipt.items() if k != act.SIGNATURE_FIELD}
            )
        document = qual.evaluate(expired, 0)
        assert result_for(document, "CORE_MAPPING_FOOTBALL")["passed"] is True

    def test_expiry_still_refuses_a_receipt_as_authority(self, workspace: Path) -> None:
        """The other half of the same distinction, unchanged by this tranche."""
        stale = signed(
            receipt_id="ad" * 8,
            moment=DAY_ONE - timedelta(days=3),
            command="discover",
            status=str(act.ActivationStatus.DISCOVERY_VERIFIED),
        )
        workspace.mkdir(parents=True, exist_ok=True)
        path = workspace / "stale.json"
        path.write_text(jsonlib.dumps(stale), encoding="utf-8")
        with pytest.raises(act.Refused):
            act.load_parent(
                str(path),
                command="core",
                status=act.ActivationStatus.DISCOVERY_VERIFIED,
                sport=FOOTBALL,
                bookmaker=BOOK,
                now=DAY_ONE,
            )


# ---------------------------------------------------------------------------
# 16-17. Cost, conflict, and the ceiling on what the machine may conclude
# ---------------------------------------------------------------------------
class TestVerdicts:
    def test_a_nonconforming_cost_fails_the_cost_criterion(self) -> None:
        receipts = everything_passing()
        receipts.append(signed(receipt_id="ae" * 8, status=str(act.ActivationStatus.COST_MISMATCH)))
        document = qual.evaluate(receipts, 0)
        assert result_for(document, "COST_CONFORMITY")["passed"] is False
        assert document["qualification_state"] != str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )

    def test_a_self_contradicting_receipt_is_a_conflict_not_a_pass(self) -> None:
        """Mapped selections with no mapped market: one of the two fields is wrong."""
        broken = signed(
            receipt_id="af" * 8,
            selections_mapped=4,
            market_states={"h2h": str(act.MarketState.NOT_RETURNED)},
            markets_mapped=[],
        )
        document = qual.evaluate([*everything_passing(), broken], 0)
        assert document["qualification_state"] == str(qual.QualificationState.EVIDENCE_CONFLICT)
        assert document["eligible_for_human_promotion_review"] is False
        assert document["evidence_conflicts"], "the conflict must be named"

    def test_all_criteria_met_reaches_the_review_gate_and_stops_there(self) -> None:
        document = qual.evaluate(everything_passing(), 0)
        assert [e["criterion_id"] for e in document["criteria_results"] if not e["passed"]] == []
        assert document["qualification_state"] == str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )
        assert document["eligible_for_human_promotion_review"] is True

    def test_the_machine_has_no_verified_verdict_to_reach(self) -> None:
        assert "VERIFIED" not in {str(state) for state in qual.QualificationState}

    def test_meeting_every_criterion_does_not_promote_the_adapter(self) -> None:
        state = act.build_activation_state(everything_passing(), 0)
        assert state["adapter_state"] == "IMPLEMENTED_UNVERIFIED"
        assert state["qualification_state"] == str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )

    def test_the_criteria_order_is_stable(self) -> None:
        first = [e["criterion_id"] for e in qual.evaluate([], 0)["criteria_results"]]
        second = [
            e["criterion_id"] for e in qual.evaluate(everything_passing(), 0)["criteria_results"]
        ]
        assert first == second


# ---------------------------------------------------------------------------
# 18-20. The command, its output, and the absence of a socket
# ---------------------------------------------------------------------------
class TestTheStatusCommand:
    def _write_all(self, directory: Path, receipts: list[dict[str, Any]]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for receipt in receipts:
            (directory / f"{receipt['receipt_id']}.json").write_text(
                jsonlib.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
            )

    def test_the_json_output_carries_the_block_and_parses_with_colour_forced(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from helpers_activation import run

        monkeypatch.setenv("FORCE_COLOR", "1")
        self._write_all(workspace, everything_passing())
        result = run("status", "--json")
        assert result.exit_code == 0
        payload = jsonlib.loads(result.stdout)
        assert payload["qualification_protocol_version"] == (
            qual.PROVIDER_VALIDATION_PROTOCOL_VERSION
        )
        assert payload["qualification_state"] == str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )
        assert payload["eligible_for_human_promotion_review"] is True
        assert "\x1b[" not in result.stdout

    def test_the_human_output_says_what_is_missing(self, workspace: Path) -> None:
        from helpers_activation import run

        self._write_all(workspace, [signed(receipt_id="b1" * 8)])
        result = run("status")
        assert result.exit_code == 0
        assert "INSUFFICIENT_EVIDENCE" in result.stdout
        assert "CORE_MAPPING_FOOTBALL" in result.stdout

    def test_every_criterion_entry_exposes_the_documented_fields(self) -> None:
        for entry in qual.evaluate(everything_passing(), 0)["criteria_results"]:
            assert set(entry) >= {
                "criterion_id",
                "passed",
                "observed",
                "required",
                "missing",
                "scope",
            }

    def test_the_output_leaks_no_odds_key_team_or_raw_receipt(self, workspace: Path) -> None:
        from helpers_activation import FAKE_KEY, run

        self._write_all(workspace, everything_passing())
        result = run("status", "--json")
        for forbidden in (FAKE_KEY, "1.63", "Olympique", "apiKey=", "signature", "://"):
            assert forbidden not in result.stdout, forbidden
        # The local HMAC tags *are* printed, in the coverage block and only there:
        # that is what bounds an observation to one event without ever naming it
        # (D-062). The assertion this replaces looked for a sentinel the fixture
        # never produces — `everything_passing()` uses a, b, c, d, f, 0, 1 and 2 —
        # so it could not fail, and its comment said the opposite of the truth.
        payload = jsonlib.loads(result.stdout)
        injected = {str(receipt["event_tag"]) for receipt in everything_passing()}
        shown = {
            observation["event_tag"] for observation in payload["bookmaker_coverage_observations"]
        }
        assert injected <= shown, injected - shown
        elsewhere = jsonlib.dumps([payload["criteria_results"], payload["qualification_reasons"]])
        for tag in injected:
            assert tag not in elsewhere, tag

    def test_evaluation_opens_no_socket(self, workspace: Path) -> None:
        """`conftest` blocks outbound connections; this asserts we never even try."""
        document = qual.evaluate(everything_passing(), 0)
        assert document["qualification_state"] == str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )
