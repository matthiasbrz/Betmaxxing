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
from betmaxxing.domain.models import (
    Candidate,
    ScanResult,
    UncertaintyEstimate,
    ValueAssessment,
)
from betmaxxing.domain.timeutil import format_display, utc_now
from betmaxxing.engine.acquisition import AcquisitionService
from betmaxxing.ingestion.identity import EventIdentityService
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
identity_app = typer.Typer(help="Identité des événements : revues d'ambiguïté et alias.")
reviews_app = typer.Typer(help="File des rapprochements que la machine a refusé de trancher.")
aliases_app = typer.Typer(help="Orthographes alternatives des participants, par source.")
budget_app = typer.Typer(help="Consommation de crédits fournisseur.")
identity_app.add_typer(reviews_app, name="reviews")
identity_app.add_typer(aliases_app, name="aliases")
app.add_typer(odds_app, name="odds")
app.add_typer(db_app, name="db")
app.add_typer(identity_app, name="identity")
app.add_typer(budget_app, name="budget")

console = Console()


def _probability_line(
    value: ValueAssessment, uncertainty: UncertaintyEstimate, half_width: float | None
) -> str:
    """Probability plus the provenance of its interval — or its absence."""
    point = f"[bold]{value.conditional_win_probability:.1%}[/]"
    lower, upper = uncertainty.lower, uncertainty.upper
    if lower is None or upper is None or half_width is None:
        return f"p modèle    : {point} · incertitude [yellow]{uncertainty.status}[/]"
    return (
        f"p modèle    : {point} [{lower:.1%} - {upper:.1%}] "
        f"(±{half_width:.1%}) · {uncertainty.status}"
    )


def _candidate_card(candidate: Candidate) -> str:
    """Dense vertical summary — information hierarchy over table width."""
    value = candidate.value
    event = candidate.event
    uncertainty = candidate.probability.uncertainty
    half_width = uncertainty.half_width

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
            f" · ligne {candidate.selection.line_canonical}"
            if candidate.selection.line is not None
            else ""
        ),
        f"Cote        : [bold]{value.decimal_odds:.2f}[/] ({candidate.bookmaker}, "
        f"observée il y a {candidate.odds_age_seconds:.0f}s)",
        f"Implicite   : {implied}",
        _probability_line(value, uncertainty, half_width),
        f"Fair odds   : {value.fair_odds:.2f} · règlement {value.settlement_rule}",
        f"EV          : [green]{value.ev * 100:+.2f}%[/] · prudente "
        + (
            f"[bold]{value.ev_conservative * 100:+.2f}%[/]"
            if value.ev_conservative is not None
            else "[yellow]indisponible[/]"
        ),
        f"Cote min.   : {value.min_acceptable_odds:.2f} "
        f"[dim](sensibilité {value.ev_sensitivity_per_odds_tick * 100:+.2f}%/0,01)[/]",
        f"Qualité     : {candidate.data_quality.score:.2f} · "
        f"confiance {candidate.confidence['label']} ({candidate.confidence['score']:.2f})",
        f"Modèle      : {candidate.model_id} v{candidate.model_version} "
        f"[yellow]{candidate.probability.validation_status}[/]",
    ]
    if uncertainty.warning:
        lines.append(f"[bold yellow]!! {uncertainty.warning}[/]")
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
    console.print(f"Collecte   : {result.collection_status}")
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
    console.print(
        f"Persistées : {result.data_health.events_persisted} événement(s) · "
        f"{result.data_health.snapshots_persisted} snapshot(s)"
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
    save: Annotated[
        bool,
        typer.Option(
            help=(
                "Persiste événements, snapshots et scan. Activé par défaut : les "
                "snapshots ne se retéléchargent pas. --no-save pour un essai à blanc."
            )
        ),
    ] = True,
) -> None:
    """Lance un scan et retourne des candidats, `NO_BET` ou `DATA_UNAVAILABLE`."""
    settings = get_settings()
    if mode:
        settings = settings.model_copy(update={"mode": RunMode(mode)})

    # One acquisition path for CLI, API and scheduler: collect, persist the
    # source data, analyse, persist the scan.
    outcome = AcquisitionService(settings).run(
        manual_odds_path=str(manual_odds) if manual_odds else None,
        persist=save,
    )
    result = outcome.scan

    if save:
        console.print(
            f"[dim]Scan {result.scan_id} enregistré · "
            f"{outcome.events_persisted} événement(s), "
            f"{outcome.snapshots_persisted} snapshot(s) écrit(s).[/]"
        )

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
    result = AcquisitionService(settings).run().scan
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


