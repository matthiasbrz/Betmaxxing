"""Uncertainty around a model probability.

**This module supersedes decision D-008. See D-019.**

What was wrong before
---------------------
A Wilson score interval was computed around ``p_model`` using a pseudo-count of
``matches_observed x INFORMATION_PER_MATCH``, and the result was used as *the
model's uncertainty* — including to gate real candidates through the conservative
EV filter.

A Wilson interval describes sampling error in an **observed binomial
proportion**. A model probability is not that. The interval it produces
propagates none of what actually makes a prediction uncertain:

* estimation error in the fitted parameters (attack/defence, Elo, serve rates);
* calibration error, and the uncertainty of the calibrator itself;
* dependence between markets on the same event, and between events;
* distribution shift between the fitting period and the event being priced;
* structural error from unmodelled effects (line-ups, retirements, fatigue).

That a plausible-looking EV came out of it is not evidence the method was sound.
A number that looks reasonable and means nothing is worse than no number, because
it passes a filter designed to stop exactly that.

What replaces it
----------------
Uncertainty is now a first-class statement with an explicit status:

``SYNTHETIC``
    A deterministic placeholder, **demo mode only**, so the interface can be
    exercised end to end. Carries a visible "NE PAS PARIER" warning and can
    never appear outside demo.
``UNAVAILABLE``
    No defensible method exists for this model yet. Bounds are ``None``,
    ``ev_conservative`` is ``None``, and the candidate is rejected with
    ``UNCERTAINTY_UNAVAILABLE``. This is the honest state for every model today.
``ESTIMATED``
    Produced by a real method (parametric/clustered bootstrap, posterior
    predictive) that has not yet passed a coverage study.
``VALIDATED``
    Produced by a method whose coverage was checked by the protocol.

Nothing promotes itself: ``ESTIMATED`` becomes ``VALIDATED`` only through the
registry, a model card and executed protocol evidence.

:func:`wilson_interval` is kept — it is the correct tool for a genuine observed
proportion, such as an empirical calibration-bin frequency in the evaluation
suite. It is simply not the uncertainty of a model prediction.
"""

from __future__ import annotations

from dataclasses import dataclass

from betmaxxing.config import RunMode
from betmaxxing.domain.enums import UncertaintyStatus
from betmaxxing.domain.models import UncertaintyEstimate

#: 90% two-sided.
Z_90 = 1.6448536269514722
#: 95% two-sided.
Z_95 = 1.959963984540054

_EPS = 1e-9

SYNTHETIC_WARNING = "SYNTHETIC — NE PAS PARIER (incertitude fabriquée, mode démo)"

UNAVAILABLE_DETAIL = (
    "Aucune méthode d'incertitude validée n'est disponible pour ce modèle. "
    "Voir docs/decisions.md D-019 et docs/validation-protocol.md."
)


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
    """Wilson score interval for a proportion observed with weight ``n_eff``.

    Correct for a genuine binomial proportion — an observed frequency in a
    calibration bin, a hit rate over settled bets. **Not** a statement about a
    model's predictive uncertainty; see the module docstring.
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


def unavailable(reason: str = UNAVAILABLE_DETAIL) -> UncertaintyEstimate:
    """The honest default for every model that has no validated method."""
    return UncertaintyEstimate(
        method="none",
        status=UncertaintyStatus.UNAVAILABLE,
        lower=None,
        upper=None,
        effective_sample_size=None,
        warning=reason,
    )


def synthetic(
    probability: float, effective_sample_size: float, z: float = Z_90
) -> UncertaintyEstimate:
    """Deterministic placeholder interval, for exercising the demo pipeline.

    Deliberately built from the Wilson formula so demo output has the right
    *shape*, and deliberately labelled ``SYNTHETIC`` so it can never be mistaken
    for a real statement or leak past :func:`uncertainty_for_mode`.
    """
    interval = wilson_interval(probability, effective_sample_size, z)
    return UncertaintyEstimate(
        method="synthetic_wilson_demo",
        status=UncertaintyStatus.SYNTHETIC,
        lower=interval.lower,
        upper=interval.upper,
        effective_sample_size=effective_sample_size,
        warning=SYNTHETIC_WARNING,
    )


def uncertainty_for_mode(
    *,
    mode: RunMode,
    probability: float,
    effective_sample_size: float | None,
    z: float = Z_90,
) -> UncertaintyEstimate:
    """The single gate deciding what may be claimed about precision.

    Demo mode gets a labelled synthetic interval so the interface can be shown
    working. Every other mode gets ``UNAVAILABLE`` until a real method exists —
    there is no argument, and no configuration value, that turns the synthetic
    interval into a real one.
    """
    if mode is RunMode.DEMO and effective_sample_size and effective_sample_size > 0:
        return synthetic(probability, effective_sample_size, z)
    return unavailable()


def blend_effective_sample_size(components: dict[str, float]) -> float:
    """Combine per-component sample sizes into one effective count.

    Uses ``n_eff = 1 / sum(1/n_i)``, so the weakest component dominates. Applies
    to genuine counts; it does not turn a model probability into a proportion.
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
    """Shrink an effective count when inputs were incomplete.

    ``completeness`` in ``[0, 1]``; the penalty is quadratic so partial gaps bite
    harder than a linear discount would.
    """
    if not (0.0 <= completeness <= 1.0):
        raise ValueError(f"completeness must lie in [0, 1], got {completeness}")
    return max(_EPS, n_eff * completeness * completeness)
