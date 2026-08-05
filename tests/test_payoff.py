"""Settlement-aware expected value.

The property that matters most: markets that cannot push must produce **exactly**
the old ``p*o - 1`` arithmetic, so introducing settlement modelling did not
silently move 1X2, match-winner or half-line totals.
"""

from __future__ import annotations

import pytest

from betmaxxing.engine.payoff import (
    PayoffError,
    SettlementRule,
    draw_no_bet_outcomes,
    ev_sensitivity,
    expected_value_from_outcomes,
    min_acceptable_odds,
    quarter_line_outcomes,
    total_with_push_outcomes,
    two_way_outcomes,
)


class TestTwoWayReducesToTheOldFormula:
    @pytest.mark.parametrize(
        ("p", "odds"),
        [(0.5, 2.0), (0.6573, 1.63), (0.226, 4.66), (0.821, 1.28), (0.1, 12.0)],
    )
    def test_ev_matches_p_times_o_minus_one(self, p: float, odds: float) -> None:
        payoff = two_way_outcomes(p_win=p, decimal_odds=odds)
        assert payoff.expected_value == pytest.approx(p * odds - 1.0)

    @pytest.mark.parametrize("p", [0.2, 0.5, 0.75])
    def test_fair_odds_matches_one_over_p(self, p: float) -> None:
        payoff = two_way_outcomes(p_win=p, decimal_odds=2.0)
        assert payoff.fair_odds == pytest.approx(1.0 / p)

    def test_min_acceptable_odds_matches_the_closed_form(self) -> None:
        payoff = two_way_outcomes(p_win=0.45, decimal_odds=2.0)
        assert min_acceptable_odds(payoff, 0.03) == pytest.approx(1.03 / 0.45)

    def test_sensitivity_matches_the_win_probability(self) -> None:
        payoff = two_way_outcomes(p_win=0.55, decimal_odds=2.0)
        assert ev_sensitivity(payoff) == pytest.approx(0.0055)

    def test_ev_is_zero_at_fair_odds(self) -> None:
        for p in (0.15, 0.4, 0.8):
            payoff = two_way_outcomes(p_win=p, decimal_odds=1.0 / p)
            assert payoff.expected_value == pytest.approx(0.0, abs=1e-12)

    def test_rule_is_recorded(self) -> None:
        assert two_way_outcomes(p_win=0.5, decimal_odds=2.0).rule is SettlementRule.WIN_LOSE

    def test_push_probability_is_zero(self) -> None:
        assert two_way_outcomes(p_win=0.5, decimal_odds=2.0).push_probability == 0.0


class TestDrawNoBet:
    P_WIN, P_DRAW, P_LOSS = 0.4846, 0.2629, 0.2525
    ODDS = 1.46

    def payoff(self, odds: float | None = None):  # type: ignore[no-untyped-def]
        return draw_no_bet_outcomes(
            p_win=self.P_WIN,
            p_push=self.P_DRAW,
            p_loss=self.P_LOSS,
            decimal_odds=odds or self.ODDS,
        )

    def test_ev_uses_the_real_payoff(self) -> None:
        assert self.payoff().expected_value == pytest.approx(
            self.P_WIN * (self.ODDS - 1) - self.P_LOSS
        )

    def test_conditional_formula_overstates_the_magnitude(self) -> None:
        """Exactly ``EV = (1 - p_push) x EV_conditional``.

        The old code used the conditional form as an EV per unit staked, which
        inflates both a positive edge and a negative one.
        """
        payoff = self.payoff()
        conditional = self.P_WIN / (self.P_WIN + self.P_LOSS)
        naive = conditional * self.ODDS - 1
        assert payoff.expected_value == pytest.approx((1 - self.P_DRAW) * naive)
        assert abs(naive) > abs(payoff.expected_value)

    def test_fair_odds_is_the_conditional_reciprocal(self) -> None:
        payoff = self.payoff()
        conditional = self.P_WIN / (self.P_WIN + self.P_LOSS)
        assert payoff.fair_odds == pytest.approx(1.0 / conditional)

    def test_ev_is_zero_at_fair_odds(self) -> None:
        fair = self.payoff().fair_odds
        assert self.payoff(fair).expected_value == pytest.approx(0.0, abs=1e-12)

    def test_min_acceptable_odds_produces_the_target_ev(self) -> None:
        target = 0.03
        odds = min_acceptable_odds(self.payoff(), target)
        assert self.payoff(odds).expected_value == pytest.approx(target)

    def test_sensitivity_is_lower_than_a_pure_win_lose_bet(self) -> None:
        """A refundable market moves less per tick at the same headline price."""
        dnb = ev_sensitivity(self.payoff())
        straight = ev_sensitivity(two_way_outcomes(p_win=self.P_WIN, decimal_odds=self.ODDS))
        assert dnb == pytest.approx(straight)

    def test_probabilities_must_sum_to_one(self) -> None:
        with pytest.raises(PayoffError, match="must equal 1"):
            draw_no_bet_outcomes(p_win=0.5, p_push=0.3, p_loss=0.4, decimal_odds=2.0)

    def test_rule_is_recorded(self) -> None:
        assert self.payoff().rule is SettlementRule.STAKE_REFUNDED_ON_PUSH

    def test_component_probabilities_are_exposed(self) -> None:
        payoff = self.payoff()
        assert payoff.win_probability == pytest.approx(self.P_WIN)
        assert payoff.push_probability == pytest.approx(self.P_DRAW)
        assert payoff.loss_probability == pytest.approx(self.P_LOSS)


