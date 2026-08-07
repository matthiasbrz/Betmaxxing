"""Controlled activation of The Odds API — four steps, bounded and evidenced.

Why this module exists
----------------------
The smoke script it replaced asked for one boolean of consent and then called
``provider.collect([FOOTBALL, TENNIS], window)``: one grouped request per
configured sport key, then one per-event request for every football event found,
bounded only by the per-scan budget. A boolean is not a spending limit. Nobody
could say, in advance, what that script would cost.

What is bounded, and by whom
----------------------------
Four words, deliberately kept apart, because collapsing them is how a spending
record starts lying:

**Local bound** — what this program will actually do. Number of requests,
endpoints, events, bookmakers and markets. Enforced here, absolutely, before a
socket is opened.

**Estimated contractual ceiling** — what those requests *should* cost under the
published rule (``markets x effective region units``), re-read 2026-08-05.
Enforced here as a refusal to proceed when the estimate exceeds what the operator
authorised.

**Observed cost** — ``x-requests-last``, what the provider says it charged.
``None`` when the header is absent or unusable. Never a stand-in for zero.

**Accounted cost** — what the spend record keeps: the observation when there is
one, the estimate otherwise. Conservative by construction.

This program cannot stop an external company from repricing a request it has
already served; it can only notice the discrepancy in the headers and stop. So
"ceiling" here means the first two — a bound on *our* behaviour and on what the
documented tariff implies — not a guarantee about someone else's invoice.

=========== ======== ============================== ==========================
command     network  local bound                    estimated contractual cost
=========== ======== ============================== ==========================
plan        no       no client is even built        0
discover    yes      2 requests, free endpoints     0
core        yes      1 request, 1 event, 1 market   1
additional  yes      1 request, 1 event, 5 markets  5
=========== ======== ============================== ==========================

Evidence, not habit
-------------------
Each step is authorised by the previous step's **receipt**, passed explicitly by
path — never discovered by scanning a directory, which would be the program
choosing its own proof. Receipts are v2: signed with a local HMAC secret over
their canonical JSON, carrying HMAC-tagged event ids rather than clear ones,
expiring, and referencing their parent. A receipt that is unsigned, altered,
expired, of the wrong schema, or about a different sport, bookmaker or event is
refused before the network.

Every network attempt writes a receipt, whatever its terminal status — a call
that was billed and then failed validation is exactly the one an audit needs. A
refusal *before* the network writes nothing: inventing a consumption record for a
call that never happened is the same error pointing the other way.

Status vocabulary: ``PREPARED_NOT_EXECUTED``, ``DISCOVERY_VERIFIED``,
``CORE_LIVE_VERIFIED``, ``ADDITIONAL_LIVE_VERIFIED``,
``ADDITIONAL_PARTIAL_COVERAGE``, ``COVERAGE_MISSING``, ``SCHEMA_MISMATCH``,
``COST_MISMATCH``, ``COST_UNVERIFIED``, ``AUTH_FAILED``,
``PROVIDER_UNAVAILABLE``.

Nothing here promotes a model, publishes a candidate, or writes a scan. A green
run is a *limited* proof — this endpoint, this bookmaker, this competition, this
event, this market, this instant. The adapter's global status stays
``IMPLEMENTED_UNVERIFIED`` until a separate, documented promotion decision.
"""

from __future__ import annotations

import hashlib
import hmac
import json as jsonlib
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
import typer

from betmaxxing.config import Settings, get_settings
from betmaxxing.domain.enums import Sport
from betmaxxing.domain.timeutil import ensure_utc, utc_now
from betmaxxing.providers.base import CollectionBatch, ProviderError, QuotaInfo
from betmaxxing.providers.budget import ProviderBudgetLedger
from betmaxxing.providers.the_odds_api.client import (
    HEADER_LAST,
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
#: Where receipts land when ``BETMAXXING_ACTIVATION_RECEIPTS`` is unset. Its
#: first path segment is listed in ``.gitignore``: a receipt is an operating
#: record of a real, billed call and belongs to the operator, not to the repo.
DEFAULT_RECEIPT_DIR = ".activation-receipts"
RECEIPT_DIR_VARIABLE = "BETMAXXING_ACTIVATION_RECEIPTS"

#: The local signing secret. Generated on first network need, never printed,
#: never committed. Overridable by environment so tests are deterministic and no
#: test ever leaves a real secret on disk.
SECRET_FILENAME = "signing-key.secret"
SECRET_VARIABLE = "BETMAXXING_ACTIVATION_RECEIPT_SECRET"

#: Injected by the test suite. Production leaves it ``None`` so httpx builds its
#: own transport; there is no other way to reach this module's network calls.
_TRANSPORT_FOR_TESTS: httpx.BaseTransport | None = None

#: Patched by tests that need a deterministic instant.
_clock = utc_now

#: Estimated contractual cost of each step, under the published v4 rule.
STEP_CEILINGS: dict[str, int] = {"plan": 0, "discover": 0, "core": 1, "additional": 5}
TOTAL_MAX_CREDITS = sum(STEP_CEILINGS.values())

#: What the program itself will do, regardless of what anything costs. These are
#: enforced by construction: there is no code path that issues a second request.
LOCAL_BOUNDS: dict[str, dict[str, int]] = {
    "plan": {"max_requests": 0, "max_events": 0, "max_bookmakers": 0, "max_markets": 0},
    "discover": {"max_requests": 2, "max_events": 0, "max_bookmakers": 1, "max_markets": 0},
    "core": {"max_requests": 1, "max_events": 1, "max_bookmakers": 1, "max_markets": 1},
    "additional": {"max_requests": 1, "max_events": 1, "max_bookmakers": 1, "max_markets": 5},
}

#: One market, deliberately. ``core_markets_for(FOOTBALL)`` is ``("h2h",
#: "totals")`` — two markets, therefore two credits. The activation asks for the
#: single market that proves the endpoint, the auth and the parser, and stops.
CORE_MARKETS: tuple[str, ...] = ("h2h",)

#: The five per-event markets, taken from the provider's own policy so the two
#: cannot drift apart.
ADDITIONAL_MARKETS: tuple[str, ...] = additional_markets_for(Sport.FOOTBALL)

MAX_WINDOW_HOURS = 24

#: Receipt schema. v1 was unsigned and carried an unsalted SHA of a public event
#: id; it is refused rather than upgraded, because a v1 file proves nothing.
#:
#: v3 changes the *meaning* of ``market_states``, so it is a new version rather
#: than v2 with extra fields. In v2 the map was partial — empty when the
#: bookmaker was absent — and ``markets_absent`` could read as "nothing was
#: missing" while a market had in fact never been looked at. In v3 the map is
#: total over ``markets_requested`` and carries the explicit
#: ``NOT_EVALUATED_BOOKMAKER_ABSENT``. A reader that applied v3's invariants to a
#: v2 file would draw a wrong conclusion, which is exactly what a version number
#: is for.
RECEIPT_SCHEMA_VERSION = 3

#: v2 receipts already on an operator's disk stay usable as authority. Every
#: field the chain actually depends on — ``event_tags``, ``event_tag``,
#: ``observed_credits``, ``accounted_credits``, ``selections_mapped``,
#: ``parent_receipt_id``, ``expires_at`` — has the same meaning in both versions;
#: only ``market_states`` and its projections changed, and those are not
#: preconditions. So a valid v2 receipt is read, verified and honoured, never
#: rewritten and never re-signed. Anything outside this set is refused.
SUPPORTED_SCHEMA_VERSIONS = frozenset({2, RECEIPT_SCHEMA_VERSION})

SIGNATURE_FIELD = "signature"

#: How long a receipt may authorise the next step. Short on purpose: yesterday's
#: discovery says nothing about today's fixtures, and a proof that never expires
#: is a proof that eventually gets reused for the wrong thing.
RECEIPT_TTL = timedelta(hours=6)


class ActivationStatus(StrEnum):
    """Every outcome the harness can report. There is no other vocabulary.

    ``PLAN_ONLY`` and ``PREPARED_NOT_EXECUTED`` are deliberately distinct.
    ``plan`` computes and reports; it knows nothing about what has been executed,
    and once real ``core`` calls exist, a label meaning "nothing has run" printed
    by ``plan`` is simply false. ``PREPARED_NOT_EXECUTED`` survives only where it
    is still true: a refusal that happened before any socket opened, and the
    paid-activation dimension reported by ``status`` while no paid call has been
    attempted.
    """

    PLAN_ONLY = "PLAN_ONLY"
    PREPARED_NOT_EXECUTED = "PREPARED_NOT_EXECUTED"
    DISCOVERY_VERIFIED = "DISCOVERY_VERIFIED"
    CORE_LIVE_VERIFIED = "CORE_LIVE_VERIFIED"
    ADDITIONAL_LIVE_VERIFIED = "ADDITIONAL_LIVE_VERIFIED"
    ADDITIONAL_PARTIAL_COVERAGE = "ADDITIONAL_PARTIAL_COVERAGE"
    COVERAGE_MISSING = "COVERAGE_MISSING"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    COST_MISMATCH = "COST_MISMATCH"
    COST_UNVERIFIED = "COST_UNVERIFIED"
    AUTH_FAILED = "AUTH_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


#: Statuses that authorise the next step and exit zero. Everything else is a
#: reportable outcome that stops the sequence.
VERIFIED_STATUSES = frozenset(
    {
        ActivationStatus.DISCOVERY_VERIFIED,
        ActivationStatus.CORE_LIVE_VERIFIED,
        ActivationStatus.ADDITIONAL_LIVE_VERIFIED,
        ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE,
    }
)


class BookmakerState(StrEnum):
    """Whether the bookmaker we asked for was quoted on the event at all.

    Its own dimension, because it is a different question from what the markets
    did. Two real ``core`` calls came back valid, for the right event, with no
    block for our bookmaker — and the receipts recorded that as an empty market
    map, which reads like "we looked and found nothing missing".
    """

    OBSERVED = "OBSERVED"
    NOT_RETURNED = "NOT_RETURNED"


class MarketState(StrEnum):
    """What became of one requested market. Four distinct findings.

    ``NOT_EVALUATED_BOOKMAKER_ABSENT`` is the one that was missing. Without it,
    "we never got to look" and "we looked and it was not there" collapse into the
    same silence — and the second is a fact about the bookmaker's offer while the
    first is a fact about nothing at all.
    """

    OBSERVED_MAPPED = "OBSERVED_MAPPED"
    OBSERVED_REJECTED = "OBSERVED_REJECTED"
    NOT_RETURNED = "NOT_RETURNED"
    NOT_EVALUATED_BOOKMAKER_ABSENT = "NOT_EVALUATED_BOOKMAKER_ABSENT"


class ExecutionState(StrEnum):
    """How far the activation has actually gone, on this installation."""

    NO_NETWORK_ATTEMPTED = "NO_NETWORK_ATTEMPTED"
    DISCOVERY_ATTEMPTED = "DISCOVERY_ATTEMPTED"
    CORE_ATTEMPTED = "CORE_ATTEMPTED"
    ADDITIONAL_ATTEMPTED = "ADDITIONAL_ATTEMPTED"


class PaidActivationState(StrEnum):
    """The paid dimension only. Separate from coverage and from mapping."""

    PREPARED_NOT_EXECUTED = "PREPARED_NOT_EXECUTED"
    CORE_EXECUTED_NO_COVERAGE = "CORE_EXECUTED_NO_COVERAGE"
    CORE_EXECUTED_COVERAGE_OBSERVED = "CORE_EXECUTED_COVERAGE_OBSERVED"
    ADDITIONAL_EXECUTED = "ADDITIONAL_EXECUTED"


class CostProof(StrEnum):
    """Whether connectivity and billing have been exercised, and conformingly."""

    NOT_EXERCISED = "NOT_EXERCISED"
    EXERCISED_CONFORMING = "EXERCISED_CONFORMING"
    EXERCISED_NONCONFORMING = "EXERCISED_NONCONFORMING"


class MappingProof(StrEnum):
    """Whether the parser and the freshness check have actually been exercised.

    ``OFFLINE_CONTRACT_VERIFIED`` is what a synthetic fixture can earn. It is not
    a live verification and must never be reported as one: the whole point of the
    distinction is that a fixture proves our code reads *the documented shape*,
    not that the provider sends it.
    """

    NOT_OBTAINED_LIVE = "NOT_OBTAINED_LIVE"
    OFFLINE_CONTRACT_VERIFIED = "OFFLINE_CONTRACT_VERIFIED"
    OBTAINED_LIVE = "OBTAINED_LIVE"


class Refused(Exception):
    """A step stopped.

    ``document`` carries the full receipt when the network was already reached,
    so the operator sees the whole outcome rather than a one-line reason.
    """

    def __init__(
        self,
        status: ActivationStatus,
        message: str,
        document: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.document = document


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Activation contrôlée de The Odds API. Quatre étapes indépendantes, "
        "chacune bornée localement, chiffrée selon le tarif publié et autorisée "
        "séparément : plan (0), discover (0), core (1 crédit), additional (5)."
    ),
)


