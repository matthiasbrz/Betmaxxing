"""Historical odds: interface and **offline** cost estimator only.

The v4 historical endpoints are billed at a different, much higher rate than the
live ones, and a naive backfill of a season across several markets is a large,
irreversible spend. Nothing in this module contacts the network. It exists so a
backfill can be *priced and discussed* before anyone decides to run one.

Two guards, both deliberate:

* :func:`estimate_historical_cost` is pure arithmetic over the request's shape.
  It returns an explicit **upper bound**, never a point estimate, because a
  budget conversation that starts from an optimistic number is useless.
* :class:`HistoricalOddsRequest` carries ``acknowledged_cost``. Any future
  execution path must refuse without it — consent to a live scan is not consent
  to a paid backfill.

The download itself is out of scope for this tranche and is not implemented.
Calling :func:`fetch_historical` raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from betmaxxing.domain.timeutil import ensure_utc

#: v4 bills historical snapshots at a multiple of the live rate. Treated as an
#: upper bound for estimation; the authoritative figure is the provider's own
#: pricing page, which must be checked before any run.
HISTORICAL_COST_MULTIPLIER = 10

#: Finest snapshot spacing v4 offers. A tighter interval cannot be requested, so
#: asking for one would silently round and under-estimate the cost.
MIN_SNAPSHOT_INTERVAL = timedelta(minutes=5)


class HistoricalNotEnabled(RuntimeError):
    """Historical download is not implemented and must not be improvised."""


@dataclass(frozen=True, slots=True)
class HistoricalOddsRequest:
    """A backfill someone is considering. Describes it; does not run it."""

    sport_keys: tuple[str, ...]
    markets: tuple[str, ...]
    regions: tuple[str, ...]
    bookmakers: tuple[str, ...]
    start: datetime
    end: datetime
    snapshot_interval: timedelta = timedelta(hours=1)
    competitions: tuple[str, ...] = ()
    #: Must be set explicitly, by a human, after reading the estimate.
    acknowledged_cost: bool = False

    def __post_init__(self) -> None:
        if ensure_utc(self.end) <= ensure_utc(self.start):
            raise ValueError("la fenêtre historique doit être strictement positive")
        if self.snapshot_interval < MIN_SNAPSHOT_INTERVAL:
            raise ValueError(
                f"intervalle minimal supporté : {MIN_SNAPSHOT_INTERVAL}. "
                "Un intervalle plus fin ne peut pas être facturé honnêtement."
            )
        if not self.sport_keys or not self.markets:
            raise ValueError("sports et marchés sont requis pour estimer un coût")


@dataclass(frozen=True, slots=True)
class HistoricalCostEstimate:
    """An **upper bound**, with the arithmetic that produced it."""

    snapshots: int
    requests: int
    credits_upper_bound: int
    assumptions: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"Snapshots demandés   : {self.snapshots}",
            f"Requêtes estimées    : {self.requests}",
            f"Crédits (borne haute): {self.credits_upper_bound}",
            "",
            "Hypothèses :",
            *[f"  · {a}" for a in self.assumptions],
            "",
            "Ce chiffre est une BORNE SUPÉRIEURE, pas un devis. Aucun appel n'a été "
            "effectué. Une exécution exige un consentement explicite et distinct.",
        ]
        return "\n".join(lines)


def estimate_historical_cost(request: HistoricalOddsRequest) -> HistoricalCostEstimate:
    """Price a backfill without contacting anything."""
    span = ensure_utc(request.end) - ensure_utc(request.start)
    snapshots = int(span / request.snapshot_interval) + 1
    per_snapshot = (
        len(request.sport_keys) * max(1, len(request.markets)) * max(1, len(request.regions))
    )
    requests = snapshots * len(request.sport_keys)
    credits = snapshots * per_snapshot * HISTORICAL_COST_MULTIPLIER

    return HistoricalCostEstimate(
        snapshots=snapshots,
        requests=requests,
        credits_upper_bound=credits,
        assumptions=[
            f"coût unitaire = marchés x régions, multiplié par {HISTORICAL_COST_MULTIPLIER} "
            "pour l'historique (tarif à revérifier auprès du fournisseur)",
            f"{len(request.sport_keys)} compétition(s) interrogée(s) à chaque snapshot",
            f"intervalle de {request.snapshot_interval}, soit {snapshots} snapshots",
            "aucune déduplication supposée entre snapshots consécutifs",
            (
                f"filtre bookmaker ({', '.join(request.bookmakers) or 'aucun'}) sans effet "
                "sur le coût : la facturation porte sur la requête, pas sur le volume rendu"
            ),
        ],
    )


def fetch_historical(request: HistoricalOddsRequest) -> None:
    """Not implemented, on purpose."""
    raise HistoricalNotEnabled(
        "Le téléchargement historique n'est pas implémenté. Cette tranche fournit "
        "uniquement l'interface et l'estimateur de coût hors ligne. Une exécution "
        "future exigera un consentement explicite et distinct du scan courant."
    )


__all__ = [
    "HISTORICAL_COST_MULTIPLIER",
    "HistoricalCostEstimate",
    "HistoricalNotEnabled",
    "HistoricalOddsRequest",
    "estimate_historical_cost",
    "fetch_historical",
]
