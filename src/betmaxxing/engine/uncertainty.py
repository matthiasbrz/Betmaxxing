"""Uncertainty around a model probability.

A point probability without an interval cannot be filtered honestly, so every
model in this project must return an effective sample size alongside its
estimate. The interval is a Wilson score interval evaluated at that pseudo-count:
closed-form, no SciPy dependency, well-behaved near 0 and 1 (unlike the normal
approximation, which happily returns negative bounds for small ``n``).

``effective_sample_size`` is deliberately *not* the number of historical matches.
It is the model's own statement of how much independent information backs the
estimate, after discounting for recency weighting, missing features and
extrapolation. Inflating it directly loosens the eligibility gate, so it is
treated as a first-class model output and recorded in the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 90% two-sided.
Z_90 = 1.6448536269514722
#: 95% two-sided.
Z_95 = 1.959963984540054

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Interval:
    lower: float
    point: float
    upper: float

    @property
    def half_width(self) -> float:
        return (self.upper - self.lower) / 2.0

    @property
    def width(self) -> float:
        return self.upper - self.lower


def wilson_interval(probability: float, n_eff: float, z: float = Z_90) -> Interval:
    """Wilson score interval for ``probability`` observed with weight ``n_eff``.

    The bounds are clipped into ``(0, 1)`` exclusive so downstream EV maths — which
    divides by a probability — never sees a zero.
    """
    if not (0.0 < probability < 1.0):
        raise ValueError(f"probability must lie in (0, 1), got {probability}")
    if n_eff <= 0:
        raise ValueError(f"effective sample size must be > 0, got {n_eff}")
    if z <= 0:
        raise ValueError(f"z must be > 0, got {z}")

    z2 = z * z
    denom = 1.0 + z2 / n_eff
    centre = (probability + z2 / (2.0 * n_eff)) / denom
    spread = (
        z
        / denom
        * ((probability * (1.0 - probability) / n_eff) + z2 / (4.0 * n_eff * n_eff)) ** 0.5
    )
    lower = max(_EPS, min(probability, centre - spread))
    upper = min(1.0 - _EPS, max(probability, centre + spread))
    return Interval(lower=lower, point=probability, upper=upper)


def blend_effective_sample_size(components: dict[str, float]) -> float:
    """Combine per-component sample sizes into one effective count.

    Uses the harmonic-style combination ``n_eff = 1 / sum(1/n_i)``, i.e. the
    weakest component dominates. This is deliberately pessimistic: a model that
    is confident about form but blind to line-ups should not inherit the
    confidence of its strongest input.
    """
    if not components:
        raise ValueError("at least one component is required")
    inverse = 0.0
    for name, n in components.items():
        if n <= 0:
            raise ValueError(f"component {name!r} must have a positive sample size")
        inverse += 1.0 / n
    return 1.0 / inverse


def penalise_for_missing_data(n_eff: float, completeness: float) -> float:
    """Shrink the effective sample size when inputs were incomplete.

    ``completeness`` in ``[0, 1]``; a fully complete input set leaves ``n_eff``
    unchanged, and the penalty is quadratic so partial gaps bite harder than a
    linear discount would.
    """
    if not (0.0 <= completeness <= 1.0):
        raise ValueError(f"completeness must lie in [0, 1], got {completeness}")
    return max(_EPS, n_eff * completeness * completeness)
