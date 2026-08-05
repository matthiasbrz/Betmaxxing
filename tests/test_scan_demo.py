"""End-to-end scan behaviour in demo mode.

Acceptance criteria covered here: demo runs keyless and deterministically, a scan
always returns one of three statuses, real modes refuse to run without a source,
and nothing synthetic is ever labelled as real.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import (
    CollectionStatus,
    RejectionCode,
    ScanStatus,
    UncertaintyStatus,
)
from betmaxxing.engine.acquisition import run_scan


@pytest.fixture
def result(settings: Settings, now: datetime):  # type: ignore[no-untyped-def]
    return run_scan(settings, now=now)


class TestDemoScan:
    def test_returns_candidates(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.status is ScanStatus.CANDIDATES_FOUND
        assert result.candidates

    def test_status_is_always_one_of_three(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.status in {
            ScanStatus.CANDIDATES_FOUND,
            ScanStatus.NO_BET,
            ScanStatus.DATA_UNAVAILABLE,
        }

    def test_is_deterministic(self, settings: Settings, now: datetime) -> None:
        """Same instant, same configuration, same decisions — byte for byte."""
        first = run_scan(settings, now=now)
        second = run_scan(settings, now=now)

        def decisions(scan):  # type: ignore[no-untyped-def]
            # Keyed on content, not on the opaque internal id: identity is
            # assigned by the identity service and is deliberately not derived
            # from the fixture, so it varies across fresh databases.
            return [
                (
                    c.event.label,
                    c.selection.key,
                    c.value.decimal_odds,
                    round(c.value.ev, 12),
                    round(c.value.ev_conservative, 12),
                )
                for c in scan.candidates
            ]

        assert decisions(first) == decisions(second)
        assert first.rejections_summary == second.rejections_summary

    def test_carries_a_disclaimer(self, result) -> None:  # type: ignore[no-untyped-def]
        assert "Aide à la décision" in result.disclaimer
        assert "Aucune garantie de gain" in result.disclaimer

    def test_records_the_config_fingerprint(self, result, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        assert result.config_fingerprint == settings.fingerprint()
        assert all(c.config_fingerprint == settings.fingerprint() for c in result.candidates)

    def test_thresholds_are_published_with_the_result(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.thresholds["min_ev"] == 0.03
        assert "devig_method" in result.thresholds


class TestSyntheticDataIsLabelled:
    def test_every_candidate_is_marked_as_coming_from_the_demo_book(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.provider == "demo"
            assert candidate.bookmaker == "DEMO_BOOK"

    def test_provider_health_states_the_data_is_synthetic(self, result) -> None:  # type: ignore[no-untyped-def]
        details = " ".join(p.detail for p in result.data_health.providers)
        assert "synthétique" in details


class TestWindow:
    def test_events_outside_the_window_are_rejected_not_dropped(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.rejections_summary.get(RejectionCode.OUTSIDE_WINDOW.value, 0) >= 1

    def test_every_candidate_starts_inside_the_window(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert result.window["from"] < candidate.event.start_time_utc <= result.window["to"]

    def test_window_length_follows_configuration(self, settings: Settings, now: datetime) -> None:
        narrow = run_scan(settings.model_copy(update={"window_hours": 4.0}), now=now)
        assert narrow.window["to"] - narrow.window["from"] == timedelta(hours=4)
        wide = run_scan(settings, now=now)
        assert len(narrow.candidates) <= len(wide.candidates)


class TestRejectionsAreExplicit:
    def test_the_scenario_exercises_multiple_rejection_codes(self, result) -> None:  # type: ignore[no-untyped-def]
        assert len(result.rejections_summary) >= 5

    def test_stale_odds_are_rejected(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.rejections_summary.get(RejectionCode.ODDS_STALE.value, 0) >= 1

    def test_incomplete_market_is_rejected(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.rejections_summary.get(RejectionCode.MARKET_INCOMPLETE.value, 0) >= 1

    def test_ambiguous_event_mapping_is_rejected(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.rejections_summary.get(RejectionCode.EVENT_MAPPING_AMBIGUOUS.value, 0) >= 1

    def test_every_rejection_carries_a_detail(self, result) -> None:  # type: ignore[no-untyped-def]
        assert all(r.detail for r in result.rejections)

    def test_summary_counts_match_the_rejection_list(self, result) -> None:  # type: ignore[no-untyped-def]
        assert sum(result.rejections_summary.values()) == len(result.rejections)


class TestCandidateContent:
    def test_every_candidate_reports_both_implied_probabilities_or_says_why_not(
        self, result
    ) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            value = candidate.value
            assert value.implied_probability_raw > 0
            if value.implied_probability_novig is None:
                # Non-partition market: must be flagged in the risks, never silent.
                assert any("marge" in risk.lower() for risk in candidate.risks)
            else:
                assert value.devig_method

    def test_ev_matches_the_definition(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            value = candidate.value
            # No V1 demo market can push, so the payoff reduces to p*o - 1.
            assert value.push_probability == pytest.approx(0.0)
            assert value.ev == pytest.approx(
                value.conditional_win_probability * value.decimal_odds - 1.0
            )

    def test_conservative_ev_is_below_central_ev(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.value.ev_conservative is not None
            assert candidate.value.ev_conservative < candidate.value.ev

    def test_current_odds_clear_the_minimum_acceptable_odds(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.value.decimal_odds >= candidate.value.min_acceptable_odds

    def test_every_candidate_has_sourced_evidence(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.evidence
            for item in candidate.evidence:
                assert item.source
                assert item.as_of is not None

    def test_every_candidate_states_risks_and_invalidation_conditions(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.risks
            assert candidate.invalidation_conditions

    def test_model_validation_status_is_visible_on_every_candidate(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.probability.validation_status.value == "BACKTEST_ONLY"

    def test_explanation_is_rendered(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.explanation
            assert "EV" in candidate.explanation

    def test_no_stake_is_suggested_without_a_bankroll(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.stake is not None
            assert candidate.stake.amount == 0.0

    def test_candidates_are_ordered_by_expected_value(self, result) -> None:  # type: ignore[no-untyped-def]
        evs = [c.value.ev for c in result.candidates]
        assert evs == sorted(evs, reverse=True)


class TestUncertaintyContract:
    """D-019: demo uncertainty is labelled synthetic and never silent."""

    def test_demo_candidates_carry_synthetic_uncertainty(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            uncertainty = candidate.probability.uncertainty
            assert uncertainty.status is UncertaintyStatus.SYNTHETIC
            assert "SYNTHETIC" in uncertainty.warning
            assert any("SYNTH" in risk.upper() for risk in candidate.risks)

    def test_model_version_is_recorded(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.model_version
            assert candidate.probability.model_version == candidate.model_version

    def test_settlement_rule_is_recorded(self, result) -> None:  # type: ignore[no-untyped-def]
        for candidate in result.candidates:
            assert candidate.value.settlement_rule
            assert candidate.value.payoff_outcomes


class TestNoBetIsANormalOutcome:
    def test_strict_thresholds_produce_no_bet_rather_than_a_forced_pick(
        self, settings: Settings, now: datetime
    ) -> None:
        strict = settings.model_copy(update={"min_ev": 0.95})
        result = run_scan(strict, now=now)
        assert result.status is ScanStatus.NO_BET
        assert result.candidates == []
        assert result.rejections


class TestRealModesRefuseWithoutASource:
    @pytest.mark.parametrize("mode", [RunMode.PAPER, RunMode.LIVE_ANALYSIS])
    def test_real_mode_reports_data_unavailable_not_demo_data(
        self, settings: Settings, now: datetime, mode: RunMode
    ) -> None:
        """The critical safety property: no silent substitution of demo data."""
        result = run_scan(settings.model_copy(update={"mode": mode}), now=now)
        assert result.status is ScanStatus.DATA_UNAVAILABLE
        assert result.candidates == []
        detail = " ".join(p.detail for p in result.data_health.providers)
        assert "démo n'est jamais" in detail or "aucun fournisseur de cotes réel" in detail.lower()
        assert result.collection_status is CollectionStatus.PROVIDER_ERROR

    def test_live_mode_names_the_missing_configuration(
        self, settings: Settings, now: datetime
    ) -> None:
        result = run_scan(settings.model_copy(update={"mode": RunMode.PAPER}), now=now)
        detail = " ".join(p.detail for p in result.data_health.providers)
        assert "BETMAXXING_ODDS_PROVIDER" in detail


class TestDataHealth:
    def test_counts_are_reported(self, result) -> None:  # type: ignore[no-untyped-def]
        health = result.data_health
        assert health.events_discovered > 0
        assert health.events_in_window > 0
        assert health.markets_evaluated > 0
        assert health.selections_priced > 0

    def test_stale_snapshots_are_counted(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.data_health.stale_snapshots >= 1
