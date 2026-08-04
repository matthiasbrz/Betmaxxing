"""Command-line entry point."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from betmaxxing import DISCLAIMER, __version__
from betmaxxing.config import RunMode, Settings, get_settings
from betmaxxing.domain.enums import ScanStatus
from betmaxxing.domain.models import Candidate, ScanResult
from betmaxxing.domain.timeutil import format_display, utc_now
from betmaxxing.engine.scan import run_scan
from betmaxxing.providers.manual import ManualImportError, load_csv
from betmaxxing.storage.db import create_all, session_scope
from betmaxxing.storage.repositories import EventRepository, OddsRepository, ScanRepository

app = typer.Typer(
    name="betmaxxing",
    help="Betmaxxing — aide à la décision pour paris sportifs prématch. Ne place aucun pari.",
    no_args_is_help=True,
    add_completion=False,
)
odds_app = typer.Typer(help="Gestion des cotes (import manuel horodaté).")
db_app = typer.Typer(help="Gestion de la base de données.")
app.add_typer(odds_app, name="odds")
app.add_typer(db_app, name="db")

console = Console()


def _candidate_card(candidate: Candidate) -> str:
    """Dense vertical summary — information hierarchy over table width."""
    value = candidate.value
    event = candidate.event
    half_width = (value.model_probability_upper - value.model_probability_lower) / 2

    header = f"[bold]{event.label}[/]"
    context = f"{event.competition}"
    if event.stage:
        context += f" · {event.stage}"
    if event.surface:
        context += f" · {event.surface}"
    start = format_display(event.start_time_utc)
    context += f" · début {start}"

    if value.implied_probability_novig is not None:
        implied = (
            f"{value.implied_probability_raw:.1%} brute · "
            f"{value.implied_probability_novig:.1%} sans marge ({value.devig_method})"
        )
    else:
        implied = f"{value.implied_probability_raw:.1%} brute [dim](marge non retirée)[/]"

    lines = [
        header,
        f"[dim]{context}[/]",
        "",
        f"Sélection   : [bold]{candidate.selection.label}[/]",
        f"Marché      : {candidate.selection.market} · {candidate.selection.period}"
        + (
            f" · ligne {candidate.selection.line:g}" if candidate.selection.line is not None else ""
        ),
        f"Cote        : [bold]{value.decimal_odds:.2f}[/] ({candidate.bookmaker}, "
        f"observée il y a {candidate.odds_age_seconds:.0f}s)",
        f"Implicite   : {implied}",
        f"p modèle    : [bold]{value.model_probability:.1%}[/] "
        f"[{value.model_probability_lower:.1%} - {value.model_probability_upper:.1%}] "
        f"(±{half_width:.1%})",
        f"Fair odds   : {value.fair_odds:.2f}",
        f"EV          : [green]{value.ev * 100:+.2f}%[/] · "
        f"prudente [bold]{value.ev_conservative * 100:+.2f}%[/]",
        f"Cote min.   : {value.min_acceptable_odds:.2f} "
        f"[dim](sensibilité {value.ev_sensitivity_per_odds_tick * 100:+.2f}%/0,01)[/]",
        f"Qualité     : {candidate.data_quality.score:.2f} · "
        f"confiance {candidate.confidence['label']} ({candidate.confidence['score']:.2f})",
        f"Modèle      : {candidate.model_id} [yellow]{candidate.probability.validation_status}[/]",
    ]
    if candidate.stake is not None:
        if candidate.stake.amount > 0:
            lines.append(
                f"Mise simulée: {candidate.stake.units:.2f} u "
                f"({candidate.stake.amount:.2f} {candidate.stake.currency})"
            )
        else:
            lines.append(f"Mise simulée: [dim]0 — {candidate.stake.rationale}[/]")
    if candidate.risks:
        lines.append("")
        lines.append("[bold]Risques[/]")
        lines.extend(f"  - {risk}" for risk in candidate.risks[:4])
    return "\n".join(lines)


def _render(result: ScanResult, settings: Settings) -> None:
    """Scan header + candidate table + rejection summary."""
    colour = {
        ScanStatus.CANDIDATES_FOUND: "green",
        ScanStatus.NO_BET: "yellow",
        ScanStatus.DATA_UNAVAILABLE: "red",
    }[result.status]

    console.print()
    console.rule(f"[bold {colour}]{result.status}[/] · mode {result.mode}")
    console.print(f"Scan       : {result.scan_id}")
    console.print(f"Généré     : {format_display(result.generated_at)}")
    console.print(
        f"Fenêtre    : {format_display(result.window['from'])} "
        f"→ {format_display(result.window['to'])}"
    )
    console.print(
        f"Événements : {result.data_health.events_discovered} découverts · "
        f"{result.data_health.events_in_window} dans la fenêtre · "
        f"{result.data_health.markets_evaluated} marchés · "
        f"{result.data_health.selections_priced} sélections cotées"
    )
    console.print(
        f"Données    : {result.data_health.stale_snapshots} cote(s) périmée(s) · "
        f"{result.data_health.quarantined_records} enregistrement(s) en quarantaine"
    )
    console.print(f"Config     : {result.config_fingerprint}")

    console.print("\n[bold]Fournisseurs[/]")
    for provider in result.data_health.providers:
        console.print(
            f"  · {provider.name} ({provider.kind}) — {provider.health}: {provider.detail}"
        )

    if result.status is ScanStatus.DATA_UNAVAILABLE:
        console.print(
            "\n[bold red]DONNÉES INDISPONIBLES[/] — aucune recommandation n'est produite. "
            "Aucune donnée ancienne n'est réutilisée en remplacement."
        )
    elif not result.candidates:
        console.print(
            "\n[bold yellow]AUCUN PARI QUALIFIÉ[/] — c'est un résultat normal, "
            "pas une erreur. Les critères configurés n'ont pas été satisfaits."
        )
    else:
        console.print(f"\n[bold]{len(result.candidates)} candidat(s) qualifié(s)[/]")
        for rank, candidate in enumerate(result.candidates, start=1):
            console.print(Panel(_candidate_card(candidate), title=f"#{rank}", expand=True))

    if result.rejections_summary:
        console.print("\n[bold]Motifs de rejet[/]")
        for code, count in result.rejections_summary.items():
            console.print(f"  · {code}: {count}")

    console.print(f"\n[dim]{result.disclaimer}[/]")
    if settings.mode is RunMode.DEMO:
        console.print("[bold yellow]MODE DÉMO[/] — toutes les cotes affichées sont synthétiques.")


@app.command()
def version() -> None:
    """Affiche la version."""
    console.print(f"betmaxxing {__version__}")


@app.command()
def scan(
    mode: Annotated[
        str | None, typer.Option(help="demo | backtest | paper | live_analysis")
    ] = None,
    manual_odds: Annotated[
        Path | None, typer.Option(help="Fichier CSV de cotes importées manuellement.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Sortie JSON brute.")] = False,
    save: Annotated[bool, typer.Option(help="Enregistre le scan en base.")] = False,
) -> None:
    """Lance un scan et retourne des candidats, `NO_BET` ou `DATA_UNAVAILABLE`."""
    settings = get_settings()
    if mode:
        settings = settings.model_copy(update={"mode": RunMode(mode)})

    result = run_scan(settings, manual_odds_path=str(manual_odds) if manual_odds else None)

    if save:
        create_all(settings)
        with session_scope(settings) as session:
            ScanRepository(session).save(result)
        console.print(f"[dim]Scan {result.scan_id} enregistré.[/]")

    if as_json:
        console.print_json(result.model_dump_json(indent=2))
    else:
        _render(result, settings)

    if result.status is ScanStatus.DATA_UNAVAILABLE:
        raise typer.Exit(code=2)


@app.command()
def explain(
    candidate_index: Annotated[
        int, typer.Argument(help="Index du candidat (1 = meilleur EV).")
    ] = 1,
    mode: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Affiche l'explication détaillée d'un candidat du dernier scan."""
    settings = get_settings()
    if mode:
        settings = settings.model_copy(update={"mode": RunMode(mode)})
    result = run_scan(settings)
    if not result.candidates:
        console.print("[yellow]Aucun candidat qualifié à expliquer.[/]")
        raise typer.Exit(code=1)
    if not (1 <= candidate_index <= len(result.candidates)):
        console.print(f"[red]Index hors limites (1..{len(result.candidates)}).[/]")
        raise typer.Exit(code=1)
    console.print(result.candidates[candidate_index - 1].explanation)


