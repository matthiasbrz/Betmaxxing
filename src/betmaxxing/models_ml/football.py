"""Football baseline: bivariate Poisson with the Dixon-Coles low-score correction.

Why start here: it is auditable, closed-form, and every market V1 supports (1X2,
draw-no-bet, double chance, totals, and their first-half counterparts) falls out
of a *single* score matrix, which guarantees the derived markets are mutually
consistent by construction.

The model is:

    goals_home ~ Poisson(lambda_home)
    goals_away ~ Poisson(lambda_away)
    P(x, y)    = tau(x, y; rho) * Poisson(x; lh) * Poisson(y; la)

with ``tau`` the Dixon-Coles adjustment applied to the four 0-0/1-0/0-1/1-1 cells,
which corrects the well-documented under-prediction of low-scoring draws by an
independent Poisson.

Team strengths are supplied by the caller (a fitted rating store, or the demo
provider). Fitting them from historical results belongs to the training pipeline
and is deliberately not done here — this class only maps strengths to market
probabilities, which is what has to be identical between backtest and live.

First half is modelled by scaling both rates by ``FIRST_HALF_GOAL_SHARE``, a
single documented constant rather than a second free-floating model. It is
flagged as an approximation in the diagnostics, and the first-half markets carry
a reduced effective sample size because of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from betmaxxing.domain.enums import MarketType, Period, Sport, ValidationStatus
from betmaxxing.domain.models import CanonicalEvent
from betmaxxing.models_ml.base import BaseModel, MarketPrediction, lookup_inputs

#: Empirically ~45% of goals fall in the first half. Provisional until fitted.
FIRST_HALF_GOAL_SHARE = 0.45
#: Score matrix truncation. P(goals > 15) is negligible for football rates.
MAX_GOALS = 15

#: Pseudo-count feeding the **demo-mode synthetic** uncertainty only.
#:
#: Superseded as a statistical claim by D-019. It was previously multiplied into
#: a Wilson interval that was presented as the model's predictive uncertainty and
#: used to gate real candidates; a Wilson interval describes an observed binomial
#: proportion and cannot carry parameter, calibration or dependence uncertainty.
#:
#: It survives purely so demo output has a realistic *shape*. It can no longer
#: reach `paper` or `live_analysis`: `uncertainty_for_mode()` returns
#: UNAVAILABLE there regardless of this value.
SYNTHETIC_INFORMATION_PER_MATCH = 2.5


def poisson_pmf(k: int, lam: float) -> float:
    """``P(X = k)`` for ``X ~ Poisson(lam)``."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam**k / math.factorial(k)


def dixon_coles_tau(x: int, y: int, lam_h: float, lam_a: float, rho: float) -> float:
    """Low-score dependency correction. Returns 1 outside the 2x2 low-score block."""
    if x == 0 and y == 0:
        return 1.0 - lam_h * lam_a * rho
    if x == 0 and y == 1:
        return 1.0 + lam_h * rho
    if x == 1 and y == 0:
        return 1.0 + lam_a * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(
    lam_home: float,
    lam_away: float,
    rho: float = 0.0,
    max_goals: int = MAX_GOALS,
) -> list[list[float]]:
    """Joint distribution over exact scores, renormalised to sum to 1.

    Renormalisation absorbs both the truncation at ``max_goals`` and the small
    mass shift introduced by ``tau``.
    """
    if lam_home <= 0 or lam_away <= 0:
        raise ValueError("Poisson rates must be strictly positive")
    home_pmf = [poisson_pmf(i, lam_home) for i in range(max_goals + 1)]
    away_pmf = [poisson_pmf(j, lam_away) for j in range(max_goals + 1)]
    matrix = [
        [
            home_pmf[i] * away_pmf[j] * dixon_coles_tau(i, j, lam_home, lam_away, rho)
            for j in range(max_goals + 1)
        ]
        for i in range(max_goals + 1)
    ]
    total = sum(sum(row) for row in matrix)
    if total <= 0:  # pragma: no cover - guarded by the rate check above
        raise ValueError("degenerate score matrix")
    return [[cell / total for cell in row] for row in matrix]


def outcome_probabilities(matrix: list[list[float]]) -> dict[str, float]:
    """1X2 probabilities from a score matrix."""
    home = draw = away = 0.0
    for i, row in enumerate(matrix):
        for j, cell in enumerate(row):
            if i > j:
                home += cell
            elif i == j:
                draw += cell
            else:
                away += cell
    return {"home": home, "draw": draw, "away": away}


def total_goals_probabilities(matrix: list[list[float]], line: float) -> dict[str, float]:
    """Over/Under probabilities for an exact line.

    Integer lines (a "push" is possible) are rejected: a market that can void is
    not the same bet as a decisive one, and pricing it as if it were would be an
    approximation between two different markets.
    """
    if abs(line - round(line)) < 1e-9:
        raise ValueError(f"integer total line {line} can push; only half-lines are supported in V1")
    over = under = 0.0
    for i, row in enumerate(matrix):
        for j, cell in enumerate(row):
            if i + j > line:
                over += cell
            else:
                under += cell
    return {"over": over, "under": under}


