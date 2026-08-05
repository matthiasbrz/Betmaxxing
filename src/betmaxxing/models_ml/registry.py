"""Model registry and the publication gate.

The registry answers one question: **may this model's output be published in this
mode?** It is the only place that answers it.

Previously the answer came from a function that deleted both its arguments and
returned ``BACKTEST_ONLY`` unconditionally, so a candidate's validation status
was decoration rather than provenance. Now a registered model carries an
explicit ``model_id``, ``version`` and status, and the status is read from the
``model_registry`` table when one is present.

A model absent from the table is ``BACKTEST_ONLY``. Promotion never happens as a
side effect: it requires a row written deliberately, backed by the executed
protocol (docs/validation-protocol.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import Sport, UncertaintyStatus, ValidationStatus
from betmaxxing.models_ml.base import BaseModel

#: Minimum validation status required to publish a candidate, per run mode.
REQUIRED_STATUS: dict[RunMode, ValidationStatus | None] = {
    # Demo output is explicitly synthetic and labelled as such everywhere.
    RunMode.DEMO: None,
    RunMode.BACKTEST: None,
    RunMode.PAPER: ValidationStatus.BACKTEST_ONLY,
    RunMode.LIVE_ANALYSIS: ValidationStatus.LIVE_ANALYSIS,
}

_ORDER: dict[ValidationStatus, int] = {
    ValidationStatus.BACKTEST_ONLY: 0,
    ValidationStatus.PAPER_VALIDATED: 1,
    ValidationStatus.LIVE_ANALYSIS: 2,
}


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    """A model together with the provenance a candidate must carry."""

    model: BaseModel
    version: str
    validation_status: ValidationStatus = ValidationStatus.BACKTEST_ONLY
    #: Status of the uncertainty method this model can currently produce.
    uncertainty_status: UncertaintyStatus = UncertaintyStatus.UNAVAILABLE

    @property
    def model_id(self) -> str:
        return self.model.model_id

    def describe(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "sport": str(self.model.sport),
            "validation_status": str(self.validation_status),
            "uncertainty_status": str(self.uncertainty_status),
        }


@dataclass(slots=True)
class ModelRegistry:
    """Maps a sport to the model that prices it."""

    models: dict[Sport, RegisteredModel] = field(default_factory=dict)

    def get(self, sport: Sport) -> RegisteredModel | None:
        return self.models.get(sport)

    @property
    def is_empty(self) -> bool:
        return not self.models

    def describe(self) -> list[dict[str, str]]:
        return [entry.describe() for _, entry in sorted(self.models.items())]


def is_publishable(status: ValidationStatus, mode: RunMode) -> bool:
    """Whether a model at ``status`` may produce a published candidate in ``mode``."""
    required = REQUIRED_STATUS.get(mode)
    if required is None:
        return True
    return _ORDER[status] >= _ORDER[required]


def load_status_from_db(settings: Settings, model_id: str, version: str) -> ValidationStatus:
    """Read a model's persisted status. Absent means ``BACKTEST_ONLY``.

    Failing closed on any error is deliberate: a database problem must never be
    able to *raise* a model's privileges.
    """
    from betmaxxing.storage.db import session_scope
    from betmaxxing.storage.tables import ModelRegistryRow

    try:
        with session_scope(settings) as session:
            row = session.scalar(
                select(ModelRegistryRow).where(
                    ModelRegistryRow.model_id == model_id,
                    ModelRegistryRow.version == version,
                )
            )
            if row is None:
                return ValidationStatus.BACKTEST_ONLY
            return ValidationStatus(row.validation_status)
    except Exception:  # pragma: no cover - fail closed, never fail open
        return ValidationStatus.BACKTEST_ONLY
