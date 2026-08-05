"""The eligibility gate. Every rejection code must be reachable and every rule
must be able to block on its own."""

from __future__ import annotations

import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import RejectionCode, UncertaintyStatus, ValidationStatus
from betmaxxing.engine.eligibility import GateInput, evaluate


def passing(**overrides: object) -> GateInput:
    """A candidate that clears every gate, so each test can break exactly one."""
    base: dict[str, object] = {
        "ev": 0.07,
        "ev_conservative": 0.01,
        "uncertainty_status": UncertaintyStatus.ESTIMATED,
        "probability_half_width": 0.04,
        "odds": 1.76,
        "odds_age_seconds": 60.0,
        "data_quality": 0.95,
        "market_complete": True,
        "mapping_ambiguous": False,
        "in_window": True,
        "in_scope": True,
        "event_scheduled": True,
        "validation_status": ValidationStatus.BACKTEST_ONLY,
        "mode": RunMode.DEMO,
    }
    base.update(overrides)
    return GateInput(**base)  # type: ignore[arg-type]


@pytest.fixture
def config() -> Settings:
    return Settings(mode=RunMode.DEMO)


class TestPassingCandidate:
    def test_a_clean_candidate_passes(self, config: Settings) -> None:
        result = evaluate(passing(), config)
        assert result.passed
        assert result.codes == []


class TestIndividualRules:
    @pytest.mark.parametrize(
        ("override", "expected"),
        [
            ({"ev": 0.01}, RejectionCode.EV_TOO_LOW),
            ({"ev_conservative": -0.02}, RejectionCode.CONSERVATIVE_EV_NEGATIVE),
            ({"probability_half_width": 0.20}, RejectionCode.UNCERTAINTY_TOO_HIGH),
            ({"odds_age_seconds": 5400.0}, RejectionCode.ODDS_STALE),
            ({"data_quality": 0.10}, RejectionCode.LOW_DATA_QUALITY),
            ({"market_complete": False}, RejectionCode.MARKET_INCOMPLETE),
            ({"mapping_ambiguous": True}, RejectionCode.EVENT_MAPPING_AMBIGUOUS),
            ({"in_window": False}, RejectionCode.OUTSIDE_WINDOW),
            ({"in_scope": False}, RejectionCode.OUT_OF_SCOPE),
            ({"event_scheduled": False}, RejectionCode.EVENT_NOT_SCHEDULED),
            ({"odds": 1.05}, RejectionCode.ODDS_OUT_OF_RANGE),
            ({"odds": 25.0}, RejectionCode.ODDS_OUT_OF_RANGE),
        ],
    )
    def test_each_rule_blocks_on_its_own(
        self, override: dict[str, object], expected: RejectionCode, config: Settings
    ) -> None:
        result = evaluate(passing(**override), config)
        assert not result.passed
        assert expected in result.codes


class TestConjunctiveBehaviour:
    def test_reports_every_failure_not_just_the_first(self, config: Settings) -> None:
        result = evaluate(passing(ev=0.001, odds_age_seconds=9999.0, data_quality=0.1), config)
        assert {
            RejectionCode.EV_TOO_LOW,
            RejectionCode.ODDS_STALE,
            RejectionCode.LOW_DATA_QUALITY,
        } <= set(result.codes)

    def test_a_large_ev_cannot_buy_forgiveness_for_stale_data(self, config: Settings) -> None:
        """No scoring compromise: a huge edge on a stale price is still rejected."""
        result = evaluate(passing(ev=0.90, ev_conservative=0.60, odds_age_seconds=7200.0), config)
        assert not result.passed
        assert RejectionCode.ODDS_STALE in result.codes

    def test_every_failure_carries_a_human_readable_detail(self, config: Settings) -> None:
        result = evaluate(passing(ev=0.001), config)
        assert len(result.details) == len(result.codes)
        assert all(detail for detail in result.details)

    def test_primary_code_is_the_first_failure(self, config: Settings) -> None:
        result = evaluate(passing(in_scope=False, ev=0.0001), config)
        assert result.primary_code is RejectionCode.OUT_OF_SCOPE


