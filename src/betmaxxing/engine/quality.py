"""Composite data-quality and confidence scoring.

Both scores are deliberately *decompositions*, not opinions: every component is a
named number in ``[0, 1]`` with a documented weight, so a low score can always be
traced to the input that caused it. Nothing here is a subjective star rating.
"""

from __future__ import annotations

from betmaxxing.domain.enums import UncertaintyStatus
from betmaxxing.domain.models import DataQuality

#: Component weights for the data-quality score. Must sum to 1.
QUALITY_WEIGHTS: dict[str, float] = {
    "freshness": 0.30,
    "market_completeness": 0.25,
    "event_mapping": 0.20,
    "feature_completeness": 0.15,
    "source_agreement": 0.10,
}

#: Component weights for the confidence score.
CONFIDENCE_WEIGHTS: dict[str, float] = {
    "data_quality": 0.35,
    "probability_precision": 0.35,
    "edge_margin": 0.20,
    "model_validation": 0.10,
}


def freshness_score(age_seconds: float, max_age_seconds: float) -> float:
    """1.0 for a just-observed price, decaying linearly to 0 at the staleness limit."""
    if max_age_seconds <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - age_seconds / max_age_seconds))


def completeness_score(present: int, expected: int) -> float:
    if expected <= 0:
        return 0.0
    return max(0.0, min(1.0, present / expected))


def score_data_quality(
    *,
    odds_age_seconds: float,
    max_odds_age_seconds: float,
    selections_present: int,
    selections_expected: int,
    mapping_ambiguous: bool,
    feature_completeness: float,
    source_agreement: float = 1.0,
) -> DataQuality:
    """Weighted data-quality score with its components and human-readable notes.

    ``source_agreement`` defaults to 1.0 when only one source priced the market;
    that is honest (nothing disagreed) and the missing corroboration is instead
    reflected in ``feature_completeness`` by the caller.
    """
    components = {
        "freshness": freshness_score(odds_age_seconds, max_odds_age_seconds),
        "market_completeness": completeness_score(selections_present, selections_expected),
        "event_mapping": 0.0 if mapping_ambiguous else 1.0,
        "feature_completeness": max(0.0, min(1.0, feature_completeness)),
        "source_agreement": max(0.0, min(1.0, source_agreement)),
    }
    score = sum(components[k] * w for k, w in QUALITY_WEIGHTS.items())

    notes: list[str] = []
    if components["freshness"] < 0.5:
        notes.append(f"Cote observée il y a {odds_age_seconds:.0f}s — fraîcheur dégradée.")
    if components["market_completeness"] < 1.0:
        notes.append(
            f"Marché incomplet : {selections_present}/{selections_expected} sélections cotées."
        )
    if mapping_ambiguous:
        notes.append("Rapprochement d'événement ambigu entre sources.")
    if components["feature_completeness"] < 0.8:
        notes.append("Certaines features du modèle sont absentes ou imputées.")
    if components["source_agreement"] < 0.8:
        notes.append("Désaccord notable entre sources sur ce marché.")

    return DataQuality(score=round(score, 4), components=components, notes=notes)


def score_confidence(
    *,
    data_quality: float,
    probability_half_width: float | None,
    max_half_width: float,
    ev: float,
    min_ev: float,
    model_validated: bool,
    uncertainty_status: UncertaintyStatus = UncertaintyStatus.UNAVAILABLE,
) -> dict[str, object]:
    """Explainable confidence score in ``[0, 1]`` plus its decomposition.

    ``edge_margin`` measures how far above the EV threshold the candidate sits,
    saturating at twice the threshold — being ten times over the bar is far more
    often a data error than a real edge, so it earns no extra confidence.
    """
    # No interval means no precision claim. Scoring it as zero is the honest
    # reading: we cannot say the estimate is precise, so we do not.
    if probability_half_width is None or uncertainty_status is UncertaintyStatus.UNAVAILABLE:
        precision = 0.0
    else:
        precision = max(0.0, min(1.0, 1.0 - probability_half_width / max_half_width))
    if min_ev > 0:
        edge_margin = max(0.0, min(1.0, (ev - min_ev) / min_ev))
    else:
        edge_margin = max(0.0, min(1.0, ev / 0.05))

    components = {
        "data_quality": max(0.0, min(1.0, data_quality)),
        "probability_precision": precision,
        "edge_margin": edge_margin,
        "model_validation": 1.0 if model_validated else 0.0,
    }
    score = sum(components[k] * w for k, w in CONFIDENCE_WEIGHTS.items())

    if score >= 0.75:
        label = "élevée"
    elif score >= 0.5:
        label = "moyenne"
    elif score >= 0.3:
        label = "faible"
    else:
        label = "très faible"

    drivers = sorted(components.items(), key=lambda kv: kv[1])
    limiting = [name for name, value in drivers[:2] if value < 0.7]

    return {
        "score": round(score, 4),
        "label": label,
        "uncertainty_status": str(uncertainty_status),
        "components": {k: round(v, 4) for k, v in components.items()},
        "weights": CONFIDENCE_WEIGHTS,
        "limiting_factors": limiting,
    }
