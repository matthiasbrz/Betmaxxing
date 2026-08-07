"""Controlled activation of The Odds API — four commands, four hard ceilings.

Why this module exists
----------------------
The previous smoke script asked for one boolean of consent and then called
``provider.collect([FOOTBALL, TENNIS], window)``. That is a fan-out: one grouped
request per configured sport key, then one per-event request for every football
event found, bounded only by the per-scan budget. A boolean is not a spending
limit. With a real key nobody could have said, in advance, what that script
would cost.

Here the sequence is split into four commands, each with a ceiling that is
checked before any socket is opened, and each authorised separately:

===========  ========  =========  ==========================================
command      network   credits    endpoints
===========  ========  =========  ==========================================
plan         no        0          none — it does not even build a client
discover     yes       0          ``/v4/sports``, ``/v4/sports/{sport}/events``
core         yes       1          ``/v4/sports/{sport}/odds?eventIds=…``
additional   yes       5          ``/v4/sports/{sport}/events/{id}/odds``
===========  ========  =========  ==========================================

Both ``discover`` endpoints are documented free: *"This endpoint does not count
against the usage quota."* If the provider ever charges for one, that is a
contract change and the command fails with ``COST_MISMATCH`` rather than
absorbing it quietly.

Rules the implementation enforces rather than documents
-------------------------------------------------------
* **The key comes from the environment only.** There is no ``--api-key`` option,
  by construction: an argument lands in shell history, in ``ps``, and in CI logs.
* **No retries.** ``max_retries=0`` everywhere. A retry is a second billable
  request; a step whose ceiling is one credit must make at most one attempt.
* **No chaining.** No command calls another. Each is a separate human decision.
* **Scope is singular.** One sport key, one bookmaker, one event, a window of at
  most 24 hours. Anything plural is refused before the network.
* **Receipts are local and sanitised.** They carry no key, no unredacted URL, no
  raw payload, no odds and no participant names, and the event id is stored as a
  hash. They are written under a gitignored directory and never committed.

Status vocabulary: ``PREPARED_NOT_EXECUTED``, ``DISCOVERY_VERIFIED``,
``CORE_LIVE_VERIFIED``, ``ADDITIONAL_LIVE_VERIFIED``, ``COVERAGE_MISSING``,
``SCHEMA_MISMATCH``, ``COST_MISMATCH``, ``AUTH_FAILED``, ``PROVIDER_UNAVAILABLE``.

Nothing here promotes a model, publishes a candidate, or writes a scan. A green
run tells you what coverage exists at that instant and nothing more.
"""

from __future__ import annotations

import hashlib
import json as jsonlib
import os
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
import typer

from betmaxxing.config import Settings, get_settings
from betmaxxing.domain.enums import Sport
from betmaxxing.domain.timeutil import ensure_utc, utc_now
from betmaxxing.providers.base import CollectionBatch, ProviderError
from betmaxxing.providers.budget import ProviderBudgetLedger
from betmaxxing.providers.the_odds_api.client import (
    TheOddsApiAuthError,
    TheOddsApiClient,
    effective_region_units,
    estimate_cost,
    redact,
)
from betmaxxing.providers.the_odds_api.mapping import MappingRejected
from betmaxxing.providers.the_odds_api.provider import (
    PROVIDER_NAME,
    ResponseShape,
    TheOddsApiProvider,
    _last_update_of,
    additional_markets_for,
)

#: Where receipts land when ``BETMAXXING_ACTIVATION_RECEIPTS`` is unset. Its
#: first path segment is listed in ``.gitignore``: a receipt is an operating
#: record of a real, billed call and belongs to the operator, not to the repo.
DEFAULT_RECEIPT_DIR = ".activation-receipts"
RECEIPT_DIR_VARIABLE = "BETMAXXING_ACTIVATION_RECEIPTS"

#: Injected by the test suite. Production leaves it ``None`` so httpx builds its
#: own transport; there is no other way to reach this module's network calls.
_TRANSPORT_FOR_TESTS: httpx.BaseTransport | None = None

#: Patched by tests that need a deterministic instant.
_clock = utc_now

#: Hard per-step ceilings. These are the contract, not a default.
STEP_CEILINGS: dict[str, int] = {"plan": 0, "discover": 0, "core": 1, "additional": 5}
TOTAL_MAX_CREDITS = sum(STEP_CEILINGS.values())

