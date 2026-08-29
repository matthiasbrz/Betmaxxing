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
Each step is authorised by the previous step's **receipt**, **named** by the
operator — never discovered by scanning a directory, which would be the program
choosing its own proof. Receipts are signed with a local HMAC secret over their
canonical JSON, carry HMAC-tagged event ids rather than clear ones, expire, and
reference their parent. A receipt that is unsigned, altered, expired, of the wrong
schema, or about a different sport, bookmaker or event is refused before the
network.

Since protocol 7, that name is reduced **textually** to a base name of the
authorised receipt directory and read through the same descriptor as the audit.
Until then :func:`load_parent` — the gate in front of both paid commands — took
every one of its decisions through ``pathlib``, including a ``resolve()`` that
follows the very symbolic links the store refuses: with the receipt directory a
link, :func:`audit_receipts` reported an empty installation while this function
authorised a paid call out of the link's target. One reader being safe proved
nothing about the other.

:func:`audit_receipts` returns an :class:`~.receipt_store.AuditResult`, and it
does not unpack into two values. It carries the boundary state as well as the
counts, because ``except StoreRefused: return (), 0`` gave an unreadable receipt
directory the same answer as a clean empty one — and ``UNAVAILABLE`` has to reach
the operator, not be rounded off to « nothing here ».

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

import contextlib
import hashlib
import hmac
import json as jsonlib
import os
import secrets
import stat as statmodule
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
import typer

from betmaxxing.config import (
    BOOKMAKERS_VARIABLE,
    Settings,
    configured_bookmakers,
    get_settings,
)
from betmaxxing.domain.enums import Sport
from betmaxxing.domain.timeutil import ensure_utc, utc_now
from betmaxxing.providers.base import CollectionBatch, ProviderError, QuotaInfo
from betmaxxing.providers.budget import ProviderBudgetLedger
from betmaxxing.providers.the_odds_api import receipt_store
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

#: The command that performs the documented recovery. Named here so the refusal
#: message and the CLI cannot drift apart: v5 told the operator to call a function
#: no command exposed, which made the only documented way out unrunnable.
QUARANTINE_COMMAND = "python -m betmaxxing.providers.the_odds_api.activation receipts quarantine"

#: The local signing secret. Generated on first network need, never printed,
#: never committed. Overridable by environment so tests are deterministic and no
#: test ever leaves a real secret on disk.
SECRET_FILENAME = "signing-key.secret"
SECRET_VARIABLE = receipt_store.SECRET_ENVIRONMENT_VARIABLE

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
#:
#: v4 adds ``qualification_protocol_version`` and
#: ``provider_adapter_evidence_version``, both covered by the signature. It is a
#: new version rather than v3 with extra fields because their *absence* is
#: meaningful: a v3 receipt cannot say which protocol judged it or which parser
#: produced it, so it cannot be current qualification evidence. See D-072.
RECEIPT_SCHEMA_VERSION = 4

#: v2 and v3 receipts already on an operator's disk stay usable as authority.
#: Every field the chain actually depends on — ``event_tags``, ``event_tag``,
#: ``observed_credits``, ``accounted_credits``, ``selections_mapped``,
#: ``parent_receipt_id``, ``expires_at`` — has the same meaning in all three
#: versions; only ``market_states`` and its projections changed at v3, and only
#: the two version stamps arrived at v4. None of those are preconditions, so a
#: valid v2 or v3 receipt is read, verified and honoured for chaining, never
#: rewritten and never re-signed. Whether it *qualifies* anything is a different
#: question, answered by the protocol and not here. Anything outside this set is
#: refused.
SUPPORTED_SCHEMA_VERSIONS = frozenset({2, 3, RECEIPT_SCHEMA_VERSION})

SIGNATURE_FIELD = "signature"


def _reported_int(value: object) -> int:
    """A signed receipt's field read as an integer for **reporting**, or zero.

    The audit block summarises whatever is on disk, including a receipt whose
    signature is ours but whose types are not what we write. `int()` on such a
    field raised out of `status`; a report that cannot be produced is worse than a
    report that says zero, and the qualification block — which decides things —
    reads the same fields strictly and refuses them.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _counted_credits(value: object) -> int:
    """A credit count that really is one, else zero — for totalling only.

    Distinct from :func:`_reported_int`, which is about not crashing on a mistyped
    field. This one is about not *adding* a mistyped field: a boolean, a numeric
    string and a negative number are all refused rather than coerced, because the
    sum is a spend figure an operator reads before deciding to spend more.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _schema_version_of(payload: Mapping[str, Any]) -> int | None:
    """The receipt's schema version when it is one we read, else ``None``.

    A JSON file can carry anything under ``schema_version`` — a mapping, a list, a
    boolean, a float, a string. Testing such a value for membership in a frozenset
    hashes it, and an unhashable one raised ``TypeError`` out of the audit and out
    of `status`. A version is a real integer or it is not a version.
    """
    version = payload.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    return version if version in SUPPORTED_SCHEMA_VERSIONS else None


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
    """How far the activation has actually gone, on this installation.

    ``NETWORK_ATTEMPT_STATE_UNESTABLISHED`` is what the enum was missing. A receipt
    whose ``network_attempted`` is absent or mistyped establishes neither that a
    request was issued nor that none was, and v4 reported ``CORE_ATTEMPTED`` for it —
    an affirmative fact read off a field that said nothing (D-075).
    """

    NO_NETWORK_ATTEMPTED = "NO_NETWORK_ATTEMPTED"
    NETWORK_ATTEMPT_STATE_UNESTABLISHED = "NETWORK_ATTEMPT_STATE_UNESTABLISHED"
    DISCOVERY_ATTEMPTED = "DISCOVERY_ATTEMPTED"
    CORE_ATTEMPTED = "CORE_ATTEMPTED"
    ADDITIONAL_ATTEMPTED = "ADDITIONAL_ATTEMPTED"


class PaidActivationState(StrEnum):
    """The paid dimension only. Separate from coverage and from mapping.

    ``PAID_ATTEMPT_INCONCLUSIVE`` is the state this enum was missing. A paid call
    that really went out but established neither coverage nor mapping — because its
    receipt is malformed, contradictory, or an error that never reached a market —
    is not "executed with no coverage": that phrase claims we looked and the
    bookmaker was absent. Rounding it down to the nearest existing label is how
    ``selections_mapped = "3"`` came to read as an observed coverage.
    """

    #: No paid step was attempted, and every receipt says so exactly.
    PREPARED_NOT_EXECUTED = "PREPARED_NOT_EXECUTED"
    #: A paid receipt exists whose attempt state cannot be established. Blocking, and
    #: never described as executed.
    PAID_ATTEMPT_STATE_UNESTABLISHED = "PAID_ATTEMPT_STATE_UNESTABLISHED"
    #: A paid request was confirmed issued and established neither coverage nor mapping.
    PAID_ATTEMPT_INCONCLUSIVE = "PAID_ATTEMPT_INCONCLUSIVE"
    #: A `core` call answered the bookmaker question, and the answer was an absence.
    CORE_EXECUTED_NO_COVERAGE = "CORE_EXECUTED_NO_COVERAGE"
    #: A `core` call produced a sound mapping observation.
    CORE_EXECUTED_COVERAGE_OBSERVED = "CORE_EXECUTED_COVERAGE_OBSERVED"
    #: An `additional` call **established** coverage or mapping. Not "an additional
    #: receipt exists": under v4 the mere presence of one forced this label, so an
    #: `additional/AUTH_FAILED` reported an executed step (D-075).
    ADDITIONAL_EXECUTED = "ADDITIONAL_EXECUTED"


class CostProof(StrEnum):
    """Whether connectivity and billing have been exercised, and conformingly.

    ``EXERCISED_UNESTABLISHED`` is distinct from both ends on purpose. A paid call
    whose cost cannot be established is not conforming — the whole point of the
    ``COST_CONFORMITY`` criterion is that an unestablished cost fails it — and it is
    not a mismatch either, because nothing was shown to disagree. Before v4 this
    dimension had nowhere to put it and reported ``EXERCISED_CONFORMING`` while the
    strict block counted the same call under
    ``paid_calls_with_unestablished_cost``.

    The precedence, applied over every real paid attempt::

        NONCONFORMING > UNESTABLISHED > CONFORMING > NOT_EXERCISED
    """

    NOT_EXERCISED = "NOT_EXERCISED"
    EXERCISED_CONFORMING = "EXERCISED_CONFORMING"
    EXERCISED_UNESTABLISHED = "EXERCISED_UNESTABLISHED"
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


# ---------------------------------------------------------------------------
# The signing secret — one format, two verbs
# ---------------------------------------------------------------------------
#: Re-exported so callers keep one vocabulary for the boundary's refusals. The
#: provenance *types* are re-exported too, deliberately: naming them is useful, and
#: since protocol 7 naming them is all a caller can do — none of the three can be
#: constructed, so an alias hands out nothing an audit did not produce.
StoreRefused = receipt_store.StoreRefused
SecretInvalid = receipt_store.SecretInvalid
SecretMissing = receipt_store.SecretMissing
DirectoryUnsafe = receipt_store.DirectoryUnsafe
DirectoryAbsent = receipt_store.DirectoryAbsent
ContentUndecodable = receipt_store.ContentUndecodable
CountInvalid = receipt_store.CountInvalid
IntentInvalid = receipt_store.IntentInvalid
PersistenceFailed = receipt_store.PersistenceFailed
UnverifiedProvenance = receipt_store.UnverifiedProvenance
VerifiedReceipt = receipt_store.VerifiedReceipt
VerifiedReceiptBatch = receipt_store.VerifiedReceiptBatch
AuditResult = receipt_store.AuditResult
BoundaryState = receipt_store.BoundaryState
SECRET_HEX_LENGTH = receipt_store.SECRET_HEX_LENGTH
INTENT_SUFFIX = receipt_store.INTENT_SUFFIX
INTENT_INVALID_STATE = receipt_store.INTENT_INVALID_STATE

validate_secret_text = receipt_store.validate_secret_text
new_secret_text = receipt_store.new_secret_text


@contextlib.contextmanager
def receipt_directory(*, create: bool = False) -> Iterator[receipt_store.SecureDirectory]:
    """The receipt directory, opened once, safely, for the whole operation.

    Every read and every write of this module goes through here. ``create`` is the
    only difference between a reporting path and a path that is about to sign
    something: ``status`` must never bring a directory — or a secret — into
    existence just by looking.
    """
    with receipt_store.SecureDirectory.open(receipt_dir(), create=create) as directory:
        yield directory


def load_receipt_secret() -> str:
    """The local signing secret, strictly validated, never created.

    One policy, implemented once, in :func:`receipt_store.installation_secret`: the
    variable when it is **set at all**, otherwise the file. Protocol 7 closed the gap
    v6 left here — ``BETMAXXING_ACTIVATION_RECEIPT_SECRET=""`` used to read as « not
    configured » and fall through to the file, while ``"   "`` was refused, so two
    spellings of nothing meant two different things and neither was written down. A
    variable that is present is a configured value, and an invalid configured value is
    a refusal.

    Nothing here repairs, rotates or rewrites: an invalid secret already on disk fails
    closed, because regenerating it would quietly turn every receipt signed with it
    into noise.
    """
    configured = receipt_store.injected_secret()
    if configured is not None:
        return configured
    with receipt_directory() as directory:
        return receipt_store.load_secret(directory, SECRET_FILENAME)


def ensure_receipt_secret() -> str:
    """The local signing secret, created atomically if this installation has none.

    Only ever called on a path that is about to *sign* something. Created bytes-first
    then published under the final name, so no crash and no race can leave a name
    that exists and is empty — which is exactly what an interrupted first run used to
    leave, and what every later run then accepted as an empty key.
    """
    configured = receipt_store.injected_secret()
    if configured is not None:
        return configured
    with receipt_directory(create=True) as directory:
        return receipt_store.ensure_secret(directory, SECRET_FILENAME)


#: The name the rest of the module used before the two verbs were separated. It
#: means "make sure there is one, because I am about to sign".
receipt_secret = ensure_receipt_secret