# ---------------------------------------------------------------------------
# Secrets and scrubbing
# ---------------------------------------------------------------------------
def _scrub(text: str, secret: str) -> str:
    """Remove the API key from a message, however it got in there.

    :func:`redact` strips ``apiKey=…`` from URLs, which covers everything the
    client itself builds. It does not cover a third party: an ``httpx`` transport
    error can quote the whole request line, and a proxy can echo the query string
    back inside a body. So the literal value is removed too, and that is the last
    thing done before anything is printed — and, for a receipt, before it is
    signed, so scrubbing can never invalidate a signature.
    """
    cleaned = redact(text)
    if secret:
        cleaned = cleaned.replace(secret, "***REDACTED***")
    return cleaned


def receipt_dir() -> Path:
    return Path(os.environ.get(RECEIPT_DIR_VARIABLE, "").strip() or DEFAULT_RECEIPT_DIR)


def receipt_secret() -> str:
    """The local HMAC secret, created on first need.

    Created with ``O_CREAT | O_EXCL`` at mode ``0600`` so two processes racing
    cannot end up with different secrets — the loser reads the winner's file.
    It lives in the gitignored receipt directory, is never printed, never logged
    and never committed. The environment variable exists so the test suite can
    inject a deterministic value rather than depend on real randomness.
    """
    injected = os.environ.get(SECRET_VARIABLE, "").strip()
    if injected:
        return injected

    directory = receipt_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SECRET_FILENAME
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_hex(32)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(value)
    # `os.open`'s mode is masked by the umask; state it outright.
    os.chmod(path, 0o600)
    return value


def event_tag(event_id: str) -> str:
    """Stable local tag for a provider event id.

    HMAC rather than a bare digest. A plain ``sha256(event_id)`` is computable by
    anyone holding the provider's public fixture list, so it hid nothing; keyed
    with a secret that never leaves this installation, it identifies the event to
    *us* — enough for ``core`` to recognise ``discover``'s approval across
    processes — without being reversible by a dictionary of public ids.
    """
    digest = hmac.new(
        receipt_secret().encode("utf-8"), f"event:{event_id}".encode(), hashlib.sha256
    )
    return digest.hexdigest()[:24]


