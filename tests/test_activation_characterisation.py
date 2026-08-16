"""What D-060 to D-064 already guarantee, pinned before 03C-1 adds anything.

03C-1's first draft proposed re-implementing five properties that the merged tree
already has. These tests exist so that claim is checkable rather than argued: each
one asserts a decision's observable consequence on the *unmodified* source. They
were green the moment they were written, and this file says so plainly rather than
presenting them as a discovery.

They are also the safety net for the qualification evaluator added next door: if
the evaluator ever needs one of these vocabularies to mean something slightly
different, one of these tests fails first.

Nothing here opens a socket and nothing here reads a real receipt.
"""

from __future__ import annotations

import json as jsonlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from helpers_activation import FAKE_RECEIPT_SECRET

pytestmark = pytest.mark.usefixtures("workspace")


def _signed(**fields: Any) -> dict[str, Any]:
    """A receipt with a real signature, built from synthetic fields only."""
    from betmaxxing.providers.the_odds_api import qualification as qual

    document: dict[str, Any] = {
        "schema_version": act.RECEIPT_SCHEMA_VERSION,
        # A v4 receipt is exactly one that carries these two stamps under its
        # signature. Declaring the version without them described a document
        # `build_receipt` never writes.
        "qualification_protocol_version": qual.PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "provider_adapter_evidence_version": qual.PROVIDER_ADAPTER_EVIDENCE_VERSION,
        "receipt_id": fields.pop("receipt_id", "aa00bb11cc22dd33"),
        "command": "core",
        "status": str(act.ActivationStatus.CORE_LIVE_VERIFIED),
        "recorded_at": "2026-08-04T12:00:00+00:00",
        "expires_at": "2026-08-04T18:00:00+00:00",
        "sport_key": "soccer_france_ligue_one",
        "bookmaker": "unibet",
        "network_attempted": True,
        # Both mandatory on every receipt the harness writes, and both missing here
        # until protocol v4 started reading them. Without them this fixture described
        # a document `build_receipt` never produces, and the dimension it exercises —
        # a live mapping observation — now legitimately refuses such a receipt.
        # Derived from the network flag so a case overriding it stays consistent.
        "may_have_reached_provider": fields.get("network_attempted", True) is True,
        "attempts": 1 if fields.get("network_attempted", True) is True else 0,
        "estimated_credits": 1,
        "observed_credits": 1,
        "accounted_credits": 1,
        "markets_requested": ["h2h"],
        "market_states": {"h2h": str(act.MarketState.OBSERVED_MAPPED)},
        "selections_mapped": 3,
        "freshness": {"h2h": 600},
        "mapping_rejections": [],
        "event_tag": "0" * 32,
        "bookmaker_state": str(act.BookmakerState.OBSERVED),
    }
    document.update(fields)
    document[act.SIGNATURE_FIELD] = act.sign_receipt(document, FAKE_RECEIPT_SECRET)
    return document