#: One market, deliberately. ``core_markets_for(FOOTBALL)`` is ``("h2h",
#: "totals")`` — two markets, therefore two credits. The activation asks for the
#: single market that proves the endpoint, the auth and the parser, and stops.
CORE_MARKETS: tuple[str, ...] = ("h2h",)

#: The five per-event markets, taken from the provider's own policy so the two
#: cannot drift apart.
ADDITIONAL_MARKETS: tuple[str, ...] = additional_markets_for(Sport.FOOTBALL)

MAX_WINDOW_HOURS = 24

RECEIPT_SCHEMA = 1


class ActivationStatus(StrEnum):
    """Every outcome the harness can report. There is no other vocabulary."""

    PREPARED_NOT_EXECUTED = "PREPARED_NOT_EXECUTED"
    DISCOVERY_VERIFIED = "DISCOVERY_VERIFIED"
    CORE_LIVE_VERIFIED = "CORE_LIVE_VERIFIED"
    ADDITIONAL_LIVE_VERIFIED = "ADDITIONAL_LIVE_VERIFIED"
    COVERAGE_MISSING = "COVERAGE_MISSING"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    COST_MISMATCH = "COST_MISMATCH"
    AUTH_FAILED = "AUTH_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class Refused(Exception):
    """A step stopped. Carries the status and a message safe to print."""

    def __init__(self, status: ActivationStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Activation contrôlée de The Odds API. Quatre étapes indépendantes, "
        "chacune plafonnée et autorisée séparément : plan (0), discover (0), "
        "core (1 crédit), additional (5 crédits)."
    ),
)


# ---------------------------------------------------------------------------
# Secrets, hashing, receipts
# ---------------------------------------------------------------------------
def _scrub(text: str, secret: str) -> str:
    """Remove the key from a message, however it got in there.

    :func:`redact` strips ``apiKey=…`` from URLs, which covers everything the
    client itself builds. It does not cover a third party: an ``httpx``
    transport error can quote the whole request line, and a proxy can echo the
    query string back inside a body. So the literal value is removed too, and
    that is the last thing done before anything is printed or written.
    """
    cleaned = redact(text)
    if secret:
        cleaned = cleaned.replace(secret, "***REDACTED***")
    return cleaned


def hash_event_id(event_id: str) -> str:
    """Stable, unsalted digest of a provider event id.

    Unsalted on purpose: ``additional`` has to recognise the receipt ``core``
    wrote for the same event, across processes and days, and a per-run salt
    would make that impossible. A provider fixture id is not personal data; the
    hash is here so a receipt cannot be used to reconstruct which matches were
    looked at, not to protect a secret.
    """
    return hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]


def receipt_dir() -> Path:
    return Path(os.environ.get(RECEIPT_DIR_VARIABLE, "").strip() or DEFAULT_RECEIPT_DIR)


def write_receipt(payload: dict[str, Any], *, secret: str) -> Path:
    """Persist one sanitised receipt locally. Never committed, never uploaded."""
    directory = receipt_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = payload["recorded_at"].replace(":", "").replace("-", "")
    path = directory / f"{stamp}-{payload['command']}-{payload['event_id_hash'][:8]}.json"
    text = jsonlib.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(_scrub(text, secret) + "\n", encoding="utf-8")
    return path


def read_receipts() -> list[dict[str, Any]]:
    directory = receipt_dir()
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            loaded = jsonlib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(loaded, dict):
            out.append(loaded)
    return out


# ---------------------------------------------------------------------------
# Scope validation — everything checkable before a socket exists
# ---------------------------------------------------------------------------
def _single(raw: str, label: str) -> str:
    """Exactly one comma-free token, or refuse.

    A list here is a fan-out, and a fan-out is precisely what the previous
    script did wrong. Multiplying the scope multiplies the bill.
    """
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if len(tokens) != 1:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{label} doit désigner exactement une valeur, reçu {tokens!r}. "
            "L'activation n'interroge jamais plusieurs cibles à la fois.",
        )
    return tokens[0]


def _check_window(window_hours: int) -> int:
    if window_hours < 1 or window_hours > MAX_WINDOW_HOURS:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"--window-hours doit être compris entre 1 et {MAX_WINDOW_HOURS}, reçu {window_hours}.",
        )
    return window_hours