# ---------------------------------------------------------------------------
# Cost model — three numbers, never conflated
# ---------------------------------------------------------------------------
def _usable_cost(value: object) -> int | None:
    """A charge is a non-negative integer. Anything else is *unknown*, not nought."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def observed_credits_of(headers: Mapping[str, Any]) -> int | None:
    """What the provider says it charged, or ``None`` if it did not say.

    ``None`` is the whole point. The previous version returned ``0`` for a
    missing header, so a call the ledger had just charged one credit for was
    recorded as free, and a documented-free endpoint that never reported its cost
    was accepted as *proof* of costing nothing.
    """
    return _usable_cost(headers.get(HEADER_LAST))


def _observed_from(quota: QuotaInfo) -> int | None:
    return _usable_cost(quota.last_cost)


def accounted_credits_of(*, estimated: int, observed: int | None) -> int:
    """What the spend record keeps.

    The observation when there is one — including an explicit nought, which v4
    really does return for an empty response. The estimate otherwise, because a
    cost we could not read is a cost we must assume we paid.
    """
    return estimated if observed is None else observed


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------
def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """The exact bytes a signature covers.

    Sorted keys and tight separators, so re-serialising a receipt — or reading it
    back through a JSON library that reorders — cannot change the signature.
    ``signature`` itself and any ``_``-prefixed scratch key are excluded.
    """
    body = {k: v for k, v in payload.items() if k != SIGNATURE_FIELD and not k.startswith("_")}
    return jsonlib.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sign_receipt(payload: Mapping[str, Any]) -> str:
    return hmac.new(
        receipt_secret().encode("utf-8"), canonical_bytes(payload), hashlib.sha256
    ).hexdigest()


def verify_receipt(payload: Mapping[str, Any]) -> bool:
    """Constant-time signature check. Everything downstream depends on it."""
    given = payload.get(SIGNATURE_FIELD)
    if not isinstance(given, str) or not given:
        return False
    return hmac.compare_digest(given, sign_receipt(payload))


def write_receipt(document: dict[str, Any]) -> Path:
    """Sign and persist one receipt locally. Never committed, never uploaded."""
    directory = receipt_dir()
    directory.mkdir(parents=True, exist_ok=True)
    signed = {k: v for k, v in document.items() if not k.startswith("_")}
    signed[SIGNATURE_FIELD] = sign_receipt(signed)
    stamp = str(signed["recorded_at"]).replace(":", "").replace("-", "")[:15]
    path = directory / f"{stamp}-{signed['command']}-{str(signed['receipt_id'])[:8]}.json"
    path.write_text(
        jsonlib.dumps(signed, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    document[SIGNATURE_FIELD] = signed[SIGNATURE_FIELD]
    document["_path"] = str(path)
    return path


def load_parent(
    raw_path: str,
    *,
    command: str,
    status: ActivationStatus,
    sport: str,
    bookmaker: str,
    now: datetime,
) -> dict[str, Any]:
    """Read and fully validate the receipt that authorises this step.

    Passed by path, deliberately. The previous version walked the receipt
    directory looking for something that matched — choosing the operator's
    evidence for them, from unauthenticated files, in a directory anything can
    write to.
    """
    directory = receipt_dir().resolve()
    path = Path(raw_path)
    if path.is_symlink():
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{raw_path} est un lien symbolique. Une preuve doit être un fichier réel "
            "du répertoire de reçus, pas un renvoi vers ailleurs.",
        )
    resolved = path.resolve()
    if not resolved.is_file() or resolved.parent != directory:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{raw_path} n'est pas un reçu de {directory}. Seul le répertoire de reçus "
            "autorisé est lu ; aucun chemin ambigu n'est suivi.",
        )

    try:
        payload = jsonlib.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED, f"{raw_path} est illisible ({exc})."
        ) from exc
    if not isinstance(payload, dict):
        raise Refused(ActivationStatus.PREPARED_NOT_EXECUTED, f"{raw_path} n'est pas un reçu.")

    version = payload.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{raw_path} porte le schéma {version!r} ; seuls "
            f"{sorted(SUPPORTED_SCHEMA_VERSIONS)} sont lus. Un reçu v1 n'est ni signé ni "
            "chaîné : il ne prouve rien et n'est pas promu silencieusement. Relancez "
            "`discover` puis les étapes suivantes avec cette version.",
        )
    if not verify_receipt(payload):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{raw_path} : signature absente ou invalide. Le reçu a été modifié, ou il "
            "vient d'une autre installation. Relancez `discover` pour repartir d'une "
            "preuve authentique.",
        )

    if payload.get("command") != command or payload.get("status") != str(status):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{raw_path} porte command={payload.get('command')!r} "
            f"status={payload.get('status')!r} ; attendu {command!r} / {status}.",
        )
    if payload.get("sport_key") != sport or payload.get("bookmaker") != bookmaker:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{raw_path} concerne {payload.get('sport_key')!r}/{payload.get('bookmaker')!r} "
            f"et non {sport!r}/{bookmaker!r}. Une preuve ne se transpose pas.",
        )

    expires = _parse_instant(payload.get("expires_at"))
    if expires is None or expires <= now:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{raw_path} a expiré ({payload.get('expires_at')}). Une découverte périmée ne "
            "dit rien des rencontres d'aujourd'hui ; relancez `discover`.",
        )
    return payload


def _parse_instant(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return ensure_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Attempt bookkeeping — so any exit path can still write a receipt
# ---------------------------------------------------------------------------
@dataclass
class Attempt:
    """Everything a receipt needs, filled in as the step proceeds.

    It exists because receipts used to be written only on the success path: a
    response that arrived, was billed, and then failed validation left no trace
    at all. Once a request has been attempted this object is enough to write a
    complete, sanitised receipt whatever happens next.
    """

    command: str
    sport: str
    bookmaker: str
    window: tuple[datetime, datetime]
    ceiling: int
    now: datetime
    event_id: str | None = None
    estimated: int = 0
    observed: int | None = None
    attempts: int = 0
    network_attempted: bool = False
    reached_provider: bool = False
    endpoints: list[str] = field(default_factory=list)
    parent_receipt_id: str | None = None
    quota_remaining: int | None = None
    event_tags: list[str] = field(default_factory=list)
    markets_requested: list[str] = field(default_factory=list)
    market_states: dict[str, str] = field(default_factory=dict)
    freshness: dict[str, int] = field(default_factory=dict)
    selections_mapped: int = 0
    rejections: list[str] = field(default_factory=list)
    events: list[dict[str, str]] = field(default_factory=list)
    #: Its own dimension, independent of what the markets did.
    bookmaker_state: str = str(BookmakerState.NOT_RETURNED)
    #: Which schema the authorising parent carried, so provenance stays traceable
    #: when a v2 receipt is honoured by a v3 step.
    parent_schema_version: int | None = None
    #: Discovery funnel, three integers and nothing else — a per-event breakdown
    #: would smuggle the schedule back into a sanitised artefact.
    events_returned: int = 0
    events_in_window: int = 0
    events_admissible: int = 0

    def record(self, endpoint: str) -> None:
        self.attempts += 1
        self.network_attempted = True
        self.endpoints.append(endpoint)

    @property
    def accounted(self) -> int:
        if not self.reached_provider and self.observed is None:
            # Proven never to have left: nothing was served, nothing was billed.
            return 0
        return accounted_credits_of(estimated=self.estimated, observed=self.observed)


def build_receipt(attempt: Attempt, status: ActivationStatus, secret: str) -> dict[str, Any]:
    """Assemble one sanitised receipt.

    Deliberately absent: the key, the full URL, the raw body, every quoted odd,
    both participant names, and the provider's event id in clear. What remains is
    which endpoint was called, how many times, whether it got there, what it was
    estimated at, what it reported, what we account for, which markets came back
    in what state, how fresh they were, and whether our parser coped — the whole
    question an activation is meant to answer.
    """
    document: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_id": secrets.token_hex(8),
        "command": attempt.command,
        "status": str(status),
        "recorded_at": attempt.now.isoformat(),
        "expires_at": (attempt.now + RECEIPT_TTL).isoformat(),
        "sport_key": attempt.sport,
        "bookmaker": attempt.bookmaker,
        "window_from": attempt.window[0].isoformat(),
        "window_to": attempt.window[1].isoformat(),
        "endpoints": list(attempt.endpoints),
        "endpoint": attempt.endpoints[-1] if attempt.endpoints else "",
        "attempts": attempt.attempts,
        "network_attempted": attempt.network_attempted,
        "may_have_reached_provider": attempt.reached_provider,
        "estimated_credits": attempt.estimated,
        "observed_credits": attempt.observed,
        "accounted_credits": attempt.accounted,
        "quota_remaining": attempt.quota_remaining,
        "markets_requested": list(attempt.markets_requested),
        # Every list below is a strict projection of `market_states`, so none of
        # them can contradict it. Together they partition `markets_requested`
        # exactly once — which is what makes `markets_absent == []` readable: it
        # now means "nothing was observed missing", with
        # `markets_not_evaluated` carrying the ones we never got to look at.
        "markets_observed": _project(
            attempt, MarketState.OBSERVED_MAPPED, MarketState.OBSERVED_REJECTED
        ),
        "markets_mapped": _project(attempt, MarketState.OBSERVED_MAPPED),
        "markets_rejected": _project(attempt, MarketState.OBSERVED_REJECTED),
        "markets_absent": _project(attempt, MarketState.NOT_RETURNED),
        "markets_not_evaluated": _project(attempt, MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT),
        "market_states": dict(attempt.market_states),
        "freshness": dict(attempt.freshness),
        "selections_mapped": attempt.selections_mapped,
        "mapping_rejections": [_scrub(r, secret) for r in attempt.rejections],
        "parent_receipt_id": attempt.parent_receipt_id,
        "parent_schema_version": attempt.parent_schema_version,
        "adapter_status": "IMPLEMENTED_UNVERIFIED",
        "model_impact": "aucun — tous les modèles restent BACKTEST_ONLY",
    }
    if attempt.command == "discover":
        # `/events` returns no bookmaker information at all, so a discovery has
        # no bookmaker observation to report. The field is omitted rather than
        # defaulted: `NOT_RETURNED` here would read as a finding about the
        # bookmaker when in fact nothing was ever asked about it.
        document["event_tags"] = list(attempt.event_tags)
        document["events_returned"] = attempt.events_returned
        document["events_in_window"] = attempt.events_in_window
        document["events_admissible"] = attempt.events_admissible
    else:
        document["bookmaker_state"] = attempt.bookmaker_state
        document["event_tag"] = attempt.event_tags[0] if attempt.event_tags else ""
    return document


def _project(attempt: Attempt, *states: MarketState) -> list[str]:
    """The requested markets currently in one of these states, in request order.

    Request order rather than dict order so two receipts for the same scope are
    comparable, and derived strictly from ``market_states`` so a projection can
    never disagree with the map it summarises.
    """
    wanted = {str(state) for state in states}
    return [m for m in attempt.markets_requested if attempt.market_states.get(m) in wanted]


# ---------------------------------------------------------------------------
# Scope validation — everything checkable before a socket exists
# ---------------------------------------------------------------------------
def _single(raw: str, label: str) -> str:
    """Exactly one comma-free token, or refuse.

    A list here is a fan-out, and a fan-out is precisely what the previous script
    did wrong. Multiplying the scope multiplies the bill.
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

    Two identical numbers typed by hand is a weak proof of intent, but it is a far
    stronger one than a boolean: it cannot be supplied without knowing what the
    step costs.
    """
    expected = STEP_CEILINGS[command]
    if max_credits != expected:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"`{command}` est chiffré à {expected} crédit(s) selon le tarif publié ; "
            f"--max-credits={max_credits} est refusé. Ce plafond ne se négocie pas depuis "
            "la ligne de commande.",
        )
    if acknowledge is None or acknowledge != expected:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"--acknowledge-credits={expected} est requis pour `{command}` : vous "
            "confirmez explicitement la dépense avant qu'elle ait lieu.",
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

    ``max_retries=0`` is the whole point: a retry is another billable request, and
    a step whose local bound is one request may make exactly one attempt.
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


def _settle_cost(attempt: Attempt, quota: QuotaInfo, endpoint: str) -> None:
    """Read what the provider charged, and decide whether we can prove it.

    Raises ``COST_MISMATCH`` above the ceiling — the billing contract is not the
    one this harness was built against, and the right response is to stop.
    ``COST_UNVERIFIED`` when the header is missing or unusable: the estimate stays
    accounted for, and an unproven step authorises nothing.
    """
    attempt.reached_provider = True
    attempt.observed = _observed_from(quota)
    attempt.quota_remaining = quota.remaining
    if attempt.observed is not None and attempt.observed > attempt.ceiling:
        raise Refused(
            ActivationStatus.COST_MISMATCH,
            f"{endpoint} : le fournisseur annonce {attempt.observed} crédit(s) facturé(s) "
            f"pour un plafond contractuel de {attempt.ceiling}. Arrêt immédiat — la "
            "tarification n'est plus celle sur laquelle cet outil est chiffré.",
        )
    if attempt.observed is None:
        raise Refused(
            ActivationStatus.COST_UNVERIFIED,
            f"{endpoint} : aucun en-tête `{HEADER_LAST}` exploitable. Le coût réel est "
            f"inconnu, l'estimation ({attempt.estimated}) reste comptabilisée par "
            "prudence, et une étape non vérifiée n'en autorise aucune autre.",
        )


# ---------------------------------------------------------------------------
# Payload inspection — no fabrication, no fallback
# ---------------------------------------------------------------------------
def _event_of(payload: Any, event_id: str, endpoint: str) -> dict[str, Any]:
    """Locate the one event we asked for, or say precisely what came back."""
    events = payload if isinstance(payload, list) else [payload]
    if not events or all(item in ({}, None) for item in events):
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            f"{endpoint} : réponse vide. Ce n'est pas une panne — aucun événement "
            "correspondant n'était disponible à cet instant.",
        )
    usable = [
        item
        for item in events
        if isinstance(item, dict) and {"id", "commence_time", "home_team"} <= set(item)
    ]
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


def _book_of(raw_event: dict[str, Any], bookmaker: str) -> dict[str, Any] | None:
    """The bookmaker's block, or ``None`` if it is not in the response.

    Returns rather than raises. The previous version raised here, *before* the
    markets were classified, so a receipt written on that path had an empty
    market map — indistinguishable from "we checked and nothing was missing".
    The caller now records the bookmaker's state, classifies every requested
    market as ``NOT_EVALUATED_BOOKMAKER_ABSENT``, and only then stops.
    """
    for book in raw_event.get("bookmakers") or []:
        if isinstance(book, dict) and str(book.get("key", "")) == bookmaker:
            return book
    return None


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


def _classify_markets(
    requested: tuple[str, ...], book: dict[str, Any] | None, batch: CollectionBatch | None
) -> dict[str, str]:
    """One explicit state per requested market. Four distinct findings.

    ``NOT_EVALUATED_BOOKMAKER_ABSENT`` — there was no block to look in, so we
    know nothing about the market. ``NOT_RETURNED`` — the bookmaker was quoted
    and did not offer it, which is a coverage fact about its offer.
    ``OBSERVED_REJECTED`` — it came back and our parser could not use it, a
    contract or mapping fact. ``OBSERVED_MAPPED`` — it worked.

    The map is **total** over ``requested``: every market asked for gets exactly
    one state, so ``set(market_states) == set(markets_requested)`` holds on every
    terminal receipt whose market scope was known. The two real ``core`` receipts
    broke that invariant by returning ``{}``.
    """
    if book is None:
        return dict.fromkeys(requested, str(MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT))
    returned = set(_market_keys(book))
    mapped = {str(s.source_meta.get("market", "")) for s in (batch.snapshots if batch else [])}
    states: dict[str, str] = {}
    for key in requested:
        if key not in returned:
            states[key] = str(MarketState.NOT_RETURNED)
        elif key in mapped:
            states[key] = str(MarketState.OBSERVED_MAPPED)
        else:
            states[key] = str(MarketState.OBSERVED_REJECTED)
    return states


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
    the code that will read it in production actually does.
    """
    provider = TheOddsApiProvider(settings, client=client, now=now)
    batch = CollectionBatch(
        provider=PROVIDER_NAME, collected_at=now, bookmakers=list(settings.bookmaker_list)
    )
    provider._ingest_event(raw_event, Sport.FOOTBALL, window, now, batch, shape=shape)
    return batch