def _write(directory: Path, document: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{document['receipt_id']}.json"
    path.write_text(jsonlib.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    return path


class TestD060TheBookmakerIsItsOwnDimension:
    def test_the_state_exists_and_has_exactly_two_values(self) -> None:
        assert {str(s) for s in act.BookmakerState} == {"OBSERVED", "NOT_RETURNED"}

    def test_a_market_can_say_it_was_never_evaluated(self) -> None:
        assert str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT) in {
            str(s) for s in act.MarketState
        }

    def test_the_market_map_is_total_over_the_requested_markets(self) -> None:
        """v3's contract: every requested market carries a state, none is silent."""
        attempt = act.Attempt(
            command="additional",
            sport="soccer_france_ligue_one",
            bookmaker="unibet",
            window=(datetime(2026, 8, 4, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)),
            ceiling=5,
            now=datetime(2026, 8, 4, 12, tzinfo=UTC),
        )
        attempt.markets_requested = list(act.ADDITIONAL_MARKETS)
        attempt.bookmaker_state = str(act.BookmakerState.NOT_RETURNED)
        for market in attempt.markets_requested:
            attempt.market_states[market] = str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)
        receipt = act.build_receipt(attempt, act.ActivationStatus.COVERAGE_MISSING, "s" * 64)
        assert set(receipt["market_states"]) == set(act.ADDITIONAL_MARKETS)
        assert receipt["markets_not_evaluated"] == list(act.ADDITIONAL_MARKETS)
        assert receipt["markets_absent"] == []

    def test_the_projections_partition_the_requested_markets_exactly_once(self) -> None:
        attempt = act.Attempt(
            command="additional",
            sport="soccer_france_ligue_one",
            bookmaker="unibet",
            window=(datetime(2026, 8, 4, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)),
            ceiling=5,
            now=datetime(2026, 8, 4, 12, tzinfo=UTC),
        )
        attempt.markets_requested = list(act.ADDITIONAL_MARKETS)
        states = [
            act.MarketState.OBSERVED_MAPPED,
            act.MarketState.OBSERVED_REJECTED,
            act.MarketState.NOT_RETURNED,
            act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT,
            act.MarketState.OBSERVED_MAPPED,
        ]
        for market, state in zip(attempt.markets_requested, states, strict=True):
            attempt.market_states[market] = str(state)
        receipt = act.build_receipt(attempt, act.ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE, "s")
        partition = (
            receipt["markets_mapped"]
            + receipt["markets_rejected"]
            + receipt["markets_absent"]
            + receipt["markets_not_evaluated"]
        )
        assert sorted(partition) == sorted(act.ADDITIONAL_MARKETS)
        assert len(partition) == len(set(partition))


class TestD061ADiscoverySaysWhichOfThreeThingsHappened:
    def test_a_discovery_receipt_carries_the_three_counters(self) -> None:
        attempt = act.Attempt(
            command="discover",
            sport="soccer_france_ligue_one",
            bookmaker="unibet",
            window=(datetime(2026, 8, 4, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)),
            ceiling=5,
            now=datetime(2026, 8, 4, 12, tzinfo=UTC),
        )
        attempt.events_returned = 9
        attempt.events_in_window = 4
        attempt.events_admissible = 2
        receipt = act.build_receipt(attempt, act.ActivationStatus.DISCOVERY_VERIFIED, "s")
        assert receipt["events_returned"] == 9
        assert receipt["events_in_window"] == 4
        assert receipt["events_admissible"] == 2

    def test_a_discovery_receipt_reports_no_bookmaker_state(self) -> None:
        """`/events` is asked nothing about the bookmaker, so it answers nothing."""
        attempt = act.Attempt(
            command="discover",
            sport="soccer_france_ligue_one",
            bookmaker="unibet",
            window=(datetime(2026, 8, 4, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)),
            ceiling=5,
            now=datetime(2026, 8, 4, 12, tzinfo=UTC),
        )
        receipt = act.build_receipt(attempt, act.ActivationStatus.DISCOVERY_VERIFIED, "s")
        assert "bookmaker_state" not in receipt

    def test_coverage_missing_is_a_status_of_its_own(self) -> None:
        assert str(act.ActivationStatus.COVERAGE_MISSING) == "COVERAGE_MISSING"
        assert act.ActivationStatus.COVERAGE_MISSING not in act.VERIFIED_STATUSES


class TestD062FiveProofDimensionsReadByStatus:
    def test_the_state_document_separates_the_five(self, workspace: Path) -> None:
        document = act.build_activation_state(act.audit_receipts())
        for field in (
            "adapter_state",
            "execution_state",
            "connectivity_and_cost_proof",
            "bookmaker_coverage_observations",
            "mapping_freshness_proof",
        ):
            assert field in document

    def test_an_empty_directory_is_an_empty_state_not_an_error(self, workspace: Path) -> None:
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert (list(receipts), unverifiable) == ([], 0)
        document = act.build_activation_state(_audit)
        assert document["execution_state"] == str(act.ExecutionState.NO_NETWORK_ATTEMPTED)
        assert document["mapping_freshness_proof"] == str(act.MappingProof.NOT_OBTAINED_LIVE)

    def test_an_unverifiable_file_is_counted_and_never_read(self, workspace: Path) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "broken.json").write_text("{not json", encoding="utf-8")
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert list(receipts) == []
        assert unverifiable == 1