def event_tag(event_id: str, secret: str) -> str:
    """Stable local tag for a provider event id.

    HMAC rather than a bare digest. A plain ``sha256(event_id)`` is computable by
    anyone holding the provider's public fixture list, so it hid nothing; keyed with a
    secret that never leaves this installation, it identifies the event to *us* —
    enough for ``core`` to recognise ``discover``'s approval across processes —
    without being reversible by a dictionary of public ids.

    The secret is a parameter. It used to be fetched from the ambient environment,
    which is how a function documented as pure ended up creating a key file.
    """
    digest = hmac.new(
        validate_secret_text(secret).encode("utf-8"), f"event:{event_id}".encode(), hashlib.sha256
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
    """The exact bytes a signature covers. See :mod:`receipt_store`."""
    return receipt_store.canonical_bytes(payload, signature_field=SIGNATURE_FIELD)


def sign_receipt(payload: Mapping[str, Any], secret: str) -> str:
    """Sign with the secret the caller holds.

    Explicit, since v6. While the secret was an implicit lookup, every reader of a
    receipt — including the qualification evaluator, which documented itself as pure
    — could reach the environment and create a key file just by checking a signature.
    """
    return receipt_store.sign(payload, secret=secret, signature_field=SIGNATURE_FIELD)


def verify_receipt(payload: Mapping[str, Any], secret: str) -> bool:
    """Constant-time signature check against an explicitly supplied secret."""
    return receipt_store.verify(payload, secret=secret, signature_field=SIGNATURE_FIELD)


def _name_component(value: object, field: str) -> str:
    """One validated component of a receipt filename.

    A filename is built from three pieces of a document, and a document is data. A
    ``recorded_at`` of ``"../../2026-08-11T12:00:00+00:00"`` used to survive the
    string slice below as ``"../../20260811T"`` and put the receipt two directories
    above the one it belongs in. So each component is checked to be a plain name
    before it is joined to anything.
    """
    if not isinstance(value, str) or not value.strip():
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{field} doit être une chaîne non vide pour nommer un reçu.",
        )
    if value in {".", ".."} or set(value) & {"/", "\\", "\0"}:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{field} contient un séparateur de chemin : un reçu est nommé, pas placé. "
            "Aucun fichier n'est écrit hors du répertoire de reçus.",
        )
    return value


QUARANTINE_SUFFIX = ".incomplete"
#: How many suffixes a quarantine will try before giving up. Bounded on purpose: an
#: unbounded retry is a spin, and a silent overwrite is what it replaces.
QUARANTINE_ATTEMPTS = 8


def _check_quarantine_scope(name: str) -> None:
    """The recovery command touches receipts, and nothing else.

    Four refusals, each naming what it protects: the root of trust, the journal of
    attempts, a publication in progress, and anything that is not a receipt at all.
    None of them is negotiable with ``--force``, which exists only to archive a
    *complete signed receipt* the operator has decided to set aside.
    """
    checked = receipt_store._check_name(name)
    if checked == SECRET_FILENAME:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Le secret de signature n'est pas un reçu et ne se met pas de côté : le "
            "déplacer rendrait invérifiable chaque reçu déjà signé. Aucune option ne "
            "l'autorise.",
        )
    if checked.endswith(receipt_store.INTENT_SUFFIX):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Un intent n'est pas un reçu et ne se met pas de côté : il est la seule "
            "trace qu'une requête a pu partir, et le faire disparaître supprimerait un "
            "conflit sans le résoudre. Publiez le reçu correspondant, ou traitez le "
            "conflit ; aucune option ne l'autorise.",
        )
    if checked.startswith(".") or checked.endswith(".tmp"):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Un temporaire de publication n'est pas un reçu et ne se met pas de côté ; "
            "il est nettoyé par la publication elle-même.",
        )
    if not checked.endswith(".json"):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Cette commande met de côté un reçu `*.json` du répertoire de reçus, et rien d'autre.",
        )


def quarantine_in(
    directory: receipt_store.SecureDirectory, name: str, *, force: bool = False
) -> str:
    """Move one **name** of this directory aside, keeping every byte.

    The recovery path v4 had no answer for. An interruption after the exclusive create
    left a zero-byte file, and the next attempt at the *same* receipt was refused for
    ever under "already exists with different signed content" — which was false, and
    which permanently made the proof of a real paid call unrecordable.

    Three things changed in v6. It takes a name, not a path, so it can only ever act
    inside the directory already opened safely — the previous version derived its
    directory from its argument and would rename any file the process could reach,
    including one outside the receipt directory and, under a substituted parent, a
    foreign one. It never replaces: ``os.rename`` overwrites its target, and a forced
    collision destroyed the bytes of the file quarantined first, against the
    protocol's own promise to lose none. And a complete signed receipt is refused
    unless the operator says otherwise, so the recovery cannot be used to make real
    evidence disappear by accident.

    Protocol 7 adds the one thing v6 left out: a **perimeter**. The command was
    documented as a recovery for ``*.json`` receipts and enforced nothing, so
    ``--name aa11bb22cc33dd44.intent`` returned 0 without ``--force`` and took the gate
    from ``EVIDENCE_CONFLICT`` to ``CRITERIA_MET_AWAITING_HUMAN_REVIEW`` — a conflict
    deleted with no receipt anywhere — and ``--name signing-key.secret`` turned eight
    verified receipts into eight unverifiable ones. Neither the root of trust nor the
    journal nor a publication temporary is a receipt, and none of them is reachable
    from here, with or without ``--force``.
    """
    _check_quarantine_scope(name)
    info = directory.stat(name)
    if not statmodule.S_ISREG(info.st_mode):
        # A boundary refusal, not a business one: a link, a directory or a device at
        # that name is not a receipt this program is willing to touch at all.
        raise receipt_store.DirectoryUnsafe(
            f"{name} n'est pas un fichier régulier du répertoire de reçus ; rien n'est "
            "mis de côté et aucun renvoi n'est suivi."
        )
    if not force and _looks_like_a_complete_receipt_text(directory, name):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{name} est un reçu signé complet, pas un fichier incomplet. Utilisez "
            "`--force` si vous voulez vraiment l'archiver, et conservez-le pour l'audit.",
        )
    stamp = utc_now().strftime("%Y%m%dT%H%M%S")
    for _ in range(QUARANTINE_ATTEMPTS):
        target = f"{name}{QUARANTINE_SUFFIX}-{stamp}-{secrets.token_hex(4)}"
        try:
            directory.rename(name, target)
        except FileExistsError:
            continue
        except OSError as exc:
            raise Refused(
                ActivationStatus.PREPARED_NOT_EXECUTED,
                f"{name} n'a pas pu être mis de côté ; il reste en place.",
            ) from exc
        directory.fsync()
        return target
    raise receipt_store.PersistenceFailed(
        f"{name} n'a pas pu être mis de côté sous un nom libre après "
        f"{QUARANTINE_ATTEMPTS} essais ; rien n'a été remplacé et le fichier reste en place."
    )


def quarantine_incomplete_receipt(name: str, *, force: bool = False) -> str:
    """Quarantine one name of the receipt directory. Returns the new name."""
    with receipt_directory() as directory:
        return quarantine_in(directory, name, force=force)


def _looks_like_a_complete_receipt_text(
    directory: receipt_store.SecureDirectory, name: str
) -> bool:
    try:
        return _looks_like_a_complete_receipt(directory.read_text(name))
    except (receipt_store.StoreRefused, OSError, ValueError):
        return False


def _looks_like_a_complete_receipt(text: str) -> bool:
    """Whether these bytes are a JSON object carrying a signature.

    Only enough to tell "a receipt that disagrees with mine" from "not a receipt at
    all". The two deserve different messages and different remedies, and conflating
    them is what made an empty file look like a rival proof.
    """
    try:
        payload = jsonlib.loads(text)
    except ValueError:
        return False
    return isinstance(payload, dict) and bool(payload.get(SIGNATURE_FIELD))


def write_receipt(document: dict[str, Any]) -> Path:
    """Sign and persist one receipt locally. Never committed, never uploaded.

    Published **atomically**, in the order :meth:`receipt_store.SecureDirectory.publish_bytes`
    documents, and never overwritten. An earlier version truncated the identifier to
    eight characters and used ``Path.write_text``, so two receipts sharing a second, a
    command and a prefix silently overwrote one another; the version after that created
    the final name first, so an interruption left an empty file that blocked its own
    receipt id for ever. Now the bytes exist in full before the name does, and the
    directory is a descriptor rather than a path, so nothing can be substituted
    underneath the operation.

    Re-writing a byte-identical receipt is idempotent. A divergent *signed receipt*
    under the same name is a collision and is refused. An incomplete or unreadable
    file at that name is neither: it is reported as incomplete, with a command the
    operator can actually run.
    """
    signed = {k: v for k, v in document.items() if not k.startswith("_")}
    command = _name_component(signed.get("command"), "command")
    receipt_id = _name_component(signed.get("receipt_id"), "receipt_id")
    moment = _parse_instant(signed.get("recorded_at"))
    if moment is None:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "recorded_at n'est pas un instant ISO 8601 avec fuseau ; un reçu sans instant "
            "lisible n'est pas nommable.",
        )
    stamp = moment.strftime("%Y%m%dT%H%M%S")
    name = f"{stamp}-{command}-{receipt_id}.json"

    # The same resolution order as every other reader and writer: an injected secret
    # wins, a stored one is validated, and one is created only because this path is
    # about to sign. Reading the file directly here signed receipts with a different
    # key than `load_parent` verified them with.
    secret = ensure_receipt_secret()
    with receipt_directory(create=True) as directory:
        signed[SIGNATURE_FIELD] = sign_receipt(signed, secret)
        body = jsonlib.dumps(signed, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        published = directory.publish_bytes(name, body.encode("utf-8"))
        if published.outcome == "exists":
            try:
                existing = directory.read_text(name)
            except (receipt_store.StoreRefused, OSError) as exc:
                raise Refused(
                    ActivationStatus.PREPARED_NOT_EXECUTED,
                    f"{name} existe déjà et n'est pas un fichier régulier lisible du "
                    "répertoire de reçus. Rien n'est écrit et rien n'est remplacé.",
                ) from exc
            if existing != body:
                if not _looks_like_a_complete_receipt(existing):
                    raise Refused(
                        ActivationStatus.PREPARED_NOT_EXECUTED,
                        f"{name} existe déjà mais est incomplet ou illisible — ce n'est pas "
                        "un reçu signé divergent. Mettez-le de côté avec "
                        f"`{QUARANTINE_COMMAND} --name {name}` pour conserver ses octets, "
                        "puis rejouez cette étape : le même reçu sera republié à l'identique.",
                    )
                raise Refused(
                    ActivationStatus.PREPARED_NOT_EXECUTED,
                    f"{name} existe déjà avec un contenu signé différent. Un reçu n'est "
                    "jamais remplacé : renommez ou archivez l'ancien avant de rejouer cette "
                    "étape, et conservez les deux pour l'audit.",
                )
    document[SIGNATURE_FIELD] = signed[SIGNATURE_FIELD]
    document["_path"] = str(receipt_dir() / name)
    return Path(document["_path"])


# ---------------------------------------------------------------------------
# Attempt intents — the trace that survives a failed publication
# ---------------------------------------------------------------------------
def _intent_of(attempt: Attempt) -> dict[str, Any]:
    """What an intent may say: identity, scope, ceiling. Nothing else.

    No key, no URL, no query string, no clear event id, no quote, no payload. The
    event appears only as its HMAC tag, exactly as a receipt carries it.
    """
    return {
        "intent_version": receipt_store.INTENT_VERSION,
        "attempt_id": attempt.attempt_id,
        "command": attempt.command,
        "sport_key": attempt.sport,
        "bookmaker": attempt.bookmaker,
        "event_tag": (attempt.event_tags[0] if attempt.event_tags else ""),
        "max_credits": attempt.ceiling,
        "state": "PREPARED",
        "prepared_at": attempt.now.isoformat(),
    }


def publish_intent(attempt: Attempt) -> str:
    """Record durably, **before** the request, that one may be about to leave.

    This is the answer to the failure mode the fifth audit reproduced: five credits
    committed, the publication of the receipt failing, and no trace at all that
    anything had been attempted. A receipt written after the fact cannot cover that
    window; a file written and ``fsync``-ed before it can.
    """
    try:
        with receipt_directory(create=True) as directory:
            return receipt_store.publish_intent(directory, _intent_of(attempt))
    except receipt_store.StoreRefused as exc:
        # Refused *before* the wire, which is the whole point: if the trace of an
        # attempt cannot be made durable, the attempt does not happen. Nothing has been
        # requested and nothing has been billed, so this is an ordinary refusal. A
        # divergent intent under an identifier already taken lands here too: two
        # attempts do not share an identity, and the second one does not go out.
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"La trace locale de la tentative n'a pas pu être rendue durable ({exc}) ; "
            "aucune requête n'est émise et aucun crédit n'est engagé.",
        ) from exc