def _check_start_time(raw_event: dict[str, Any], window: tuple[datetime, datetime]) -> None:
    raw = str(raw_event.get("commence_time", ""))
    start = _parse_instant(raw.replace("Z", "+00:00"))
    if start is None:
        raise Refused(
            ActivationStatus.SCHEMA_MISMATCH,
            f"commence_time illisible ({raw!r}) — aucune date n'est supposée.",
        )
    if not (window[0] < start <= window[1]):
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            "L'événement demandé démarre hors de la fenêtre déclarée. L'activation "
            "n'élargit jamais sa portée pour trouver quelque chose à mesurer.",
        )


def _inside(item: dict[str, Any], window: tuple[datetime, datetime]) -> bool:
    start = _parse_instant(str(item.get("commence_time", "")).replace("Z", "+00:00"))
    return start is not None and window[0] < start <= window[1]


def _generalise(error: str) -> str:
    """Keep the reason, drop anything that could be a name or a quoted value."""
    return error.split(":")[0].strip()[:80]


def _status_of(error: ProviderError) -> ActivationStatus:
    return (
        ActivationStatus.AUTH_FAILED
        if isinstance(error, TheOddsApiAuthError)
        else ActivationStatus.PROVIDER_UNAVAILABLE
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def _emit(document: dict[str, Any], lines: list[str], *, as_json: bool, secret: str = "") -> None:
    payload = {k: v for k, v in document.items() if not k.startswith("_")}
    if as_json:
        typer.echo(_scrub(jsonlib.dumps(payload, indent=2, sort_keys=True), secret))
        return
    for line in lines:
        typer.echo(_scrub(line, secret))


def _finish(
    document: dict[str, Any],
    lines: list[str],
    *,
    as_json: bool,
    secret: str,
    ok: bool,
) -> None:
    _emit(document, lines, as_json=as_json, secret=secret)
    if not ok:
        raise typer.Exit(1)


def _fail(
    status: ActivationStatus,
    message: str,
    *,
    as_json: bool,
    secret: str = "",
    document: dict[str, Any] | None = None,
) -> None:
    if document is not None:
        _emit(
            document,
            [f"{status} : {message}", "", *_summary(document)],
            as_json=as_json,
            secret=secret,
        )
    elif as_json:
        typer.echo(_scrub(jsonlib.dumps({"status": str(status), "detail": message}), secret))
    else:
        typer.echo(_scrub(f"{status} : {message}", secret))
    raise typer.Exit(1)


def _summary(document: dict[str, Any]) -> list[str]:
    lines = [
        f"Statut          : {document['status']}",
        f"Endpoint        : {document.get('endpoint') or 'aucun'}",
        f"Requêtes        : {document.get('attempts', 0)} "
        f"(borne locale {LOCAL_BOUNDS[document['command']]['max_requests']})",
        f"Crédits estimés : {document.get('estimated_credits')}",
        f"Crédits annoncés: {_none(document.get('observed_credits'))}",
        f"Crédits retenus : {document.get('accounted_credits')} (prudence)",
    ]
    if document.get("bookmaker_state"):
        wording = (
            "coté sur cet événement"
            if document["bookmaker_state"] == str(BookmakerState.OBSERVED)
            else "non retourné par le fournisseur"
        )
        lines.append(
            f"Bookmaker       : {document.get('bookmaker')} — "
            f"{document['bookmaker_state']} ({wording})"
        )
    states = document.get("market_states") or {}
    if states:
        lines.append("Marchés         :")
        for key, state in states.items():
            age = document.get("freshness", {}).get(key)
            suffix = f" · {age} s" if age is not None else ""
            gloss = (
                "  ← non évalué : aucun bloc bookmaker à examiner"
                if state == str(MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)
                else ""
            )
            lines.append(f"  · {key:<18} {state}{suffix}{gloss}")
    if document.get("markets_not_evaluated"):
        lines.append(
            "                  aucun de ces marchés n'a été évalué : le bookmaker "
            "demandé n'était pas dans la réponse."
        )
    if document.get("events_returned") is not None and document.get("command") == "discover":
        lines.append(
            f"Événements      : {document['events_returned']} retourné(s) · "
            f"{document['events_in_window']} dans la fenêtre · "
            f"{document['events_admissible']} exploitable(s)"
        )
    if document.get("selections_mapped") is not None:
        lines.append(f"Sélections      : {document['selections_mapped']} cartographiée(s)")
    if document.get("_path"):
        lines.append(f"Reçu            : {document['_path']}")
    lines += [
        "",
        "Preuve limitée à cet endpoint, ce bookmaker, cette compétition, cet événement, "
        "ce marché et cet instant.",
        f"Statut de l'adaptateur inchangé : {document.get('adapter_status')}. "
        f"Modèles : {document.get('model_impact')}.",
    ]
    return lines


def _none(value: object) -> str:
    return "inconnu" if value is None else str(value)


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
            "local_bound": LOCAL_BOUNDS["plan"],
            "endpoints": [],
            "markets": [],
            "note": "Aucune socket, aucune clé lue, aucun secret lu, aucun reçu écrit.",
        },
        {
            "command": "discover",
            "network": True,
            "max_credits": STEP_CEILINGS["discover"],
            "local_bound": LOCAL_BOUNDS["discover"],
            "endpoints": ["/v4/sports", f"/v4/sports/{sport}/events"],
            "markets": [],
            "note": (
                "Endpoints documentés gratuits ; un coût annoncé non nul arrête l'étape, "
                "un coût non annoncé la laisse non vérifiée."
            ),
        },
        {
            "command": "core",
            "network": True,
            "max_credits": STEP_CEILINGS["core"],
            "local_bound": LOCAL_BOUNDS["core"],
            "endpoints": [f"/v4/sports/{sport}/odds"],
            "markets": list(CORE_MARKETS),
            "note": (
                f"{len(CORE_MARKETS)} marché x {units} unité(s) régionale(s) = "
                f"{estimate_cost(markets=len(CORE_MARKETS), region_units=units)} crédit(s) "
                "selon le tarif publié. Exige le reçu de `discover`."
            ),
        },
        {
            "command": "additional",
            "network": True,
            "max_credits": STEP_CEILINGS["additional"],
            "local_bound": LOCAL_BOUNDS["additional"],
            "endpoints": [f"/v4/sports/{sport}/events/<event>/odds"],
            "markets": list(ADDITIONAL_MARKETS),
            "note": (
                f"{len(ADDITIONAL_MARKETS)} marchés x {units} unité(s) régionale(s) = "
                f"{estimate_cost(markets=len(ADDITIONAL_MARKETS), region_units=units)} "
                "crédit(s) selon le tarif publié. Exige le reçu de `core`."
            ),
        },
    ]
    return {
        # `plan` computes; it does not know what has been executed. Claiming
        # PREPARED_NOT_EXECUTED here became false the moment real `core` calls
        # happened — the activation's actual state is what `status` reports.
        "status": str(ActivationStatus.PLAN_ONLY),
        "generated_at": generated_at,
        "sport_key": sport,
        "bookmaker": bookmaker,
        "window_hours": window_hours,
        "effective_region_units": units,
        "total_max_credits": TOTAL_MAX_CREDITS,
        "steps": steps,
        "cost_model": {
            "local_bound": (
                "Ce que ce programme fera : nombre de requêtes, endpoints, événements, "
                "bookmakers et marchés. Imposé ici, avant toute socket."
            ),
            "estimated_contractual_ceiling": TOTAL_MAX_CREDITS,
            "observed": (
                "`x-requests-last`, ce que le fournisseur déclare avoir facturé. "
                "`null` s'il ne le déclare pas — jamais remplacé par zéro."
            ),
            "accounted": (
                "Ce qui est retenu en comptabilité : l'observation si elle existe, "
                "l'estimation sinon."
            ),
        },
        "guarantees": [
            "Aucun endpoint historique ou payant n'est joignable depuis cet outil.",
            "Aucune tentative n'est répétée : max_retries=0 sur chaque étape.",
            "Aucune étape n'en déclenche une autre ; chaque preuve est fournie en argument.",
            "La clé provient de l'environnement et n'est jamais acceptée en argument.",
        ],
        "limite": (
            "Ce programme ne peut pas empêcher le fournisseur de modifier sa "
            "tarification et de facturer autrement une requête déjà servie ; il peut "
            "seulement le constater dans les en-têtes et s'arrêter."
        ),
    }


