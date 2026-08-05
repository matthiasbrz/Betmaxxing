"""Model contract.

Every model returns a *distribution over the outcomes of a market*, plus the
effective sample size backing it. Returning a bare probability is not allowed:
the eligibility gate needs the uncertainty, and a model that cannot state its own
precision has no business publishing a candidate.

Derived markets on the same event must come from one coherent joint
distribution — never from independently tuned numbers — so that, for example,
``P(home win) + P(draw) + P(away win) == 1`` and the draw-no-bet price implied by
the model is consistent with its 1X2 prices.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TypeVar

from betmaxxing.domain.enums import MarketType, Period, Sport, ValidationStatus
from betmaxxing.domain.models import CanonicalEvent


@dataclass(frozen=True, slots=True)
class MarketPrediction:
    """Model probabilities for every selection of one market."""

    market: MarketType
    period: Period
    line: Decimal | None
    #: selection code -> **unconditional** probability that the selection wins.
    #: For a market with no refund path these sum to 1 across the partition.
    probabilities: dict[str, float]
    #: selection code -> probability the stake is refunded (draw-no-bet, integer
    #: totals). Absent means zero. Keeping this separate is what lets the EV use
    #: a real payoff instead of pretending a push cannot happen.
    push_probabilities: dict[str, float] = field(default_factory=dict)
    #: Deterministic pseudo-count used ONLY to build demo-mode synthetic
    #: uncertainty. It is not a claim about predictive precision — see D-019.
    synthetic_sample_size: float = 1.0
    #: Fraction of the model's inputs that were actually available, in [0, 1].
    feature_completeness: float = 1.0
    #: Free-form, sourced facts the explanation layer may quote.
    diagnostics: dict[str, float | str] = field(default_factory=dict)

    def push_for(self, code: str) -> float:
        return self.push_probabilities.get(code, 0.0)


T = TypeVar("T")


def lookup_inputs(mapping: dict[str, T], event: CanonicalEvent) -> T | None:
    """Find a model's inputs for an event, whatever id they were keyed by.

    Inputs are supplied before identity resolution runs, so they are usually
    keyed by a provider's own event id. Trying the internal id first and then
    each known source id keeps a model working across the remap instead of
    silently reporting that it cannot price anything.
    """
    found = mapping.get(event.internal_id)
    if found is not None:
        return found
    for source_id in event.source_ids.values():
        found = mapping.get(source_id)
        if found is not None:
            return found
    return None


class BaseModel(ABC):
    """A probabilistic model for one sport."""

    #: Stable identifier recorded on every candidate, e.g. "football-dc-v1".
    model_id: str = "abstract"
    sport: Sport
    #: Models start at BACKTEST_ONLY and are promoted only by the protocol in
    #: docs/validation-protocol.md.
    validation_status: ValidationStatus = ValidationStatus.BACKTEST_ONLY

    @abstractmethod
    def supported_markets(self) -> frozenset[MarketType]:
        """Markets this model can price."""

    @abstractmethod
    def predict(
        self,
        event: CanonicalEvent,
        market: MarketType,
        period: Period,
        line: Decimal | None = None,
    ) -> MarketPrediction | None:
        """Return the prediction, or ``None`` when this model cannot price it.

        Returning ``None`` produces a ``NO_MODEL_AVAILABLE`` rejection. It must
        never return a guess to avoid an empty result.
        """


class ModelNotAvailable(LookupError):
    """No model is registered for the requested sport."""
