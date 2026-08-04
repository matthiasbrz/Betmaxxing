"""Provider selection per run mode.

The important behaviour here is the refusal: in ``paper`` and ``live_analysis``
a missing key does not fall back to the demo pack. It raises, the scan reports
``DATA_UNAVAILABLE``, and the user is told exactly which variable is missing.
Silent substitution of synthetic data for real data is the failure mode this
whole project is built to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import Sport
from betmaxxing.models_ml.football import FootballDixonColesModel
from betmaxxing.models_ml.registry import ModelRegistry
from betmaxxing.models_ml.tennis import TennisHierarchicalModel
from betmaxxing.providers.base import ProviderUnavailable
from betmaxxing.providers.demo import (
    DemoContextProvider,
    DemoOddsProvider,
    DemoResultsProvider,
)
from betmaxxing.providers.demo.world import football_inputs, tennis_inputs
from betmaxxing.providers.manual import ManualCsvOddsProvider, load_csv


@dataclass(slots=True)
class ProviderBundle:
    odds: object
    context: object
    results: object
    models: ModelRegistry
    #: Warnings to surface in the scan header (degraded modes, manual imports...).
    warnings: list[str]


def build_providers(
    settings: Settings, now: datetime, manual_odds_path: str | None = None
) -> ProviderBundle:
    """Assemble the provider bundle for the configured mode."""
    warnings: list[str] = []

    if manual_odds_path:
        report = load_csv(manual_odds_path)
        if report.quarantined:
            warnings.append(
                f"{len(report.quarantined)} ligne(s) du fichier manuel mises en quarantaine."
            )
        odds_provider: object = ManualCsvOddsProvider(report)
        warnings.append("Cotes issues d'un import manuel horodaté — pas d'un flux temps réel.")
        return ProviderBundle(
            odds=odds_provider,
            context=DemoContextProvider(now) if settings.mode is RunMode.DEMO else _NoContext(),
            results=DemoResultsProvider(),
            models=_models_for(settings, now),
            warnings=warnings,
        )

    if settings.mode is RunMode.DEMO:
        warnings.append(
            "MODE DÉMO — toutes les cotes et statistiques sont synthétiques. "
            "Aucune donnée réelle, aucune décision à prendre sur cette base."
        )
        return ProviderBundle(
            odds=DemoOddsProvider(now),
            context=DemoContextProvider(now),
            results=DemoResultsProvider(),
            models=_models_for(settings, now),
            warnings=warnings,
        )

    if settings.winamax_mode == "manual":
        warnings.append(
            "Winamax indisponible par voie programmatique autorisée — "
            "utilisez `betmaxxing scan --manual-odds <fichier.csv>`."
        )

    if settings.odds_provider in ("", "demo"):
        raise ProviderUnavailable(
            f"Mode {settings.mode} : aucun fournisseur de cotes réel configuré. "
            "Renseignez BETMAXXING_ODDS_PROVIDER (et sa clé), ou fournissez un "
            "import manuel avec --manual-odds. Le mode démo n'est jamais "
            "substitué automatiquement."
        )
    if not settings.odds_api_key:
        raise ProviderUnavailable(
            f"Fournisseur de cotes « {settings.odds_provider} » sélectionné mais "
            "BETMAXXING_ODDS_API_KEY est vide."
        )
    raise ProviderUnavailable(
        f"Aucun adaptateur n'est implémenté pour « {settings.odds_provider} ». "
        "L'intégration d'un fournisseur autorisé est la tranche 3 de la feuille de "
        "route (docs/roadmap.md) ; l'interface OddsProvider est prête à la recevoir."
    )


def _models_for(settings: Settings, now: datetime) -> ModelRegistry:
    """Build the model registry.

    Outside demo mode the registry is empty until a fitted rating store exists
    (tranche 4). An empty registry produces ``NO_MODEL_AVAILABLE`` rejections —
    an honest "I cannot price this", not a fabricated probability.
    """
    if settings.mode is RunMode.DEMO:
        return ModelRegistry(
            models={
                Sport.FOOTBALL: FootballDixonColesModel(football_inputs(now)),
                Sport.TENNIS: TennisHierarchicalModel(tennis_inputs(now)),
            }
        )
    return ModelRegistry(models={})


class _NoContext:
    """Context provider that honestly returns nothing."""

    name = "none"

    def health(self) -> object:
        from betmaxxing.domain.enums import ProviderHealth
        from betmaxxing.domain.models import ProviderStatus

        return ProviderStatus(
            name=self.name,
            kind="context",
            health=ProviderHealth.NOT_CONFIGURED,
            detail="Aucun fournisseur de contexte configuré.",
        )

    def context_for(self, event: object) -> list[object]:
        del event
        return []
