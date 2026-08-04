"""Football Dixon-Coles baseline.

The property that matters most: every market this model prices comes from one
score matrix, so the derived markets cannot contradict the 1X2 prices.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from betmaxxing.domain.enums import MarketType, Period, Sport, ValidationStatus
from betmaxxing.domain.models import CanonicalEvent, Participant
from betmaxxing.models_ml.football import (
    FootballDixonColesModel,
    FootballInputs,
    TeamStrength,
    dixon_coles_tau,
    expected_goals,
    outcome_probabilities,
    poisson_pmf,
    score_matrix,
    total_goals_probabilities,
)

EVENT = CanonicalEvent(
    canonical_id="fb-1",
    sport=Sport.FOOTBALL,
    competition="Ligue 1",
    home=Participant(canonical_id="p1", name="Lyon"),
    away=Participant(canonical_id="p2", name="Rennes"),
    start_time_utc=datetime(2026, 8, 4, 19, 0, tzinfo=UTC),
)

INPUTS = FootballInputs(
    home=TeamStrength(attack=1.38, defence=0.86, matches_observed=168),
    away=TeamStrength(attack=0.96, defence=1.06, matches_observed=171),
)


@pytest.fixture
def model() -> FootballDixonColesModel:
    return FootballDixonColesModel({EVENT.canonical_id: INPUTS})


class TestPoisson:
    def test_pmf_matches_known_values(self) -> None:
        assert poisson_pmf(0, 1.0) == pytest.approx(0.3678794412)
        assert poisson_pmf(1, 1.0) == pytest.approx(0.3678794412)
        assert poisson_pmf(2, 2.0) == pytest.approx(0.2706705665)

    def test_pmf_sums_to_one_over_its_support(self) -> None:
        assert sum(poisson_pmf(k, 1.5) for k in range(30)) == pytest.approx(1.0, abs=1e-9)


class TestDixonColesTau:
    def test_is_neutral_outside_the_low_score_block(self) -> None:
        assert dixon_coles_tau(2, 1, 1.4, 1.1, -0.05) == 1.0
        assert dixon_coles_tau(0, 3, 1.4, 1.1, -0.05) == 1.0

    def test_negative_rho_lifts_low_scoring_draws(self) -> None:
        # The correction exists because independent Poisson under-predicts 0-0/1-1.
        assert dixon_coles_tau(0, 0, 1.4, 1.1, -0.05) > 1.0
        assert dixon_coles_tau(1, 1, 1.4, 1.1, -0.05) > 1.0

    def test_zero_rho_is_the_identity(self) -> None:
        for x, y in ((0, 0), (0, 1), (1, 0), (1, 1)):
            assert dixon_coles_tau(x, y, 1.4, 1.1, 0.0) == 1.0


class TestScoreMatrix:
    def test_is_a_normalised_distribution(self) -> None:
        matrix = score_matrix(1.6, 1.1, -0.05)
        assert sum(sum(row) for row in matrix) == pytest.approx(1.0, abs=1e-12)
        assert all(cell >= 0 for row in matrix for cell in row)

    def test_rejects_non_positive_rates(self) -> None:
        with pytest.raises(ValueError):
            score_matrix(0.0, 1.1)

    def test_stronger_home_rate_raises_home_win_probability(self) -> None:
        weak = outcome_probabilities(score_matrix(1.2, 1.2))
        strong = outcome_probabilities(score_matrix(2.0, 1.2))
        assert strong["home"] > weak["home"]


class TestOutcomeProbabilities:
    def test_sum_to_one(self) -> None:
        probs = outcome_probabilities(score_matrix(1.6, 1.1, -0.05))
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-12)

    def test_equal_rates_give_symmetric_probabilities(self) -> None:
        probs = outcome_probabilities(score_matrix(1.3, 1.3, -0.05))
        assert probs["home"] == pytest.approx(probs["away"], abs=1e-12)


class TestTotalGoals:
    def test_over_and_under_partition_the_space(self) -> None:
        probs = total_goals_probabilities(score_matrix(1.6, 1.1), 2.5)
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-12)

    def test_higher_line_lowers_the_over_probability(self) -> None:
        matrix = score_matrix(1.6, 1.1)
        assert (
            total_goals_probabilities(matrix, 3.5)["over"]
            < total_goals_probabilities(matrix, 2.5)["over"]
        )

    def test_integer_lines_are_rejected(self) -> None:
        # An integer line can push; pricing it as a decisive market would be
        # approximating between two genuinely different bets.
        with pytest.raises(ValueError, match="can push"):
            total_goals_probabilities(score_matrix(1.6, 1.1), 3.0)


class TestExpectedGoals:
    def test_home_advantage_raises_the_home_rate(self) -> None:
        neutral = expected_goals(
            FootballInputs(home=INPUTS.home, away=INPUTS.away, home_advantage=1.0)
        )
        with_advantage = expected_goals(
            FootballInputs(home=INPUTS.home, away=INPUTS.away, home_advantage=1.3)
        )
        assert with_advantage[0] > neutral[0]
        assert with_advantage[1] == pytest.approx(neutral[1])


class TestModelCoherence:
    """Derived markets must agree with the 1X2 prices they come from."""

    def test_draw_no_bet_matches_conditional_1x2(self, model: FootballDixonColesModel) -> None:
        one_x_two = model.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FULL_TIME)
        dnb = model.predict(EVENT, MarketType.DRAW_NO_BET, Period.FULL_TIME)
        assert one_x_two is not None and dnb is not None
        decisive = one_x_two.probabilities["home"] + one_x_two.probabilities["away"]
        assert dnb.probabilities["home"] == pytest.approx(
            one_x_two.probabilities["home"] / decisive
        )
        assert sum(dnb.probabilities.values()) == pytest.approx(1.0)

    def test_double_chance_matches_1x2_pairs(self, model: FootballDixonColesModel) -> None:
        one_x_two = model.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FULL_TIME)
        dc = model.predict(EVENT, MarketType.DOUBLE_CHANCE, Period.FULL_TIME)
        assert one_x_two is not None and dc is not None
        p = one_x_two.probabilities
        assert dc.probabilities["home_or_draw"] == pytest.approx(p["home"] + p["draw"])
        assert dc.probabilities["draw_or_away"] == pytest.approx(p["draw"] + p["away"])
        # The three double chances overlap and therefore sum to 2, not 1.
        assert sum(dc.probabilities.values()) == pytest.approx(2.0)

    def test_1x2_probabilities_sum_to_one(self, model: FootballDixonColesModel) -> None:
        prediction = model.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FULL_TIME)
        assert prediction is not None
        assert sum(prediction.probabilities.values()) == pytest.approx(1.0)


class TestFirstHalf:
    def test_first_half_has_fewer_goals_than_full_time(
        self, model: FootballDixonColesModel
    ) -> None:
        full = model.predict(EVENT, MarketType.TOTAL_GOALS, Period.FULL_TIME, 2.5)
        half = model.predict(EVENT, MarketType.TOTAL_GOALS, Period.FIRST_HALF, 2.5)
        assert full is not None and half is not None
        assert half.probabilities["over"] < full.probabilities["over"]

    def test_first_half_draw_is_more_likely_than_full_time(
        self, model: FootballDixonColesModel
    ) -> None:
        full = model.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FULL_TIME)
        half = model.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FIRST_HALF)
        assert full is not None and half is not None
        assert half.probabilities["draw"] > full.probabilities["draw"]

    def test_first_half_carries_lower_confidence(self, model: FootballDixonColesModel) -> None:
        # The half-time split is a fixed constant, not a fitted parameter, so the
        # model must report itself as less certain there.
        full = model.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FULL_TIME)
        half = model.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FIRST_HALF)
        assert full is not None and half is not None
        assert half.effective_sample_size < full.effective_sample_size
        assert half.feature_completeness < full.feature_completeness


class TestModelContract:
    def test_ships_as_backtest_only(self, model: FootballDixonColesModel) -> None:
        assert model.validation_status is ValidationStatus.BACKTEST_ONLY

    def test_returns_none_for_an_unknown_event(self, model: FootballDixonColesModel) -> None:
        other = EVENT.model_copy(update={"canonical_id": "unknown"})
        assert model.predict(other, MarketType.MATCH_RESULT_1X2, Period.FULL_TIME) is None

    def test_returns_none_for_an_unsupported_market(self, model: FootballDixonColesModel) -> None:
        assert model.predict(EVENT, MarketType.MATCH_WINNER, Period.FULL_TIME) is None

    def test_returns_none_when_a_required_line_is_missing(
        self, model: FootballDixonColesModel
    ) -> None:
        assert model.predict(EVENT, MarketType.TOTAL_GOALS, Period.FULL_TIME, None) is None

    def test_effective_sample_size_shrinks_with_incomplete_features(self) -> None:
        partial = FootballDixonColesModel(
            {
                EVENT.canonical_id: FootballInputs(
                    home=INPUTS.home, away=INPUTS.away, feature_completeness=0.5
                )
            }
        )
        full = FootballDixonColesModel({EVENT.canonical_id: INPUTS})
        partial_prediction = partial.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FULL_TIME)
        full_prediction = full.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FULL_TIME)
        assert partial_prediction is not None and full_prediction is not None
        assert partial_prediction.effective_sample_size < full_prediction.effective_sample_size
