"""Settlement-aware expected value.

The general definition, and the only one used anywhere:

    EV = sum over outcomes of  p(outcome) x net_return(outcome)

``net_return`` is per unit staked, measured as profit — so a winning bet at
decimal odds ``o`` returns ``o - 1``, a refunded (void/push) bet returns ``0``,
and a loser returns ``-1``.

Why this replaces ``p * o - 1``
-------------------------------
``p * o - 1`` is correct **only** when the bet is a Bernoulli with no refund. It
is not correct for draw-no-bet, where the draw refunds the stake, nor for an
integer total that can push, nor for Asian lines with half-win/half-loss.

For draw-no-bet the two formulations differ by exactly the decisive-outcome
mass. With ``p_cond = p_win / (p_win + p_loss)``::

    EV_true = p_win * (o - 1) - p_loss
            = (p_win + p_loss) * (p_cond * o - 1)
            = (1 - p_push) * EV_conditional

Since ``p_push > 0``, the conditional form overstates the magnitude of the EV —
it flatters a positive edge and exaggerates a negative one. The conditional
probability remains the right thing to compare against a de-vigged market price,
and the right basis for fair odds; it is simply not an EV per unit staked.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_TOL = 1e-9


class SettlementRule(StrEnum):
    """How a market settles. Recorded on every candidate for audit."""

    #: Win or lose, no refund path (1X2, half-line totals, match winner).
    WIN_LOSE = "WIN_LOSE"
    #: A defined outcome refunds the stake (draw-no-bet, integer totals).
    STAKE_REFUNDED_ON_PUSH = "STAKE_REFUNDED_ON_PUSH"
    #: Asian quarter lines: half the stake wins, half is refunded.
    HALF_WIN_HALF_PUSH = "HALF_WIN_HALF_PUSH"
    #: Asian quarter lines: half the stake loses, half is refunded.
    HALF_LOSS_HALF_PUSH = "HALF_LOSS_HALF_PUSH"


class PayoffError(ValueError):
    """The outcome distribution is not a valid settlement description."""


@dataclass(frozen=True, slots=True)
class Outcome:
    """One settlement branch: how likely, and what it pays per unit staked."""

    name: str
    probability: float
    net_return: float


@dataclass(frozen=True, slots=True)
class PayoffDistribution:
    """A complete settlement description for one priced selection."""

    outcomes: tuple[Outcome, ...]
    rule: SettlementRule
    decimal_odds: float

    def __post_init__(self) -> None:
        if self.decimal_odds <= 1.0:
            raise PayoffError(f"decimal odds must be > 1.0, got {self.decimal_odds}")
        if not self.outcomes:
            raise PayoffError("a payoff needs at least one outcome")
        total = sum(o.probability for o in self.outcomes)
        if abs(total - 1.0) > 1e-6:
            raise PayoffError(f"outcome probabilities must sum to 1, got {total:.9f}")
        if any(o.probability < -_TOL for o in self.outcomes):
            raise PayoffError("outcome probabilities must be non-negative")

    @property
    def expected_value(self) -> float:
        """EV per unit staked."""
        return sum(o.probability * o.net_return for o in self.outcomes)

    @property
    def win_probability(self) -> float:
        return sum(o.probability for o in self.outcomes if o.net_return > 0)

    @property
    def push_probability(self) -> float:
        return sum(o.probability for o in self.outcomes if abs(o.net_return) < _TOL)

    @property
    def loss_probability(self) -> float:
        return sum(o.probability for o in self.outcomes if o.net_return < 0)

    @property
    def conditional_win_probability(self) -> float:
        """``p_win / (p_win + p_loss)`` — the figure comparable to a de-vigged
        market price, and the reciprocal of the fair odds."""
        decisive = self.win_probability + self.loss_probability
        if decisive <= 0:
            raise PayoffError("no decisive outcome: fair odds are undefined")
        return self.win_probability / decisive

    @property
    def fair_odds(self) -> float:
        """The price at which this payoff breaks even.

        Derived from the payoff rather than special-cased per market: solving
        ``p_win*(o-1) - p_loss = 0`` gives ``o = (p_win + p_loss) / p_win``,
        which reduces to ``1/p`` when nothing can push.
        """
        return 1.0 / self.conditional_win_probability

    def as_dict(self) -> dict[str, object]:
        return {
            "rule": str(self.rule),
            "decimal_odds": self.decimal_odds,
            "outcomes": [
                {"name": o.name, "probability": o.probability, "net_return": o.net_return}
                for o in self.outcomes
            ],
            "win_probability": self.win_probability,
            "push_probability": self.push_probability,
            "loss_probability": self.loss_probability,
            "conditional_win_probability": self.conditional_win_probability,
            "fair_odds": self.fair_odds,
            "expected_value": self.expected_value,
        }


def expected_value_from_outcomes(payoff: PayoffDistribution) -> float:
    """``sum p(outcome) x net_return(outcome)``."""
    return payoff.expected_value


def two_way_outcomes(*, p_win: float, decimal_odds: float) -> PayoffDistribution:
    """A bet that can only win or lose.

    Reduces to ``p*o - 1``, so 1X2, match winner and half-line totals keep the
    exact arithmetic they had before settlement modelling was introduced.
    """
    if not (0.0 < p_win < 1.0):
        raise PayoffError(f"p_win must lie in (0, 1), got {p_win}")
    return PayoffDistribution(
        outcomes=(
            Outcome("win", p_win, decimal_odds - 1.0),
            Outcome("loss", 1.0 - p_win, -1.0),
        ),
        rule=SettlementRule.WIN_LOSE,
        decimal_odds=decimal_odds,
    )


def draw_no_bet_outcomes(
    *, p_win: float, p_push: float, p_loss: float, decimal_odds: float
) -> PayoffDistribution:
    """Draw-no-bet: the draw refunds the stake.

    ``p_win``/``p_push``/``p_loss`` are **unconditional** probabilities of the
    underlying 1X2 outcomes and must sum to 1.
    """
    total = p_win + p_push + p_loss
    if abs(total - 1.0) > 1e-6:
        raise PayoffError(f"p_win + p_push + p_loss must equal 1, got {total:.9f}")
    return PayoffDistribution(
        outcomes=(
            Outcome("win", p_win, decimal_odds - 1.0),
            Outcome("push", p_push, 0.0),
            Outcome("loss", p_loss, -1.0),
        ),
        rule=SettlementRule.STAKE_REFUNDED_ON_PUSH,
        decimal_odds=decimal_odds,
    )


def total_with_push_outcomes(
    *, p_win: float, p_push: float, p_loss: float, decimal_odds: float
) -> PayoffDistribution:
    """An integer total, where landing exactly on the line refunds the stake.

    V1 rejects integer lines upstream, so this exists to make the settlement
    contract complete and testable rather than to price a live market.
    """
    return draw_no_bet_outcomes(
        p_win=p_win, p_push=p_push, p_loss=p_loss, decimal_odds=decimal_odds
    )


def quarter_line_outcomes(
    *,
    p_full_win: float,
    p_half_win: float,
    p_half_loss: float,
    p_full_loss: float,
    decimal_odds: float,
) -> PayoffDistribution:
    """Asian quarter line: half the stake settles on each adjacent line.

    Implemented for completeness of the settlement contract. No V1 market maps
    to it, and none is priced with it until a provider supplies quarter lines.
    """
    total = p_full_win + p_half_win + p_half_loss + p_full_loss
    if abs(total - 1.0) > 1e-6:
        raise PayoffError(f"quarter-line probabilities must sum to 1, got {total:.9f}")
    profit = decimal_odds - 1.0
    return PayoffDistribution(
        outcomes=(
            Outcome("win", p_full_win, profit),
            Outcome("half_win", p_half_win, profit / 2.0),
            Outcome("half_loss", p_half_loss, -0.5),
            Outcome("loss", p_full_loss, -1.0),
        ),
        rule=SettlementRule.HALF_WIN_HALF_PUSH,
        decimal_odds=decimal_odds,
    )


def min_acceptable_odds(payoff: PayoffDistribution, ev_threshold: float) -> float:
    """Lowest price at which this payoff still meets ``ev_threshold``.

    Every winning branch pays a fixed multiple of ``(o - 1)`` and every other
    branch is independent of ``o``, so ``EV(o) = A*(o - 1) + B`` is affine.
    Solving ``EV = threshold`` gives ``o = 1 + (threshold - B) / A``, which
    reduces to ``(1 + threshold) / p`` for a pure win/lose bet.
    """
    a = sum(
        o.probability * (o.net_return / (payoff.decimal_odds - 1.0))
        for o in payoff.outcomes
        if o.net_return > 0
    )
    b = sum(o.probability * o.net_return for o in payoff.outcomes if o.net_return <= 0)
    if a <= 0:
        raise PayoffError("payoff has no winning branch: minimum odds undefined")
    return 1.0 + (ev_threshold - b) / a


def ev_sensitivity(payoff: PayoffDistribution, tick: float = 0.01) -> float:
    """Change in EV for a ``tick`` change in decimal odds.

    Equals the effective winning mass, so a market that can push is less
    sensitive to a price move than a pure win/lose bet at the same headline
    probability.
    """
    a = sum(
        o.probability * (o.net_return / (payoff.decimal_odds - 1.0))
        for o in payoff.outcomes
        if o.net_return > 0
    )
    return a * tick