# ---------------------------------------------------------------------------
# Identity: reviews and aliases
# ---------------------------------------------------------------------------
# Both mechanisms shipped in the previous tranche with no way to operate them.
# A review queue nobody can read, and an alias table nothing can populate, are
# not controls — they are places where a control could go. These commands are
# deliberately CLI-only: the web interface is a later tranche, and an operator
# should not have to write SQL in the meantime.


def _candidates(review: dict[str, object]) -> list[str]:
    value = review.get("candidate_internal_ids")
    return [str(item) for item in value] if isinstance(value, list) else []


def _identity_service() -> EventIdentityService:
    settings = get_settings()
    create_all(settings)
    return EventIdentityService(settings)


@reviews_app.command("list")
def identity_reviews_list(
    as_json: Annotated[bool, typer.Option("--json", help="Sortie JSON brute.")] = False,
) -> None:
    """Ambiguïtés en attente d'une décision humaine."""
    pending = _identity_service().pending_review()
    if as_json:
        console.print_json(json.dumps(pending, ensure_ascii=False))
        return
    if not pending:
        console.print("[green]Aucune ambiguïté en attente.[/green]")
        return

    table = Table(title="Rapprochements à trancher", show_lines=False)
    table.add_column("ID", justify="right")
    table.add_column("Fournisseur")
    table.add_column("Id source")
    table.add_column("Rencontre")
    table.add_column("Coup d'envoi")
    table.add_column("Candidats", justify="right")
    for review in pending:
        table.add_row(
            str(review["id"]),
            str(review["provider"]),
            str(review["provider_event_id"]),
            str(review["label"]),
            str(review["start_time_utc"]),
            str(len(_candidates(review))),
        )
    console.print(table)
    console.print(
        "[yellow]Aucune de ces cotes n'est rattachée.[/yellow] Tranchez avec "
        "`betmaxxing identity reviews resolve <id> --event-id <internal_id> "
        "--operator <vous>`."
    )


@reviews_app.command("show")
def identity_reviews_show(review_id: int) -> None:
    """Détail d'une revue, avec les événements qui correspondaient."""
    from betmaxxing.ingestion.identity import ReviewNotFound

    try:
        review = _identity_service().review(review_id)
    except ReviewNotFound as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(
        Panel(
            f"[bold]{review['label']}[/bold]\n"
            f"Fournisseur   : {review['provider']} / {review['provider_event_id']}\n"
            f"Sport         : {review['sport']}\n"
            f"Compétition   : {review['competition']}\n"
            f"Coup d'envoi  : {review['start_time_utc']}\n"
            f"Statut        : {'tranchée' if review['resolved'] else 'en attente'}",
            title=f"Revue d'identité {review_id}",
        )
    )
    table = Table(title="Événements existants qui correspondaient")
    table.add_column("internal_id")
    for candidate in _candidates(review):
        table.add_row(str(candidate))
    console.print(table)
    console.print(str(review["detail"]))
    if review["resolved"]:
        console.print(
            f"Tranchée par [bold]{review['resolved_by']}[/bold] le {review['resolved_at']} "
            f"→ {review['resolved_internal_id']}"
        )


@reviews_app.command("resolve")
def identity_reviews_resolve(
    review_id: int,
    event_id: Annotated[
        str,
        typer.Option(
            "--event-id",
            help="internal_id de l'événement choisi. Doit figurer parmi les candidats.",
        ),
    ],
    operator: Annotated[
        str, typer.Option("--operator", help="Qui prend la décision (conservé).")
    ] = "",
) -> None:
    """Rattacher une ambiguïté à l'événement que **vous** désignez.

    Il n'existe volontairement aucune résolution automatique : la file existe
    précisément parce que la machine n'a pas pu trancher.
    """
    from betmaxxing.ingestion.identity import (
        ReviewAlreadyResolved,
        ReviewNotFound,
        ReviewResolutionRejected,
    )

    if not operator.strip():
        console.print("[red]--operator est requis : une décision a un auteur.[/red]")
        raise typer.Exit(code=2)

    try:
        _identity_service().resolve_review(
            review_id, internal_id=event_id, operator=operator.strip()
        )
    except ReviewNotFound as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except ReviewAlreadyResolved as exc:
        console.print(f"[red]Revue déjà tranchée : {exc}[/red]")
        raise typer.Exit(code=1) from exc
    except ReviewResolutionRejected as exc:
        console.print(f"[red]Refusé : {exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]Revue {review_id} tranchée[/green] : les prochaines cotes de cette "
        f"source iront sur {event_id}."
    )
    console.print(
        "Les snapshots déjà enregistrés ne sont pas réattribués — une décision "
        "d'aujourd'hui ne réécrit pas ce qu'un scan passé a observé."
    )