@dataclass(frozen=True, slots=True)
class TeamStrength:
    """Fitted ratings for one team. ``matches_observed`` drives the uncertainty."""

    attack: float
    defence: float
    matches_observed: int


@dataclass(frozen=True, slots=True)
class FootballInputs:
    """Everything the model needs for one fixture, all of it sourced."""

    home: TeamStrength
    away: TeamStrength
    #: League-average goals per team per match.
    league_mean_goals: float = 1.35
    #: Multiplicative home advantage on the home rate.
    home_advantage: float = 1.20
    rho: float = -0.05
    #: Fraction of model inputs actually available, in [0, 1].
    feature_completeness: float = 1.0


def expected_goals(inputs: FootballInputs) -> tuple[float, float]:
    """Full-time Poisson rates for (home, away)."""
    lam_home = (
        inputs.league_mean_goals * inputs.home.attack * inputs.away.defence * inputs.home_advantage
    )
    lam_away = inputs.league_mean_goals * inputs.away.attack * inputs.home.defence
    return max(lam_home, 1e-6), max(lam_away, 1e-6)


class FootballDixonColesModel(BaseModel):
    """Dixon-Coles baseline. Ships as ``BACKTEST_ONLY``."""

    model_id = "football-dixon-coles-v1"
    sport = Sport.FOOTBALL
    validation_status = ValidationStatus.BACKTEST_ONLY

    def __init__(self, inputs_by_event: dict[str, FootballInputs]) -> None:
        self._inputs = inputs_by_event

    def supported_markets(self) -> frozenset[MarketType]:
        return frozenset(
            {
                MarketType.MATCH_RESULT_1X2,
                MarketType.DRAW_NO_BET,
                MarketType.DOUBLE_CHANCE,
                MarketType.TOTAL_GOALS,
            }
        )

    def predict(
        self,
        event: CanonicalEvent,
        market: MarketType,
        period: Period,
        line: Decimal | None = None,
    ) -> MarketPrediction | None:
        inputs = lookup_inputs(self._inputs, event)
        if inputs is None or market not in self.supported_markets():
            return None

        lam_home, lam_away = expected_goals(inputs)
        if period is Period.FIRST_HALF:
            lam_home *= FIRST_HALF_GOAL_SHARE
            lam_away *= FIRST_HALF_GOAL_SHARE

        matrix = score_matrix(lam_home, lam_away, inputs.rho)
        outcomes = outcome_probabilities(matrix)

        pushes: dict[str, float] = {}
        if market is MarketType.MATCH_RESULT_1X2:
            probs = outcomes
        elif market is MarketType.DRAW_NO_BET:
            # Unconditional win probabilities plus the draw as an explicit push.
            # The conditional figure is derived from the payoff when needed, so
            # the EV can account for the refunded stake (see engine/payoff.py).
            probs = {"home": outcomes["home"], "away": outcomes["away"]}
            pushes = {"home": outcomes["draw"], "away": outcomes["draw"]}
        elif market is MarketType.DOUBLE_CHANCE:
            probs = {
                "home_or_draw": outcomes["home"] + outcomes["draw"],
                "home_or_away": outcomes["home"] + outcomes["away"],
                "draw_or_away": outcomes["draw"] + outcomes["away"],
            }
        elif market is MarketType.TOTAL_GOALS:
            if line is None:
                return None
            probs = total_goals_probabilities(matrix, float(line))
        else:  # pragma: no cover - guarded by supported_markets
            return None

        n_eff = self._effective_sample_size(inputs, period)
        completeness = inputs.feature_completeness
        if period is Period.FIRST_HALF:
            # The half-time split is a fixed constant, not a fitted parameter.
            completeness *= 0.8

        return MarketPrediction(
            market=market,
            period=period,
            line=line,
            probabilities=probs,
            push_probabilities=pushes,
            synthetic_sample_size=n_eff,
            feature_completeness=completeness,
            diagnostics={
                "lambda_home": round(lam_home, 4),
                "lambda_away": round(lam_away, 4),
                "rho": inputs.rho,
                "home_matches_observed": inputs.home.matches_observed,
                "away_matches_observed": inputs.away.matches_observed,
                "period_note": (
                    "mi-temps dérivée d'un partage fixe des buts (approximation documentée)"
                    if period is Period.FIRST_HALF
                    else "temps réglementaire"
                ),
            },
        )

    @staticmethod
    def _effective_sample_size(inputs: FootballInputs, period: Period) -> float:
        """Pseudo-count for demo-mode synthetic uncertainty only (D-019).

        Halved for first-half markets: the goal-share split is a fixed constant
        rather than a fitted parameter, so those probabilities are strictly less
        determined than the full-time ones they derive from.
        """
        base = float(min(inputs.home.matches_observed, inputs.away.matches_observed))
        base = max(base, 1.0) * SYNTHETIC_INFORMATION_PER_MATCH
        if period is Period.FIRST_HALF:
            base *= 0.5
        return max(base * inputs.feature_completeness**2, 1.0)