def resolve_intent(attempt_id: str) -> bool:
    """Forget one intent, once its receipt is durably published. Idempotent."""
    try:
        with receipt_directory() as directory:
            return receipt_store.resolve_intent(directory, attempt_id)
    except receipt_store.StoreRefused:
        return False


def unresolved_intents() -> list[dict[str, Any]]:
    """Every intent still on disk, sanitised. Each one blocks the qualification gate.

    The bodies come back from the store already checked against the intent contract:
    a valid one as this program wrote it, an invalid or unreadable one reduced to its
    local name and ``UNREADABLE_OR_INVALID``. v6 returned the parsed file verbatim,
    and ``unresolved_attempt_intent_details`` published it — so a hostile ``command``
    and a hostile ``max_credits`` were echoed into the operator's JSON and terminal.
    """
    try:
        with receipt_directory() as directory:
            return receipt_store.unresolved_intents(directory)
    except receipt_store.StoreRefused:
        # An unreadable boundary hides nothing: `audit_receipts` reports UNAVAILABLE
        # for the same directory, and that alone closes the gate.
        return []


def _matches_intent(intent: Mapping[str, Any], receipt: Mapping[str, Any]) -> bool:
    """Whether this verified receipt is the outcome of *this* intent.

    Identifier **and** material scope. v6 compared identifiers only, against a set
    built by parsing JSON without verifying anything, so a two-key file was enough to
    delete an intent and reopen the gate; a receipt of another command, sport,
    bookmaker, tag or cost did it just as well.
    """
    if str(receipt.get("receipt_id") or "") != str(intent.get("attempt_id") or ""):
        return False
    if str(receipt.get("command") or "") != str(intent.get("command") or ""):
        return False
    for receipt_field, intent_field in (
        ("sport_key", "sport_key"),
        ("bookmaker", "bookmaker"),
    ):
        if str(receipt.get(receipt_field) or "") != str(intent.get(intent_field) or ""):
            return False
    expected_tag = str(intent.get("event_tag") or "")
    if expected_tag:
        tags = {str(expected_tag)}
        carried = receipt.get("event_tag")
        listed = receipt.get("event_tags")
        seen = {str(carried)} if isinstance(carried, str) else set()
        if isinstance(listed, (list, tuple)):
            seen |= {str(item) for item in listed}
        if not (tags & seen):
            return False
    charged = _usable_cost(receipt.get("accounted_credits"))
    ceiling = intent.get("max_credits")
    if charged is None or not isinstance(ceiling, int) or charged > ceiling:
        return False
    # Imported here rather than at module scope: `qualification` imports *from* this
    # module, so a top-level import would be a cycle. The catalogue is the single
    # source of what a command can actually persist, and duplicating it here to avoid
    # one deferred import is how two lists of couples drift apart.
    from betmaxxing.providers.the_odds_api import qualification as qual

    couple = (str(receipt.get("command") or ""), str(receipt.get("status") or ""))
    if couple not in set(qual.PERSISTED_COUPLES):
        return False
    # Sound and current, judged by the contract itself rather than by a second copy of
    # it here. A historical receipt, a malformed one and a self-contradictory one all
    # kept the identifier and the scope intact, so scope alone let each of them delete
    # an intent — and an intent deleted by a receipt the contract refuses to read is an
    # intent deleted by nothing.
    if qual.structural_faults(receipt) or qual.contradictions(receipt):
        return False
    # Two different questions, kept apart on purpose.
    #
    # *Accounting* — this function — asks « does a durable, verified receipt record the
    # outcome of this attempt? ». It requires the same **lineage**: schema, protocol and
    # adapter-evidence versions must be the current ones, so a receipt produced under an
    # earlier protocol never closes an intent opened under this one.
    #
    # *Admissibility* — `qualification.evaluate` — asks « does this receipt support a
    # pre-registered criterion? ». That is where the effective instant belongs, and a
    # receipt recorded before it stays **historical and non-qualifying** however well it
    # resolves an intent.
    #
    # Applying the instant rule here as well would make every protocol change orphan the
    # intents in flight: an intent no receipt can ever resolve blocks the gate for ever,
    # which turns a correction into a durable denial. So a receipt of the right lineage
    # can close its intent *and* contribute nothing to the criteria — the two facts are
    # reported separately and neither is inferred from the other.
    return qual.currency_reason(receipt) not in {
        "stale_schema",
        "other_protocol_version",
        "other_adapter_evidence_version",
        "unusable_recorded_at",
    }


def reconcile_intents() -> int:
    """Resolve intents whose receipt is already published and matching. Returns how many.

    The idempotent half of the crash story: if the process died between publishing a
    receipt and forgetting its intent, replaying finds the receipt, drops the intent
    and counts nothing twice — the receipt was and remains the single record of the
    cost.

    Every candidate now comes from :func:`audit_receipts`, so it has been read through
    the descriptor, matched against an accepted schema and verified against this
    installation's secret; and it must satisfy :func:`_matches_intent`, so it is the
    outcome of *that* attempt and not merely a file bearing the same identifier.
    """
    try:
        resolved = reconcile_intents_report()["resolved_intents"]
    except (Refused, receipt_store.StoreRefused):
        return 0
    # A completed report always carries an integer here; the guard is for the callers
    # of this legacy shape, which have no way to express « not established ».
    return int(resolved or 0)


#: What ``intent_counts_state`` may say. A count reaches a report only once it has
#: been taken — there is no fourth value, and in particular no zero standing in for
#: « je n'ai pas regardé ».
INTENT_COUNTS_ESTABLISHED = "ESTABLISHED"
INTENT_COUNTS_PARTIAL = "PARTIAL"
INTENT_COUNTS_UNESTABLISHED = "UNESTABLISHED"

#: What ``intent_resolution_durability`` may say, and it is orthogonal to the counts:
#: a run can establish both counts exactly and still not know that its removals
#: survive a crash.
DURABILITY_NOT_ATTEMPTED = "NOT_ATTEMPTED"
DURABILITY_DURABLE = "DURABLE"
DURABILITY_UNCERTAIN = "UNCERTAIN"

#: How a count that was never taken renders for a human. ``null`` in JSON, this in
#: prose, and never ``0`` in either.
UNESTABLISHED_COUNT = "NON ÉTABLI"


@dataclass(frozen=True, slots=True)
class _Resolution:
    """The outcome of a completed resolution phase."""

    resolved: int
    durability: str


class _ResolutionInterrupted(Exception):
    """A storage fault stopped the resolution phase, after zero or more removals.

    It carries the counts the phase *did* establish, because the alternative — losing
    them in the traceback and publishing the initialised zeros — is the defect this
    whole path exists to avoid.
    """

    def __init__(self, message: str, *, resolved: int, durability: str) -> None:
        super().__init__(message)
        self.message = message
        self.resolved = resolved
        self.durability = durability


def _resolve_matched_intents(
    directory: receipt_store.SecureDirectory, audit: receipt_store.AuditResult
) -> _Resolution:
    """Drop every intent an admitted receipt of identical scope already accounts for.

    Each removal goes through :func:`receipt_store.resolve_intent`, so the entry is
    unlinked relative to the open descriptor and the directory is ``fsync``-ed: a
    reconciliation that says it forgot an intent has forgotten it durably.

    An ``unlink`` that fails is a durability failure, not a silent skip — the previous
    version returned ``0`` for any :class:`~receipt_store.StoreRefused` and could not
    tell « nothing matched » from « the disk refused ». Those are different answers and
    an operator acts differently on each.
    """
    resolved = 0
    removed_any = False
    for intent in receipt_store.unresolved_intents(directory):
        if intent.get("state") == receipt_store.INTENT_INVALID_STATE:
            continue
        identifier = str(intent.get("attempt_id") or "")
        if not identifier:
            continue
        if not any(_matches_intent(intent, receipt) for receipt in audit.batch):
            continue
        try:
            outcome = receipt_store.resolve_intent_reporting(directory, identifier)
        except FileNotFoundError:
            # Another reconciliation won the race and removed the same entry. The
            # receipt remains the single record of the cost, so this is not an error
            # and it is not a second resolution either.
            continue
        except OSError as exc:
            raise _ResolutionInterrupted(
                "Un intent rapproché n'a pas pu être retiré du répertoire de reçus ; "
                f"le rapprochement s'arrête et rien d'autre n'est retiré ({exc.errno}).",
                resolved=resolved,
                durability=(DURABILITY_DURABLE if removed_any else DURABILITY_NOT_ATTEMPTED),
            ) from exc
        if not outcome.removed:
            continue
        resolved += 1
        removed_any = True
        if not outcome.durable:
            # The entry is gone from the current namespace. That is observed, so it is
            # counted; what is *not* established is that the removal survives a crash.
            # The phase stops here rather than unlinking more entries against a
            # directory that has just refused to synchronise.
            raise _ResolutionInterrupted(
                "Un intent rapproché a été retiré du répertoire, mais la suppression "
                "n'a pas pu être rendue durable ; l'état courant n'est pas établi "
                "durablement et le rapprochement s'arrête.",
                resolved=resolved,
                durability=DURABILITY_UNCERTAIN,
            )
    # Synchronised even when nothing was removed. That is what lets a replay after an
    # interrupted run answer ``DURABLE`` about the state it found, instead of merely
    # « rien à faire » — the directory is the thing being established, not the delta.
    try:
        directory.fsync()
    except (receipt_store.PersistenceFailed, OSError) as exc:
        raise _ResolutionInterrupted(
            "Le répertoire de reçus n'a pas pu être synchronisé ; l'état courant n'est "
            "pas établi durablement.",
            resolved=resolved,
            durability=DURABILITY_UNCERTAIN,
        ) from exc
    return _Resolution(resolved=resolved, durability=DURABILITY_DURABLE)


def _refuse_unreadable_intents(directory: receipt_store.SecureDirectory) -> None:
    """Stop the reconciliation if the storage itself fails while reading an intent.

    Two failures that look alike and are not. An object the boundary **declines** —
    a symlink, a FIFO, a directory, undecodable bytes — raises
    :class:`~receipt_store.StoreRefused`; those keep blocking the gate through
    :func:`~receipt_store.unresolved_intents`, which reduces them to a category rather
    than echoing what someone wrote, and that is the behaviour P2-E8 asked for. An
    ``EIO`` or ``ENOSPC`` raised by the read itself is a **storage** fault: the disk is
    not answering, so the count of remaining intents is not trustworthy. Reporting
    « rien à rapprocher » from a directory that could not be read is the same category
    of error as v6's ``except StoreRefused: return (), 0``.
    """
    for name in directory.names_ending(receipt_store.INTENT_SUFFIX):
        try:
            directory.read_text(name)
        except receipt_store.StoreRefused:
            # Refused, not broken. It stays on disk and it stays blocking.
            continue
        except OSError as exc:
            raise receipt_store.PersistenceFailed(
                "Un intent n'a pas pu être lu depuis le répertoire de reçus ; le "
                "rapprochement s'arrête et le nombre d'intents restants n'est pas "
                f"établi ({exc.errno}).",
                published=False,
            ) from exc