@app.command()
def plan(
    sport: str = typer.Option(..., "--sport", help="Une seule clé de compétition v4."),
    bookmaker: str = typer.Option(..., "--bookmaker", help="Un seul bookmaker."),
    max_credits: int = typer.Option(
        ..., "--max-credits", help="Plafond contractuel total, à restituer exactement."
    ),
    window_hours: int = typer.Option(24, "--window-hours", help="Fenêtre, 24 h au maximum."),
    json_output: bool = typer.Option(False, "--json", help="Sortie JSON."),
) -> None:
    """Chiffrer la séquence hors ligne. Aucune socket, aucun secret lu, 0 crédit."""
    try:
        one_sport = _single(sport, "--sport")
        one_book = _single(bookmaker, "--bookmaker")
        hours = _check_window(window_hours)
        if max_credits != TOTAL_MAX_CREDITS:
            raise Refused(
                ActivationStatus.PREPARED_NOT_EXECUTED,
                f"La séquence complète est chiffrée à {TOTAL_MAX_CREDITS} crédits "
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
        f"Plafond total   : {TOTAL_MAX_CREDITS} crédits (tarif publié)",
        "",
    ]
    for step in document["steps"]:
        endpoints = ", ".join(step["endpoints"]) or "aucun"
        bound = step["local_bound"]["max_requests"]
        lines.append(
            f"  {step['command']:<11} {step['max_credits']} crédit(s) · "
            f"{bound} requête(s) au plus  {endpoints}"
        )
        if step["markets"]:
            lines.append(f"              marchés : {', '.join(step['markets'])}")
    lines += [
        "",
        f"Limite : {document['limite']}",
        "",
        "Cette commande n'a rien exécuté et ne dit rien de ce qui l'a été : "
        "l'état réel de l'activation sur cette installation est donné par "
        "`status`. Chaque étape s'autorise séparément et exige le reçu signé de "
        "la précédente.",
    ]
    _emit(document, lines, as_json=json_output)


# ---------------------------------------------------------------------------
# discover — free endpoints only
# ---------------------------------------------------------------------------
def run_discovery(
    attempt: Attempt, settings: Settings, secret: str
) -> tuple[dict[str, Any], ActivationStatus]:
    """The two documented-free endpoints, and nothing else."""
    client = _client(settings, secret, ledger=None)

    attempt.record("/v4/sports")
    catalogue = client.get("sports", params={"all": "false"}, cost=0, billable=False)
    _settle_cost(attempt, catalogue.quota, "/v4/sports")

    entries = catalogue.payload if isinstance(catalogue.payload, list) else []
    descriptor = next(
        (e for e in entries if isinstance(e, dict) and str(e.get("key")) == attempt.sport), None
    )
    if descriptor is None or not descriptor.get("active", True):
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            f"{attempt.sport} n'est pas retournée active par /v4/sports. L'étape s'arrête "
            "ici : interroger une compétition hors saison coûterait un crédit pour rien.",
        )

    endpoint = f"/v4/sports/{attempt.sport}/events"
    attempt.record(endpoint)
    listing = client.get(
        f"sports/{attempt.sport}/events",
        params={
            "dateFormat": "iso",
            "commenceTimeFrom": _iso_z(attempt.window[0]),
            "commenceTimeTo": _iso_z(attempt.window[1]),
        },
        cost=0,
        billable=False,
    )
    _settle_cost(attempt, listing.quota, endpoint)

    attempt.events = [
        {
            "id": str(item["id"]),
            "commence_time": str(item.get("commence_time", "")),
            "home_team": str(item.get("home_team", "")),
            "away_team": str(item.get("away_team", "")),
        }
        for item in _count_the_funnel(attempt, listing.payload)
    ]
    # Deduplicated: a provider repeating an event must not inflate the count.
    attempt.event_tags = list(dict.fromkeys(event_tag(e["id"]) for e in attempt.events))
    attempt.events_admissible = len(attempt.event_tags)
    if not attempt.events:
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            _discovery_reason(attempt),
            build_receipt(attempt, ActivationStatus.COVERAGE_MISSING, secret),
        )
    return build_receipt(attempt, ActivationStatus.DISCOVERY_VERIFIED, secret), (
        ActivationStatus.DISCOVERY_VERIFIED
    )


