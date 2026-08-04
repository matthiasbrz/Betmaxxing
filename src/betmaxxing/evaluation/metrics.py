"""Evaluation metrics for the pre-registered validation protocol.

Pure functions over ``(probability, outcome)`` pairs — no I/O, no model, no
config — so they can be unit-tested against known values and reused identically
by the backtester, the paper-trading monitor and the model-evaluation page.

Return/yield is deliberately reported next to a bootstrap confidence interval:
a yield figure without an interval is the single most misleading number in
betting analytics, and this project does not display one.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

_EPS = 1e-15


def _validate(probabilities: list[float], outcomes: list[int]) -> None:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    if not probabilities:
        raise ValueError("at least one observation is required")
    if any(not (0.0 <= p <= 1.0) for p in probabilities):
        raise ValueError("probabilities must lie in [0, 1]")
    if any(o not in (0, 1) for o in outcomes):
        raise ValueError("outcomes must be 0 or 1")


def log_loss(probabilities: list[float], outcomes: list[int]) -> float:
    """Mean negative log-likelihood. Lower is better; 0.6931 is a coin flip."""
    _validate(probabilities, outcomes)
    total = 0.0
    for p, y in zip(probabilities, outcomes, strict=True):
        clipped = min(max(p, _EPS), 1.0 - _EPS)
        total += -(y * math.log(clipped) + (1 - y) * math.log(1.0 - clipped))
    return total / len(probabilities)


def brier_score(probabilities: list[float], outcomes: list[int]) -> float:
    """Mean squared error of the probability. Lower is better."""
    _validate(probabilities, outcomes)
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes, strict=True)) / len(
        probabilities
    )


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_predicted: float
    observed_frequency: float

    @property
    def gap(self) -> float:
        return abs(self.mean_predicted - self.observed_frequency)


def calibration_curve(
    probabilities: list[float], outcomes: list[int], bins: int = 10
) -> list[CalibrationBin]:
    """Reliability diagram data. Empty bins are omitted, not reported as zero."""
    _validate(probabilities, outcomes)
    if bins < 2:
        raise ValueError("at least two bins are required")
    edges = [i / bins for i in range(bins + 1)]
    out: list[CalibrationBin] = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        # The last bin is closed on the right so p == 1.0 is not dropped.
        members = [
            (p, y)
            for p, y in zip(probabilities, outcomes, strict=True)
            if (lo <= p < hi) or (i == bins - 1 and p == hi)
        ]
        if not members:
            continue
        out.append(
            CalibrationBin(
                lower=lo,
                upper=hi,
                count=len(members),
                mean_predicted=sum(p for p, _ in members) / len(members),
                observed_frequency=sum(y for _, y in members) / len(members),
            )
        )
    return out


def expected_calibration_error(
    probabilities: list[float], outcomes: list[int], bins: int = 10
) -> float:
    """Count-weighted mean absolute gap between predicted and observed."""
    curve = calibration_curve(probabilities, outcomes, bins)
    total = sum(b.count for b in curve)
    if total == 0:  # pragma: no cover - guarded by _validate
        return 0.0
    return sum(b.gap * b.count for b in curve) / total


def interval_coverage(
    lowers: list[float], uppers: list[float], outcomes: list[int], bins: int = 10
) -> float:
    """Empirical coverage of the model's probability intervals.

    Groups observations by their interval and checks how often the realised
    frequency in a group falls inside the group's mean interval. This is the
    test that keeps ``INFORMATION_PER_MATCH`` honest: a nominal 90% interval
    should cover ~90% of the time, and a value that is set too high shows up
    here as coverage well below nominal.
    """
    if not (len(lowers) == len(uppers) == len(outcomes)):
        raise ValueError("lowers, uppers and outcomes must have the same length")
    if not lowers:
        raise ValueError("at least one observation is required")

    midpoints = [(lo + hi) / 2.0 for lo, hi in zip(lowers, uppers, strict=True)]
    edges = [i / bins for i in range(bins + 1)]
    covered = 0
    considered = 0
    for i in range(bins):
        lo_edge, hi_edge = edges[i], edges[i + 1]
        members = [
            (lo, hi, y)
            for lo, hi, mid, y in zip(lowers, uppers, midpoints, outcomes, strict=True)
            if (lo_edge <= mid < hi_edge) or (i == bins - 1 and mid == hi_edge)
        ]
        if len(members) < 2:
            continue
        observed = sum(y for _, _, y in members) / len(members)
        mean_lower = sum(lo for lo, _, _ in members) / len(members)
        mean_upper = sum(hi for _, hi, _ in members) / len(members)
        considered += 1
        if mean_lower <= observed <= mean_upper:
            covered += 1
    return covered / considered if considered else 0.0


@dataclass(frozen=True, slots=True)
class BettingPerformance:
    bets: int
    staked: float
    profit: float
    yield_pct: float
    max_drawdown: float
    win_rate: float


def betting_performance(
    odds: list[float], outcomes: list[int], stakes: list[float] | None = None
) -> BettingPerformance:
    """Realised return of a set of settled bets, at flat or supplied stakes."""
    if len(odds) != len(outcomes):
        raise ValueError("odds and outcomes must have the same length")
    if not odds:
        raise ValueError("at least one bet is required")
    sizes = stakes if stakes is not None else [1.0] * len(odds)
    if len(sizes) != len(odds):
        raise ValueError("stakes must have the same length as odds")

    staked = sum(sizes)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    profit = 0.0
    wins = 0
    for o, y, stake in zip(odds, outcomes, sizes, strict=True):
        pnl = stake * (o - 1.0) if y == 1 else -stake
        profit += pnl
        wins += y
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return BettingPerformance(
        bets=len(odds),
        staked=staked,
        profit=profit,
        yield_pct=100.0 * profit / staked if staked else 0.0,
        max_drawdown=max_dd,
        win_rate=wins / len(odds),
    )


def bootstrap_yield_interval(
    odds: list[float],
    outcomes: list[int],
    *,
    iterations: int = 2000,
    confidence: float = 0.95,
    seed: int = 12345,
) -> tuple[float, float]:
    """Percentile bootstrap interval for the yield, in percent.

    Seeded so a reported interval is reproducible from the archived run.
    """
    if len(odds) != len(outcomes):
        raise ValueError("odds and outcomes must have the same length")
    if not odds:
        raise ValueError("at least one bet is required")
    if not (0.0 < confidence < 1.0):
        raise ValueError("confidence must lie in (0, 1)")

    rng = random.Random(seed)
    n = len(odds)
    samples: list[float] = []
    for _ in range(iterations):
        indices = [rng.randrange(n) for _ in range(n)]
        profit = sum(odds[i] - 1.0 if outcomes[i] == 1 else -1.0 for i in indices)
        samples.append(100.0 * profit / n)
    samples.sort()
    tail = (1.0 - confidence) / 2.0
    lo_index = max(0, int(tail * iterations) - 1)
    hi_index = min(iterations - 1, int((1.0 - tail) * iterations))
    return samples[lo_index], samples[hi_index]


def closing_line_value(entry_odds: float, closing_odds: float) -> float:
    """CLV as a fraction: positive means the price shortened after entry.

    Diagnostic only. It is never used as an entry price in a backtest — doing so
    is the classic look-ahead leak this project's protocol forbids.
    """
    if entry_odds <= 1.0 or closing_odds <= 1.0:
        raise ValueError("odds must be > 1.0")
    return entry_odds / closing_odds - 1.0