def reconcile_intents_report() -> dict[str, Any]:
    """Reconcile the intents, and report what an operator needs to decide next.

    The whole operation happens inside **one** :class:`~receipt_store.SecureDirectory`,
    opened once: the secret is loaded through it, the audit reads through it, the
    intents are listed through it and the matched ones are unlinked through it. Nothing
    here returns to ``directory / name`` after the open, and nothing here creates
    anything — not the directory, not the secret. ``status`` and this command are the
    two paths that must be safe to run on an installation that has never been used.

    The secret is loaded with :func:`~receipt_store.installation_secret` rather than
    ``ensure``: a recovery path that mints a key would make every receipt already
    signed with the old one unverifiable, which is the opposite of recovering.
    Loading it explicitly also turns « no usable key » into a refusal, where
    :func:`~receipt_store.audit_directory` alone would have reported every receipt
    unverifiable and resolved nothing — the same outcome for two different causes.

    Raises :class:`Refused` carrying a partial document when the boundary, the secret
    or the storage refuses, so the caller can publish the boundary state it did
    establish instead of an empty error. *Partial* is meant literally: every count in
    that document is either a number this run took, or ``None``. The initialised
    document holds no zeros, because a zero that was never measured is a false
    statement about the directory, and a report is not allowed to make one — the same
    reasoning that gave an unreadable boundary its own state rather than letting it
    answer « 0 reçu ».
    """
    document: dict[str, Any] = _reconcile_defaults()
    audit: receipt_store.AuditResult | None = None
    interruption: _ResolutionInterrupted | None = None
    uncounted: Exception | None = None
    try:
        with receipt_directory() as directory:
            document["boundary_state"] = str(receipt_store.BoundaryState.AVAILABLE)
            document["boundary_reason"] = ""
            # Loaded, never used to sign and never printed: this call exists so that a
            # missing or malformed key stops the recovery instead of quietly making
            # every receipt unverifiable.
            receipt_store.installation_secret(directory, SECRET_FILENAME)
            audit = receipt_store.audit_directory(
                directory,
                secret_name=SECRET_FILENAME,
                signature_field=SIGNATURE_FIELD,
                accepted_schema_versions=SUPPORTED_SCHEMA_VERSIONS,
            )
            document["verified_receipts_considered"] = len(audit.batch)
            document["unverifiable_receipts"] = audit.unverifiable
            _refuse_unreadable_intents(directory)
            try:
                outcome = _resolve_matched_intents(directory, audit)
            except _ResolutionInterrupted as exc:
                interruption = exc
                document["resolved_intents"] = exc.resolved
                document["intent_resolution_durability"] = exc.durability
            else:
                document["resolved_intents"] = outcome.resolved
                document["intent_resolution_durability"] = outcome.durability
            # Taken whether or not the phase completed. A measurement that succeeds is
            # published even when another one failed: that is the whole difference
            # between a partial report and an empty one.
            try:
                document["remaining_intents"] = len(receipt_store.unresolved_intents(directory))
            except (receipt_store.StoreRefused, OSError) as exc:
                uncounted = exc
    except receipt_store.DirectoryAbsent as exc:
        document["boundary_state"] = str(receipt_store.BoundaryState.ABSENT)
        document["boundary_reason"] = "absent"
        raise _reconcile_refused(
            document,
            "Le répertoire de reçus autorisé n'existe pas ; aucun intent n'est "
            "inventorié, aucun compte n'est établi, et cette commande ne crée rien.",
        ) from exc
    except receipt_store.DirectoryUnsafe as exc:
        document["boundary_state"] = str(receipt_store.BoundaryState.UNAVAILABLE)
        document["boundary_reason"] = getattr(exc, "reason", "unreadable")
        raise _reconcile_refused(
            document,
            "La frontière du répertoire de reçus n'a pas pu être franchie sans "
            "ambiguïté ; aucun intent n'est retiré ni compté.",
        ) from exc
    except receipt_store.StoreRefused as exc:
        raise _reconcile_refused(document, getattr(exc, "message", str(exc))) from exc
    except OSError as exc:
        # The last door. Reading the secret goes through `os.read` too, and neither
        # `load_secret` nor `read_text` wraps a failing disk — so an `EACCES` there used
        # to leave this command with a bare `PermissionError` and zero bytes on stdout,
        # which is the defect P2-E3 and P2-E5 closed for the other verbs. Every storage
        # fault of this operation now leaves as a typed refusal with a report.
        raise _reconcile_refused(
            document,
            "Le répertoire de reçus n'a pas pu être lu ou modifié de façon fiable ; "
            f"aucun intent n'est retiré sur la base d'une lecture incomplète ({exc.errno}).",
        ) from exc

    if interruption is not None:
        raise _reconcile_refused(document, interruption.message) from interruption
    if uncounted is not None:
        raise _reconcile_refused(
            document,
            "Le nombre d'intents restants n'a pas pu être établi ; la porte reste "
            "fermée et rien n'est conclu d'un inventaire incomplet.",
        ) from uncounted

    # Deferred, like every other use in this module: `qualification` imports *from*
    # here, so a top-level import would be a cycle.
    from .qualification import evaluate as evaluate_qualification

    verdict = evaluate_qualification(audit, unresolved_intents=document["remaining_intents"])
    document["qualification_state"] = verdict["qualification_state"]
    document["eligible_for_human_promotion_review"] = verdict["eligible_for_human_promotion_review"]
    return _settle_counts(document)


def _settle_counts(document: dict[str, Any]) -> dict[str, Any]:
    """Derive ``intent_counts_state`` from what was measured, never from intent.

    Computed rather than assigned at each exit, so the published state cannot drift
    from the published counts: the two answers come from the same values.
    """
    taken = (
        document.get("resolved_intents") is not None,
        document.get("remaining_intents") is not None,
    )
    document["intent_counts_state"] = (
        INTENT_COUNTS_ESTABLISHED
        if all(taken)
        else INTENT_COUNTS_PARTIAL
        if any(taken)
        else INTENT_COUNTS_UNESTABLISHED
    )
    return document


def _reconcile_refused(document: dict[str, Any], message: str) -> Refused:
    """A refusal that carries everything this run did establish, and nothing more."""
    return Refused(ActivationStatus.PREPARED_NOT_EXECUTED, message, _settle_counts(document))


def qualification_state_unknown() -> str:
    """The state to publish when the boundary never became readable.

    Not ``INSUFFICIENT_EVIDENCE``: that is a conclusion about a corpus this command
    was unable to read. An unreadable boundary establishes no count, so it concludes
    nothing — the same reasoning that gave ``UNAVAILABLE`` its own boundary state.
    """
    return "EVIDENCE_CONFLICT"


def _published_count(value: Any) -> str:
    """A count as prose. ``None`` says so; it never borrows the appearance of zero."""
    return UNESTABLISHED_COUNT if value is None else str(value)


def reconcile_lines(document: dict[str, Any]) -> list[str]:
    """The operator's rendering. Counts and categories only — never a path or a body.

    Word for word the same facts as the JSON, including the absences: a ``null`` there
    is ``NON ÉTABLI`` here, and the closing sentence is chosen by the state rather than
    fixed, so the prose can no longer say « un intent restant bloque la porte » under a
    line that reads « Intents restants : 0 ».
    """
    remaining = document["remaining_intents"]
    durability = document["intent_resolution_durability"]
    lines = [
        "Rapprochement des intents — aucun réseau, aucun crédit, aucun secret créé.",
        f"Frontière            : {document['boundary_state']}"
        + (f" ({document['boundary_reason']})" if document["boundary_reason"] else ""),
        f"Reçus vérifiés lus   : {_published_count(document['verified_receipts_considered'])}"
        f" · invérifiables : {_published_count(document['unverifiable_receipts'])}",
        f"Intents résolus      : {_published_count(document['resolved_intents'])}",
        f"Intents restants     : {_published_count(remaining)}",
        f"Comptage des intents : {document['intent_counts_state']}",
        f"Durabilité           : {durability}",
        f"Qualification        : {document['qualification_state']}"
        f" · éligible revue humaine : {document['eligible_for_human_promotion_review']}",
    ]
    if durability == DURABILITY_UNCERTAIN:
        lines.append(
            (
                "La suppression a été observée dans le répertoire, mais sa durabilité "
                "n'est pas établie : "
                if document["resolved_intents"]
                else "L'état courant n'a pas pu être rendu durable : "
            )
            + "relancez le rapprochement pour établir durablement l'état du répertoire."
        )
    if remaining is None:
        lines.append(
            "Le nombre d'intents restants n'est pas établi : rien ici n'affirme qu'il "
            "n'en reste aucun, et la porte reste fermée. Aucune suppression manuelle "
            "n'est autorisée."
        )
    elif remaining:
        lines.append(
            "Un intent restant bloque la porte : il n'est retiré que par un reçu durable, "
            "vérifié et de portée identique. Aucune suppression manuelle n'est autorisée."
        )
    else:
        lines.append(
            "Aucun intent ne reste en attente : un intent n'est retiré que par un reçu "
            "durable, vérifié et de portée identique. Aucune suppression manuelle "
            "n'est autorisée."
        )
    return lines


def _signing_secret() -> str:
    """The receipt secret for a path that is about to sign, as a business refusal.

    ``ensure`` rather than ``load``: these callers are the ones allowed to create a
    secret, because they are the ones about to produce a receipt. A malformed secret
    already on disk stops the step instead of being replaced — replacing it would make
    every receipt already signed with it unverifiable.
    """
    try:
        return ensure_receipt_secret()
    except receipt_store.StoreRefused as exc:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"Le secret de signature local est inutilisable : {exc} Aucune étape n'est "
            "engagée et aucun secret n'est remplacé.",
        ) from exc


def campaign_preflight(
    command: str, *, sport: str, bookmaker: str, event_tag_value: str | None = None
) -> None:
    """Refuse a network command the pre-registered campaign does not authorise.

    Called **before** the provider key is read, before an intent is published and
    before any socket exists, so a refusal here leaves nothing behind: no request,
    no receipt, no intent, no credit. It reads the local boundary and the signing
    secret, which the caller has already obtained — auditing our own receipts is what
    makes the count possible, and it costs nothing at the provider.

    Until protocol 8 this function did not exist, and the campaign's bounds lived in
    a prose table nothing consulted. The static audit 03C-2D bis showed the
    consequence by measurement: an overrun of the four allocated discoveries was
    indistinguishable, in every published field, from a conforming corpus.
    """
    from .qualification import (
        CAMPAIGN_ADDITIONAL_PER_COMPETITION,
        CAMPAIGN_BOOKMAKER,
        CAMPAIGN_CORE_PER_FAMILY,
        CAMPAIGN_INVOCATION_LIMITS,
        CampaignExecutionState,
        campaign_family,
        campaign_ledger,
        campaign_scopes_for,
    )

    def refuse(message: str) -> None:
        raise Refused(ActivationStatus.PREPARED_NOT_EXECUTED, message)

    if bookmaker != CAMPAIGN_BOOKMAKER:
        refuse(
            f"La campagne v8 est préenregistrée sur le bookmaker {CAMPAIGN_BOOKMAKER} ; "
            f"{bookmaker!r} n'est pas autorisé. Aucune requête n'est émise, aucun crédit "
            "n'est engagé. Changer de bookmaker après coup exigerait un nouveau protocole."
        )
    allowed = campaign_scopes_for(command)
    if sport not in allowed:
        refuse(
            f"{sport} n'est pas une compétition préenregistrée pour {command}. La campagne "
            f"v8 n'autorise que {', '.join(allowed)}. Aucune substitution n'est faite."
        )

    # The parser's own configuration, checked here because a mismatch is not a parsing
    # problem the operator can see coming. The harness runs a paid response through the
    # adapter's parser, and that parser keeps only the bookmakers named by
    # `BETMAXXING_BOOKMAKERS` — not the one on the command line. The two agreed by
    # accident while both were `winamax_fr`, which is still the shipped default; under
    # this manifest they do not. The final re-audit measured the cost of leaving that
    # documentary: a `core` call made exactly as the manifest requires, with the variable
    # simply absent, reached the paid endpoint, kept no selection, published
    # SCHEMA_MISMATCH, spent one credit and put the campaign in ABORTED — and restarting
    # an aborted campaign needs a new protocol.
    #
    # Read by name rather than through `get_settings()`: instantiating `Settings` fills
    # every field from the environment, the provider key included, and this must run
    # before the key may be read at all. It applies to `discover` too, which parses no
    # odds: stopping at the free step costs nothing, while discovering first and failing
    # on the first paid call costs the campaign.
    if CAMPAIGN_BOOKMAKER not in configured_bookmakers():
        refuse(
            "Bookmaker de campagne non configuré pour le parser : "
            f"bookmaker requis = {CAMPAIGN_BOOKMAKER}. Le parseur de l'adaptateur ne "
            f"retient que les bookmakers nommés par {BOOKMAKERS_VARIABLE}, et celui de la "
            "campagne v8 n'y figure pas — une réponse payante parfaitement valide serait "
            "vidée de toute sélection, publierait SCHEMA_MISMATCH et abandonnerait la "
            f"campagne. Configurez `export {BOOKMAKERS_VARIABLE}={CAMPAIGN_BOOKMAKER}` "
            "(la casse exacte compte) puis relancez. Aucune requête n'est émise, aucun "
            "crédit n'est engagé, aucune invocation n'est consommée."
        )

    ledger = campaign_ledger(audit_receipts(), unresolved_intents=len(unresolved_intents()))
    if not ledger.established or ledger.counts is None:
        refuse(
            "Le compte des invocations de la campagne v8 est UNESTABLISHED : "
            f"{ledger.unestablished_reason} Un compte non établi ne s'interprète pas comme "
            "un compte nul, donc aucune requête n'est émise."
        )
        return
    if ledger.execution_state is CampaignExecutionState.CONFLICT:
        refuse(
            "La campagne v8 est en CONFLICT : le corpus de reçus contredit le manifeste "
            "préenregistré. Aucune nouvelle commande réseau n'est autorisée ; reprendre "
            "exigerait un nouveau protocole."
        )
    if ledger.execution_state is CampaignExecutionState.ABORTED:
        refuse(
            f"La campagne v8 est ABORTED : {ledger.abort_reason} Aucune nouvelle commande "
            "réseau n'est autorisée, et un échec ne crée aucun droit de relance."
        )

    limit = CAMPAIGN_INVOCATION_LIMITS[command]
    if ledger.counts[command] >= limit:
        refuse(
            f"Le plafond préenregistré de {limit} invocation(s) {command} est déjà atteint "
            f"({ledger.counts[command]}). Un échec consomme sa place et n'ouvre aucun "
            "remplacement."
        )

    if command == "discover":
        if sport in ledger.discovered:
            refuse(
                f"{sport} a déjà été découverte. Une compétition ne se découvre qu'une "
                "fois : ni réessai, ni élargissement de fenêtre, ni seconde chance."
            )
        return

    if command == "core":
        family = campaign_family(sport)
        if ledger.core_by_family.get(family, 0) >= CAMPAIGN_CORE_PER_FAMILY:
            refuse(
                f"La famille {family} a déjà consommé ses {CAMPAIGN_CORE_PER_FAMILY} appels "
                "core préenregistrés."
            )
    else:
        if ledger.additional_by_competition.get(sport, 0) >= CAMPAIGN_ADDITIONAL_PER_COMPETITION:
            refuse(
                f"{sport} a déjà consommé son appel additional. La campagne v8 en autorise "
                f"{CAMPAIGN_ADDITIONAL_PER_COMPETITION} par compétition football."
            )
    if event_tag_value is not None and event_tag_value in ledger.used_event_tags.get(command, ()):
        refuse(
            f"Cet événement a déjà fait l'objet d'un appel {command}. Rejouer un événement "
            "ne rapproche d'aucun seuil et n'était pas autorisé deux fois."
        )