def _count_the_funnel(attempt: Attempt, payload: Any) -> list[dict[str, Any]]:
    """Record how many events survived each stage, and return the survivors.

    Three integers, because the Ligue 1 attempt could not say which of three
    things had happened: the provider returned nothing; it returned fixtures that
    all fall outside the declared window; or it returned fixtures we refused as
    unusable. Only the first is a calendar fact — the others would point at our
    own filter, and re-running to find out is not consequence-free.

    Integers only, never a per-event breakdown: that would put the schedule back
    into a receipt whose whole point is to carry none of it.
    """
    raw = payload if isinstance(payload, list) else []
    items = [item for item in raw if isinstance(item, dict)]
    attempt.events_returned = len(items)
    in_window = [item for item in items if _inside(item, attempt.window)]
    attempt.events_in_window = len(in_window)
    return [item for item in in_window if str(item.get("id", "")).strip()]


def _discovery_reason(attempt: Attempt) -> str:
    """Say which of the three findings this actually was."""
    if attempt.events_returned == 0:
        return (
            f"/v4/sports/{attempt.sport}/events n'a retourné aucun événement. La réponse "
            "est valide et vide : c'est un fait de calendrier, pas une panne."
        )
    if attempt.events_in_window == 0:
        return (
            f"{attempt.events_returned} événement(s) retourné(s), aucun dans la fenêtre "
            "déclarée. La fenêtre n'est pas élargie automatiquement."
        )
    return (
        f"{attempt.events_in_window} événement(s) dans la fenêtre, aucun exploitable "
        "(identifiant absent ou horaire illisible). Aucun événement n'est deviné."
    )


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
    attempt: Attempt | None = None
    try:
        one_sport = _single(sport, "--sport")
        one_book = _single(bookmaker, "--bookmaker")
        hours = _check_window(window_hours)
        _require_network(allow_network)
        settings = get_settings()
        secret = _require_key(settings)

        now = _clock()
        attempt = Attempt(
            command="discover",
            sport=one_sport,
            bookmaker=one_book,
            window=(now, now + timedelta(hours=hours)),
            ceiling=STEP_CEILINGS["discover"],
            now=now,
        )
        document, status = run_discovery(attempt, settings, secret)
    except Refused as exc:
        _fail(
            exc.status,
            exc.message,
            as_json=json_output,
            secret=secret,
            document=_record_failure(attempt, exc.status, secret),
        )
        return
    except ProviderError as exc:
        status = _status_of(exc)
        if attempt is not None:
            attempt.reached_provider = getattr(exc, "reached_provider", True)
        _fail(
            status,
            str(exc),
            as_json=json_output,
            secret=secret,
            document=_record_failure(attempt, status, secret),
        )
        return

    write_receipt(document)
    document["events"] = attempt.events
    lines = [
        f"Statut          : {document['status']}",
        f"Compétition     : {one_sport}",
        f"Crédits annoncés: {_none(document['observed_credits'])} (plafond 0)",
        f"Événements      : {len(attempt.events)}",
        "",
    ]
    for event in attempt.events:
        lines.append(
            f"  {event['id']}  {event['commence_time']}  "
            f"{event['home_team']} - {event['away_team']}"
        )
    lines += [
        "",
        f"Reçu            : {document['_path']}",
        "",
        "Choisissez UN identifiant, puis relancez `core --event-id <id> "
        "--discovery-receipt <ce reçu>`. Aucune sélection n'est faite pour vous.",
    ]
    _finish(document, lines, as_json=json_output, secret=secret, ok=status in VERIFIED_STATUSES)


def _record_failure(
    attempt: Attempt | None, status: ActivationStatus, secret: str
) -> dict[str, Any] | None:
    """Write the audit trail for an attempt that reached the wire and then failed.

    Nothing is written when the network was never touched: a consumption record
    for a call that never happened is a fabrication, the same error as losing the
    record of one that did.
    """
    if attempt is None or not attempt.network_attempted:
        return None
    document = build_receipt(attempt, status, secret)
    write_receipt(document)
    return document


# ---------------------------------------------------------------------------
# core — one event, one bookmaker, one market, one credit
# ---------------------------------------------------------------------------
def run_core(
    attempt: Attempt, settings: Settings, secret: str, parent: dict[str, Any]
) -> tuple[dict[str, Any], ActivationStatus]:
    """One grouped request, filtered to one event. One credit at the published tariff."""
    event_id = str(attempt.event_id)
    ledger = ProviderBudgetLedger(settings)
    client = _client(settings, secret, ledger=ledger)

    units = effective_region_units(bookmakers=[attempt.bookmaker], regions=None)
    attempt.estimated = estimate_cost(markets=len(CORE_MARKETS), region_units=units)
    attempt.markets_requested = list(CORE_MARKETS)
    attempt.parent_receipt_id = str(parent["receipt_id"])
    attempt.parent_schema_version = int(parent["schema_version"])
    if attempt.estimated > attempt.ceiling:
        raise Refused(
            ActivationStatus.COST_MISMATCH,
            f"L'estimation ({attempt.estimated}) dépasse le plafond ({attempt.ceiling}) "
            "— appel non tenté.",
        )

    endpoint = f"/v4/sports/{attempt.sport}/odds"
    attempt.record(endpoint)
    response = client.get(
        f"sports/{attempt.sport}/odds",
        params={
            "eventIds": event_id,
            "markets": ",".join(CORE_MARKETS),
            "bookmakers": attempt.bookmaker,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        },
        cost=attempt.estimated,
    )
    _settle_cost(attempt, response.quota, endpoint)

    raw_event = _event_of(response.payload, event_id, endpoint)
    _check_start_time(raw_event, attempt.window)

    # The bookmaker's state is recorded, and every requested market classified,
    # *before* anything stops. That ordering is the whole of E1: the previous
    # version raised on an absent bookmaker and wrote a receipt whose market map
    # was empty, which reads as "we looked and nothing was missing".
    book = _observe_bookmaker(attempt, raw_event, CORE_MARKETS)
    if book is None:
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            f"{endpoint} : {attempt.bookmaker} n'est pas coté sur cet événement — bookmaker "
            "non retourné, marché non évalué. Une réponse valide sans le bookmaker demandé "
            "est une couverture manquante, pas une panne.",
            build_receipt(attempt, ActivationStatus.COVERAGE_MISSING, secret),
        )

    batch = _parse_with_the_real_parser(
        settings,
        client,
        raw_event,
        window=attempt.window,
        now=attempt.now,
        shape=ResponseShape.GROUPED_ODDS,
    )
    attempt.freshness = _freshness(book, ResponseShape.GROUPED_ODDS, attempt.now)
    attempt.market_states = _classify_markets(CORE_MARKETS, book, batch)
    attempt.selections_mapped = len(batch.snapshots)
    attempt.rejections = [_generalise(e) for e in batch.partial_errors]

    if not batch.snapshots:
        raise Refused(
            ActivationStatus.SCHEMA_MISMATCH,
            "Le bookmaker est présent mais le parseur n'a retenu aucune sélection : "
            f"{'; '.join(attempt.rejections) or 'aucun détail'}.",
            build_receipt(attempt, ActivationStatus.SCHEMA_MISMATCH, secret),
        )
    return build_receipt(attempt, ActivationStatus.CORE_LIVE_VERIFIED, secret), (
        ActivationStatus.CORE_LIVE_VERIFIED
    )


def _observe_bookmaker(
    attempt: Attempt, raw_event: dict[str, Any], requested: tuple[str, ...]
) -> dict[str, Any] | None:
    """Record the bookmaker's state and a total market map, then hand back the block.

    Called before any early exit so the receipt is complete on every path. When
    the block is missing, every requested market is marked
    ``NOT_EVALUATED_BOOKMAKER_ABSENT`` rather than left out of the map.
    """
    book = _book_of(raw_event, attempt.bookmaker)
    attempt.bookmaker_state = str(
        BookmakerState.OBSERVED if book is not None else BookmakerState.NOT_RETURNED
    )
    attempt.market_states = _classify_markets(requested, book, None)
    return book