@app.command()
def config() -> None:
    """Affiche la configuration effective, secrets masqués."""
    settings = get_settings()
    console.print_json(json.dumps(settings.redacted(), indent=2, default=str))
    console.print(f"\nEmpreinte de configuration : [bold]{settings.fingerprint()}[/]")
    console.print(f"[dim]{DISCLAIMER}[/]")


@app.command()
def providers() -> None:
    """État des fournisseurs pour le mode courant."""
    from betmaxxing.providers.base import ProviderUnavailable
    from betmaxxing.providers.factory import build_providers

    settings = get_settings()
    try:
        bundle = build_providers(settings, utc_now())
    except ProviderUnavailable as exc:
        console.print(f"[red]Indisponible[/] : {exc}")
        raise typer.Exit(code=2) from exc

    table = Table(title=f"Fournisseurs — mode {settings.mode}")
    table.add_column("Nom")
    table.add_column("Type")
    table.add_column("État")
    table.add_column("Détail", overflow="fold")
    for provider in (bundle.odds, bundle.context, bundle.results):
        status = provider.health()  # type: ignore[attr-defined]
        table.add_row(status.name, status.kind, str(status.health), status.detail)
    console.print(table)

    console.print("\n[bold]Modèles[/]")
    for entry in bundle.models.describe():
        console.print(
            f"  · {entry['sport']}: {entry['model_id']} [yellow]{entry['validation_status']}[/]"
        )
    if not bundle.models.describe():
        console.print("  [yellow]Aucun modèle enregistré pour ce mode.[/]")
    for warning in bundle.warnings:
        console.print(f"[yellow]![/] {warning}")