def _persist_or_report(
    document: dict[str, Any],
    *,
    attempt: Attempt | None,
    as_json: bool,
    secret: str,
) -> None:
    """Publish one receipt, or tell the operator plainly that it could not be.

    The five call sites of :func:`write_receipt` sat outside every handler, and the
    module installed no global one, so ``ENOSPC`` at the ``discover`` site exited with a
    bare ``OSError``, printed **nothing**, and left no receipt: the operator learned
    neither the outcome nor that a request had been attempted. At the ``additional``
    site the same shape loses the only proof of a five-credit call. Every site goes
    through here now, and the intent written before the wire is what survives.

    Protocol 7 widened the net to the exception graph that actually exists. v6 caught
    ``PersistenceFailed`` and nothing else, while ``write_receipt`` can also raise
    ``Refused`` — a divergent signed receipt already at the name — and any
    ``StoreRefused``: ``open_file`` converts *every* ``OSError`` into
    ``DirectoryUnsafe``, so ``EACCES``, ``EROFS``, ``EPERM`` and ``ENOSPC`` at the
    creation of the receipt's temporary went straight past the handler and out of the
    command with **zero bytes** on stdout. The store now reports a failed temporary as
    a durability failure, and this function catches the rest of the family too.
    """
    try:
        write_receipt(document)
    except receipt_store.PersistenceFailed as exc:
        _fail_persistence(exc, attempt=attempt, document=document, as_json=as_json, secret=secret)
        return
    except Refused as exc:
        _fail_persistence(
            receipt_store.PersistenceFailed(exc.message, published=False),
            attempt=attempt,
            document=document,
            as_json=as_json,
            secret=secret,
        )
        return
    except receipt_store.StoreRefused as exc:
        _fail_persistence(
            receipt_store.PersistenceFailed(str(exc), published=False),
            attempt=attempt,
            document=document,
            as_json=as_json,
            secret=secret,
        )
        return
    except OSError as exc:
        # Nothing in the store is meant to let a bare OSError through any more. If one
        # ever does, the operator still gets a sentence and a non-zero exit rather than
        # a traceback and an empty terminal.
        _fail_persistence(
            receipt_store.PersistenceFailed(
                f"Erreur de stockage inattendue lors de la publication ({exc.errno}).",
                published=False,
            ),
            attempt=attempt,
            document=document,
            as_json=as_json,
            secret=secret,
        )
        return
    resolve_intent(str(document.get("receipt_id") or ""))


def _fail_persistence(
    failure: receipt_store.PersistenceFailed,
    *,
    attempt: Attempt | None,
    document: Mapping[str, Any],
    as_json: bool,
    secret: str,
) -> None:
    """Report a lost or unproven publication. Sanitised, non-empty, non-zero exit."""
    identifier = str(document.get("receipt_id") or (attempt.attempt_id if attempt else ""))
    payload: dict[str, Any] = {
        "status": str(document.get("status") or ActivationStatus.PREPARED_NOT_EXECUTED),
        "command": str(document.get("command") or (attempt.command if attempt else "")),
        "attempt_id": identifier,
        "may_have_reached_provider": document.get("may_have_reached_provider"),
        "accounted_credits": _reported_int(document.get("accounted_credits")),
        "persistence_failure": {
            "detail": str(failure),
            "receipt_published": bool(failure.published),
            "cleanup_pending": bool(failure.cleanup_pending),
        },
        "unresolved_attempt_intents": len(unresolved_intents()),
    }
    lines = [
        f"ÉCHEC DE PERSISTANCE : {failure}",
        f"Commande            : {payload['command']}",
        f"Tentative           : {identifier}",
        f"Atteinte fournisseur: {payload['may_have_reached_provider']}",
        f"Crédits comptés     : {payload['accounted_credits']}",
        f"Reçu publié         : {payload['persistence_failure']['receipt_published']}",
        f"Intents non résolus : {payload['unresolved_attempt_intents']}",
        "",
        "Une tentative a pu partir et sa preuve n'est pas durable. L'intent local "
        "conservé ci-dessus est la trace qui reste ; il bloque la porte de "
        "qualification jusqu'à résolution.",
    ]
    if as_json:
        typer.echo(_scrub(jsonlib.dumps(payload, ensure_ascii=False, sort_keys=True), secret))
    else:
        typer.echo(_scrub("\n".join(lines), secret))
    raise typer.Exit(1)


def parent_name(raw_path: str) -> str:
    """The base name of the authorised directory this argument denotes.

    Textual, and only textual. The point of protocol 7's correction here is that no
    security decision is taken by resolving anything: ``Path.resolve`` follows the
    very symbolic links the store refuses, which is how a receipt directory that had
    become a link authorised a paid call that the audit of the same directory refused
    to read at all.

    So an argument is accepted in exactly two shapes — a bare name of the receipt
    directory, or the path this program itself printed, whose directory part equals
    the configured one after ``normpath``. Everything else is refused, and the refusal
    tells the operator to pass the name.
    """
    if not isinstance(raw_path, str) or not raw_path:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Aucun reçu parent n'est nommé. Attendu le nom d'un fichier du répertoire "
            "de reçus autorisé.",
        )
    head, tail = os.path.split(raw_path)
    if head and os.path.normpath(head) != os.path.normpath(str(receipt_dir())):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Un reçu parent est désigné par son nom dans le répertoire de reçus "
            "autorisé, ou par le chemin que cette commande a imprimé. Aucun autre "
            "chemin n'est interprété et aucun renvoi n'est suivi.",
        )
    if not tail.endswith(".json"):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Un reçu parent est un fichier `*.json` du répertoire de reçus autorisé.",
        )
    try:
        return receipt_store._check_name(tail)
    except receipt_store.DirectoryUnsafe as exc:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Le nom du reçu parent n'est pas un nom simple du répertoire de reçus.",
        ) from exc


def load_parent(
    raw_path: str,
    *,
    signing: str,
    command: str,
    status: ActivationStatus,
    sport: str,
    bookmaker: str,
    now: datetime,
) -> dict[str, Any]:
    """Read and fully validate the receipt that authorises this step.

    Named by the operator, deliberately: an earlier version walked the directory
    looking for something that matched — choosing the operator's evidence for them,
    from unauthenticated files, in a directory anything can write to.

    Read through the **same descriptor as the audit**, since protocol 7. Until then
    this function made every one of its decisions through ``pathlib`` —
    ``receipt_dir().resolve()``, ``path.is_symlink()``, ``path.resolve()``,
    ``resolved.read_text()`` — four separate lookups of one name, in front of the two
    commands that spend money. With the receipt directory a symbolic link,
    ``audit_receipts`` reported an empty installation and this function authorised a
    paid call out of the link's target. One reader being safe proved nothing about
    the other; now there is one boundary and both use it.
    """
    name = parent_name(raw_path)
    try:
        with receipt_directory() as directory:
            text = directory.read_text(name)
    except receipt_store.DirectoryAbsent as exc:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "Le répertoire de reçus autorisé n'existe pas ; aucune preuve ne peut en "
            "venir et aucune requête n'est émise.",
        ) from exc
    except receipt_store.StoreRefused as exc:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{name} n'est pas un fichier régulier lisible du répertoire de reçus "
            "autorisé, ou ce répertoire lui-même n'est pas sûr. Aucun renvoi n'est "
            "suivi et aucune requête n'est émise.",
        ) from exc

    try:
        payload = jsonlib.loads(text)
    except ValueError as exc:
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED, f"{name} n'est pas un reçu lisible."
        ) from exc
    if not isinstance(payload, dict):
        raise Refused(ActivationStatus.PREPARED_NOT_EXECUTED, f"{name} n'est pas un reçu.")
    raw_path = name

    version = payload.get("schema_version")
    if not _schema_version_of(payload):
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{raw_path} porte le schéma {version!r} ; seuls "
            f"{sorted(SUPPORTED_SCHEMA_VERSIONS)} sont lus. Un reçu v1 n'est ni signé ni "
            "chaîné : il ne prouve rien et n'est pas promu silencieusement. Relancez "
            "`discover` puis les étapes suivantes avec cette version.",
        )
    if not verify_receipt(payload, signing):
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
    #: Minted **before** the first request, so the intent written ahead of the wire
    #: and the receipt written after it carry the same identifier. v5 minted it
    #: inside `build_receipt`, which is to say after the money had been spent.
    attempt_id: str = field(default_factory=lambda: secrets.token_hex(8))

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
    # The single common path, so `discover`, `core` and `additional` all carry the
    # two version stamps and all three are covered by the signature below.
    # Imported here rather than at module level because `qualification` imports
    # this module for its vocabularies.
    from .qualification import (
        PROVIDER_ADAPTER_EVIDENCE_VERSION,
        PROVIDER_VALIDATION_PROTOCOL_VERSION,
    )

    document: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        # Which protocol would judge this receipt, and which parser produced it.
        # Without them a proof cannot be told apart from a proof about code we
        # have since changed — see D-072.
        "qualification_protocol_version": PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "provider_adapter_evidence_version": PROVIDER_ADAPTER_EVIDENCE_VERSION,
        "receipt_id": attempt.attempt_id,
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
def _campaign_plan() -> dict[str, Any]:
    """The pre-registered campaign, priced beside the local sequence and never merged.

    ``plan --max-credits 6`` prices one event through two paid steps. Reading that as
    the campaign's budget is a mistake the protocol document has warned about in prose
    since v1; since v8 the two numbers are published side by side so the reader does
    not have to hold the distinction in their head.
    """
    from .qualification import (
        CAMPAIGN_BOOKMAKER,
        CAMPAIGN_INVOCATION_LIMITS,
        CAMPAIGN_SCOPES,
        PROVIDER_VALIDATION_PROTOCOL_VERSION,
        campaign_budget,
    )

    return {
        "protocol_version": PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "bookmaker": CAMPAIGN_BOOKMAKER,
        "scopes": {family: list(scopes) for family, scopes in CAMPAIGN_SCOPES.items()},
        "invocation_limits": dict(CAMPAIGN_INVOCATION_LIMITS),
        **campaign_budget(),
        "note": (
            "La séquence locale ci-dessus coûte "
            f"{TOTAL_MAX_CREDITS} crédits et porte sur un seul événement : elle ne "
            "satisfait aucun critère. La campagne préenregistrée en coûte "
            f"{campaign_budget()['contractual_credits']} et exige une autorisation "
            "humaine distincte par invocation."
        ),
    }


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
        # The two figures a reader used to conflate. `total_max_credits` prices the
        # **local sequence** — one event through `core` then `additional`, six credits
        # — and satisfies no criterion on its own. The block below prices the
        # **pre-registered campaign**, which is a different thing and costs sixteen.
        "campaign": _campaign_plan(),
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
    campaign = document["campaign"]
    lines += [
        f"Campagne v{campaign['protocol_version']} préenregistrée — à ne pas confondre "
        f"avec la séquence locale ci-dessus :",
        f"  bookmaker    : {campaign['bookmaker']}",
        "  compétitions : "
        + " · ".join(
            f"{family} {', '.join(scopes)}" for family, scopes in campaign["scopes"].items()
        ),
        f"  invocations  : {campaign['cli_invocations']} ({campaign['invocation_limits']})",
        f"  requêtes HTTP: {campaign['http_requests']}, dont "
        f"{campaign['paid_http_requests']} payantes",
        f"  budget       : {campaign['contractual_credits']} crédits contractuels, "
        f"contre {TOTAL_MAX_CREDITS} crédits pour la séquence locale d'un seul événement",
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
    attempt: Attempt, settings: Settings, secret: str, signing: str
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
    attempt.event_tags = list(dict.fromkeys(event_tag(e["id"], signing) for e in attempt.events))
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
        # The signing secret first, then the campaign guard, and only then the
        # provider key: auditing our own receipts is what makes the count possible,
        # and it must happen while a refusal still costs nothing.
        signing = _signing_secret()
        campaign_preflight("discover", sport=one_sport, bookmaker=one_book)
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
        publish_intent(attempt)
        document, status = run_discovery(attempt, settings, secret, signing)
    except Refused as exc:
        _fail(
            exc.status,
            exc.message,
            as_json=json_output,
            secret=secret,
            document=_record_failure(attempt, exc.status, secret, as_json=json_output),
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
            document=_record_failure(attempt, status, secret, as_json=json_output),
        )
        return

    _persist_or_report(document, attempt=attempt, as_json=json_output, secret=secret)
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
    attempt: Attempt | None,
    status: ActivationStatus,
    secret: str,
    *,
    as_json: bool = False,
) -> dict[str, Any] | None:
    """Write the audit trail for an attempt that reached the wire and then failed.

    Nothing is written when the network was never touched: a consumption record
    for a call that never happened is a fabrication, the same error as losing the
    record of one that did.
    """
    if attempt is None or not attempt.network_attempted:
        return None
    document = build_receipt(attempt, status, secret)
    # The same reporting path as a successful step: losing the record of a call that
    # *failed* after reaching the wire is exactly as bad as losing one that worked.
    _persist_or_report(document, attempt=attempt, as_json=as_json, secret=secret)
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
        signing = _signing_secret()
        campaign_preflight(
            "core",
            sport=one_sport,
            bookmaker=one_book,
            event_tag_value=event_tag(one_event, signing),
        )
        settings = get_settings()
        secret = _require_key(settings)

        now = _clock()
        parent = load_parent(
            discovery_receipt,
            signing=signing,
            command="discover",
            status=ActivationStatus.DISCOVERY_VERIFIED,
            sport=one_sport,
            bookmaker=one_book,
            now=now,
        )
        _check_discovery(parent, one_event, discovery_receipt, signing)

        attempt = Attempt(
            command="core",
            sport=one_sport,
            bookmaker=one_book,
            window=(now, now + timedelta(hours=hours)),
            ceiling=ceiling,
            now=now,
            event_id=one_event,
            event_tags=[event_tag(one_event, signing)],
        )
        publish_intent(attempt)
        document, status = run_core(attempt, settings, secret, parent)
    except Refused as exc:
        _fail(
            exc.status,
            exc.message,
            as_json=json_output,
            secret=secret,
            document=_record_failure(attempt, exc.status, secret, as_json=json_output),
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
            document=_record_failure(attempt, status, secret, as_json=json_output),
        )
        return

    _persist_or_report(document, attempt=attempt, as_json=json_output, secret=secret)
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


