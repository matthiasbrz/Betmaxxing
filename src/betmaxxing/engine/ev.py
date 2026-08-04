"""Expected-value arithmetic.

All definitions are fixed here once, and every other module calls into this one
so a single change of convention cannot drift between the scanner, the backtester
and the dashboard.

For a decimal price ``o`` and an estimated probability ``p``::

    p_raw            = 1 / o                    (implied, margin included)
    fair_odds        = 1 / p
    EV               = p * o - 1                (per unit staked)
    EV%              = 100 * EV
    min odds for t   = (1 + t) / p              (price at which EV == t)

``EV`` is expressed per unit staked, so ``EV = 0.053`` means +5.3% of the stake in
expectation — the same convention as the reference screenshots.
"""

from __future__ import annotations

from dataclasses import dataclass

#: One "tick" of decimal odds used for the sensitivity report.
ODDS_TICK = 0.01


class EvError(ValueError):
    """Invalid input to a value computation."""


def _check_odds(odds: float) -> float:
    if odds <= 1.0:
        raise EvError(f"decimal odds must be > 1.0, got {odds}")
    return odds


def _check_prob(p: float, name: str = "probability") -> float:
    if not (0.0 < p < 1.0):
        raise EvError(f"{name} must lie strictly in (0, 1), got {p}")
    return p


def implied_probability(odds: float) -> float:
    """``1 / o``. Margin included — label it as such wherever it is displayed."""
    return 1.0 / _check_odds(odds)


def fair_odds(probability: float) -> float:
    """The price at which a bet on ``probability`` breaks even."""
    return 1.0 / _check_prob(probability)


def expected_value(probability: float, odds: float) -> float:
    """``p * o - 1``, per unit staked."""
    return _check_prob(probability) * _check_odds(odds) - 1.0


def expected_value_pct(probability: float, odds: float) -> float:
    return 100.0 * expected_value(probability, odds)


def min_acceptable_odds(probability: float, ev_threshold: float) -> float:
    """Lowest price still meeting ``ev_threshold``.

    Solves ``p * o - 1 = t`` for ``o``. With ``t = 0`` this is exactly the fair
    odds, which is the correct break-even reference.
    """
    if ev_threshold <= -1.0:
        raise EvError("ev_threshold must be > -1")
    return (1.0 + ev_threshold) / _check_prob(probability)


def ev_sensitivity(probability: float, tick: float = ODDS_TICK) -> float:
    """Change in EV for a ``tick`` change in decimal odds.

    ``dEV/do = p`` exactly, so the reported figure is ``p * tick``. It answers
    "how much of my edge disappears if the price moves against me by one tick".
    """
    return _check_prob(probability) * tick


def breakeven_probability(odds: float) -> float:
    """Alias of :func:`implied_probability`, named for how it is used in copy."""
    return implied_probability(odds)


def kelly_fraction(probability: float, odds: float) -> float:
    """Full-Kelly fraction of bankroll: ``(p*o - 1) / (o - 1)``.

    Negative when the bet has no edge; callers clamp at zero.
    """
    ev = expected_value(probability, odds)
    return ev / (_check_odds(odds) - 1.0)


@dataclass(frozen=True, slots=True)
class ValueMath:
    """Full value picture for one price, computed from a probability interval."""

    odds: float
    probability: float
    probability_lower: float
    probability_upper: float
    ev_threshold: float

    @property
    def implied_raw(self) -> float:
        return implied_probability(self.odds)

    @property
    def fair(self) -> float:
        return fair_odds(self.probability)

    @property
    def ev(self) -> float:
        return expected_value(self.probability, self.odds)

    @property
    def ev_conservative(self) -> float:
        """EV recomputed at the *lower* bound of the probability interval.

        This is the figure the eligibility gate leans on: a wide interval whose
        lower bound has no edge must not qualify, however attractive the point
        estimate looks.
        """
        return expected_value(self.probability_lower, self.odds)

    @property
    def ev_upper(self) -> float:
        return expected_value(self.probability_upper, self.odds)

    @property
    def min_odds(self) -> float:
        return min_acceptable_odds(self.probability, self.ev_threshold)

    @property
    def min_odds_conservative(self) -> float:
        return min_acceptable_odds(self.probability_lower, self.ev_threshold)

    @property
    def sensitivity(self) -> float:
        return ev_sensitivity(self.probability)

    def as_dict(self) -> dict[str, float]:
        return {
            "odds": self.odds,
            "implied_probability_raw": self.implied_raw,
            "model_probability": self.probability,
            "model_probability_lower": self.probability_lower,
            "model_probability_upper": self.probability_upper,
            "fair_odds": self.fair,
            "ev": self.ev,
            "ev_pct": 100.0 * self.ev,
            "ev_conservative": self.ev_conservative,
            "ev_conservative_pct": 100.0 * self.ev_conservative,
            "ev_upper": self.ev_upper,
            "min_acceptable_odds": self.min_odds,
            "ev_sensitivity_per_odds_tick": self.sensitivity,
        }