@app.command()
def core(
    sport: str = typer.Option(..., "--sport"),
    bookmaker: str = typer.Option(..., "--bookmaker"),
    event_id: str = typer.Option(..., "--event-id"),
    discovery_receipt: str = typer.Option(
        ..., "--discovery-receipt", help="Chemin du reçu émis par `discover`."
    ),
    max_credits: int = typer.Option(..., "--max-credits"),
    acknowledge_credits: int = typer.Option(None, "--acknowledge-credits"),
    window_hours: int = typer.Option(24, "--window-hours"),
    allow_network: bool = typer.Option(False, "--allow-network"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Un seul événement, un seul marché, un seul bookmaker. 1 crédit au tarif publié."""
    secret = ""
    attempt: Attempt | None = None
    try:
        one_sport = _single(sport, "--sport")
        one_book = _single(bookmaker, "--bookmaker")
        one_event = _single(event_id, "--event-id")
        hours = _check_window(window_hours)
        ceiling = _check_ceiling("core", max_credits, acknowledge_credits)
        _require_network(allow_network)
        settings = get_settings()
        secret = _require_key(settings)

        now = _clock()
        parent = load_parent(
            discovery_receipt,
            command="discover",
            status=ActivationStatus.DISCOVERY_VERIFIED,
            sport=one_sport,
            bookmaker=one_book,
            now=now,
        )
        _check_discovery(parent, one_event, discovery_receipt)

        attempt = Attempt(
            command="core",
            sport=one_sport,
            bookmaker=one_book,
            window=(now, now + timedelta(hours=hours)),
            ceiling=ceiling,
            now=now,
            event_id=one_event,
            event_tags=[event_tag(one_event)],
        )
        document, status = run_core(attempt, settings, secret, parent)
    except Refused as exc:
        _fail(
            exc.status,
            exc.message,
            as_json=json_output,
            secret=secret,
            document=_record_failure(attempt, exc.status, secret),
        )
        return
    except ProviderError as exc:
        status = _status_of(exc)
        if attempt is not None:
            attempt.reached_provider = getattr(exc, "reached_provider", True)
        _fail(
            status,
            str(exc),
            as_json=json_output,
            secret=secret,
            document=_record_failure(attempt, status, secret),
        )
        return

    write_receipt(document)
    _finish(
        document,
        [
            *_summary(document),
            "",
            "Étape suivante possible : `additional --core-receipt "
            f"{document['_path']}` (5 crédits, autorisation distincte).",
        ],
        as_json=json_output,
        secret=secret,
        ok=status in VERIFIED_STATUSES,
    )


def _check_discovery(parent: dict[str, Any], event_id: str, label: str) -> None:
    """The discovery must actually have approved *this* event, at nil cost."""
    tags = parent.get("event_tags")
    if not isinstance(tags, list) or event_tag(event_id) not in tags:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{label} n'a pas retenu cet événement. `core` ne facture que ce qu'une "
            "découverte approuvée a listé ; relancez `discover` si la fenêtre a bougé.",
        )
    if parent.get("observed_credits") != 0:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{label} n'atteste pas un coût observé nul "
            f"({parent.get('observed_credits')!r}). Une découverte dont le coût n'a pas "
            "été prouvé n'autorise aucune dépense.",
        )
    remaining = parent.get("quota_remaining")
    if isinstance(remaining, int) and remaining < STEP_CEILINGS["core"]:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{label} indique {remaining} crédit(s) restant(s), insuffisant pour "
            f"les {STEP_CEILINGS['core']} du présent appel.",
        )


# ---------------------------------------------------------------------------
# additional — same event, five markets, five credits
# ---------------------------------------------------------------------------
def run_additional(
    attempt: Attempt, settings: Settings, secret: str, parent: dict[str, Any]
) -> tuple[dict[str, Any], ActivationStatus]:
    """The per-event markets, classified one by one."""
    event_id = str(attempt.event_id)
    ledger = ProviderBudgetLedger(settings)
    client = _client(settings, secret, ledger=ledger)

    units = effective_region_units(bookmakers=[attempt.bookmaker], regions=None)
    attempt.estimated = estimate_cost(markets=len(ADDITIONAL_MARKETS), region_units=units)
    attempt.markets_requested = list(ADDITIONAL_MARKETS)
    attempt.parent_receipt_id = str(parent["receipt_id"])
    attempt.parent_schema_version = int(parent["schema_version"])
    if attempt.estimated > attempt.ceiling:
        raise Refused(
            ActivationStatus.COST_MISMATCH,
            f"L'estimation ({attempt.estimated}) dépasse le plafond ({attempt.ceiling}) "
            "— appel non tenté.",
        )

    endpoint = f"/v4/sports/{attempt.sport}/events/<event>/odds"
    attempt.record(endpoint)
    response = client.get(
        f"sports/{attempt.sport}/events/{event_id}/odds",
        params={
            "markets": ",".join(ADDITIONAL_MARKETS),
            "bookmakers": attempt.bookmaker,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        },
        cost=attempt.estimated,
    )
    _settle_cost(attempt, response.quota, endpoint)

    raw_event = _event_of(response.payload, event_id, endpoint)
    _check_start_time(raw_event, attempt.window)

    book = _observe_bookmaker(attempt, raw_event, ADDITIONAL_MARKETS)
    if book is None:
        raise Refused(
            ActivationStatus.COVERAGE_MISSING,
            f"{endpoint} : {attempt.bookmaker} n'est pas coté sur cet événement — bookmaker "
            "non retourné, aucun des cinq marchés n'est évalué.",
            build_receipt(attempt, ActivationStatus.COVERAGE_MISSING, secret),
        )

    batch = _parse_with_the_real_parser(
        settings,
        client,
        raw_event,
        window=attempt.window,
        now=attempt.now,
        shape=ResponseShape.EVENT_ODDS,
    )
    attempt.freshness = _freshness(book, ResponseShape.EVENT_ODDS, attempt.now)
    attempt.market_states = _classify_markets(ADDITIONAL_MARKETS, book, batch)
    attempt.selections_mapped = len(batch.snapshots)
    attempt.rejections = [_generalise(e) for e in batch.partial_errors]

    status = _additional_status(attempt.market_states)
    document = build_receipt(attempt, status, secret)
    if status not in VERIFIED_STATUSES:
        raise Refused(status, _additional_reason(status), document)
    return document, status


def _additional_status(states: dict[str, str]) -> ActivationStatus:
    """Absence, rejection and success are three answers, not one.

    Nothing returned is a coverage fact about the bookmaker. Everything returned
    and nothing usable is a fact about the contract or our parser. Some of each is
    genuinely partial, and saying so is more useful than rounding it to either
    end. A market never evaluated is none of those, and is handled before this
    function is reached.
    """
    values = list(states.values())
    if all(state == MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT for state in values):
        return ActivationStatus.COVERAGE_MISSING
    if all(state == MarketState.NOT_RETURNED for state in values):
        return ActivationStatus.COVERAGE_MISSING
    if not any(state == MarketState.OBSERVED_MAPPED for state in values):
        return ActivationStatus.SCHEMA_MISMATCH
    if all(state == MarketState.OBSERVED_MAPPED for state in values):
        return ActivationStatus.ADDITIONAL_LIVE_VERIFIED
    return ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE


def _additional_reason(status: ActivationStatus) -> str:
    if status is ActivationStatus.COVERAGE_MISSING:
        return (
            "Le bookmaker est coté sur cet événement mais aucun des marchés demandés "
            "n'est revenu. Rien n'est compensé, rien n'est réessayé, aucun autre "
            "bookmaker n'est substitué."
        )
    return (
        "Des marchés sont revenus mais aucun n'a produit de sélection cartographiée : "
        "horodatage au niveau marché absent, ou structure inattendue."
    )


@app.command()
def additional(
    sport: str = typer.Option(..., "--sport"),
    bookmaker: str = typer.Option(..., "--bookmaker"),
    event_id: str = typer.Option(..., "--event-id"),
    core_receipt: str = typer.Option(..., "--core-receipt", help="Chemin du reçu émis par `core`."),
    max_credits: int = typer.Option(..., "--max-credits"),
    acknowledge_credits: int = typer.Option(None, "--acknowledge-credits"),
    window_hours: int = typer.Option(24, "--window-hours"),
    allow_network: bool = typer.Option(False, "--allow-network"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Les cinq marchés par événement, sur l'événement déjà prouvé. 5 crédits au plus."""
    secret = ""
    attempt: Attempt | None = None
    try:
        one_sport = _single(sport, "--sport")
        one_book = _single(bookmaker, "--bookmaker")
        one_event = _single(event_id, "--event-id")
        hours = _check_window(window_hours)
        ceiling = _check_ceiling("additional", max_credits, acknowledge_credits)
        _require_network(allow_network)
        settings = get_settings()
        secret = _require_key(settings)

        now = _clock()
        parent = load_parent(
            core_receipt,
            command="core",
            status=ActivationStatus.CORE_LIVE_VERIFIED,
            sport=one_sport,
            bookmaker=one_book,
            now=now,
        )
        _check_core(parent, one_event, core_receipt)

        attempt = Attempt(
            command="additional",
            sport=one_sport,
            bookmaker=one_book,
            window=(now, now + timedelta(hours=hours)),
            ceiling=ceiling,
            now=now,
            event_id=one_event,
            event_tags=[event_tag(one_event)],
        )
        document, status = run_additional(attempt, settings, secret, parent)
    except Refused as exc:
        recorded = (
            exc.document
            if exc.document is not None
            else _record_failure(attempt, exc.status, secret)
        )
        if exc.document is not None:
            write_receipt(exc.document)
        _fail(exc.status, exc.message, as_json=json_output, secret=secret, document=recorded)
        return
    except ProviderError as exc:
        status = _status_of(exc)
        if attempt is not None:
            attempt.reached_provider = getattr(exc, "reached_provider", True)
        _fail(
            status,
            str(exc),
            as_json=json_output,
            secret=secret,
            document=_record_failure(attempt, status, secret),
        )
        return

    write_receipt(document)
    _finish(document, _summary(document), as_json=json_output, secret=secret, ok=True)


def _check_core(parent: dict[str, Any], event_id: str, label: str) -> None:
    """Five credits are committed only on a proof that one already worked."""
    if parent.get("event_tag") != event_tag(event_id):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{label} porte sur un autre événement. Une preuve ne se transpose pas d'une "
            "rencontre à une autre.",
        )
    if not parent.get("parent_receipt_id"):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{label} ne référence aucune découverte. La chaîne doit être complète : "
            "`discover` puis `core` puis `additional`.",
        )
    if not isinstance(parent.get("selections_mapped"), int) or parent["selections_mapped"] < 1:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{label} n'atteste aucune sélection h2h cartographiée. Rien ne prouve que le "
            "parseur lira la réponse par événement.",
        )
    observed = parent.get("observed_credits")
    accounted = parent.get("accounted_credits")
    if not isinstance(observed, int) or observed > STEP_CEILINGS["core"]:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{label} n'atteste pas un coût observé compatible avec le plafond de "
            f"{STEP_CEILINGS['core']} crédit ({observed!r}).",
        )
    if not isinstance(accounted, int) or accounted > STEP_CEILINGS["core"]:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{label} comptabilise {accounted!r} crédit(s), au-delà du plafond de "
            f"{STEP_CEILINGS['core']}.",
        )