def _check_discovery(parent: dict[str, Any], event_id: str, label: str, signing: str) -> None:
    """The discovery must actually have approved *this* event, at nil cost."""
    tags = parent.get("event_tags")
    if not isinstance(tags, list) or event_tag(event_id, signing) not in tags:
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
        signing = _signing_secret()
        campaign_preflight(
            "additional",
            sport=one_sport,
            bookmaker=one_book,
            event_tag_value=event_tag(one_event, signing),
        )
        settings = get_settings()
        secret = _require_key(settings)

        now = _clock()
        parent = load_parent(
            core_receipt,
            signing=signing,
            command="core",
            status=ActivationStatus.CORE_LIVE_VERIFIED,
            sport=one_sport,
            bookmaker=one_book,
            now=now,
        )
        _check_core(parent, one_event, core_receipt, signing)

        attempt = Attempt(
            command="additional",
            sport=one_sport,
            bookmaker=one_book,
            window=(now, now + timedelta(hours=hours)),
            ceiling=ceiling,
            now=now,
            event_id=one_event,
            event_tags=[event_tag(one_event, signing)],
        )
        publish_intent(attempt)
        document, status = run_additional(attempt, settings, secret, parent)
    except Refused as exc:
        recorded = (
            exc.document
            if exc.document is not None
            else _record_failure(attempt, exc.status, secret, as_json=json_output)
        )
        if exc.document is not None:
            _persist_or_report(exc.document, attempt=attempt, as_json=json_output, secret=secret)
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
            document=_record_failure(attempt, status, secret, as_json=json_output),
        )
        return

    _persist_or_report(document, attempt=attempt, as_json=json_output, secret=secret)
    _finish(document, _summary(document), as_json=json_output, secret=secret, ok=True)


def _check_core(parent: dict[str, Any], event_id: str, label: str, signing: str) -> None:
    """Five credits are committed only on a proof that one already worked."""
    if parent.get("event_tag") != event_tag(event_id, signing):
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
def audit_receipts() -> receipt_store.AuditResult:
    """One look at the receipt directory: what is verified, and whether it could be read.

    Read-only, and deliberately **not** a source of authority: nothing here is ever
    passed to :func:`load_parent`. A step is authorised by a receipt the operator
    names on the command line, never by one this function happened to find. Reporting
    and authorising are different jobs, and conflating them is what let ``additional``
    pick its own proof out of a writable directory.

    This is still the only path in production that yields provenance, and since
    protocol 7 it is the only path at all: the reading, the schema check and the HMAC
    all happen inside :func:`receipt_store.audit_directory`, which takes no payload and
    no key. What comes back is an :class:`~receipt_store.AuditResult`, not a pair —
    because v6 returned a pair, and the third fact fell off the end.

    That third fact is the boundary. ``except StoreRefused: return (), 0`` gave a
    symlinked receipt directory, a substituted parent and an unopenable directory the
    same answer as a clean empty one, so ``status`` told an operator « 0 reçu » while
    the paid commands were still reading that directory through another door. Now
    ``ABSENT``, ``AVAILABLE`` and ``UNAVAILABLE`` are three different answers, and only
    the middle one means the counts are worth anything.
    """
    try:
        with receipt_directory() as directory:
            return receipt_store.audit_directory(
                directory,
                secret_name=SECRET_FILENAME,
                signature_field=SIGNATURE_FIELD,
                accepted_schema_versions=SUPPORTED_SCHEMA_VERSIONS,
            )
    except receipt_store.DirectoryAbsent:
        return receipt_store.audit_absent()
    except receipt_store.DirectoryUnsafe as exc:
        return receipt_store.audit_unreadable(getattr(exc, "reason", "unreadable"))
    except receipt_store.StoreRefused:
        return receipt_store.audit_unreadable("unreadable")