class TestUncertaintyGate:
    """D-019: no usable uncertainty means no publication, whatever the EV."""

    def test_unavailable_uncertainty_blocks_publication(self, config: Settings) -> None:
        result = evaluate(
            passing(
                uncertainty_status=UncertaintyStatus.UNAVAILABLE,
                ev_conservative=None,
                probability_half_width=None,
            ),
            config,
        )
        assert not result.passed
        assert RejectionCode.UNCERTAINTY_UNAVAILABLE in result.codes

    def test_a_huge_ev_cannot_compensate_for_missing_uncertainty(self, config: Settings) -> None:
        result = evaluate(
            passing(
                ev=5.0,
                uncertainty_status=UncertaintyStatus.UNAVAILABLE,
                ev_conservative=None,
                probability_half_width=None,
            ),
            config,
        )
        assert not result.passed
        assert RejectionCode.UNCERTAINTY_UNAVAILABLE in result.codes

    @pytest.mark.parametrize("mode", [RunMode.PAPER, RunMode.LIVE_ANALYSIS])
    def test_synthetic_uncertainty_is_refused_outside_demo(self, mode: RunMode) -> None:
        config = Settings(mode=mode)
        result = evaluate(
            passing(
                uncertainty_status=UncertaintyStatus.SYNTHETIC,
                mode=mode,
                validation_status=ValidationStatus.LIVE_ANALYSIS,
            ),
            config,
        )
        assert not result.passed
        assert RejectionCode.UNCERTAINTY_UNAVAILABLE in result.codes

    def test_synthetic_uncertainty_is_allowed_in_demo(self, config: Settings) -> None:
        result = evaluate(passing(uncertainty_status=UncertaintyStatus.SYNTHETIC), config)
        assert result.passed

    def test_missing_conservative_ev_blocks_even_when_status_looks_fine(
        self, config: Settings
    ) -> None:
        result = evaluate(
            passing(uncertainty_status=UncertaintyStatus.ESTIMATED, ev_conservative=None),
            config,
        )
        assert not result.passed
        assert RejectionCode.UNCERTAINTY_UNAVAILABLE in result.codes


class TestModelValidationGate:
    def test_backtest_only_model_cannot_publish_in_live_analysis(self) -> None:
        config = Settings(mode=RunMode.LIVE_ANALYSIS)
        result = evaluate(
            passing(validation_status=ValidationStatus.BACKTEST_ONLY, mode=RunMode.LIVE_ANALYSIS),
            config,
        )
        assert not result.passed
        assert RejectionCode.MODEL_NOT_VALIDATED in result.codes

    def test_validated_model_may_publish_in_live_analysis(self) -> None:
        config = Settings(mode=RunMode.LIVE_ANALYSIS)
        result = evaluate(
            passing(validation_status=ValidationStatus.LIVE_ANALYSIS, mode=RunMode.LIVE_ANALYSIS),
            config,
        )
        assert result.passed

    def test_paper_mode_accepts_a_backtest_only_model(self) -> None:
        config = Settings(mode=RunMode.PAPER)
        result = evaluate(
            passing(validation_status=ValidationStatus.BACKTEST_ONLY, mode=RunMode.PAPER),
            config,
        )
        assert result.passed


class TestThresholdsAreConfigurable:
    def test_raising_the_ev_threshold_rejects_a_previously_passing_candidate(self) -> None:
        strict = Settings(mode=RunMode.DEMO, min_ev=0.15)
        assert not evaluate(passing(ev=0.07), strict).passed

    def test_tightening_uncertainty_rejects_a_wide_interval(self) -> None:
        strict = Settings(mode=RunMode.DEMO, max_prob_half_width=0.01)
        result = evaluate(passing(probability_half_width=0.04), strict)
        assert RejectionCode.UNCERTAINTY_TOO_HIGH in result.codes