def _check_ceiling(command: str, max_credits: int, acknowledge: int | None) -> int:
    """The ceiling is fixed by the contract; the operator restates it twice.

    ``--max-credits`` must equal the published ceiling for that command, and
    ``--acknowledge-credits`` must equal it again. Two identical numbers typed by
    hand is a weak proof of intent, but it is a far stronger one than a boolean:
    it cannot be satisfied without knowing what the step costs.
    """
    expected = STEP_CEILINGS[command]
    if max_credits != expected:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"`{command}` est plafonné à {expected} crédit(s) ; --max-credits={max_credits} "
            "est refusé. Le plafond n'est pas négociable depuis la ligne de commande.",
        )
    if acknowledge is None or acknowledge != expected:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"--acknowledge-credits={expected} est requis pour `{command}` : "
            "vous confirmez explicitement la dépense avant qu'elle ait lieu.",
        )
    return expected


def _require_network(allow_network: bool) -> None:
    if not allow_network:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "--allow-network est requis. Sans ce drapeau, aucune socket n'est ouverte.",
        )


def _require_key(settings: Settings) -> str:
    key = settings.resolved_the_odds_api_key
    if not key:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Aucune clé configurée. Définissez BETMAXXING_THE_ODDS_API_KEY dans "
            "l'environnement — jamais en argument, jamais dans un fichier versionné.",
        )
    return key


def _client(
    settings: Settings, key: str, *, ledger: ProviderBudgetLedger | None
) -> TheOddsApiClient:
    """One client, zero retries.

    ``max_retries=0`` is the whole point: a retry is another billable request,
    and a step whose ceiling is one credit may make exactly one attempt.
    """
    return TheOddsApiClient(
        api_key=key,
        base_url=settings.the_odds_api_base_url,
        timeout=settings.provider_timeout_seconds,
        max_retries=0,
        budget_per_scan=max(1, TOTAL_MAX_CREDITS),
        transport=_TRANSPORT_FOR_TESTS,
        budget_ledger=ledger,
        provider_name=PROVIDER_NAME,
        now=_clock(),
    )


def _check_observed_cost(observed: int | None, ceiling: int, endpoint: str) -> int:
    """What the provider says it charged, against what we authorised.

    ``x-requests-last`` is authoritative. A figure above the ceiling means the
    billing contract is not what this harness was built against, and the right
    response is to stop and say so — not to keep going and find out how much the
    next step costs.
    """
    if observed is None:
        return 0
    if observed > ceiling:
        raise Refused(
            ActivationStatus.COST_MISMATCH,
            f"{endpoint} : le fournisseur annonce {observed} crédit(s) facturé(s) pour "
            f"un plafond de {ceiling}. Arrêt immédiat — le contrat de facturation a changé.",
        )
    return observed


# ---------------------------------------------------------------------------
# Payload inspection — no fabrication, no fallback
# ---------------------------------------------------------------------------
def _event_of(payload: Any, event_id: str, endpoint: str) -> dict[str, Any]:
    """Locate the one event we asked for, or say precisely what came back."""
    events = payload if isinstance(payload, list) else [payload]
    usable = [
        item
        for item in events
        if isinstance(item, dict) and {"id", "commence_time", "home_team"} <= set(item)
    ]
    if not events or all(item in ({}, None) for item in events):
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            f"{endpoint} : réponse vide. Ce n'est pas une panne — aucun événement "
            "correspondant n'était disponible à cet instant.",
        )
    if not usable:
        raise Refused(
            ActivationStatus.SCHEMA_MISMATCH,
            f"{endpoint} : la réponse ne contient aucun événement exploitable "
            "(champs id / commence_time / home_team absents).",
        )
    for item in usable:
        if str(item.get("id")) == event_id:
            return item
    raise Refused(
        ActivationStatus.COVERAGE_MISSING,
        f"{endpoint} : l'événement demandé n'est pas dans la réponse.",
    )


def _book_of(raw_event: dict[str, Any], bookmaker: str, endpoint: str) -> dict[str, Any]:
    for book in raw_event.get("bookmakers") or []:
        if isinstance(book, dict) and str(book.get("key", "")) == bookmaker:
            return book
    raise Refused(
        ActivationStatus.COVERAGE_MISSING,
        f"{endpoint} : {bookmaker} n'est pas coté sur cet événement. Une réponse "
        "valide sans le bookmaker demandé est une couverture manquante, pas une panne.",
    )


def _freshness(book: dict[str, Any], shape: ResponseShape, now: datetime) -> dict[str, int]:
    """Age in seconds of each quoted market, from the stamp v4 actually sends.

    Seconds rather than the raw instant: the age is the decision-relevant figure
    and it keeps a provider timestamp out of the receipt. A market whose stamp is
    missing or unusable is simply absent — no age is invented for it.
    """
    ages: dict[str, int] = {}
    for market in book.get("markets") or []:
        if not isinstance(market, dict):
            continue
        key = str(market.get("key", ""))
        holder = book if shape is ResponseShape.GROUPED_ODDS else market
        try:
            stamp = _last_update_of(holder, key)
        except MappingRejected:
            continue
        ages[key] = int((now - ensure_utc(stamp)).total_seconds())
    return ages


