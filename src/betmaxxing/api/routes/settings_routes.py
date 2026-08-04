"""Configuration and threshold inspection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from betmaxxing import DISCLAIMER
from betmaxxing.config import CONFIG_SCHEMA_VERSION, get_settings

router = APIRouter(tags=["settings"])


@router.get("/settings")
def read_settings() -> dict[str, Any]:
    """Effective configuration, secrets masked."""
    settings = get_settings()
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "config_fingerprint": settings.fingerprint(),
        "settings": settings.redacted(),
        "disclaimer": DISCLAIMER,
    }


@router.get("/settings/thresholds")
def read_thresholds() -> dict[str, Any]:
    """The exact eligibility thresholds applied, and their provisional status."""
    settings = get_settings()
    return {
        "thresholds": settings.eligibility_thresholds(),
        "config_fingerprint": settings.fingerprint(),
        "status": "PROVISIONAL",
        "note": (
            "Ces seuils sont provisoires tant que le protocole de validation "
            "hors échantillon (docs/validation-protocol.md) n'a pas été exécuté. "
            "Ils ne doivent pas être ajustés après consultation du jeu de test final."
        ),
    }


@router.get("/responsible-gambling")
def responsible_gambling() -> dict[str, Any]:
    """Responsible-gambling controls and information."""
    settings = get_settings()
    return {
        "staking_suggestions_enabled": settings.staking_enabled,
        "bankroll_configured": settings.bankroll > 0,
        "max_stake_pct_of_bankroll": settings.max_stake_pct_of_bankroll,
        "max_daily_exposure_pct": settings.max_daily_exposure_pct,
        "kelly_fraction": settings.kelly_fraction,
        "principles": [
            "Aucune martingale, aucune poursuite des pertes, aucune mise de récupération.",
            "Une défaite termine une montante par défaut.",
            "Les suggestions de mise peuvent être désactivées entièrement.",
            "Une probabilité trop incertaine produit une mise de zéro.",
            "L'application ne place aucun pari et n'accède à aucun compte de bookmaker.",
            "Usage réservé aux personnes majeures, dans une juridiction où il est autorisé.",
        ],
        "stop_control": "POST /challenges/{id}/stop met fin immédiatement à un challenge.",
        "france_help_note": (
            "En France, un dispositif national d'aide aux joueurs existe. Vérifiez la "
            "formulation et les coordonnées officielles en vigueur auprès de l'autorité "
            "compétente (ANJ) avant toute diffusion — elles ne sont pas codées en dur ici "
            "pour éviter d'afficher une information périmée."
        ),
        "disclaimer": DISCLAIMER,
    }
