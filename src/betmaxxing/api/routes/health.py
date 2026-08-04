"""Health and provider status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from betmaxxing import __version__
from betmaxxing.config import get_settings
from betmaxxing.domain.timeutil import utc_now
from betmaxxing.providers.base import ProviderUnavailable
from betmaxxing.providers.factory import build_providers

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "mode": str(settings.mode),
        "time_utc": utc_now().isoformat(),
        "config_fingerprint": settings.fingerprint(),
    }


@router.get("/providers")
def providers() -> dict[str, Any]:
    """Provider health, quotas and freshness for the current mode."""
    settings = get_settings()
    try:
        bundle = build_providers(settings, utc_now())
    except ProviderUnavailable as exc:
        return {
            "mode": str(settings.mode),
            "available": False,
            "reason": str(exc),
            "providers": [],
            "models": [],
        }
    statuses = [
        p.health().model_dump(mode="json")  # type: ignore[attr-defined]
        for p in (bundle.odds, bundle.context, bundle.results)
    ]
    return {
        "mode": str(settings.mode),
        "available": True,
        "providers": statuses,
        "models": bundle.models.describe(),
        "warnings": bundle.warnings,
    }


@router.get("/models")
def models() -> dict[str, Any]:
    """Registered models and their validation status."""
    settings = get_settings()
    try:
        bundle = build_providers(settings, utc_now())
    except ProviderUnavailable as exc:
        return {"models": [], "reason": str(exc)}
    return {
        "models": bundle.models.describe(),
        "note": (
            "Un modèle au statut BACKTEST_ONLY ne peut pas publier de candidat en "
            "mode live_analysis. Voir docs/validation-protocol.md."
        ),
    }
