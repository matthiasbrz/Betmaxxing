"""Canonical domain objects.

Two identity rules drive the shape of this module:

* **Event identity is opaque and stable.** ``internal_id`` carries no temporal or
  participant semantics, so a postponement across midnight does not mint a new
  event and two legs on one day cannot collide. Resolution from a provider's own
  id happens in :mod:`betmaxxing.ingestion.identity`.
* **Line identity is decimal, never float.** ``2.5``, ``2.50`` and ``2.500`` are
  one line; ``2.5`` and ``2.75`` are two. Identity uses a canonical decimal
  string, so it never depends on binary floating-point rendering.

Odds snapshots are immutable by construction: a price observed at an instant is a
historical fact, and a new observation produces a new snapshot.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from betmaxxing.domain.enums import (
    LINE_REQUIRED_MARKETS,
    BetOutcome,
    CollectionStatus,
    EventStatus,
    MarketType,
    Period,
    ProviderHealth,
    RejectionCode,
    ScanStatus,
    Sport,
    UncertaintyStatus,
    ValidationStatus,
)
from betmaxxing.domain.timeutil import ensure_utc

#: Maximum decimal places a market line may carry. Covers quarter lines (0.25).
MAX_LINE_DP = 3


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def canonical_line(value: Decimal | int | str) -> str:
    """Canonical text form of a market line.

    Normalises trailing zeros so ``2.50`` and ``2.500`` collapse onto ``2.5``,
    while keeping genuinely different lines apart. Rejects non-finite values and
    anything finer than :data:`MAX_LINE_DP`, which would signal a parsing error
    rather than a real market.
    """
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"line is not a valid decimal: {value!r}") from exc
    if not dec.is_finite():
        raise ValueError(f"line must be finite, got {value!r}")
    if -dec.as_tuple().exponent > MAX_LINE_DP:  # type: ignore[operator]
        raise ValueError(f"line has more than {MAX_LINE_DP} decimal places: {value!r}")
    normalised = dec.normalize()
    # normalize() renders integers in exponent form (2E+1); expand them back.
    if normalised == normalised.to_integral_value():
        normalised = normalised.quantize(Decimal(1))
    return format(normalised, "f")


class Participant(_Frozen):
    """A team or a player, with the identifiers needed to reconcile sources."""

    canonical_id: str
    name: str
    source_ids: dict[str, str] = Field(default_factory=dict)


class CanonicalEvent(_Frozen):
    """One sporting event, reconciled across sources."""

    #: Opaque, stable identity. Never derived from date or participants.
    internal_id: str
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
    #: provider -> provider's own event id.
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
    #: Decimal, never float — identity must not depend on binary rendering.
    line: Decimal | None = None

    @field_validator("line", mode="before")
    @classmethod
    def _coerce_line(cls, v: Any) -> Decimal | None:
        if v is None:
            return None
        # Validate through the canonical form so a bad line fails here, not later.
        return Decimal(canonical_line(v))

    @model_validator(mode="after")
    def _line_consistency(self) -> Self:
        needs_line = self.market in LINE_REQUIRED_MARKETS
        if needs_line and self.line is None:
            raise ValueError(f"market {self.market} requires an explicit line")
        if not needs_line and self.line is not None:
            raise ValueError(f"market {self.market} must not carry a line")
        return self

    @property
    def line_canonical(self) -> str | None:
        return None if self.line is None else canonical_line(self.line)

    @property
    def key(self) -> str:
        return f"{self.market}|{self.period}|{self.line_canonical or '-'}|{self.code}"


class OddsSnapshot(_Frozen):
    """An immutable observation of one price, at one instant, from one book."""

    provider: str
    bookmaker: str
    event_internal_id: str
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

    @field_validator("decimal_odds")
    @classmethod
    def _finite_odds(cls, v: float) -> float:
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("decimal odds must be finite")
        return v

    @property
    def fingerprint(self) -> str:
        """Deduplication key: same book, same selection, same price, same instant."""
        parts = [
            self.provider,
            self.bookmaker,
            self.event_internal_id,
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

    event_internal_id: str
    bookmaker: str
    market: MarketType
    period: Period
    line: Decimal | None = None
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


class UncertaintyEstimate(_Frozen):
    """What the system can honestly say about the precision of a probability.

    Bounds are optional on purpose. When no defensible method exists the status
    is ``UNAVAILABLE`` and every bound is ``None`` — the alternative, inventing a
    plausible-looking interval, is what D-019 supersedes.
    """

    method: str
    status: UncertaintyStatus
    lower: float | None = None
    upper: float | None = None
    #: Only meaningful for a genuine binomial proportion or a synthetic stand-in.
    effective_sample_size: float | None = None
    warning: str = ""

    @model_validator(mode="after")
    def _bounds_consistent(self) -> Self:
        has_bounds = self.lower is not None and self.upper is not None
        if self.status is UncertaintyStatus.UNAVAILABLE and has_bounds:
            raise ValueError("UNAVAILABLE uncertainty must not carry bounds")
        if has_bounds and not (0.0 <= self.lower <= self.upper <= 1.0):  # type: ignore[operator]
            raise ValueError("uncertainty bounds must satisfy 0 <= lower <= upper <= 1")
        if (self.lower is None) != (self.upper is None):
            raise ValueError("uncertainty bounds must be given together or not at all")
        return self

    @property
    def half_width(self) -> float | None:
        if self.lower is None or self.upper is None:
            return None
        return (self.upper - self.lower) / 2.0

    @property
    def is_usable_for_gating(self) -> bool:
        """Only a real method may gate a candidate outside demo mode."""
        return self.status in (UncertaintyStatus.ESTIMATED, UncertaintyStatus.VALIDATED)


class ProbabilityEstimate(_Frozen):
    """A model probability, its provenance, and its uncertainty — kept separate.

    Conflating these three is what made the previous version dishonest: a point
    estimate carried bounds that described nothing, and a validation status that
    was hard-coded rather than looked up.
    """

    probability: float = Field(gt=0.0, lt=1.0)
    model_id: str
    model_version: str
    #: Read from the model registry, never hard-coded at the call site.
    validation_status: ValidationStatus
    uncertainty: UncertaintyEstimate

    @property
    def lower(self) -> float | None:
        return self.uncertainty.lower

    @property
    def upper(self) -> float | None:
        return self.uncertainty.upper

    @property
    def half_width(self) -> float | None:
        return self.uncertainty.half_width


class ValueAssessment(_Frozen):
    """Everything the value maths produced for one priced selection."""

    decimal_odds: float
    implied_probability_raw: float
    implied_probability_novig: float | None
    devig_method: str | None
    #: Probability the selection wins, unconditional.
    win_probability: float
    #: Probability the stake is refunded (draw-no-bet, integer totals).
    push_probability: float
    #: ``p_win / (p_win + p_loss)`` — the figure comparable to a de-vigged price.
    conditional_win_probability: float
    #: How the market settles, recorded for audit.
    settlement_rule: str
    #: Full outcome distribution used to compute the EV.
    payoff_outcomes: list[dict[str, Any]]
    fair_odds: float
    ev: float
    #: ``None`` whenever no usable uncertainty method exists.
    ev_conservative: float | None
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
    model_version: str
    config_fingerprint: str
    explanation: str = ""


class Rejection(_Frozen):
    """Why one priced selection was dropped. Kept and displayed, never hidden."""

    event_internal_id: str
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
    quota_used: int | None = None
    last_request_cost: int | None = None


class DataHealth(_Frozen):
    providers: list[ProviderStatus]
    events_discovered: int
    events_in_window: int
    markets_evaluated: int
    selections_priced: int
    stale_snapshots: int
    quarantined_records: int
    #: Source records actually written by this run.
    events_persisted: int = 0
    snapshots_persisted: int = 0


class ScanResult(_Frozen):
    """The stable output contract of a scan."""

    scan_id: str
    status: ScanStatus
    #: Fine-grained reason. Distinguishes "no model" from "provider down".
    collection_status: CollectionStatus
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
    #: Identifier of the collection batch whose records back this scan.
    batch_id: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)


class SettlementResult(_Frozen):
    """Verified outcome of a recorded bet."""

    event_internal_id: str
    selection_key: str
    outcome: BetOutcome
    settled_at: datetime
    proof: str
    detail: str = ""
