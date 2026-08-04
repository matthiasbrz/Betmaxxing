"""Canonical domain objects.

Odds snapshots are immutable by construction (``frozen=True``): a price observed
at an instant is a historical fact and is never edited in place. A new
observation produces a new snapshot with its own fingerprint.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from betmaxxing.domain.enums import (
    LINE_REQUIRED_MARKETS,
    BetOutcome,
    EventStatus,
    MarketType,
    Period,
    ProviderHealth,
    RejectionCode,
    ScanStatus,
    Sport,
    ValidationStatus,
)
from betmaxxing.domain.timeutil import ensure_utc


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Participant(_Frozen):
    """A team or a player, with the identifiers needed to reconcile sources."""

    canonical_id: str
    name: str
    source_ids: dict[str, str] = Field(default_factory=dict)


class CanonicalEvent(_Frozen):
    """One sporting event, reconciled across sources."""

    canonical_id: str
    sport: Sport
    competition: str
    #: Round / matchday label as published by the source, e.g. "R1", "J3".
    stage: str | None = None
    #: Tennis only: "hard", "clay", "grass", "carpet".
    surface: str | None = None
    #: Tennis only: number of sets required to win (2 == best of 3).
    sets_to_win: int | None = None
    home: Participant
    away: Participant
    start_time_utc: datetime
    status: EventStatus = EventStatus.SCHEDULED
    source_ids: dict[str, str] = Field(default_factory=dict)
    #: Set when two source events could not be reconciled unambiguously.
    mapping_ambiguous: bool = False

    @field_validator("start_time_utc")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)

    @property
    def label(self) -> str:
        return f"{self.home.name} vs {self.away.name}"


class Selection(_Frozen):
    """The precise thing being priced.

    Two selections are comparable only if every field here matches. ``line`` is
    mandatory for over/under style markets and forbidden elsewhere.
    """

    market: MarketType
    period: Period
    #: Stable machine key, e.g. "home", "draw", "away", "over", "under",
    #: "home_or_draw", "player_a".
    code: str
    #: Exactly the label the bookmaker shows, kept verbatim for auditability.
    label: str
    line: float | None = None

    @model_validator(mode="after")
    def _line_consistency(self) -> Self:
        needs_line = self.market in LINE_REQUIRED_MARKETS
        if needs_line and self.line is None:
            raise ValueError(f"market {self.market} requires an explicit line")
        if not needs_line and self.line is not None:
            raise ValueError(f"market {self.market} must not carry a line")
        return self

    @property
    def key(self) -> str:
        line = "-" if self.line is None else f"{self.line:g}"
        return f"{self.market}|{self.period}|{line}|{self.code}"


class OddsSnapshot(_Frozen):
    """An immutable observation of one price, at one instant, from one book."""

    provider: str
    bookmaker: str
    event_canonical_id: str
    event_source_id: str
    selection: Selection
    decimal_odds: float = Field(gt=1.0)
    currency: str = "EUR"
    event_status: EventStatus = EventStatus.SCHEDULED
    #: Timestamp the provider itself attributes to the price, when supplied.
    provider_updated_at: datetime | None = None
    #: When Betmaxxing considers the price to have been true.
    observed_at: datetime
    #: When Betmaxxing received it (>= observed_at in practice).
    received_at: datetime
    #: Free-form provenance (endpoint, request id, file name...).
    source_meta: dict[str, str] = Field(default_factory=dict)

    @field_validator("observed_at", "received_at", "provider_updated_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else ensure_utc(v)

    @property
    def fingerprint(self) -> str:
        """Deduplication key: same book, same selection, same price, same instant."""
        parts = [
            self.provider,
            self.bookmaker,
            self.event_canonical_id,
            self.selection.key,
            f"{self.decimal_odds:.6f}",
            self.observed_at.isoformat(),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]

    @property
    def implied_probability_raw(self) -> float:
        """``1 / o`` — includes the bookmaker margin. Never compare this to a
        model probability without saying so."""
        return 1.0 / self.decimal_odds


class MarketBook(BaseModel):
    """All prices for one (event, market, period, line) from one bookmaker."""

    model_config = ConfigDict(extra="forbid")

    event_canonical_id: str
    bookmaker: str
    market: MarketType
    period: Period
    line: float | None = None
    snapshots: list[OddsSnapshot] = Field(default_factory=list)

    @property
    def overround(self) -> float:
        """Sum of raw implied probabilities. ``> 1`` for a normal book."""
        return sum(s.implied_probability_raw for s in self.snapshots)

    @property
    def margin(self) -> float:
        """Bookmaker margin as a fraction, e.g. 0.05 for a 5% book."""
        return self.overround - 1.0

    def by_code(self, code: str) -> OddsSnapshot | None:
        return next((s for s in self.snapshots if s.selection.code == code), None)


class ProbabilityEstimate(_Frozen):
    """A model probability with its uncertainty, never a bare number."""

    probability: float = Field(gt=0.0, lt=1.0)
    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)
    #: Effective sample size behind the estimate; drives the interval width.
    effective_sample_size: float = Field(gt=0)
    model_id: str
    validation_status: ValidationStatus

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.lower <= self.probability <= self.upper:
            raise ValueError("probability must lie inside [lower, upper]")
        return self

    @property
    def half_width(self) -> float:
        return (self.upper - self.lower) / 2.0


class ValueAssessment(_Frozen):
    """Everything the value maths produced for one priced selection."""

    decimal_odds: float
    implied_probability_raw: float
    implied_probability_novig: float | None
    devig_method: str | None
    model_probability: float
    model_probability_lower: float
    model_probability_upper: float
    fair_odds: float
    ev: float
    ev_conservative: float
    min_acceptable_odds: float
    #: dEV per +0.01 of decimal odds.
    ev_sensitivity_per_odds_tick: float
    overround: float | None


class EvidenceItem(_Frozen):
    """One sourced factual argument. ``source`` and ``as_of`` are mandatory —
    an argument without provenance is not publishable."""

    text: str
    source: str
    as_of: datetime
    #: "fact" | "weak_signal" | "uncertainty"
    kind: str = "fact"

    @field_validator("as_of")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)


class DataQuality(_Frozen):
    """Composite, explainable data-quality score in ``[0, 1]``."""

    score: float = Field(ge=0.0, le=1.0)
    components: dict[str, float]
    notes: list[str] = Field(default_factory=list)


class StakeSuggestion(_Frozen):
    """Simulated stake. Zero whenever staking is disabled or p is too uncertain."""

    units: float = Field(ge=0.0)
    amount: float = Field(ge=0.0)
    currency: str
    kelly_full_fraction: float
    kelly_applied_fraction: float
    capped_by: str | None
    rationale: str


class Candidate(_Frozen):
    """A qualified bet candidate. Produced only when every gate passed."""

    candidate_id: str
    event: CanonicalEvent
    selection: Selection
    bookmaker: str
    provider: str
    observed_at: datetime
    odds_age_seconds: float
    value: ValueAssessment
    probability: ProbabilityEstimate
    data_quality: DataQuality
    confidence: dict[str, Any]
    evidence: list[EvidenceItem]
    risks: list[str]
    missing_information: list[str]
    invalidation_conditions: list[str]
    odds_movement: list[dict[str, Any]] = Field(default_factory=list)
    stake: StakeSuggestion | None = None
    model_id: str
    config_fingerprint: str
    explanation: str = ""


class Rejection(_Frozen):
    """Why one priced selection was dropped. Kept and displayed, never hidden."""

    event_canonical_id: str
    event_label: str
    selection_key: str
    code: RejectionCode
    detail: str


class ProviderStatus(_Frozen):
    name: str
    kind: str
    health: ProviderHealth
    detail: str = ""
    events_returned: int = 0
    freshest_observation_age_seconds: float | None = None
    quota_remaining: int | None = None


class DataHealth(_Frozen):
    providers: list[ProviderStatus]
    events_discovered: int
    events_in_window: int
    markets_evaluated: int
    selections_priced: int
    stale_snapshots: int
    quarantined_records: int


class ScanResult(_Frozen):
    """The stable output contract of a scan."""

    scan_id: str
    status: ScanStatus
    mode: str
    generated_at: datetime
    window: dict[str, datetime]
    data_health: DataHealth
    candidates: list[Candidate]
    rejections: list[Rejection]
    rejections_summary: dict[str, int]
    thresholds: dict[str, Any]
    config_fingerprint: str
    disclaimer: str

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)


class SettlementResult(_Frozen):
    """Verified outcome of a recorded bet."""

    event_canonical_id: str
    selection_key: str
    outcome: BetOutcome
    settled_at: datetime
    proof: str
    detail: str = ""
