"""Tennis baseline: surface Elo mapped onto a hierarchical point model.

The problem with pricing tennis markets independently is incoherence: a match
winner probability of 60%, a "wins at least one set" of 70% and a total-games
line priced by a separate regression will contradict each other, and the
contradiction is exactly where a fake edge appears.

So this module builds **one** object — the point-win probabilities on serve for
both players — and derives every market from it by exact enumeration:

    point -> game -> tiebreak -> set (with its games distribution) -> match

Calibration runs the chain backwards. Surface Elo gives a target match-win
probability; a bisection finds the serve-advantage ``delta`` around a documented
surface baseline such that the chain reproduces that target. Everything else
(win a set, total games) then follows from the same parameters, so the derived
markets cannot disagree with the match winner.

Sources of imprecision that are *not* modelled are reported rather than invented:
retirement risk, fatigue and injury adjust ``feature_completeness`` and the
diagnostics, they do not silently shift a probability.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

from betmaxxing.domain.enums import MarketType, Period, Sport, ValidationStatus
from betmaxxing.domain.models import CanonicalEvent
from betmaxxing.models_ml.base import BaseModel, MarketPrediction

#: Average probability of winning a point on serve, by surface. Provisional
#: constants, documented in docs/model-cards.md; they set the baseline around
#: which the calibrated serve advantage is applied.
SERVE_BASELINE_BY_SURFACE: dict[str, float] = {
    "hard": 0.640,
    "clay": 0.615,
    "grass": 0.665,
    "carpet": 0.650,
}
DEFAULT_SERVE_BASELINE = 0.635

_MAX_TIEBREAK_POINTS = 100
_BISECTION_ITERS = 80

#: Information carried by one observed match, relative to a single Bernoulli
#: trial on the market outcome. A tennis match supplies ~150 service points and
#: the model estimates only two serve parameters from them, so a match is worth
#: considerably more than one win/lose bit. Set above the football value for
#: that reason.
#:
#: PROVISIONAL, and falsifiable the same way: the validation protocol checks
#: that the nominal 90% interval achieves ~90% empirical coverage. Inflating
#: this constant would narrow intervals and let under-determined candidates
#: through the gate, which coverage testing is designed to catch.
INFORMATION_PER_MATCH = 3.0


def elo_win_probability(elo_a: float, elo_b: float) -> float:
    """Standard Elo expectation for player A."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def game_win_probability(p: float) -> float:
    """Probability the server wins a game, given point-win probability ``p``.

    Exact closed form: the four ways to win without deuce, plus reaching deuce
    (6 orderings of 3-3) and winning the deuce sub-game with ``p²/(p²+q²)``.
    """
    if not (0.0 < p < 1.0):
        raise ValueError(f"point probability must lie in (0, 1), got {p}")
    q = 1.0 - p
    deuce = p * p / (p * p + q * q)
    return p**4 + 4.0 * p**4 * q + 10.0 * p**4 * q**2 + 20.0 * p**3 * q**3 * deuce


