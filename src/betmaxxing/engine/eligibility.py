"""The eligibility gate.

One function decides whether a priced selection becomes a candidate, and it
returns *every* reason it failed rather than the first, so the dashboard can show
"rejected for three things" instead of sending the user round a loop.

The gate is deliberately conjunctive: a candidate must pass EV, conservative EV,
uncertainty, freshness, odds range, data quality, scope and model-validation
checks simultaneously. There is no scoring compromise where a great EV buys
forgiveness for stale data — that trade is exactly how a fake edge gets published.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import RejectionCode, UncertaintyStatus, ValidationStatus
from betmaxxing.models_ml.registry import is_publishable


@dataclass(frozen=True, slots=True)
class GateInput:
    """Everything the gate needs. Assembled by the scorer, never by a provider."""

    ev: float
    #: ``None`` when no usable uncertainty method exists (D-019).
    ev_conservative: float | None
    uncertainty_status: UncertaintyStatus
    probability_half_width: float | None
    odds: float
    odds_age_seconds: float
    data_quality: float
    market_complete: bool
    mapping_ambiguous: bool
    in_window: bool
    in_scope: bool
    event_scheduled: bool
    validation_status: ValidationStatus
    mode: RunMode


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    codes: list[RejectionCode] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    @property
    def primary_code(self) -> RejectionCode | None:
        return self.codes[0] if self.codes else None

    @property
    def detail(self) -> str:
        return " | ".join(self.details)


def evaluate(candidate: GateInput, settings: Settings) -> GateResult:
    """Apply every eligibility rule. Order of checks is cheapest-first."""
    codes: list[RejectionCode] = []
    details: list[str] = []

    def fail(code: RejectionCode, detail: str) -> None:
        codes.append(code)
        details.append(detail)

    # --- scope -------------------------------------------------------------
    if not candidate.in_scope:
        fail(RejectionCode.OUT_OF_SCOPE, "Sport ou marché hors périmètre V1.")
    if not candidate.in_window:
        fail(
            RejectionCode.OUTSIDE_WINDOW,
            f"Événement hors de la fenêtre de {settings.window_hours:g} h.",
        )
    if not candidate.event_scheduled:
        fail(
            RejectionCode.EVENT_NOT_SCHEDULED,
            "L'événement n'est pas au statut « programmé » (V1 : prématch uniquement).",
        )

    # --- data integrity ----------------------------------------------------
    if candidate.mapping_ambiguous:
        fail(
            RejectionCode.EVENT_MAPPING_AMBIGUOUS,
            "Rapprochement d'événement ambigu entre sources — aucune décision publiée.",
        )
    if not candidate.market_complete:
        fail(
            RejectionCode.MARKET_INCOMPLETE,
            "Marché incomplet : la marge ne peut pas être retirée de façon fiable.",
        )
    if candidate.odds_age_seconds > settings.max_odds_age_seconds:
        fail(
            RejectionCode.ODDS_STALE,
            f"Cote observée il y a {candidate.odds_age_seconds:.0f}s "
            f"(> {settings.max_odds_age_seconds}s).",
        )
    if candidate.data_quality < settings.min_data_quality:
        fail(
            RejectionCode.LOW_DATA_QUALITY,
            f"Qualité des données {candidate.data_quality:.2f} < {settings.min_data_quality:.2f}.",
        )

    # --- price -------------------------------------------------------------
    if not (settings.min_odds <= candidate.odds <= settings.max_odds):
        fail(
            RejectionCode.ODDS_OUT_OF_RANGE,
            f"Cote {candidate.odds:.2f} hors plage "
            f"[{settings.min_odds:.2f}, {settings.max_odds:.2f}].",
        )

    # --- value -------------------------------------------------------------
    if candidate.ev < settings.min_ev:
        fail(
            RejectionCode.EV_TOO_LOW,
            f"EV {candidate.ev * 100:+.2f}% < seuil {settings.min_ev * 100:+.2f}%.",
        )
    # --- uncertainty -------------------------------------------------------
    # An unavailable uncertainty is not a small problem to be weighed against a
    # good EV: without it there is no conservative bound at all, so outside demo
    # the candidate cannot be published. This is the D-019 gate.
    if candidate.uncertainty_status is UncertaintyStatus.UNAVAILABLE:
        fail(
            RejectionCode.UNCERTAINTY_UNAVAILABLE,
            "Aucune méthode d'incertitude validée n'est disponible : "
            "EV prudente non calculable (voir D-019).",
        )
    elif candidate.uncertainty_status is UncertaintyStatus.SYNTHETIC and (
        candidate.mode is not RunMode.DEMO
    ):
        fail(
            RejectionCode.UNCERTAINTY_UNAVAILABLE,
            "Incertitude synthétique interdite hors du mode démo.",
        )
    elif candidate.ev_conservative is None:
        fail(
            RejectionCode.UNCERTAINTY_UNAVAILABLE,
            "EV prudente indisponible malgré une incertitude annoncée.",
        )
    else:
        if candidate.ev_conservative < settings.min_conservative_ev:
            fail(
                RejectionCode.CONSERVATIVE_EV_NEGATIVE,
                f"EV prudente {candidate.ev_conservative * 100:+.2f}% "
                f"< seuil {settings.min_conservative_ev * 100:+.2f}%.",
            )
        if (
            candidate.probability_half_width is not None
            and candidate.probability_half_width > settings.max_prob_half_width
        ):
            fail(
                RejectionCode.UNCERTAINTY_TOO_HIGH,
                f"Demi-largeur de l'intervalle {candidate.probability_half_width:.3f} "
                f"> {settings.max_prob_half_width:.3f}.",
            )

    # --- model governance --------------------------------------------------
    if not is_publishable(candidate.validation_status, candidate.mode):
        fail(
            RejectionCode.MODEL_NOT_VALIDATED,
            f"Modèle au statut {candidate.validation_status} — insuffisant "
            f"pour le mode {candidate.mode}.",
        )

    return GateResult(passed=not codes, codes=codes, details=details)