class TestD063ReceiptsAreV4AndOlderSchemasStayReadable:
    """D-063's *policy* is unchanged; D-072 moved the current version to 4.

    Characterisation pinned "the current version is 3". That was correct until the
    protocol needed a receipt to name the protocol and parser versions it was
    produced under — fields whose absence is meaningful, so a new version rather
    than v3 with extras. What this class actually guards is the compatibility rule:
    older schemas are read, honoured and never rewritten. That rule still holds,
    and the numbers move with the authorised bump.
    """

    def test_the_current_version_is_four_and_older_ones_are_still_read(self) -> None:
        assert act.RECEIPT_SCHEMA_VERSION == 4
        assert frozenset({2, 3, 4}) == act.SUPPORTED_SCHEMA_VERSIONS

    def test_a_v3_receipt_is_read_without_being_rewritten(self, workspace: Path) -> None:
        document = _signed(receipt_id="beef0000beef0004", schema_version=3)
        path = _write(workspace, document)
        before = path.read_text(encoding="utf-8")
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert unverifiable == 0
        assert [r["schema_version"] for r in receipts] == [3]
        assert path.read_text(encoding="utf-8") == before

    def test_a_v2_receipt_is_read_without_being_rewritten(self, workspace: Path) -> None:
        document = _signed(receipt_id="beef0000beef0001", schema_version=2)
        path = _write(workspace, document)
        before = path.read_text(encoding="utf-8")
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert unverifiable == 0
        assert [r["schema_version"] for r in receipts] == [2]
        assert path.read_text(encoding="utf-8") == before

    def test_a_v1_receipt_is_refused_rather_than_upgraded(self, workspace: Path) -> None:
        document = _signed(receipt_id="beef0000beef0002", schema_version=1)
        _write(workspace, document)
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert list(receipts) == []
        assert unverifiable == 1


class TestD064AFixtureNeverEarnsALiveStatus:
    def test_the_offline_status_exists_and_differs_from_the_live_one(self) -> None:
        values = {str(s) for s in act.MappingProof}
        assert {"NOT_OBTAINED_LIVE", "OFFLINE_CONTRACT_VERIFIED", "OBTAINED_LIVE"} == values

    def test_the_state_never_reports_offline_as_live(self, workspace: Path) -> None:
        """`build_activation_state` derives the live proof from mapped selections only."""
        document = _signed(receipt_id="beef0000beef0003", selections_mapped=0)
        _write(workspace, document)
        _audit = act.audit_receipts()
        state = act.build_activation_state(_audit)
        assert state["mapping_freshness_proof"] == str(act.MappingProof.NOT_OBTAINED_LIVE)

    def test_a_single_live_observation_does_not_promote_the_adapter(self, workspace: Path) -> None:
        _write(workspace, _signed(receipt_id="beef0000beef0004"))
        _audit = act.audit_receipts()
        state = act.build_activation_state(_audit)
        assert state["mapping_freshness_proof"] == str(act.MappingProof.OBTAINED_LIVE)
        # …and the adapter is still exactly where it was.
        assert state["adapter_state"] == "IMPLEMENTED_UNVERIFIED"
        assert state["model_impact"].startswith("aucun")

    def test_an_expired_receipt_is_refused_as_authority(self, workspace: Path) -> None:
        stale = _signed(
            receipt_id="beef0000beef0005",
            recorded_at="2026-08-01T00:00:00+00:00",
            expires_at="2026-08-01T06:00:00+00:00",
        )
        path = _write(workspace, stale)
        with pytest.raises(act.Refused):
            act.load_parent(
                str(path),
                signing=FAKE_RECEIPT_SECRET,
                command="core",
                status=act.ActivationStatus.DISCOVERY_VERIFIED,
                sport="soccer_france_ligue_one",
                bookmaker="unibet",
                now=datetime(2026, 8, 4, 12, tzinfo=UTC),
            )
