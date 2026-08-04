"""Deterministic explanation of a candidate.

This is the template renderer that always exists, with or without an LLM. It only
restates numbers the engine already computed and evidence that already carries a
source — it cannot introduce a new claim, and it never touches a probability or an
eligibility decision.

The separation matters: an LLM may later be handed the same evidence pack to
phrase it more fluently, but the pack is built here, from validated inputs, and
the LLM's output is treated as prose, never as data.
"""

from __future__ import annotations

from betmaxxing.domain.models import (
    Candidate,
    CanonicalEvent,
    DataQuality,
    EvidenceItem,
    ProbabilityEstimate,
    Selection,
    ValueAssessment,
)
from betmaxxing.domain.timeutil import format_display

#: Sample sizes below this are called out as too thin to lean on.
THIN_SAMPLE = 30


def build_risks(
    *,
    event: CanonicalEvent,
    selection: Selection,
    probability: ProbabilityEstimate,
    value: ValueAssessment,
    data_quality: DataQuality,
) -> list[str]:
    """Concrete, checkable risk statements — no generic filler."""
    risks: list[str] = []

    if value.implied_probability_novig is None:
        risks.append(
            "Marché non départageable en book complet : la marge n'a pas pu être retirée, "
            "la comparaison utilise la probabilité implicite brute (1/cote)."
        )
    if probability.effective_sample_size < THIN_SAMPLE:
        risks.append(
            f"Échantillon effectif faible ({probability.effective_sample_size:.0f}) — "
            "l'estimation est peu contrainte."
        )
    drop = value.decimal_odds - value.min_acceptable_odds
    if drop < 0.10:
        risks.append(
            f"Marge de manœuvre étroite : la value disparaît sous {value.min_acceptable_odds:.2f} "
            f"(cote actuelle {value.decimal_odds:.2f}, écart {drop:+.2f})."
        )
    if data_quality.score < 0.8:
        risks.extend(data_quality.notes)
    if event.sport.value == "tennis":
        risks.append(
            "Abandon, forfait ou blessure en cours de match : le règlement dépend des règles "
            "du bookmaker concerné et n'est pas modélisé."
        )
    if selection.period.value == "first_half":
        risks.append(
            "Marché mi-temps dérivé d'un partage fixe des buts — approximation documentée, "
            "moins fiable que le temps réglementaire."
        )
    return risks


def build_invalidation_conditions(value: ValueAssessment, event: CanonicalEvent) -> list[str]:
    """What would make this candidate stop being one."""
    return [
        f"La cote descend sous {value.min_acceptable_odds:.2f} (seuil d'EV configuré).",
        "Une absence, un forfait ou une composition publiée modifie les hypothèses du modèle.",
        f"L'événement quitte le statut « programmé » (actuellement : {event.status}).",
        "La cote dépasse la limite de fraîcheur sans nouvelle observation.",
    ]


def build_missing_information(evidence: list[EvidenceItem]) -> list[str]:
    """What the engine knows it does not know."""
    missing: list[str] = []
    kinds = {item.kind for item in evidence}
    if "uncertainty" in kinds:
        missing.extend(item.text for item in evidence if item.kind == "uncertainty")
    if not evidence:
        missing.append("Aucun élément de contexte sourcé n'était disponible à l'heure du scan.")
    return missing


def render_explanation(candidate: Candidate) -> str:
    """Human-readable summary. Pure function of the candidate — no I/O, no model."""
    value = candidate.value
    probability = candidate.probability
    event = candidate.event
    selection = candidate.selection

    lines: list[str] = []
    lines.append(
        f"{event.competition}"
        + (f" — {event.stage}" if event.stage else "")
        + (f" · {event.surface}" if event.surface else "")
    )
    lines.append(f"{event.label} — début {format_display(event.start_time_utc)}")
    lines.append("")
    lines.append(f"Sélection : {selection.label}")
    lines.append(
        f"Marché : {selection.market} · période {selection.period}"
        + (f" · ligne {selection.line:g}" if selection.line is not None else "")
    )
    lines.append(
        f"Cote {candidate.bookmaker} : {value.decimal_odds:.2f} "
        f"(observée il y a {candidate.odds_age_seconds:.0f}s)"
    )
    lines.append("")

    if value.implied_probability_novig is not None:
        lines.append(
            f"Probabilité implicite : {value.implied_probability_raw:.1%} brute · "
            f"{value.implied_probability_novig:.1%} sans marge ({value.devig_method})"
        )
    else:
        lines.append(
            f"Probabilité implicite brute : {value.implied_probability_raw:.1%} "
            "(marge non retirée — book incomplet pour ce marché)"
        )
    lines.append(
        f"Probabilité modèle : {probability.probability:.1%} "
        f"[{probability.lower:.1%} - {probability.upper:.1%}]"
    )
    lines.append(f"Fair odds modèle : {value.fair_odds:.2f}")
    lines.append(f"EV : {value.ev * 100:+.2f}% · EV prudente : {value.ev_conservative * 100:+.2f}%")
    lines.append(
        f"Cote minimale acceptable : {value.min_acceptable_odds:.2f} · "
        f"sensibilité {value.ev_sensitivity_per_odds_tick * 100:+.2f}% par 0,01 de cote"
    )
    lines.append(
        f"Qualité des données : {candidate.data_quality.score:.2f} · "
        f"confiance : {candidate.confidence['label']} ({candidate.confidence['score']:.2f})"
    )
    lines.append(
        f"Modèle : {candidate.model_id} ({probability.validation_status}) · "
        f"config {candidate.config_fingerprint}"
    )

    if candidate.evidence:
        lines.append("")
        lines.append("Éléments factuels sourcés :")
        for item in candidate.evidence:
            marker = {"fact": "•", "weak_signal": "~", "uncertainty": "?"}.get(item.kind, "•")
            lines.append(f"  {marker} {item.text} [{item.source}, {format_display(item.as_of)}]")

    if candidate.risks:
        lines.append("")
        lines.append("Risques :")
        lines.extend(f"  - {risk}" for risk in candidate.risks)

    if candidate.missing_information:
        lines.append("")
        lines.append("Informations manquantes :")
        lines.extend(f"  - {item}" for item in candidate.missing_information)

    if candidate.invalidation_conditions:
        lines.append("")
        lines.append("Conditions d'invalidation :")
        lines.extend(f"  - {item}" for item in candidate.invalidation_conditions)

    if candidate.stake is not None:
        lines.append("")
        if candidate.stake.amount > 0:
            lines.append(
                f"Mise simulée : {candidate.stake.units:.2f} u "
                f"({candidate.stake.amount:.2f} {candidate.stake.currency}) — "
                f"{candidate.stake.rationale}"
            )
        else:
            lines.append(f"Mise simulée : 0 — {candidate.stake.rationale}")

    return "\n".join(lines)