def _market_keys(book: dict[str, Any]) -> list[str]:
    return [
        str(market["key"])
        for market in book.get("markets") or []
        if isinstance(market, dict) and market.get("key")
    ]


def _parse_with_the_real_parser(
    settings: Settings,
    client: TheOddsApiClient,
    raw_event: dict[str, Any],
    *,
    window: tuple[datetime, datetime],
    now: datetime,
    shape: ResponseShape,
) -> CollectionBatch:
    """Run the response through the adapter's own parser.

    The point of a live step is not to see JSON arrive; it is to find out whether
    the code that will read it in production actually does. So the real
    ``_ingest_event`` is used, under the shape the endpoint declares.
    """
    provider = TheOddsApiProvider(settings, client=client, now=now)
    batch = CollectionBatch(
        provider=PROVIDER_NAME, collected_at=now, bookmakers=list(settings.bookmaker_list)
    )
    provider._ingest_event(raw_event, Sport.FOOTBALL, window, now, batch, shape=shape)
    return batch


def _check_start_time(raw_event: dict[str, Any], window: tuple[datetime, datetime]) -> None:
    raw = str(raw_event.get("commence_time", ""))
    try:
        start = ensure_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError as exc:
        raise Refused(
            ActivationStatus.SCHEMA_MISMATCH,
            f"commence_time illisible ({raw!r}) — aucune date n'est supposée.",
        ) from exc
    if not (window[0] < start <= window[1]):
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            "L'événement demandé démarre hors de la fenêtre déclarée. L'activation "
            "n'élargit jamais sa portée pour trouver quelque chose à mesurer.",
        )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def _emit(payload: dict[str, Any], lines: list[str], *, as_json: bool, secret: str = "") -> None:
    if as_json:
        typer.echo(_scrub(jsonlib.dumps(payload, indent=2, sort_keys=True), secret))
        return
    for line in lines:
        typer.echo(_scrub(line, secret))


def _fail(status: ActivationStatus, message: str, *, as_json: bool, secret: str = "") -> None:
    if as_json:
        typer.echo(_scrub(jsonlib.dumps({"status": str(status), "detail": message}), secret))
    else:
        typer.echo(_scrub(f"{status} : {message}", secret))
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------
def build_plan(
    *, sport: str, bookmaker: str, window_hours: int, generated_at: str
) -> dict[str, Any]:
    """The whole sequence, priced, with no key read and no client built."""
    units = effective_region_units(bookmakers=[bookmaker], regions=None)
    steps = [
        {
            "command": "plan",
            "network": False,
            "max_credits": STEP_CEILINGS["plan"],
            "endpoints": [],
            "markets": [],
            "note": "Aucune socket, aucune clé lue, aucun reçu écrit.",
        },
        {
            "command": "discover",
            "network": True,
            "max_credits": STEP_CEILINGS["discover"],
            "endpoints": ["/v4/sports", f"/v4/sports/{sport}/events"],
            "markets": [],
            "note": "Endpoints documentés gratuits ; un coût annoncé non nul arrête l'étape.",
        },
        {
            "command": "core",
            "network": True,
            "max_credits": STEP_CEILINGS["core"],
            "endpoints": [f"/v4/sports/{sport}/odds"],
            "markets": list(CORE_MARKETS),
            "note": (
                f"{len(CORE_MARKETS)} marché x {units} unité(s) régionale(s) = "
                f"{estimate_cost(markets=len(CORE_MARKETS), region_units=units)} crédit(s)."
            ),
        },
        {
            "command": "additional",
            "network": True,
            "max_credits": STEP_CEILINGS["additional"],
            "endpoints": [f"/v4/sports/{sport}/events/<event>/odds"],
            "markets": list(ADDITIONAL_MARKETS),
            "note": (
                f"{len(ADDITIONAL_MARKETS)} marchés x {units} unité(s) régionale(s) = "
                f"{estimate_cost(markets=len(ADDITIONAL_MARKETS), region_units=units)} crédit(s)."
            ),
        },
    ]
    return {
        "status": str(ActivationStatus.PREPARED_NOT_EXECUTED),
        "generated_at": generated_at,
        "sport_key": sport,
        "bookmaker": bookmaker,
        "window_hours": window_hours,
        "effective_region_units": units,
        "total_max_credits": TOTAL_MAX_CREDITS,
        "steps": steps,
        "guarantees": [
            "Aucun endpoint historique ou payant n'est joignable depuis cet outil.",
            "Aucune tentative n'est répétée : max_retries=0 sur chaque étape.",
            "Aucune étape n'en déclenche une autre.",
            "La clé provient de l'environnement et n'est jamais acceptée en argument.",
        ],
    }