class TestTotalsWithPush:
    def test_an_integer_total_refunds_on_the_line(self) -> None:
        payoff = total_with_push_outcomes(p_win=0.45, p_push=0.12, p_loss=0.43, decimal_odds=2.1)
        assert payoff.expected_value == pytest.approx(0.45 * 1.1 - 0.43)
        assert payoff.rule is SettlementRule.STAKE_REFUNDED_ON_PUSH


class TestQuarterLines:
    def test_half_win_and_half_loss_are_priced(self) -> None:
        payoff = quarter_line_outcomes(
            p_full_win=0.4,
            p_half_win=0.1,
            p_half_loss=0.1,
            p_full_loss=0.4,
            decimal_odds=2.0,
        )
        expected = 0.4 * 1.0 + 0.1 * 0.5 + 0.1 * -0.5 + 0.4 * -1.0
        assert payoff.expected_value == pytest.approx(expected)

    def test_probabilities_must_sum_to_one(self) -> None:
        with pytest.raises(PayoffError):
            quarter_line_outcomes(
                p_full_win=0.5,
                p_half_win=0.5,
                p_half_loss=0.5,
                p_full_loss=0.5,
                decimal_odds=2.0,
            )


class TestValidation:
    def test_odds_must_exceed_one(self) -> None:
        with pytest.raises(PayoffError):
            two_way_outcomes(p_win=0.5, decimal_odds=1.0)

    def test_win_probability_must_be_in_the_open_unit_interval(self) -> None:
        with pytest.raises(PayoffError):
            two_way_outcomes(p_win=0.0, decimal_odds=2.0)
        with pytest.raises(PayoffError):
            two_way_outcomes(p_win=1.0, decimal_odds=2.0)

    def test_a_payoff_with_no_decisive_outcome_has_no_fair_odds(self) -> None:
        payoff = draw_no_bet_outcomes(
            p_win=1e-12, p_push=1.0 - 2e-12, p_loss=1e-12, decimal_odds=2.0
        )
        assert payoff.fair_odds > 1.0


class TestSerialisation:
    def test_dict_exposes_the_full_settlement_description(self) -> None:
        payload = draw_no_bet_outcomes(
            p_win=0.48, p_push=0.26, p_loss=0.26, decimal_odds=1.9
        ).as_dict()
        for key in (
            "rule",
            "outcomes",
            "win_probability",
            "push_probability",
            "loss_probability",
            "conditional_win_probability",
            "fair_odds",
            "expected_value",
        ):
            assert key in payload
        assert len(payload["outcomes"]) == 3  # type: ignore[arg-type]

    def test_expected_value_helper_matches_the_property(self) -> None:
        payoff = two_way_outcomes(p_win=0.6, decimal_odds=1.9)
        assert expected_value_from_outcomes(payoff) == payoff.expected_value