@odds_app.command("import")
def odds_import(
    path: Annotated[Path, typer.Argument(help="Fichier CSV de cotes.")],
    save: Annotated[bool, typer.Option(help="Enregistre les snapshots en base.")] = True,
) -> None:
    """Importe des cotes manuellement relevées et horodatées."""
    settings = get_settings()
    try:
        report = load_csv(path)
    except ManualImportError as exc:
        console.print(f"[red]Import échoué[/] : {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"{len(report.events)} événement(s), {len(report.snapshots)} cote(s) lues, "
        f"{len(report.quarantined)} ligne(s) en quarantaine."
    )
    for row, reason in report.quarantined:
        console.print(f"  [yellow]ligne {row}[/] : {reason}")

    if save and report.snapshots:
        create_all(settings)
        with session_scope(settings) as session:
            for event in report.events:
                EventRepository(session).upsert(event)
            written = OddsRepository(session).store(report.snapshots)
        console.print(
            f"[green]{written} nouveau(x) snapshot(s) écrit(s)[/] "
            f"({len(report.snapshots) - written} déjà présent(s) — ingestion idempotente)."
        )


@db_app.command("init")
def db_init() -> None:
    """Crée le schéma (usage local ; en production, utilisez Alembic)."""
    settings = get_settings()
    create_all(settings)
    console.print(f"[green]Schéma créé[/] sur {settings.database_url.split('://')[0]}://…")


@db_app.command("scans")
def db_scans(limit: Annotated[int, typer.Option()] = 10) -> None:
    """Liste les derniers scans enregistrés."""
    settings = get_settings()
    create_all(settings)
    with session_scope(settings) as session:
        rows = ScanRepository(session).latest(limit)
    if not rows:
        console.print("[yellow]Aucun scan enregistré.[/]")
        return
    table = Table(title="Scans enregistrés")
    table.add_column("Scan")
    table.add_column("Généré")
    table.add_column("Mode")
    table.add_column("Statut")
    table.add_column("Cand.", justify="right")
    table.add_column("Rejets", justify="right")
    table.add_column("Config")
    for row in rows:
        table.add_row(
            row.scan_id,
            format_display(row.generated_at),
            row.mode,
            row.status,
            str(row.candidate_count),
            str(row.rejection_count),
            row.config_fingerprint,
        )
    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    app()