@lru_cache(maxsize=4096)
def tiebreak_win_probability(p_a: float, p_b: float, a_serves_first: bool) -> float:
    """Probability A wins a first-to-7, win-by-2 tiebreak.

    Serve order is the real one: the first server takes one point, then service
    alternates every two points.
    """
    memo: dict[tuple[int, int, int], float] = {}

    def solve(a: int, b: int, n: int) -> float:
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        if n >= _MAX_TIEBREAK_POINTS:  # pragma: no cover - mass here is ~1e-15
            return 0.5
        key = (a, b, n)
        cached = memo.get(key)
        if cached is not None:
            return cached
        first_server_on_point = (((n + 1) // 2) % 2) == 0
        a_is_serving = first_server_on_point == a_serves_first
        p_point_a = p_a if a_is_serving else 1.0 - p_b
        value = p_point_a * solve(a + 1, b, n + 1) + (1.0 - p_point_a) * solve(a, b + 1, n + 1)
        memo[key] = value
        return value

    return solve(0, 0, 0)


def _is_set_over(ga: int, gb: int) -> bool:
    """Standard advantage set with a tiebreak at 6-6."""
    if ga == 6 and gb <= 4:
        return True
    if gb == 6 and ga <= 4:
        return True
    if ga == 7 and gb == 5:
        return True
    return bool(gb == 7 and ga == 5)


@lru_cache(maxsize=4096)
def set_distribution(
    p_a: float, p_b: float, a_serves_first: bool
) -> tuple[tuple[tuple[int, int], float], ...]:
    """Exact distribution over final set scores ``(games_a, games_b)``.

    Returned as a sorted tuple of pairs so the result is hashable and cacheable.
    """
    g_a_on_serve = game_win_probability(p_a)
    g_b_on_serve = game_win_probability(p_b)

    live: dict[tuple[int, int], float] = {(0, 0): 1.0}
    final: dict[tuple[int, int], float] = defaultdict(float)

    while live:
        nxt: dict[tuple[int, int], float] = defaultdict(float)
        for (ga, gb), mass in live.items():
            games_played = ga + gb
            a_is_serving = ((games_played % 2) == 0) == a_serves_first
            p_a_takes_game = g_a_on_serve if a_is_serving else 1.0 - g_b_on_serve

            for a_won, p_game in ((True, p_a_takes_game), (False, 1.0 - p_a_takes_game)):
                weight = mass * p_game
                if weight <= 0.0:
                    continue
                nga, ngb = (ga + 1, gb) if a_won else (ga, gb + 1)
                if _is_set_over(nga, ngb):
                    final[(nga, ngb)] += weight
                elif nga == 6 and ngb == 6:
                    tb_a_serves = (((nga + ngb) % 2) == 0) == a_serves_first
                    p_tb = tiebreak_win_probability(p_a, p_b, tb_a_serves)
                    final[(7, 6)] += weight * p_tb
                    final[(6, 7)] += weight * (1.0 - p_tb)
                else:
                    nxt[(nga, ngb)] += weight
        live = nxt

    return tuple(sorted(final.items()))


@dataclass(frozen=True, slots=True)
class MatchDistribution:
    """Joint distribution over (sets won by A, sets won by B, total games)."""

    outcomes: dict[tuple[int, int, int], float]
    sets_to_win: int

    @property
    def p_a_wins_match(self) -> float:
        return sum(p for (sa, _, _), p in self.outcomes.items() if sa == self.sets_to_win)

    def p_player_wins_at_least_one_set(self, player: str) -> float:
        idx = 0 if player == "home" else 1
        return sum(p for key, p in self.outcomes.items() if key[idx] >= 1)

    def total_games_probabilities(self, line: float) -> dict[str, float]:
        """Over/Under on total games for an exact half-line."""
        if abs(line - round(line)) < 1e-9:
            raise ValueError(
                f"integer total-games line {line} can push; only half-lines are supported in V1"
            )
        over = under = 0.0
        for (_, _, games), p in self.outcomes.items():
            if games > line:
                over += p
            else:
                under += p
        return {"over": over, "under": under}

    def expected_total_games(self) -> float:
        return sum(games * p for (_, _, games), p in self.outcomes.items())


def match_distribution(
    p_a: float, p_b: float, sets_to_win: int, a_serves_first: bool = True
) -> MatchDistribution:
    """Enumerate the match exactly, carrying the running games total.

    Who serves first in the next set is determined, not assumed: after an
    odd number of games the first server of the set served last, so the
    opponent opens the following set.
    """
    if sets_to_win not in (2, 3):
        raise ValueError(f"sets_to_win must be 2 or 3, got {sets_to_win}")

    # state: (sets_a, sets_b, a_serves_first_next_set, games_so_far) -> mass
    live: dict[tuple[int, int, bool, int], float] = {(0, 0, a_serves_first, 0): 1.0}
    final: dict[tuple[int, int, int], float] = defaultdict(float)

    while live:
        nxt: dict[tuple[int, int, bool, int], float] = defaultdict(float)
        for (sa, sb, serves_first, games), mass in live.items():
            for (ga, gb), p_set in set_distribution(p_a, p_b, serves_first):
                weight = mass * p_set
                if weight <= 0.0:
                    continue
                nsa, nsb = (sa + 1, sb) if ga > gb else (sa, sb + 1)
                ngames = games + ga + gb
                next_serves_first = serves_first if (ga + gb) % 2 == 0 else not serves_first
                if nsa == sets_to_win or nsb == sets_to_win:
                    final[(nsa, nsb, ngames)] += weight
                else:
                    nxt[(nsa, nsb, next_serves_first, ngames)] += weight
        live = nxt

    return MatchDistribution(outcomes=dict(final), sets_to_win=sets_to_win)


def calibrate_serve_probabilities(
    target_match_probability: float,
    sets_to_win: int,
    baseline: float,
    a_serves_first: bool = True,
) -> tuple[float, float]:
    """Find serve probabilities reproducing ``target_match_probability``.

    Sets ``p_a = baseline + delta`` and ``p_b = baseline - delta`` and bisects on
    ``delta``; the chain's match probability is monotonically increasing in
    ``delta``, so the root is unique.
    """
    if not (0.0 < target_match_probability < 1.0):
        raise ValueError("target match probability must lie in (0, 1)")

    max_delta = min(baseline - 0.30, 0.95 - baseline, 0.30)
    lo, hi = -max_delta, max_delta

    def match_prob(delta: float) -> float:
        p_a = round(baseline + delta, 6)
        p_b = round(baseline - delta, 6)
        return match_distribution(p_a, p_b, sets_to_win, a_serves_first).p_a_wins_match

    if match_prob(hi) < target_match_probability:
        return round(baseline + hi, 6), round(baseline - hi, 6)
    if match_prob(lo) > target_match_probability:
        return round(baseline + lo, 6), round(baseline - lo, 6)

    for _ in range(_BISECTION_ITERS):
        mid = (lo + hi) / 2.0
        if hi - lo < 1e-6:
            break
        if match_prob(mid) < target_match_probability:
            lo = mid
        else:
            hi = mid
    delta = (lo + hi) / 2.0
    return round(baseline + delta, 6), round(baseline - delta, 6)


@dataclass(frozen=True, slots=True)
class TennisInputs:
    """Sourced inputs for one match."""

    elo_home: float
    elo_away: float
    #: Surface-specific Elo; falls back to the global rating when absent.
    elo_home_surface: float | None = None
    elo_away_surface: float | None = None
    matches_home: int = 0
    matches_away: int = 0
    surface: str = "hard"
    sets_to_win: int = 2
    home_serves_first: bool = True
    feature_completeness: float = 1.0
    #: Free-text, sourced notes (rest days, retirement history...). Never used
    #: to move a probability — only surfaced in the explanation.
    notes: tuple[str, ...] = field(default_factory=tuple)


class TennisHierarchicalModel(BaseModel):
    """Surface Elo + hierarchical point model. Ships as ``BACKTEST_ONLY``."""

    model_id = "tennis-elo-hierarchical-v1"
    sport = Sport.TENNIS
    validation_status = ValidationStatus.BACKTEST_ONLY

    def __init__(self, inputs_by_event: dict[str, TennisInputs]) -> None:
        self._inputs = inputs_by_event

    def supported_markets(self) -> frozenset[MarketType]:
        return frozenset(
            {
                MarketType.MATCH_WINNER,
                MarketType.PLAYER_WINS_A_SET,
                MarketType.TOTAL_GAMES,
            }
        )

    def predict(
        self,
        event: CanonicalEvent,
        market: MarketType,
        period: Period,
        line: float | None = None,
    ) -> MarketPrediction | None:
        inputs = self._inputs.get(event.canonical_id)
        if inputs is None or market not in self.supported_markets():
            return None
        # Tennis markets in V1 settle on the full match only.
        if period is not Period.FULL_TIME:
            return None

        elo_a = inputs.elo_home_surface if inputs.elo_home_surface is not None else inputs.elo_home
        elo_b = inputs.elo_away_surface if inputs.elo_away_surface is not None else inputs.elo_away
        target = elo_win_probability(elo_a, elo_b)
        baseline = SERVE_BASELINE_BY_SURFACE.get(inputs.surface.lower(), DEFAULT_SERVE_BASELINE)

        p_a, p_b = calibrate_serve_probabilities(
            target, inputs.sets_to_win, baseline, inputs.home_serves_first
        )
        dist = match_distribution(p_a, p_b, inputs.sets_to_win, inputs.home_serves_first)

        if market is MarketType.MATCH_WINNER:
            p_home = dist.p_a_wins_match
            probs = {"home": p_home, "away": 1.0 - p_home}
        elif market is MarketType.PLAYER_WINS_A_SET:
            # Not a partition: both selections can win. Reported as-is; the
            # scorer knows not to de-vig this market as a book.
            probs = {
                "home": dist.p_player_wins_at_least_one_set("home"),
                "away": dist.p_player_wins_at_least_one_set("away"),
            }
        elif market is MarketType.TOTAL_GAMES:
            if line is None:
                return None
            probs = dist.total_games_probabilities(line)
        else:  # pragma: no cover - guarded by supported_markets
            return None

        n_eff = self._effective_sample_size(inputs)
        return MarketPrediction(
            market=market,
            period=period,
            line=line,
            probabilities=probs,
            effective_sample_size=n_eff,
            feature_completeness=inputs.feature_completeness,
            diagnostics={
                "elo_used_home": round(elo_a, 1),
                "elo_used_away": round(elo_b, 1),
                "elo_match_probability_home": round(target, 4),
                "serve_point_prob_home": p_a,
                "serve_point_prob_away": p_b,
                "surface": inputs.surface,
                "sets_to_win": inputs.sets_to_win,
                "expected_total_games": round(dist.expected_total_games(), 2),
                "settlement_note": (
                    "Abandon/forfait réglés selon les règles du bookmaker — non modélisés"
                ),
            },
        )

    @staticmethod
    def _effective_sample_size(inputs: TennisInputs) -> float:
        """The less-observed player governs the precision of the estimate."""
        base = float(min(inputs.matches_home, inputs.matches_away))
        base = max(base, 1.0) * INFORMATION_PER_MATCH
        return max(base * inputs.feature_completeness**2, 1.0)