# ---------------------------------------------------------------------------
# status — what has actually happened, in five separate dimensions
# ---------------------------------------------------------------------------
def audit_receipts() -> tuple[list[dict[str, Any]], int]:
    """Every locally verifiable receipt, and how many failed verification.

    Read-only, and deliberately **not** a source of authority: nothing here is
    ever passed to :func:`load_parent`. A step is authorised by a receipt the
    operator names on the command line, never by one this function happened to
    find. Reporting and authorising are different jobs, and conflating them is
    what let ``additional`` pick its own proof out of a writable directory.

    A file that fails signature or schema verification is counted, not read: it
    must neither become evidence nor vanish silently.
    """
    directory = receipt_dir()
    if not directory.is_dir():
        return [], 0
    verified: list[dict[str, Any]] = []
    unverifiable = 0
    for path in sorted(directory.glob("*.json")):
        try:
            payload = jsonlib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unverifiable += 1
            continue
        if not isinstance(payload, dict):
            unverifiable += 1
            continue
        if payload.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
            unverifiable += 1
            continue
        if not verify_receipt(payload):
            unverifiable += 1
            continue
        payload["_path"] = str(path)
        verified.append(payload)
    return verified, unverifiable


def build_activation_state(receipts: list[dict[str, Any]], unverifiable: int) -> dict[str, Any]:
    """Five dimensions, reported separately because they are separate facts.

    One label cannot carry them. Two real ``core`` calls proved connectivity,
    authentication and billing while proving nothing at all about the parser, and
    found no coverage on the two events they looked at. Condensing that into a
    single word loses whichever part the reader needed — and
    ``PREPARED_NOT_EXECUTED`` in particular became simply false.
    """
    attempted = [r for r in receipts if r.get("network_attempted")]
    paid = [r for r in attempted if r.get("command") in ("core", "additional")]
    statuses = {str(r.get("status")) for r in paid}

    execution = ExecutionState.NO_NETWORK_ATTEMPTED
    if any(r.get("command") == "additional" for r in paid):
        execution = ExecutionState.ADDITIONAL_ATTEMPTED
    elif any(r.get("command") == "core" for r in paid):
        execution = ExecutionState.CORE_ATTEMPTED
    elif attempted:
        execution = ExecutionState.DISCOVERY_ATTEMPTED

    if not attempted:
        cost_proof = CostProof.NOT_EXERCISED
    elif statuses & {
        str(ActivationStatus.COST_MISMATCH),
        str(ActivationStatus.COST_UNVERIFIED),
    }:
        cost_proof = CostProof.EXERCISED_NONCONFORMING
    else:
        cost_proof = CostProof.EXERCISED_CONFORMING

    mapped_live = any(int(r.get("selections_mapped") or 0) > 0 for r in paid)
    mapping_proof = MappingProof.OBTAINED_LIVE if mapped_live else MappingProof.NOT_OBTAINED_LIVE

    if not paid:
        paid_state = PaidActivationState.PREPARED_NOT_EXECUTED
    elif any(r.get("command") == "additional" for r in paid):
        paid_state = PaidActivationState.ADDITIONAL_EXECUTED
    elif mapped_live:
        paid_state = PaidActivationState.CORE_EXECUTED_COVERAGE_OBSERVED
    else:
        paid_state = PaidActivationState.CORE_EXECUTED_NO_COVERAGE

    return {
        # 1. The adapter itself. A ponctual observation never promotes it.
        "adapter_state": "IMPLEMENTED_UNVERIFIED",
        # 2. How far the sequence has gone here.
        "execution_state": str(execution),
        # 3. Connectivity, authentication and billing.
        "connectivity_and_cost_proof": str(cost_proof),
        # 4. Coverage — a list of scoped observations, never a verdict.
        "bookmaker_coverage_observations": [
            {
                "sport_key": r.get("sport_key", ""),
                "bookmaker": r.get("bookmaker", ""),
                "event_tag": r.get("event_tag") or "",
                "recorded_at": r.get("recorded_at", ""),
                "bookmaker_state": r.get("bookmaker_state") or "UNKNOWN_SCHEMA_V2",
                "market_states": r.get("market_states") or {},
                "status": str(r.get("status")),
                "schema_version": r.get("schema_version"),
            }
            for r in paid
        ],
        # 5. Whether the parser and freshness path have been exercised for real.
        "mapping_freshness_proof": str(mapping_proof),
        "paid_activation_state": str(paid_state),
        "accounted_credits_total": sum(int(r.get("accounted_credits") or 0) for r in receipts),
        "verified_receipts": len(receipts),
        "unverifiable_receipts": unverifiable,
        "receipt_directory": str(receipt_dir()),
        "scope_note": (
            "Chaque observation de couverture vaut pour un fournisseur, un bookmaker, "
            "une compétition, un événement tagué, un marché et un instant — rien de plus."
        ),
        "model_impact": "aucun — tous les modèles restent BACKTEST_ONLY",
    }


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Lire l'état réel de l'activation sur cette installation. Aucun réseau."""
    receipts, unverifiable = audit_receipts()
    document = build_activation_state(receipts, unverifiable)
    lines = [
        f"Adaptateur          : {document['adapter_state']}",
        f"Exécution           : {document['execution_state']}",
        f"Connectivité + coût : {document['connectivity_and_cost_proof']}",
        f"Mapping + fraîcheur : {document['mapping_freshness_proof']}",
        f"Activation payante  : {document['paid_activation_state']}",
        f"Crédits comptés     : {document['accounted_credits_total']}",
        f"Reçus vérifiés      : {document['verified_receipts']}"
        f" · non vérifiables : {document['unverifiable_receipts']}",
        # A local path, printed as a path. It is gitignored and has no remote.
        f"Répertoire (local)  : {document['receipt_directory']}",
        "",
    ]
    if document["bookmaker_coverage_observations"]:
        lines.append("Observations de couverture (portée stricte) :")
        for one in document["bookmaker_coverage_observations"]:
            lines.append(
                f"  · {one['recorded_at']}  {one['sport_key']}  {one['bookmaker']}  "
                f"événement {one['event_tag'][:12]}…  {one['bookmaker_state']}  "
                f"→ {one['status']}"
            )
    else:
        lines.append("Aucune observation de couverture enregistrée.")
    lines += ["", document["scope_note"], f"Modèles : {document['model_impact']}."]
    _emit(document, lines, as_json=json_output)


def _iso_z(moment: datetime) -> str:
    return ensure_utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":  # pragma: no cover - manual entry point
    app()
