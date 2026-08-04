"""Probability intervals."""

from __future__ import annotations

import pytest

from betmaxxing.engine.uncertainty import (
    Z_90,
    Z_95,
    blend_effective_sample_size,
    penalise_for_missing_data,
    wilson_interval,
)


class TestWilsonInterval:
    def test_brackets_the_point_estimate(self) -> None:
        interval = wilson_interval(0.6, 100)
        assert interval.lower < interval.point < interval.upper

    def test_narrows_as_sample_size_grows(self) -> None:
        small = wilson_interval(0.5, 25)
        large = wilson_interval(0.5, 400)
        assert large.half_width < small.half_width

    def test_widens_with_a_higher_confidence_level(self) -> None:
        ninety = wilson_interval(0.5, 100, Z_90)
        ninety_five = wilson_interval(0.5, 100, Z_95)
        assert ninety_five.half_width > ninety.half_width

    def test_stays_strictly_inside_the_unit_interval(self) -> None:
        # Extreme probability with a tiny sample: the naive normal approximation
        # would return a negative lower bound here.
        interval = wilson_interval(0.99, 3)
        assert 0.0 < interval.lower < interval.upper < 1.0

    def test_half_width_is_symmetric_around_the_reported_bounds(self) -> None:
        interval = wilson_interval(0.4, 200)
        assert interval.half_width == pytest.approx((interval.upper - interval.lower) / 2)

    @pytest.mark.parametrize("bad_p", [0.0, 1.0, -0.2, 1.4])
    def test_rejects_degenerate_probabilities(self, bad_p: float) -> None:
        with pytest.raises(ValueError):
            wilson_interval(bad_p, 100)

    @pytest.mark.parametrize("bad_n", [0, -5])
    def test_rejects_non_positive_sample_sizes(self, bad_n: float) -> None:
        with pytest.raises(ValueError):
            wilson_interval(0.5, bad_n)


class TestBlendEffectiveSampleSize:
    def test_weakest_component_dominates(self) -> None:
        blended = blend_effective_sample_size({"form": 500.0, "lineups": 10.0})
        assert blended < 10.0

    def test_single_component_is_returned_unchanged(self) -> None:
        assert blend_effective_sample_size({"only": 42.0}) == pytest.approx(42.0)

    def test_rejects_empty_or_invalid_components(self) -> None:
        with pytest.raises(ValueError):
            blend_effective_sample_size({})
        with pytest.raises(ValueError):
            blend_effective_sample_size({"bad": 0.0})


class TestPenaliseForMissingData:
    def test_complete_data_leaves_sample_size_untouched(self) -> None:
        assert penalise_for_missing_data(100.0, 1.0) == pytest.approx(100.0)

    def test_penalty_is_quadratic(self) -> None:
        assert penalise_for_missing_data(100.0, 0.5) == pytest.approx(25.0)

    def test_rejects_completeness_outside_unit_interval(self) -> None:
        with pytest.raises(ValueError):
            penalise_for_missing_data(100.0, 1.2)