def build_activation_state(audit: receipt_store.AuditResult) -> dict[str, Any]:
    """Five dimensions, reported separately because they are separate facts.

    One label cannot carry them. Two real ``core`` calls proved connectivity,
    authentication and billing while proving nothing at all about the parser, and
    found no coverage on the two events they looked at. Condensing that into a
    single word loses whichever part the reader needed — and
    ``PREPARED_NOT_EXECUTED`` in particular became simply false.

    Separate is not the same as lenient, which is what v4 corrects. Every dimension
    below now reads its receipts through the same strict lens as the qualification
    block: ``is True`` for a flag, a real non-negative integer for a count, and
    :func:`~.qualification.mapping_observation_is_sound` for anything that claims
    the parser read a live market. None of them can print a positive label about a
    fact the sixth block rejects.
    """
    # Imported here rather than at module level because `qualification` imports this
    # module for its vocabularies.
    from .qualification import (
        COST_BUCKETS,
        AttemptState,
        CommandState,
        ReceiptPhase,
        admissible_phases,
        attempt_state,
        canonical,
        command_state,
        cost_category,
        is_paid_command,
        mapping_observation_is_sound,
        provider_was_reached,
        semantic_receipts,
        structural_faults,
    )
    from .qualification import (
        contradictions as receipt_contradictions,
    )
    from .qualification import (
        evaluate as evaluate_qualification,
    )

    # Every reading below runs over the canonical collection: one entry per distinct
    # signed receipt. Physical file counts stay in `verified_receipts`,
    # `unverifiable_receipts` and `qualification_exact_duplicate_copies`, which are the
    # only three numbers here that answer "how many files", and none of them is evidence.
    verified = receipt_store.require_audited(audit)
    unverifiable = audit.unverifiable
    distinct = canonical(verified)
    # v6: a receipt the contract rejects — malformed, self-contradictory, of an unknown
    # couple, or sharing an identifier with a different receipt — feeds the forensic
    # counters, the reasons and `rejected_receipt_credits_not_counted`, and **nothing
    # semantic**. Until v5 it still fed the cost census, the connectivity label,
    # `execution_state` and `paid_activation_state`, which is exactly what the body of
    # the pull request claimed it did not do.
    sound = semantic_receipts(distinct)
    rejected = [r for r in distinct if r not in sound]
    rejected_paid = [r for r in rejected if is_paid_command(r)]
    states = {id(r): attempt_state(r) for r in sound}
    paid = [r for r in sound if is_paid_command(r)]
    confirmed = [r for r in paid if states[id(r)] is AttemptState.CONFIRMED_ATTEMPT]
    unestablished = [r for r in paid if states[id(r)] is AttemptState.ATTEMPT_STATE_UNESTABLISHED]
    any_confirmed = [r for r in sound if states[id(r)] is AttemptState.CONFIRMED_ATTEMPT]
    any_unestablished = [
        r for r in sound if states[id(r)] is AttemptState.ATTEMPT_STATE_UNESTABLISHED
    ]

    # A receipt establishes a coverage answer when its phase actually asked the
    # bookmaker question, its fields are readable, and the provider really was reached.
    def answered_the_bookmaker(receipt: Mapping[str, Any]) -> bool:
        if not provider_was_reached(receipt):
            return False
        if ReceiptPhase.CLASSIFIED not in admissible_phases(receipt):
            return False
        if structural_faults(receipt) or receipt_contradictions(receipt):
            return False
        market_states = receipt.get("market_states")
        return isinstance(market_states, Mapping) and bool(market_states)

    mapped = [r for r in sound if mapping_observation_is_sound(r)]
    answered = [r for r in paid if answered_the_bookmaker(r)]
    established = mapped + [r for r in answered if r not in mapped]

    # `execution_state` reports how far the sequence went, and only a confirmed attempt
    # is far. An unestablished attempt state is its own value rather than being rounded
    # up to `*_ATTEMPTED`, which is what v4 did from an absent flag.
    # v6: the command is read through `command_state`, a closed domain. v5 fell through
    # to `DISCOVERY_ATTEMPTED` for *any* confirmed attempt that was not `core` or
    # `additional` — including `plan`, an absent command, `sync`, `7`, `Core` and
    # `" core "`. That is the same two-valued reading of an unset field D-075 removed
    # from `network_attempted`, and it published a discovery nobody had made.
    execution = ExecutionState.NO_NETWORK_ATTEMPTED
    #: A receipt the contract rejects may feed no **positive** claim — but it cannot
    #: certify a negative one either. `NO_NETWORK_ATTEMPTED` asserts that nothing was
    #: attempted, which a document we refuse to read is in no position to establish, so
    #: anything other than a clean "never attempted" leaves the state unestablished.
    rejected_may_have_attempted = any(
        attempt_state(r) is not AttemptState.NOT_ATTEMPTED for r in rejected
    )
    if any(command_state(r) is CommandState.ADDITIONAL for r in confirmed):
        execution = ExecutionState.ADDITIONAL_ATTEMPTED
    elif any(command_state(r) is CommandState.CORE for r in confirmed):
        execution = ExecutionState.CORE_ATTEMPTED
    elif any(command_state(r) is CommandState.DISCOVER for r in any_confirmed):
        execution = ExecutionState.DISCOVERY_ATTEMPTED
    elif any_confirmed or any_unestablished or rejected_may_have_attempted:
        execution = ExecutionState.NETWORK_ATTEMPT_STATE_UNESTABLISHED

    # One CostProof per paid step, then the declared precedence. The census it is
    # derived from is published beside it, over the same canonical population.
    # v6 splits v5's single "unestablished" bucket in two, because its name asserted
    # what two of its three feeders denied: a reach that was never established is not a
    # reach whose *cost* could not be established.
    per_call = {
        "provider_reached_nonconforming_cost": CostProof.EXERCISED_NONCONFORMING,
        "provider_reached_cost_unestablished": CostProof.EXERCISED_UNESTABLISHED,
        "provider_reach_unestablished": CostProof.EXERCISED_UNESTABLISHED,
        "paid_attempt_state_unestablished": CostProof.EXERCISED_UNESTABLISHED,
        "provider_reached_conforming_cost": CostProof.EXERCISED_CONFORMING,
        # Confirmed issued, confirmed not served: it measured no tariff at all.
        "confirmed_attempts_not_sent": CostProof.NOT_EXERCISED,
    }
    precedence = [
        CostProof.EXERCISED_NONCONFORMING,
        CostProof.EXERCISED_UNESTABLISHED,
        CostProof.EXERCISED_CONFORMING,
        CostProof.NOT_EXERCISED,
    ]
    census = dict.fromkeys(COST_BUCKETS, 0)
    for receipt in paid:
        if category := cost_category(receipt):
            census[category] += 1
    seen_proofs = {per_call[name] for name, count in census.items() if count}
    cost_proof = next((p for p in precedence if p in seen_proofs), CostProof.NOT_EXERCISED)

    mapping_proof = MappingProof.OBTAINED_LIVE if mapped else MappingProof.NOT_OBTAINED_LIVE

    # The cascade, evidence first and command name last. v4 tested
    # `any(command == "additional")` before anything else, so the mere presence of an
    # `additional` receipt reported `ADDITIONAL_EXECUTED` for an `AUTH_FAILED`.
    rejected_paid_may_have_attempted = any(
        attempt_state(r) is not AttemptState.NOT_ATTEMPTED for r in rejected_paid
    )
    if not confirmed and not unestablished and not rejected_paid_may_have_attempted:
        # Every paid receipt says exactly "no request was issued", or there are none.
        paid_state = PaidActivationState.PREPARED_NOT_EXECUTED
    elif not confirmed and not unestablished:
        # Only rejected paid receipts, and none of them establishes that nothing was
        # issued. Reporting `PREPARED_NOT_EXECUTED` here would be an affirmative claim
        # drawn from a document the contract refuses to read.
        paid_state = PaidActivationState.PAID_ATTEMPT_STATE_UNESTABLISHED
    elif not confirmed:
        paid_state = PaidActivationState.PAID_ATTEMPT_STATE_UNESTABLISHED
    elif not established:
        paid_state = PaidActivationState.PAID_ATTEMPT_INCONCLUSIVE
    elif any(command_state(r) is CommandState.ADDITIONAL for r in established):
        paid_state = PaidActivationState.ADDITIONAL_EXECUTED
    elif mapped:
        paid_state = PaidActivationState.CORE_EXECUTED_COVERAGE_OBSERVED
    else:
        paid_state = PaidActivationState.CORE_EXECUTED_NO_COVERAGE

    # Sixth block, added by 03C-1: the pre-registered qualification criteria,
    # evaluated over the same receipts.
    intents = unresolved_intents()
    qualification = evaluate_qualification(audit, unresolved_intents=len(intents))

    return {
        # 1. The adapter itself. A ponctual observation never promotes it —
        # including when every criterion below is satisfied.
        "adapter_state": "IMPLEMENTED_UNVERIFIED",
        # 2. How far the sequence has gone here.
        "execution_state": str(execution),
        # 3. Connectivity, authentication and billing.
        "connectivity_and_cost_proof": str(cost_proof),
        # The census the label above is derived from, over the population it speaks
        # about: one entry per **distinct** paid step this installation can read —
        # deduplicated by identifier and sealed fingerprint, earlier protocols included,
        # receipts the contract rejects excluded. ``COST_CONFORMITY`` counts the same
        # population restricted to the current protocol, so its numbers are narrower by
        # design. The comment here used to say "no deduplication", which the code had
        # never done since v5.
        "paid_call_cost_census": dict(census),
        # Rejected paid receipts are counted, never priced: their cost claim is made by
        # a document the contract refuses to read.
        "rejected_paid_receipts": len(rejected_paid),
        # The same taxonomy, over the receipts the contract refuses to read. Published
        # so the information is not lost with the receipt: two of the six populations —
        # an unestablished reach and an unestablished attempt state — can only arise
        # from a receipt whose flags are outside the structural contract, so they are
        # always nought above and speak here instead.
        "rejected_paid_cost_census": {
            bucket: sum(1 for r in rejected_paid if cost_category(r) == bucket)
            for bucket in COST_BUCKETS
        },
        "unresolved_attempt_intents": len(intents),
        "unresolved_attempt_intent_details": [dict(intent) for intent in intents],
        "unresolved_attempt_intent_scope": (
            "toute tentative dont l'intent local, écrit et synchronisé avant la requête, "
            "n'a pas été résolu par la publication durable de son reçu. Chacun bloque la "
            "porte de qualification tant qu'il subsiste."
        ),
        "paid_call_cost_census_population": (
            "tout pas payant distinct que le contrat accepte de lire — commande core ou "
            "additional, dédupliqué par identifiant et empreinte scellée, protocoles "
            "antérieurs compris, reçus rejetés exclus et recensés à part dans "
            "rejected_paid_cost_census. Une tentative est dite confirmée seulement si "
            "network_attempted vaut exactement True et attempts au moins 1 ; sinon son "
            "état est non établi et publié comme tel. COST_CONFORMITY compte la même "
            "population restreinte au protocole courant."
        ),
        # 4. Coverage — a list of scoped observations, never a verdict. Only
        # receipts whose phase actually answered the bookmaker question and whose
        # displayed fields are structurally valid appear here. A malformed receipt
        # contributed one before v4, which both stated a coverage nobody had
        # observed and echoed its own bad values into the report.
        "bookmaker_coverage_observations": [
            {
                "sport_key": str(r.get("sport_key", "")),
                "bookmaker": str(r.get("bookmaker", "")),
                "event_tag": str(r.get("event_tag") or ""),
                "recorded_at": str(r.get("recorded_at", "")),
                "bookmaker_state": str(r.get("bookmaker_state")),
                "market_states": (
                    dict(r["market_states"]) if isinstance(r.get("market_states"), Mapping) else {}
                ),
                "status": str(r.get("status")),
                "schema_version": _reported_int(r.get("schema_version")),
            }
            for r in answered
        ],
        "bookmaker_coverage_observation_scope": (
            "un reçu par observation distincte, de phase classifiée, structurellement "
            "valide, non contradictoire, et dont l'atteinte du fournisseur est établie"
        ),
        # 5. Whether the parser and freshness path have been exercised for real.
        "mapping_freshness_proof": str(mapping_proof),
        "paid_activation_state": str(paid_state),
        # Real non-negative integers only. `True` is not one credit, `"7"` is not
        # seven, and a negative count is not a count — each of those would move a
        # spend total the operator reads to decide whether to keep going.
        # Semantic: distinct receipts, structurally readable, real non-negative
        # integers. Seven copies of one call are one credit, and a receipt we refuse to
        # read is not a spend record we can add up.
        "accounted_credits_total": sum(_counted_credits(r.get("accounted_credits")) for r in sound),
        # The prudent counterpart, named so it cannot be mistaken for the figure above:
        # credits claimed by receipts the contract rejects. Visible, never summed in.
        "rejected_receipt_credits_not_counted": sum(
            _counted_credits(r.get("accounted_credits")) for r in rejected
        ),
        # Whether the two counts below mean anything at all. v6 published them for an
        # unreadable boundary exactly as for an empty one, so a receipt directory that
        # had become a symbolic link read « 0 reçu, 0 invérifiable » — and the paid
        # commands went on reading it. `reason` is a category of BOUNDARY_REASONS, never
        # a path and never anything an attacker chose.
        "receipt_boundary_state": str(audit.boundary),
        "receipt_boundary_reason": audit.reason,
        "receipt_boundary_note": (
            "ABSENT : aucun répertoire de reçus, donc aucune preuve et rien à lire. "
            "AVAILABLE : répertoire sûr et lu ; les comptes ci-dessous sont exacts. "
            "UNAVAILABLE : le répertoire existe mais n'est pas lisible sans ambiguïté ; "
            "aucun compte n'est établi et la porte reste fermée."
        ),
        "verified_receipts": len(verified),
        # D-062's own audit counter: files this installation could not verify.
        # Spelled out rather than spread from the block below, because the
        # qualification block counts the same idea over a different population
        # and a dict spread let it silently win the key.
        "unverifiable_receipts": unverifiable,
        "receipt_directory": str(receipt_dir()),
        # 6. Whether the pre-registered criteria are met. Deleting the receipt
        # directory resets this to zero evidence, exactly as D-062 says. Every key
        # is listed, so adding one to the protocol can never overwrite one here.
        "qualification_protocol_version": qualification["qualification_protocol_version"],
        "qualification_adapter_evidence_version": qualification[
            "qualification_adapter_evidence_version"
        ],
        "qualification_evidence_not_before": qualification["qualification_evidence_not_before"],
        "qualification_state": qualification["qualification_state"],
        "criteria_results": qualification["criteria_results"],
        "eligible_for_human_promotion_review": qualification["eligible_for_human_promotion_review"],
        "evidence_conflicts": qualification["evidence_conflicts"],
        "qualification_admissible_receipts": qualification["qualification_admissible_receipts"],
        "qualification_usable_receipts": qualification["qualification_usable_receipts"],
        "qualification_current_malformed_receipts": qualification[
            "qualification_current_malformed_receipts"
        ],
        "qualification_current_contradictory_receipts": qualification[
            "qualification_current_contradictory_receipts"
        ],
        "qualification_unknown_pair_receipts": qualification["qualification_unknown_pair_receipts"],
        "qualification_historical_nonqualifying_receipts": qualification[
            "qualification_historical_nonqualifying_receipts"
        ],
        "qualification_duplicate_excluded_receipts": qualification[
            "qualification_duplicate_excluded_receipts"
        ],
        "qualification_unverifiable_receipts": qualification["qualification_unverifiable_receipts"],
        "qualification_exact_duplicate_copies": qualification[
            "qualification_exact_duplicate_copies"
        ],
        "qualification_population_equation": qualification["qualification_population_equation"],
        "qualification_reasons": qualification["qualification_reasons"],
        # 7. The pre-registered campaign, counted from the receipts on this boundary.
        # Every key is listed rather than spread, so adding one to the evaluator can
        # never silently overwrite one here.
        "campaign_protocol_version": qualification["campaign_protocol_version"],
        "campaign_counts_state": qualification["campaign_counts_state"],
        "campaign_invocation_counts": qualification["campaign_invocation_counts"],
        "campaign_invocation_limits": qualification["campaign_invocation_limits"],
        "campaign_execution_state": qualification["campaign_execution_state"],
        "campaign_abort_reason": qualification["campaign_abort_reason"],
        "campaign_required_bookmaker": qualification["campaign_required_bookmaker"],
        "campaign_required_scopes": qualification["campaign_required_scopes"],
        "campaign_note": qualification["campaign_note"],
        "qualification_note": qualification["qualification_note"],
        "scope_note": (
            "Chaque observation de couverture vaut pour un fournisseur, un bookmaker, "
            "une compétition, un événement tagué, un marché et un instant — rien de plus."
        ),
        "model_impact": "aucun — tous les modèles restent BACKTEST_ONLY",
    }


def _reason_suffix(document: Mapping[str, Any]) -> str:
    reason = document.get("receipt_boundary_reason") or ""
    return f" ({reason})" if reason else ""