@aliases_app.command("import")
def identity_aliases_import(
    path: Annotated[Path, typer.Argument(help="CSV : sport,alias,canonical_participant_id,source")],
    as_json: Annotated[bool, typer.Option("--json", help="Sortie JSON brute.")] = False,
) -> None:
    """Charger des alias de participants. Idempotent, lignes fautives en quarantaine."""
    import csv

    from betmaxxing.ingestion.identity import AliasRow

    if not path.exists():
        console.print(f"[red]Fichier introuvable : {path}[/red]")
        raise typer.Exit(code=2)

    rows: list[AliasRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"sport", "alias", "canonical_participant_id", "source"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            console.print(f"[red]Colonnes manquantes : {', '.join(sorted(missing))}[/red]")
            raise typer.Exit(code=2)
        # Line numbers count the header, so the operator can open the file and
        # find the offending row directly.
        for number, record in enumerate(reader, start=2):
            rows.append(
                AliasRow(
                    line=number,
                    sport=(record.get("sport") or "").strip(),
                    alias=(record.get("alias") or "").strip(),
                    canonical_participant_id=(record.get("canonical_participant_id") or "").strip(),
                    source=(record.get("source") or "").strip(),
                )
            )

    report = _identity_service().import_aliases(rows)
    if as_json:
        console.print_json(json.dumps(report.as_dict(), ensure_ascii=False))
        return

    console.print(
        f"Importés : [green]{report.imported}[/green] · "
        f"inchangés : {report.unchanged} · "
        f"en quarantaine : [yellow]{len(report.quarantined)}[/yellow]"
    )
    if report.quarantined:
        table = Table(title="Lignes en quarantaine (aucune n'a été importée)")
        table.add_column("Ligne", justify="right")
        table.add_column("Raison")
        for item in report.quarantined:
            table.add_row(str(item["line"]), str(item["reason"]))
        console.print(table)


@aliases_app.command("list")
def identity_aliases_list(
    sport: Annotated[str, typer.Option("--sport", help="Filtrer par sport.")] = "",
    source: Annotated[str, typer.Option("--source", help="Filtrer par source.")] = "",
    as_json: Annotated[bool, typer.Option("--json", help="Sortie JSON brute.")] = False,
) -> None:
    """Alias déclarés, consultés par le rapprochement inter-fournisseurs."""
    rows = _identity_service().aliases(sport=sport or None, source=source or None)
    if as_json:
        console.print_json(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        console.print("Aucun alias déclaré.")
        return
    table = Table(title="Alias de participants")
    table.add_column("Sport")
    table.add_column("Alias")
    table.add_column("Participant canonique")
    table.add_column("Source")
    for row in rows:
        table.add_row(row["sport"], row["alias"], row["canonical_participant_id"], row["source"])
    console.print(table)


@budget_app.command("audit")
def budget_audit(
    provider: Annotated[str, typer.Option("--provider", help="Fournisseur à auditer.")] = (
        "the_odds_api"
    ),
) -> None:
    """Vérifier que le compteur journalier correspond au détail qu'il résume."""
    from betmaxxing.providers.budget import ProviderBudgetLedger

    settings = get_settings()
    create_all(settings)
    ledger = ProviderBudgetLedger(settings)
    invariant = ledger.verify_invariant(provider, utc_now())
    console.print(invariant.describe())
    entries = ledger.entries_for_day(utc_now(), provider)
    if entries:
        table = Table(title=f"Tentatives du jour — {provider}")
        table.add_column("Requête")
        table.add_column("Réservé", justify="right")
        table.add_column("Constaté", justify="right")
        table.add_column("Libéré")
        for entry in entries:
            table.add_row(
                entry.request,
                str(entry.reserved_cost),
                "—" if entry.observed_cost is None else str(entry.observed_cost),
                "oui" if entry.released else "non",
            )
        console.print(table)
    if not invariant:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