@app.command()
def plan(
    sport: str = typer.Option(..., "--sport", help="Une seule clé de compétition v4."),
    bookmaker: str = typer.Option(..., "--bookmaker", help="Un seul bookmaker."),
    max_credits: int = typer.Option(
        ..., "--max-credits", help="Plafond total de la séquence, à restituer exactement."
    ),
    window_hours: int = typer.Option(24, "--window-hours", help="Fenêtre, 24 h au maximum."),
    json_output: bool = typer.Option(False, "--json", help="Sortie JSON."),
) -> None:
    """Chiffrer la séquence hors ligne. Aucune socket, aucune clé lue, 0 crédit."""
    try:
        one_sport = _single(sport, "--sport")
        one_book = _single(bookmaker, "--bookmaker")
        hours = _check_window(window_hours)
        if max_credits != TOTAL_MAX_CREDITS:
            raise Refused(
                ActivationStatus.PREPARED_NOT_EXECUTED,
                f"La séquence complète est plafonnée à {TOTAL_MAX_CREDITS} crédits "
                f"({STEP_CEILINGS}) ; --max-credits={max_credits} est refusé.",
            )
    except Refused as exc:
        _fail(exc.status, exc.message, as_json=json_output)
        return

    document = build_plan(
        sport=one_sport,
        bookmaker=one_book,
        window_hours=hours,
        generated_at=_clock().isoformat(),
    )
    lines = [
        f"Statut          : {document['status']}",
        f"Compétition     : {one_sport}",
        f"Bookmaker       : {one_book}",
        f"Fenêtre         : {hours} h",
        f"Unités région   : {document['effective_region_units']}",
        f"Plafond total   : {TOTAL_MAX_CREDITS} crédits",
        "",
    ]
    for step in document["steps"]:
        endpoints = ", ".join(step["endpoints"]) or "aucun"
        lines.append(f"  {step['command']:<11} {step['max_credits']} crédit(s)  {endpoints}")
        if step["markets"]:
            lines.append(f"              marchés : {', '.join(step['markets'])}")
    lines += ["", "Rien n'a été exécuté. Chaque étape suivante s'autorise séparément."]
    _emit(document, lines, as_json=json_output)


