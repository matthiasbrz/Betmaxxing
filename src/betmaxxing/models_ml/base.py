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

from betmaxxing.domain.enums import MarketType, Period, Sport, ValidationStatus
from betmaxxing.domain.models import CanonicalEvent


@dataclass(frozen=True, slots=True)
class MarketPrediction:
    """Model probabilities for every selection of one market."""

    market: MarketType
    period: Period
    line: float | None
    #: selection code -> probability. Must sum to 1 for partition markets.
    probabilities: dict[str, float]
    #: Effective sample size backing this market's estimate.
    effective_sample_size: float
    #: Fraction of the model's inputs that were actually available, in [0, 1].
    feature_completeness: float
    #: Free-form, sourced facts the explanation layer may quote.
    diagnostics: dict[str, float | str] = field(default_factory=dict)


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
        line: float | None = None,
    ) -> MarketPrediction | None:
        """Return the prediction, or ``None`` when this model cannot price it.

        Returning ``None`` produces a ``NO_MODEL_AVAILABLE`` rejection. It must
        never return a guess to avoid an empty result.
        """


class ModelNotAvailable(LookupError):
    """No model is registered for the requested sport."""
