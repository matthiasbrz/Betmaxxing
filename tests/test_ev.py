"""The value formulas. Acceptance criterion: margin, fair odds, EV, conservative
EV and minimum acceptable odds are all covered by tests."""

from __future__ import annotations

import pytest

from betmaxxing.engine.ev import (
    EvError,
    ValueMath,
    expected_value,
    expected_value_pct,
    fair_odds,
    implied_probability,
    kelly_fraction,
    min_acceptable_odds,
)


class TestImpliedProbability:
    def test_is_reciprocal_of_odds(self) -> None:
        assert implied_probability(2.0) == pytest.approx(0.5)
        assert implied_probability(4.0) == pytest.approx(0.25)
        assert implied_probability(1.25) == pytest.approx(0.8)

    def test_rejects_odds_at_or_below_one(self) -> None:
        with pytest.raises(EvError):
            implied_probability(1.0)
        with pytest.raises(EvError):
            implied_probability(0.5)


class TestFairOdds:
    def test_is_reciprocal_of_probability(self) -> None:
        assert fair_odds(0.5) == pytest.approx(2.0)
        assert fair_odds(0.25) == pytest.approx(4.0)

    def test_round_trips_with_implied_probability(self) -> None:
        for odds in (1.2, 1.9, 2.5, 6.0):
            assert fair_odds(implied_probability(odds)) == pytest.approx(odds)

    @pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5])
    def test_rejects_probabilities_outside_open_unit_interval(self, bad: float) -> None:
        with pytest.raises(EvError):
            fair_odds(bad)


class TestExpectedValue:
    def test_matches_definition(self) -> None:
        # p * o - 1
        assert expected_value(0.5, 2.10) == pytest.approx(0.05)
        assert expected_value(0.226, 4.66) == pytest.approx(0.05316, abs=1e-5)

    def test_is_zero_at_fair_odds(self) -> None:
        for p in (0.1, 0.35, 0.6, 0.9):
            assert expected_value(p, fair_odds(p)) == pytest.approx(0.0, abs=1e-12)

    def test_percentage_is_hundred_times_fraction(self) -> None:
        assert expected_value_pct(0.5, 2.10) == pytest.approx(5.0)


class TestMinAcceptableOdds:
    def test_equals_fair_odds_at_zero_threshold(self) -> None:
        assert min_acceptable_odds(0.4, 0.0) == pytest.approx(fair_odds(0.4))

    def test_produces_exactly_the_threshold_ev(self) -> None:
        p, threshold = 0.45, 0.03
        odds = min_acceptable_odds(p, threshold)
        assert expected_value(p, odds) == pytest.approx(threshold)

    def test_increases_with_threshold(self) -> None:
        assert min_acceptable_odds(0.5, 0.05) > min_acceptable_odds(0.5, 0.02)


class TestKellyFraction:
    def test_matches_closed_form(self) -> None:
        # (p*o - 1) / (o - 1)
        assert kelly_fraction(0.6, 2.0) == pytest.approx(0.2)

    def test_is_zero_at_fair_odds(self) -> None:
        assert kelly_fraction(0.5, 2.0) == pytest.approx(0.0)

    def test_is_negative_without_edge(self) -> None:
        assert kelly_fraction(0.4, 2.0) < 0


class TestValueMath:
    def test_conservative_ev_uses_the_lower_bound(self) -> None:
        maths = ValueMath(
            odds=2.0,
            probability=0.55,
            probability_lower=0.50,
            probability_upper=0.60,
            ev_threshold=0.03,
        )
        assert maths.ev == pytest.approx(0.10)
        assert maths.ev_conservative == pytest.approx(0.0)
        assert maths.ev_upper == pytest.approx(0.20)

    def test_conservative_ev_is_never_above_central_ev(self) -> None:
        maths = ValueMath(
            odds=3.2,
            probability=0.35,
            probability_lower=0.30,
            probability_upper=0.41,
            ev_threshold=0.03,
        )
        assert maths.ev_conservative < maths.ev < maths.ev_upper

    def test_sensitivity_equals_probability_times_tick(self) -> None:
        maths = ValueMath(
            odds=2.0,
            probability=0.55,
            probability_lower=0.5,
            probability_upper=0.6,
            ev_threshold=0.0,
        )
        # dEV/do == p exactly, so a 0.01 move is worth 0.01 * p.
        assert maths.sensitivity == pytest.approx(0.0055)
        moved = ValueMath(
            odds=2.01,
            probability=0.55,
            probability_lower=0.5,
            probability_upper=0.6,
            ev_threshold=0.0,
        )
        assert moved.ev - maths.ev == pytest.approx(maths.sensitivity, abs=1e-12)

    def test_as_dict_exposes_every_published_figure(self) -> None:
        maths = ValueMath(
            odds=1.76,
            probability=0.6145,
            probability_lower=0.5719,
            probability_upper=0.6556,
            ev_threshold=0.03,
        )
        payload = maths.as_dict()
        for key in (
            "implied_probability_raw",
            "fair_odds",
            "ev",
            "ev_conservative",
            "min_acceptable_odds",
            "ev_sensitivity_per_odds_tick",
        ):
            assert key in payload
        assert payload["ev_pct"] == pytest.approx(100 * payload["ev"])
