"""Model registry and validation gate.

The registry is the single place that answers "may this model's output be
published?". A model whose ``validation_status`` is ``BACKTEST_ONLY`` can still
produce probabilities — that is how backtests run — but the eligibility engine
refuses to turn them into a live candidate. This is what stops an unvalidated
model from silently reaching the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass

from betmaxxing.config import RunMode
from betmaxxing.domain.enums import Sport, ValidationStatus
from betmaxxing.models_ml.base import BaseModel

#: The minimum validation status required to publish a candidate, per run mode.
REQUIRED_STATUS: dict[RunMode, ValidationStatus | None] = {
    RunMode.DEMO: None,  # demo output is explicitly synthetic and labelled as such
    RunMode.BACKTEST: None,
    RunMode.PAPER: ValidationStatus.BACKTEST_ONLY,
    RunMode.LIVE_ANALYSIS: ValidationStatus.LIVE_ANALYSIS,
}

_ORDER: dict[ValidationStatus, int] = {
    ValidationStatus.BACKTEST_ONLY: 0,
    ValidationStatus.PAPER_VALIDATED: 1,
    ValidationStatus.LIVE_ANALYSIS: 2,
}


@dataclass(slots=True)
class ModelRegistry:
    """Maps a sport to the model that prices it."""

    models: dict[Sport, BaseModel]

    def get(self, sport: Sport) -> BaseModel | None:
        return self.models.get(sport)

    def describe(self) -> list[dict[str, str]]:
        return [
            {
                "sport": str(sport),
                "model_id": model.model_id,
                "validation_status": str(model.validation_status),
            }
            for sport, model in sorted(self.models.items())
        ]


def is_publishable(status: ValidationStatus, mode: RunMode) -> bool:
    """Whether a model at ``status`` may produce a published candidate in ``mode``."""
    required = REQUIRED_STATUS.get(mode)
    if required is None:
        return True
    return _ORDER[status] >= _ORDER[required]
