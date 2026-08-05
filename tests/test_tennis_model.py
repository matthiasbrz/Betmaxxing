"""Tennis hierarchical model.

The chain point -> game -> tiebreak -> set -> match is verified against values
that can be derived by hand, and the derived markets are checked for coherence
with the match winner they share a parameterisation with.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import cache

import pytest

from betmaxxing.domain.enums import MarketType, Period, Sport, ValidationStatus
from betmaxxing.domain.models import CanonicalEvent, Participant
from betmaxxing.models_ml.tennis import (
    SERVE_BASELINE_BY_SURFACE,
    TennisHierarchicalModel,
    TennisInputs,
    calibrate_serve_probabilities,
    elo_win_probability,
    game_win_probability,
    match_distribution,
    set_distribution,
    tiebreak_win_probability,
)

EVENT = CanonicalEvent(
    internal_id="tn-1",
    sport=Sport.TENNIS,
    competition="ATP Masters 1000",
    surface="hard",
    sets_to_win=2,
    home=Participant(canonical_id="p1", name="Tabilo"),
    away=Participant(canonical_id="p2", name="Jodar"),
    start_time_utc=datetime(2026, 8, 4, 13, 0, tzinfo=UTC),
)

INPUTS = TennisInputs(
    elo_home=1871.0,
    elo_away=1790.0,
    matches_home=143,
    matches_away=118,
    surface="hard",
    sets_to_win=2,
)


@pytest.fixture
def model() -> TennisHierarchicalModel:
    return TennisHierarchicalModel({EVENT.internal_id: INPUTS})


class TestElo:
    def test_equal_ratings_give_even_odds(self) -> None:
        assert elo_win_probability(1800, 1800) == pytest.approx(0.5)

    def test_four_hundred_points_is_ten_to_one(self) -> None:
        assert elo_win_probability(1800, 1400) == pytest.approx(10 / 11)

    def test_is_monotonic_in_the_rating_gap(self) -> None:
        assert elo_win_probability(1900, 1800) > elo_win_probability(1850, 1800)


class TestGameWinProbability:
    def test_fair_point_probability_gives_a_fair_game(self) -> None:
        assert game_win_probability(0.5) == pytest.approx(0.5)

    @pytest.mark.parametrize("p", [0.45, 0.5, 0.55, 0.62, 0.64, 0.70, 0.80])
    def test_closed_form_matches_an_independent_enumeration(self, p: float) -> None:
        """Cross-check the algebra against a brute-force DP over game states.

        The closed form folds the deuce sub-game into ``p²/(p²+q²)``; this
        recursion makes no such assumption, so agreement to machine precision
        confirms the formula rather than restating it.
        """

        @cache
        def enumerate_game(a: int, b: int, n: int) -> float:
            if a >= 4 and a - b >= 2:
                return 1.0
            if b >= 4 and b - a >= 2:
                return 0.0
            if n > 400:  # pragma: no cover - unreachable mass
                return 0.5
            return p * enumerate_game(a + 1, b, n + 1) + (1 - p) * enumerate_game(a, b + 1, n + 1)

        assert game_win_probability(p) == pytest.approx(enumerate_game(0, 0, 0), abs=1e-12)

    def test_amplifies_the_point_edge(self) -> None:
        # A small per-point edge becomes a large per-game edge.
        assert game_win_probability(0.55) > 0.62

    def test_is_monotonic(self) -> None:
        assert game_win_probability(0.70) > game_win_probability(0.60)

    @pytest.mark.parametrize("bad", [0.0, 1.0, -0.1])
    def test_rejects_degenerate_point_probabilities(self, bad: float) -> None:
        with pytest.raises(ValueError):
            game_win_probability(bad)


class TestTiebreak:
    def test_equal_servers_split_the_tiebreak(self) -> None:
        assert tiebreak_win_probability(0.64, 0.64, True) == pytest.approx(0.5)

    @pytest.mark.parametrize(("p_a", "p_b"), [(0.64, 0.64), (0.70, 0.60), (0.80, 0.55)])
    def test_serve_order_does_not_change_the_outcome(self, p_a: float, p_b: float) -> None:
        """The 1-2-2 tiebreak is order-fair, and that is worth pinning down.

        Under iid points the probability of winning a first-to-7 tiebreak is
        independent of who serves the opening point — the 1-2-2 pattern balances
        service exactly. Verified here to machine precision and cross-checked
        against a Monte-Carlo simulation during development.

        It matters downstream: set and match probabilities inherit it, so a
        change that broke the serve-rotation indexing would show up here rather
        than as a quiet bias in every tennis price.
        """
        assert tiebreak_win_probability(p_a, p_b, True) == pytest.approx(
            tiebreak_win_probability(p_a, p_b, False), abs=1e-12
        )

    def test_stronger_server_wins_more_tiebreaks(self) -> None:
        assert tiebreak_win_probability(0.70, 0.60, True) > 0.5


class TestSetDistribution:
    def test_is_a_normalised_distribution(self) -> None:
        dist = dict(set_distribution(0.64, 0.64, True))
        assert sum(dist.values()) == pytest.approx(1.0, abs=1e-12)

    def test_equal_players_split_the_set(self) -> None:
        dist = dict(set_distribution(0.64, 0.64, True))
        home = sum(p for (ga, gb), p in dist.items() if ga > gb)
        assert home == pytest.approx(0.5, abs=1e-9)

    def test_only_legal_set_scores_appear(self) -> None:
        legal = {(6, 0), (6, 1), (6, 2), (6, 3), (6, 4), (7, 5), (7, 6)}
        legal |= {(b, a) for a, b in legal}
        for score in dict(set_distribution(0.64, 0.60, True)):
            assert score in legal


class TestMatchDistribution:
    def test_is_a_normalised_distribution(self) -> None:
        dist = match_distribution(0.64, 0.64, 2, True)
        assert sum(dist.outcomes.values()) == pytest.approx(1.0, abs=1e-12)

    def test_equal_players_split_the_match(self) -> None:
        dist = match_distribution(0.64, 0.64, 2, True)
        assert dist.p_a_wins_match == pytest.approx(0.5, abs=1e-9)

    def test_equal_players_win_at_least_one_set_three_quarters_of_the_time(self) -> None:
        """Exactly derivable: only a 0-2 loss fails, and that has probability 1/4."""
        dist = match_distribution(0.64, 0.64, 2, True)
        assert dist.p_player_wins_at_least_one_set("home") == pytest.approx(0.75, abs=1e-9)

    def test_best_of_five_favours_the_stronger_player_more(self) -> None:
        bo3 = match_distribution(0.68, 0.62, 2, True).p_a_wins_match
        bo5 = match_distribution(0.68, 0.62, 3, True).p_a_wins_match
        assert bo5 > bo3

    def test_best_of_five_produces_more_games(self) -> None:
        bo3 = match_distribution(0.64, 0.64, 2, True).expected_total_games()
        bo5 = match_distribution(0.64, 0.64, 3, True).expected_total_games()
        assert bo5 > bo3

    def test_total_games_over_under_partitions(self) -> None:
        dist = match_distribution(0.66, 0.62, 2, True)
        probs = dist.total_games_probabilities(22.5)
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-12)

    def test_integer_games_line_is_rejected(self) -> None:
        dist = match_distribution(0.64, 0.64, 2, True)
        with pytest.raises(ValueError, match="can push"):
            dist.total_games_probabilities(22.0)

    def test_rejects_unsupported_match_formats(self) -> None:
        with pytest.raises(ValueError):
            match_distribution(0.64, 0.64, 4, True)


class TestCalibration:
    @pytest.mark.parametrize("target", [0.35, 0.5, 0.62, 0.78])
    def test_reproduces_the_target_match_probability(self, target: float) -> None:
        p_a, p_b = calibrate_serve_probabilities(target, 2, 0.64)
        achieved = match_distribution(p_a, p_b, 2, True).p_a_wins_match
        assert achieved == pytest.approx(target, abs=1e-3)

    def test_even_target_gives_equal_serve_probabilities(self) -> None:
        p_a, p_b = calibrate_serve_probabilities(0.5, 2, 0.64)
        assert p_a == pytest.approx(p_b, abs=1e-4)

    def test_rejects_degenerate_targets(self) -> None:
        with pytest.raises(ValueError):
            calibrate_serve_probabilities(0.0, 2, 0.64)


class TestModelCoherence:
    """Everything is derived from one point model, so nothing may contradict."""

    def test_match_winner_probabilities_sum_to_one(self, model: TennisHierarchicalModel) -> None:
        prediction = model.predict(EVENT, MarketType.MATCH_WINNER, Period.FULL_TIME)
        assert prediction is not None
        assert sum(prediction.probabilities.values()) == pytest.approx(1.0)

    def test_winning_a_set_is_more_likely_than_winning_the_match(
        self, model: TennisHierarchicalModel
    ) -> None:
        winner = model.predict(EVENT, MarketType.MATCH_WINNER, Period.FULL_TIME)
        a_set = model.predict(EVENT, MarketType.PLAYER_WINS_A_SET, Period.FULL_TIME)
        assert winner is not None and a_set is not None
        for side in ("home", "away"):
            assert a_set.probabilities[side] > winner.probabilities[side]

    def test_wins_a_set_probabilities_exceed_one_together(
        self, model: TennisHierarchicalModel
    ) -> None:
        # Both players can win a set, so this market is not a partition and must
        # never be de-vigged as a book.
        prediction = model.predict(EVENT, MarketType.PLAYER_WINS_A_SET, Period.FULL_TIME)
        assert prediction is not None
        assert sum(prediction.probabilities.values()) > 1.0

    def test_favourite_is_consistent_across_derived_markets(
        self, model: TennisHierarchicalModel
    ) -> None:
        winner = model.predict(EVENT, MarketType.MATCH_WINNER, Period.FULL_TIME)
        a_set = model.predict(EVENT, MarketType.PLAYER_WINS_A_SET, Period.FULL_TIME)
        assert winner is not None and a_set is not None
        assert winner.probabilities["home"] > winner.probabilities["away"]
        assert a_set.probabilities["home"] > a_set.probabilities["away"]

    def test_elo_target_is_reproduced_by_the_match_chain(
        self, model: TennisHierarchicalModel
    ) -> None:
        prediction = model.predict(EVENT, MarketType.MATCH_WINNER, Period.FULL_TIME)
        assert prediction is not None
        target = float(prediction.diagnostics["elo_match_probability_home"])
        assert prediction.probabilities["home"] == pytest.approx(target, abs=2e-3)


class TestSurface:
    def test_surface_baseline_is_applied(self) -> None:
        assert SERVE_BASELINE_BY_SURFACE["grass"] > SERVE_BASELINE_BY_SURFACE["clay"]

    def test_surface_elo_overrides_global_elo(self) -> None:
        surface_specific = TennisHierarchicalModel(
            {
                EVENT.internal_id: TennisInputs(
                    elo_home=1800,
                    elo_away=1800,
                    elo_home_surface=1950,
                    elo_away_surface=1750,
                    matches_home=100,
                    matches_away=100,
                )
            }
        )
        prediction = surface_specific.predict(EVENT, MarketType.MATCH_WINNER, Period.FULL_TIME)
        assert prediction is not None
        assert prediction.probabilities["home"] > 0.6

    def test_grass_produces_more_tiebreaks_than_clay(self) -> None:
        """Higher serve dominance means more sets reach 6-6."""
        grass = dict(
            set_distribution(
                SERVE_BASELINE_BY_SURFACE["grass"], SERVE_BASELINE_BY_SURFACE["grass"], True
            )
        )
        clay = dict(
            set_distribution(
                SERVE_BASELINE_BY_SURFACE["clay"], SERVE_BASELINE_BY_SURFACE["clay"], True
            )
        )
        grass_tb = grass.get((7, 6), 0.0) + grass.get((6, 7), 0.0)
        clay_tb = clay.get((7, 6), 0.0) + clay.get((6, 7), 0.0)
        assert grass_tb > clay_tb


class TestModelContract:
    def test_ships_as_backtest_only(self, model: TennisHierarchicalModel) -> None:
        assert model.validation_status is ValidationStatus.BACKTEST_ONLY

    def test_refuses_half_time_markets(self, model: TennisHierarchicalModel) -> None:
        assert model.predict(EVENT, MarketType.MATCH_WINNER, Period.FIRST_HALF) is None

    def test_returns_none_for_an_unsupported_market(self, model: TennisHierarchicalModel) -> None:
        assert model.predict(EVENT, MarketType.MATCH_RESULT_1X2, Period.FULL_TIME) is None

    def test_reports_settlement_rules_as_unmodelled(self, model: TennisHierarchicalModel) -> None:
        # Retirement and walkover settle per bookmaker rules; the model says so
        # rather than inventing a probability for them.
        prediction = model.predict(EVENT, MarketType.MATCH_WINNER, Period.FULL_TIME)
        assert prediction is not None
        assert "Abandon" in str(prediction.diagnostics["settlement_note"])