def status_lines(document: Mapping[str, Any]) -> list[str]:
    """The human rendering of the activation state.

    Extracted from the command, and completed. v5 published the cost census, the
    population it speaks about and the rejected credits in the JSON only, while the
    runbook described ``--json`` as « le même contenu » — so an operator reading the
    text saw a collapsed label and none of the numbers behind it. Compactness is
    allowed; omitting a fact that would change a decision is not.
    """
    lines = [
        f"Adaptateur          : {document['adapter_state']}",
        f"Exécution           : {document['execution_state']}",
        f"Connectivité + coût : {document['connectivity_and_cost_proof']}",
        f"Mapping + fraîcheur : {document['mapping_freshness_proof']}",
        f"Activation payante  : {document['paid_activation_state']}",
        f"Crédits comptés     : {document['accounted_credits_total']}"
        f" · crédits rejetés non comptés : {document['rejected_receipt_credits_not_counted']}",
        f"Frontière des reçus : {document['receipt_boundary_state']}{_reason_suffix(document)}",
        f"Reçus vérifiés      : {document['verified_receipts']}"
        f" · non vérifiables : {document['unverifiable_receipts']}"
        f" · reçus payants rejetés : {document['rejected_paid_receipts']}",
        f"Intents non résolus : {document['unresolved_attempt_intents']}",
        # A local path, printed as a path. It is gitignored and has no remote.
        f"Répertoire (local)  : {document['receipt_directory']}",
        "",
        "Recensement du coût des appels payants :",
    ]
    for bucket, count in document["paid_call_cost_census"].items():
        lines.append(f"  · {bucket:<38} {count}")
    lines.append(f"  population : {document['paid_call_cost_census_population']}")
    if document["receipt_boundary_state"] == "UNAVAILABLE":
        lines += [
            "",
            "FRONTIÈRE INDISPONIBLE — le répertoire de reçus existe mais n'a pas pu être "
            "lu sans ambiguïté, donc aucun compte ci-dessus n'est établi et la porte reste "
            f"fermée. Catégorie : {document['receipt_boundary_reason']}.",
        ]
    if any(document["rejected_paid_cost_census"].values()):
        lines.append("Recensement médico-légal — reçus payants rejetés par le contrat :")
        for bucket, count in document["rejected_paid_cost_census"].items():
            if count:
                lines.append(f"  · {bucket:<38} {count}")
    if document["unresolved_attempt_intents"]:
        lines += [
            "",
            "Tentatives dont l'intent local n'est pas résolu — une requête a pu partir "
            "sans que sa preuve soit durable :",
        ]
        for intent in document["unresolved_attempt_intent_details"]:
            lines.append(
                f"  · {intent.get('attempt_id', '')}  {intent.get('command', '')}  "
                f"plafond {intent.get('max_credits', '?')}  {intent.get('state', '')}"
            )
        lines.append(f"  portée : {document['unresolved_attempt_intent_scope']}")
    lines.append("")
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
    from .qualification import summary_lines

    lines += summary_lines(document)
    lines += ["", document["scope_note"], f"Modèles : {document['model_impact']}."]
    return lines


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Lire l'état réel de l'activation sur cette installation. Aucun réseau."""
    document = build_activation_state(audit_receipts())
    _emit(document, status_lines(document), as_json=json_output)


receipts_app = typer.Typer(
    help=(
        "Opérations locales sur le répertoire de reçus. Aucun réseau, aucun crédit, "
        "aucune promotion."
    ),
    no_args_is_help=True,
)
app.add_typer(receipts_app, name="receipts")


@receipts_app.command("quarantine")
def receipts_quarantine(
    name: str = typer.Option(
        ...,
        "--name",
        help=(
            "Nom de fichier du reçu, sans chemin — tel qu'il apparaît dans le répertoire de reçus."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Archiver aussi un reçu signé complet. À n'utiliser qu'en connaissance de cause.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Mettre un reçu incomplet de côté, sans perdre un octet, et libérer son nom.

    La sortie de secours que v5 documentait sans la rendre exécutable : le message de
    refus renvoyait vers une fonction qu'aucune commande n'exposait.
    """
    try:
        moved = quarantine_incomplete_receipt(name, force=force)
    except (Refused, receipt_store.StoreRefused) as exc:
        message = getattr(exc, "message", str(exc))
        if json_output:
            typer.echo(jsonlib.dumps({"status": "REFUSED", "detail": message}, ensure_ascii=False))
        else:
            typer.echo(f"Refusé : {message}")
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(
            jsonlib.dumps(
                {"status": "QUARANTINED", "name": name, "moved_to": moved}, ensure_ascii=False
            )
        )
    else:
        typer.echo(
            f"{name} est mis de côté sous {moved}. Ses octets sont conservés, il est hors "
            "de l'audit, et le nom d'origine est libre : rejouez l'étape."
        )


def _named_boundary() -> Path:
    """The receipt directory, required to be named explicitly and absolutely.

    Provisioning is the one verb that writes a *durable* key, so it is the one verb
    that refuses the relative default. ``DEFAULT_RECEIPT_DIR`` resolves against the
    process's working directory — which is the right thing for an operator running a
    step inside a project, and a trap for a key meant to outlive the campaign: the
    boundary would land wherever the shell happened to be, and a later run from one
    directory up would report a clean slate while eight signed receipts sat elsewhere.

    Refusing here rather than in :func:`receipt_dir` is deliberate: the default stays
    the default for every other command, and this one asks to be told.
    """
    configured = os.environ.get(RECEIPT_DIR_VARIABLE)
    if configured is None or not configured.strip():
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{RECEIPT_DIR_VARIABLE} doit être définie sur un chemin absolu. Le défaut "
            f"relatif {DEFAULT_RECEIPT_DIR!r} se résout contre le répertoire courant : "
            "une clé durable n'y est pas provisionnée par accident.",
        )
    candidate = Path(configured.strip())
    if not candidate.is_absolute():
        raise Refused(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            f"{RECEIPT_DIR_VARIABLE} n'est pas un chemin absolu. Rien n'est créé.",
        )
    return candidate


@receipts_app.command("provision")
def receipts_provision(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Ouvrir la frontière de reçus. Aucun réseau, aucun crédit, aucune promotion.

    Le secret de signature naissait jusqu'ici **au premier besoin réseau** :
    :func:`ensure_receipt_secret` n'est atteint que depuis un chemin qui s'apprête à
    signer, et ``status`` refuse de créer quoi que ce soit en regardant. La première
    commande qui ouvrait donc la frontière était ``discover``, c'est-à-dire un appel
    fournisseur — provisionner *avant* toute socket n'était pas exécutable. C'est le
    seul trou que cette commande comble.

    Elle ne réimplémente rien : la génération et la publication restent celles de
    :func:`ensure_receipt_secret`, donc la publication atomique « octets d'abord, nom
    ensuite » qui empêche une interruption de laisser un nom qui existe et qui est
    vide. Ce qui est ajouté ici est la politique du chemin, et la relecture qui suit.

    Ce qu'elle ne fait jamais : remplacer, faire tourner ou « réparer » un secret
    existant, même invalide. Le réécrire transformerait en bruit tout reçu déjà signé
    avec lui, et détruire silencieusement la preuve d'un opérateur est pire que de
    s'arrêter. Elle n'affiche pas davantage le secret, ni sa longueur, ni un fragment,
    ni une empreinte : une clé qu'on peut reconstituer depuis un journal n'est plus
    une clé.
    """
    try:
        boundary = _named_boundary()
        # `create=True` même quand la variable fournit la clé : le répertoire reste
        # nécessaire aux reçus, et la frontière doit être lisible ensuite.
        with receipt_store.SecureDirectory.open(boundary, create=True):
            pass
        # La seule génération et la seule publication du programme. La valeur n'est
        # liée à rien : la connaître ici ne sert à rien et la journaliser serait un
        # défaut.
        ensure_receipt_secret()
    except (Refused, receipt_store.StoreRefused) as exc:
        message = getattr(exc, "message", str(exc))
        _fail(ActivationStatus.PREPARED_NOT_EXECUTED, message, as_json=json_output)
        return

    # Le succès n'est pas la fin de l'écriture : c'est ce que la frontière publie
    # ensuite. Une commande qui se déclare victorieuse sans relire est une commande
    # qui affirme un état qu'elle n'a pas mesuré.
    audit = audit_receipts()
    intents = len(unresolved_intents())
    if str(audit.boundary) != str(receipt_store.BoundaryState.AVAILABLE) or audit.reason:
        _fail(
            ActivationStatus.PREPARED_NOT_EXECUTED,
            "La frontière de reçus n'est pas lisible après provisionnement "
            f"(état {audit.boundary}, catégorie {audit.reason or 'aucune'}).",
            as_json=json_output,
        )
        return

    document = {
        "status": "PROVISIONED",
        "boundary_state": str(audit.boundary),
        "boundary_reason": audit.reason,
        "unresolved_attempt_intents": intents,
    }
    if json_output:
        typer.echo(jsonlib.dumps(document, ensure_ascii=False))
    else:
        typer.echo(
            "Frontière de reçus ouverte. Le secret de signature local est en place et "
            "n'a pas été affiché.\n"
            f"Frontière : {document['boundary_state']} · intents non résolus : {intents}.\n"
            "Conservez cette clé jusqu'à la fin de la campagne : sa perte rendrait "
            "invérifiables tous les reçus signés avec elle. Aucun appel fournisseur, "
            "aucune tentative et aucun crédit n'ont été engagés."
        )


@receipts_app.command("reconcile")
def receipts_reconcile(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Rapprocher les intents dont le reçu est déjà publié. Aucun réseau, 0 crédit.

    La seule récupération autorisée après la fenêtre de crash : l'intent est écrit et
    ``fsync``-é *avant* la requête, retiré une fois son reçu durablement publié, et le
    processus peut mourir entre les deux. L'intent survit alors, la porte se ferme, et
    jusqu'ici aucune commande n'exposait la résolution — `reconcile_intents` existait,
    était documentée au §3.2 du protocole et testée, mais n'était joignable que depuis
    Python. C'est le défaut que le registre tredecies avait consigné comme fermé pour la
    quarantaine, un cran plus bas : une sortie de secours documentée et non exécutable.

    Ce que cette commande ne fait pas, et qui est le point : elle ne supprime jamais un
    intent que rien ne prouve. Un intent n'est retiré que par un reçu **durable**,
    **vérifié par l'audit** contre le secret local, de **portée matérielle identique**
    et de **même lignée** de versions. La quarantaine continue de refuser les `*.intent`
    avec et sans ``--force``, et il n'existe aucune commande de suppression : retirer un
    intent à la main rouvrirait la porte sans preuve, ce qui est exactement le contraire
    d'une récupération.
    """
    try:
        document = reconcile_intents_report()
    except (Refused, receipt_store.StoreRefused) as exc:
        partial = getattr(exc, "document", None) or {}
        message = getattr(exc, "message", str(exc))
        # The same merge feeds both renderings, so a refusal cannot publish a field in
        # one and omit it in the other.
        refused = _settle_counts({**_reconcile_defaults(), **partial})
        if json_output:
            typer.echo(
                jsonlib.dumps(
                    {**refused, "status": "REFUSED", "detail": message},
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
            )
        else:
            for line in reconcile_lines(refused):
                typer.echo(line)
            typer.echo(f"Refusé : {message}")
        raise typer.Exit(1) from exc
    _emit(document, reconcile_lines(document), as_json=json_output)


def _reconcile_defaults() -> dict[str, Any]:
    """Every field the rendering needs, so a partial refusal still renders.

    Every count starts at ``None``, not at ``0``. A refusal that never reached the
    directory has not counted zero intents — it has counted nothing, and those are
    different reports for an operator deciding whether the crash window is closed.
    """
    return {
        "boundary_state": str(receipt_store.BoundaryState.UNAVAILABLE),
        "boundary_reason": "unreadable",
        "verified_receipts_considered": None,
        "unverifiable_receipts": None,
        "resolved_intents": None,
        "remaining_intents": None,
        "intent_counts_state": INTENT_COUNTS_UNESTABLISHED,
        "intent_resolution_durability": DURABILITY_NOT_ATTEMPTED,
        "qualification_state": qualification_state_unknown(),
        "eligible_for_human_promotion_review": False,
    }


def _iso_z(moment: datetime) -> str:
    return ensure_utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":  # pragma: no cover - manual entry point
    app()