# ---------------------------------------------------------------------------
# discover — free endpoints only
# ---------------------------------------------------------------------------
@app.command()
def discover(
    sport: str = typer.Option(..., "--sport"),
    bookmaker: str = typer.Option(..., "--bookmaker"),
    window_hours: int = typer.Option(24, "--window-hours"),
    allow_network: bool = typer.Option(False, "--allow-network"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Lister les événements sur les deux endpoints gratuits. 0 crédit."""
    secret = ""
    try:
        one_sport = _single(sport, "--sport")
        one_book = _single(bookmaker, "--bookmaker")
        hours = _check_window(window_hours)
        _require_network(allow_network)
        settings = get_settings()
        secret = _require_key(settings)
        document = _discovery(settings, secret, one_sport, one_book, hours)
    except Refused as exc:
        _fail(exc.status, exc.message, as_json=json_output, secret=secret)
        return
    except ProviderError as exc:
        status = (
            ActivationStatus.AUTH_FAILED
            if isinstance(exc, TheOddsApiAuthError)
            else ActivationStatus.PROVIDER_UNAVAILABLE
        )
        _fail(status, str(exc), as_json=json_output, secret=secret)
        return

    lines = [
        f"Statut          : {document['status']}",
        f"Compétition     : {one_sport}",
        f"Crédits         : {document['observed_credits']} (plafond 0)",
        f"Événements      : {len(document['events'])}",
        "",
    ]
    for event in document["events"]:
        lines.append(
            f"  {event['id']}  {event['commence_time']}  "
            f"{event['home_team']} - {event['away_team']}"
        )
    lines += [
        "",
        "Choisissez UN identifiant et relancez `core --event-id <id>` : "
        "aucune sélection n'est faite pour vous.",
    ]
    _emit(document, lines, as_json=json_output, secret=secret)


def _discovery(
    settings: Settings, secret: str, sport: str, bookmaker: str, window_hours: int
) -> dict[str, Any]:
    now = _clock()
    window = (now, now + timedelta(hours=window_hours))
    client = _client(settings, secret, ledger=None)

    catalogue = client.get("sports", params={"all": "false"}, cost=0, billable=False)
    spent = _check_observed_cost(catalogue.quota.last_cost, 0, "/v4/sports")
    entries = catalogue.payload if isinstance(catalogue.payload, list) else []
    descriptor = next(
        (e for e in entries if isinstance(e, dict) and str(e.get("key")) == sport), None
    )
    if descriptor is None or not descriptor.get("active", True):
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            f"{sport} n'est pas retournée active par /v4/sports. L'étape s'arrête ici : "
            "interroger une compétition hors saison coûterait un crédit pour rien.",
        )

    listing = client.get(
        f"sports/{sport}/events",
        params={
            "dateFormat": "iso",
            "commenceTimeFrom": _iso_z(window[0]),
            "commenceTimeTo": _iso_z(window[1]),
        },
        cost=0,
        billable=False,
    )
    spent += _check_observed_cost(listing.quota.last_cost, 0, f"/v4/sports/{sport}/events")

    events = [
        {
            "id": str(item["id"]),
            "commence_time": str(item.get("commence_time", "")),
            "home_team": str(item.get("home_team", "")),
            "away_team": str(item.get("away_team", "")),
        }
        for item in (listing.payload if isinstance(listing.payload, list) else [])
        if isinstance(item, dict) and item.get("id") and _inside(item, window)
    ]
    if not events:
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            f"Aucun événement à venir pour {sport} dans les {window_hours} h déclarées. "
            "La fenêtre n'est pas élargie automatiquement.",
        )

    return {
        "status": str(ActivationStatus.DISCOVERY_VERIFIED),
        "recorded_at": now.isoformat(),
        "sport_key": sport,
        "bookmaker": bookmaker,
        "window_hours": window_hours,
        "max_credits": STEP_CEILINGS["discover"],
        "observed_credits": spent,
        "events": events,
    }


def _inside(item: dict[str, Any], window: tuple[datetime, datetime]) -> bool:
    raw = str(item.get("commence_time", ""))
    try:
        start = ensure_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return False
    return window[0] < start <= window[1]


# ---------------------------------------------------------------------------
# core — one event, one bookmaker, one market, one credit
# ---------------------------------------------------------------------------
def run_core(
    settings: Settings,
    secret: str,
    *,
    sport: str,
    bookmaker: str,
    event_id: str,
    window_hours: int,
    ceiling: int,
) -> dict[str, Any]:
    """One grouped request, filtered to one event. At most one credit."""
    now = _clock()
    window = (now, now + timedelta(hours=window_hours))
    ledger = ProviderBudgetLedger(settings)
    client = _client(settings, secret, ledger=ledger)

    units = effective_region_units(bookmakers=[bookmaker], regions=None)
    cost = estimate_cost(markets=len(CORE_MARKETS), region_units=units)
    if cost > ceiling:
        raise Refused(
            ActivationStatus.COST_MISMATCH,
            f"L'estimation ({cost}) dépasse le plafond ({ceiling}) — appel non tenté.",
        )

    endpoint = f"/v4/sports/{sport}/odds"
    response = client.get(
        f"sports/{sport}/odds",
        params={
            "eventIds": event_id,
            "markets": ",".join(CORE_MARKETS),
            "bookmakers": bookmaker,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        },
        cost=cost,
    )
    observed = _check_observed_cost(response.quota.last_cost, ceiling, endpoint)

    raw_event = _event_of(response.payload, event_id, endpoint)
    _check_start_time(raw_event, window)
    book = _book_of(raw_event, bookmaker, endpoint)

    batch = _parse_with_the_real_parser(
        settings, client, raw_event, window=window, now=now, shape=ResponseShape.GROUPED_ODDS
    )
    if not batch.snapshots:
        raise Refused(
            ActivationStatus.SCHEMA_MISMATCH,
            "Le bookmaker est présent mais le parseur n'a retenu aucune sélection : "
            f"{'; '.join(batch.partial_errors) or 'aucun détail'}.",
        )

    return _receipt(
        command="core",
        status=ActivationStatus.CORE_LIVE_VERIFIED,
        now=now,
        sport=sport,
        bookmaker=bookmaker,
        event_id=event_id,
        ceiling=ceiling,
        observed=observed,
        requested=list(CORE_MARKETS),
        book=book,
        shape=ResponseShape.GROUPED_ODDS,
        batch=batch,
        endpoint=endpoint,
    )


@app.command()
def core(
    sport: str = typer.Option(..., "--sport"),
    bookmaker: str = typer.Option(..., "--bookmaker"),
    event_id: str = typer.Option(..., "--event-id"),
    max_credits: int = typer.Option(..., "--max-credits"),
    acknowledge_credits: int = typer.Option(None, "--acknowledge-credits"),
    window_hours: int = typer.Option(24, "--window-hours"),
    allow_network: bool = typer.Option(False, "--allow-network"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Un seul événement, un seul marché, un seul bookmaker. 1 crédit au plus."""
    secret = ""
    try:
        one_sport = _single(sport, "--sport")
        one_book = _single(bookmaker, "--bookmaker")
        one_event = _single(event_id, "--event-id")
        hours = _check_window(window_hours)
        ceiling = _check_ceiling("core", max_credits, acknowledge_credits)
        _require_network(allow_network)
        settings = get_settings()
        secret = _require_key(settings)
        document = run_core(
            settings,
            secret,
            sport=one_sport,
            bookmaker=one_book,
            event_id=one_event,
            window_hours=hours,
            ceiling=ceiling,
        )
    except Refused as exc:
        _fail(exc.status, exc.message, as_json=json_output, secret=secret)
        return
    except ProviderError as exc:
        status = (
            ActivationStatus.AUTH_FAILED
            if isinstance(exc, TheOddsApiAuthError)
            else ActivationStatus.PROVIDER_UNAVAILABLE
        )
        _fail(status, str(exc), as_json=json_output, secret=secret)
        return

    write_receipt(document, secret=secret)
    _emit(document, _summary(document), as_json=json_output, secret=secret)


# ---------------------------------------------------------------------------
# additional — same event, five markets, five credits
# ---------------------------------------------------------------------------
def run_additional(
    settings: Settings,
    secret: str,
    *,
    sport: str,
    bookmaker: str,
    event_id: str,
    window_hours: int,
    ceiling: int,
) -> dict[str, Any]:
    """The per-event markets, for an event a previous step already verified."""
    digest = hash_event_id(event_id)
    verified = [
        receipt
        for receipt in read_receipts()
        if receipt.get("status") == str(ActivationStatus.CORE_LIVE_VERIFIED)
        and receipt.get("event_id_hash") == digest
    ]
    if not verified:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Aucun reçu CORE_LIVE_VERIFIED pour cet événement. Cinq crédits ne sont "
            "engagés qu'après qu'un seul a démontré l'endpoint, l'auth et le parseur.",
        )

    now = _clock()
    window = (now, now + timedelta(hours=window_hours))
    ledger = ProviderBudgetLedger(settings)
    client = _client(settings, secret, ledger=ledger)

    units = effective_region_units(bookmakers=[bookmaker], regions=None)
    cost = estimate_cost(markets=len(ADDITIONAL_MARKETS), region_units=units)
    if cost > ceiling:
        raise Refused(
            ActivationStatus.COST_MISMATCH,
            f"L'estimation ({cost}) dépasse le plafond ({ceiling}) — appel non tenté.",
        )

    endpoint = f"/v4/sports/{sport}/events/<event>/odds"
    response = client.get(
        f"sports/{sport}/events/{event_id}/odds",
        params={
            "markets": ",".join(ADDITIONAL_MARKETS),
            "bookmakers": bookmaker,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        },
        cost=cost,
    )
    observed = _check_observed_cost(response.quota.last_cost, ceiling, endpoint)

    raw_event = _event_of(response.payload, event_id, endpoint)
    _check_start_time(raw_event, window)
    book = _book_of(raw_event, bookmaker, endpoint)

    batch = _parse_with_the_real_parser(
        settings, client, raw_event, window=window, now=now, shape=ResponseShape.EVENT_ODDS
    )
    return _receipt(
        command="additional",
        status=ActivationStatus.ADDITIONAL_LIVE_VERIFIED,
        now=now,
        sport=sport,
        bookmaker=bookmaker,
        event_id=event_id,
        ceiling=ceiling,
        observed=observed,
        requested=list(ADDITIONAL_MARKETS),
        book=book,
        shape=ResponseShape.EVENT_ODDS,
        batch=batch,
        endpoint=endpoint,
    )


@app.command()
def additional(
    sport: str = typer.Option(..., "--sport"),
    bookmaker: str = typer.Option(..., "--bookmaker"),
    event_id: str = typer.Option(..., "--event-id"),
    max_credits: int = typer.Option(..., "--max-credits"),
    acknowledge_credits: int = typer.Option(None, "--acknowledge-credits"),
    window_hours: int = typer.Option(24, "--window-hours"),
    allow_network: bool = typer.Option(False, "--allow-network"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Les cinq marchés par événement, sur l'événement déjà vérifié. 5 crédits au plus."""
    secret = ""
    try:
        one_sport = _single(sport, "--sport")
        one_book = _single(bookmaker, "--bookmaker")
        one_event = _single(event_id, "--event-id")
        hours = _check_window(window_hours)
        ceiling = _check_ceiling("additional", max_credits, acknowledge_credits)
        _require_network(allow_network)
        settings = get_settings()
        secret = _require_key(settings)
        document = run_additional(
            settings,
            secret,
            sport=one_sport,
            bookmaker=one_book,
            event_id=one_event,
            window_hours=hours,
            ceiling=ceiling,
        )
    except Refused as exc:
        _fail(exc.status, exc.message, as_json=json_output, secret=secret)
        return
    except ProviderError as exc:
        status = (
            ActivationStatus.AUTH_FAILED
            if isinstance(exc, TheOddsApiAuthError)
            else ActivationStatus.PROVIDER_UNAVAILABLE
        )
        _fail(status, str(exc), as_json=json_output, secret=secret)
        return

    write_receipt(document, secret=secret)
    _emit(document, _summary(document), as_json=json_output, secret=secret)


# ---------------------------------------------------------------------------
# Receipt assembly and human summary
# ---------------------------------------------------------------------------
def _receipt(
    *,
    command: str,
    status: ActivationStatus,
    now: datetime,
    sport: str,
    bookmaker: str,
    event_id: str,
    ceiling: int,
    observed: int,
    requested: list[str],
    book: dict[str, Any],
    shape: ResponseShape,
    batch: CollectionBatch,
    endpoint: str,
) -> dict[str, Any]:
    """Everything worth auditing, and nothing that would be worth exfiltrating.

    Deliberately absent: the key, the full URL, the raw body, every quoted odd,
    both participant names, and the provider's event id in clear. What remains is
    which endpoint was called, what it cost, which markets came back, how fresh
    they were and whether our parser coped — which is the whole question an
    activation is meant to answer.
    """
    observed_markets = _market_keys(book)
    return {
        "schema": RECEIPT_SCHEMA,
        "command": command,
        "status": str(status),
        "recorded_at": now.isoformat(),
        "endpoint": endpoint,
        "response_shape": str(shape),
        "sport_key": sport,
        "bookmaker": bookmaker,
        "event_id_hash": hash_event_id(event_id),
        "max_credits": ceiling,
        "observed_credits": observed,
        "markets_requested": requested,
        "markets_observed": observed_markets,
        "markets_absent": [m for m in requested if m not in observed_markets],
        "freshness": _freshness(book, shape, now),
        "selections_mapped": len(batch.snapshots),
        "mapping_rejections": [_generalise(error) for error in batch.partial_errors],
        "model_impact": "aucun — tous les modèles restent BACKTEST_ONLY",
    }


def _generalise(error: str) -> str:
    """Keep the reason, drop anything that could be a name or a quoted value."""
    return error.split(":")[0].strip()[:80]


def _summary(document: dict[str, Any]) -> list[str]:
    absent = document["markets_absent"]
    lines = [
        f"Statut          : {document['status']}",
        f"Endpoint        : {document['endpoint']}",
        f"Crédits         : {document['observed_credits']} annoncé(s), "
        f"plafond {document['max_credits']}",
        f"Marchés demandés: {', '.join(document['markets_requested'])}",
        f"Marchés obtenus : {', '.join(document['markets_observed']) or 'aucun'}",
    ]
    if absent:
        lines.append(
            f"Marchés absents : {', '.join(absent)} — constat, non compensé et non réessayé."
        )
    lines += [
        f"Sélections      : {document['selections_mapped']} cartographiée(s)",
        f"Fraîcheur (s)   : {document['freshness'] or 'aucune'}",
        "",
        "Reçu local écrit (non versionné). Aucun modèle promu, aucun candidat publié.",
    ]
    return lines


def _iso_z(moment: datetime) -> str:
    return ensure_utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":  # pragma: no cover - manual entry point
    app()
