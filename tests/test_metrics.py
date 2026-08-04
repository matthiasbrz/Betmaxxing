"""Evaluation metrics, checked against values derivable by hand."""

from __future__ import annotations

import math

import pytest

from betmaxxing.evaluation.metrics import (
    betting_performance,
    bootstrap_yield_interval,
    brier_score,
    calibration_curve,
    closing_line_value,
    expected_calibration_error,
    interval_coverage,
    log_loss,
)


class TestLogLoss:
    def test_perfect_prediction_scores_near_zero(self) -> None:
        assert log_loss([0.999999, 0.000001], [1, 0]) == pytest.approx(0.0, abs=1e-5)

    def test_coin_flip_scores_ln_two(self) -> None:
        assert log_loss([0.5, 0.5], [1, 0]) == pytest.approx(math.log(2))

    def test_confident_and_wrong_is_heavily_penalised(self) -> None:
        assert log_loss([0.01], [1]) > log_loss([0.5], [1])

    def test_rejects_mismatched_lengths(self) -> None:
        with pytest.raises(ValueError):
            log_loss([0.5], [1, 0])

    def test_rejects_non_binary_outcomes(self) -> None:
        with pytest.raises(ValueError):
            log_loss([0.5], [2])


class TestBrierScore:
    def test_perfect_prediction_is_zero(self) -> None:
        assert brier_score([1.0, 0.0], [1, 0]) == pytest.approx(0.0)

    def test_coin_flip_is_one_quarter(self) -> None:
        assert brier_score([0.5, 0.5], [1, 0]) == pytest.approx(0.25)

    def test_worst_case_is_one(self) -> None:
        assert brier_score([0.0], [1]) == pytest.approx(1.0)


class TestCalibration:
    def test_perfectly_calibrated_predictions_have_zero_error(self) -> None:
        # 10 predictions at 0.5, exactly 5 of which come in.
        probabilities = [0.5] * 10
        outcomes = [1, 0] * 5
        assert expected_calibration_error(probabilities, outcomes, bins=10) == pytest.approx(0.0)

    def test_overconfident_predictions_show_a_gap(self) -> None:
        probabilities = [0.9] * 10
        outcomes = [1] * 5 + [0] * 5
        assert expected_calibration_error(probabilities, outcomes, bins=10) == pytest.approx(0.4)

    def test_curve_omits_empty_bins(self) -> None:
        curve = calibration_curve([0.05, 0.06], [0, 1], bins=10)
        assert len(curve) == 1
        assert curve[0].count == 2

    def test_probability_of_one_lands_in_the_last_bin(self) -> None:
        curve = calibration_curve([1.0], [1], bins=10)
        assert len(curve) == 1
        assert curve[0].upper == 1.0

    def test_rejects_too_few_bins(self) -> None:
        with pytest.raises(ValueError):
            calibration_curve([0.5], [1], bins=1)


class TestIntervalCoverage:
    def test_well_calibrated_intervals_achieve_full_coverage(self) -> None:
        lowers = [0.45] * 10
        uppers = [0.55] * 10
        outcomes = [1, 0] * 5  # observed frequency 0.5, inside [0.45, 0.55]
        assert interval_coverage(lowers, uppers, outcomes) == pytest.approx(1.0)

    def test_intervals_that_miss_the_truth_score_zero(self) -> None:
        lowers = [0.80] * 10
        uppers = [0.90] * 10
        outcomes = [1, 0] * 5  # observed 0.5, well outside the stated interval
        assert interval_coverage(lowers, uppers, outcomes) == pytest.approx(0.0)

    def test_rejects_mismatched_inputs(self) -> None:
        with pytest.raises(ValueError):
            interval_coverage([0.4], [0.6, 0.7], [1])


class TestBettingPerformance:
    def test_computes_profit_and_yield(self) -> None:
        # Two bets at 2.0, one wins: +1.0 and -1.0 = break-even.
        performance = betting_performance([2.0, 2.0], [1, 0])
        assert performance.profit == pytest.approx(0.0)
        assert performance.yield_pct == pytest.approx(0.0)
        assert performance.bets == 2
        assert performance.win_rate == pytest.approx(0.5)

    def test_profitable_run_has_positive_yield(self) -> None:
        performance = betting_performance([3.0, 3.0], [1, 0])
        assert performance.profit == pytest.approx(1.0)
        assert performance.yield_pct == pytest.approx(50.0)

    def test_drawdown_tracks_the_worst_decline_from_a_peak(self) -> None:
        # +1, then -1, -1: equity goes 1, 0, -1; peak 1, trough -1 -> drawdown 2.
        performance = betting_performance([2.0, 2.0, 2.0], [1, 0, 0])
        assert performance.max_drawdown == pytest.approx(2.0)

    def test_honours_variable_stakes(self) -> None:
        performance = betting_performance([2.0, 2.0], [1, 0], stakes=[10.0, 1.0])
        assert performance.staked == pytest.approx(11.0)
        assert performance.profit == pytest.approx(9.0)

    def test_rejects_mismatched_lengths(self) -> None:
        with pytest.raises(ValueError):
            betting_performance([2.0], [1, 0])


class TestBootstrap:
    def test_interval_brackets_the_point_estimate(self) -> None:
        odds = [2.0] * 100
        outcomes = [1, 0] * 50
        low, high = bootstrap_yield_interval(odds, outcomes, iterations=500)
        point = betting_performance(odds, outcomes).yield_pct
        assert low <= point <= high

    def test_is_reproducible_from_the_seed(self) -> None:
        odds = [2.5] * 60
        outcomes = [1, 0, 0] * 20
        first = bootstrap_yield_interval(odds, outcomes, iterations=300, seed=42)
        second = bootstrap_yield_interval(odds, outcomes, iterations=300, seed=42)
        assert first == second

    def test_small_samples_produce_a_wide_interval(self) -> None:
        """The point of reporting the interval at all.

        Ten bets cannot distinguish a good strategy from a lucky one, and the
        interval has to say so loudly.
        """
        low, high = bootstrap_yield_interval([3.0] * 10, [1, 0] * 5, iterations=500)
        assert high - low > 40.0

    def test_larger_samples_narrow_the_interval(self) -> None:
        small = bootstrap_yield_interval([3.0] * 20, [1, 0] * 10, iterations=500)
        large = bootstrap_yield_interval([3.0] * 400, [1, 0] * 200, iterations=500)
        assert (large[1] - large[0]) < (small[1] - small[0])


class TestClosingLineValue:
    def test_shortening_price_is_positive_clv(self) -> None:
        assert closing_line_value(2.10, 2.00) == pytest.approx(0.05)

    def test_drifting_price_is_negative_clv(self) -> None:
        assert closing_line_value(2.00, 2.10) < 0

    def test_rejects_invalid_odds(self) -> None:
        with pytest.raises(ValueError):
            closing_line_value(1.0, 2.0)
