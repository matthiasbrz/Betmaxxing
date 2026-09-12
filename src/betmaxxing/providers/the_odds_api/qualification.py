"""Pre-registered criteria for deciding when live evidence would be *enough*.

The gap this closes is not a missing observation. It is that nothing said, in
advance, how much live evidence would justify asking a human to promote the
adapter. Without that, any result can be read as encouraging: two `core` calls
that found no coverage were once summarised as an activation that "worked".

Protocol **v7**. Each version closed defects an independent read-only audit
reproduced on the previous one. v2 fixed three false claims in D-071; v3 closed the
type coercions that let a signed receipt manufacture positive proof; v4 fixed what v3
got wrong in the other direction, strictness applied without asking what the producer
writes; v5 made a proof of a response require a response. v6 moved the boundary
between disk and belief into one place: the secret became a validated format, the
receipt directory a descriptor rather than a path, an attempt left a durable trace
*before* the wire, and the command became a closed domain.

v7 finishes what v6 named. The sixth audit built eight receipts with the ``signature``
key *deleted*, wrapped them in the provenance type by hand, and reached the human-review
gate — so the provenance type lost its public constructor, and in the supported
application pipeline the only objects reaching this module come from
:func:`~.receipt_store.audit_directory`, which verified their HMAC first. **D-078** fixes
what that is worth and what it is not: the marker guards against ordinary misuse of the
application code, not against arbitrary Python executed in this process. The sixth audit
also wrote ``receipt["freshness"][market] = 300`` through the documented Mapping API and
moved a corpus from ``INSUFFICIENT_EVIDENCE`` to that same gate *after* verification — so
an admitted receipt is a recursively frozen value. And a receipt directory that could not
be read safely used to report exactly what an empty one reports, so the boundary now has
three states and the unreadable one blocks.

**Pure, and provably so.** :func:`evaluate` reads no environment, no clock and no
file, writes nothing, and computes no HMAC. It accepts only the result of a real audit —
:class:`~.receipt_store.AuditResult`, produced by
:func:`~.activation.audit_receipts` — because until v6 its call graph reached
``verify_receipt``, and through it the environment and a key file it created, and until
v7 the type it required could be manufactured by any caller. A list, a tuple and a
hand-built batch are all refused.

**A closed command domain.** :class:`CommandState` reads ``command`` as strictly as
:class:`AttemptState` reads ``network_attempted``. v5 fell through to
``DISCOVERY_ATTEMPTED`` for any confirmed attempt that was not exactly ``core`` or
``additional`` — ``plan``, an absent field, ``sync``, ``7``, ``Core``, ``" core "`` —
and ``Core`` and ``" core "`` also escaped ``PAID_COMMANDS``, taking a paid step out of
the cost census entirely.

**Six cost populations.** v5's single unestablished bucket asserted in its own name
that the provider had been reached, while two of its three feeders were exactly the
receipts where the reach was not established. It is split, and both halves block.

**Rejected receipts are forensic only.** A malformed, self-contradictory,
unknown-couple or divergent-identifier receipt feeds the reasons, the populations and
``rejected_receipt_credits_not_counted`` — and no semantic counter. It used to feed the
census, the connectivity label, ``execution_state`` and ``paid_activation_state``.

**A catalogue checked in both directions.** :data:`PERSISTED_COUPLES` is compared with
what the real command paths write, so a couple the producer emits and the table lacks
fails the suite, and so does a couple the table declares with no producer. v5 declared
``discover/SCHEMA_MISMATCH``, which nothing writes, and lacked
``discover/COST_UNVERIFIED`` and ``discover/COST_MISMATCH``, which ``run_discovery``
writes whenever the free endpoints omit or overshoot the credit header — filing an
honest receipt as an unknown couple and driving a whole corpus to
``EVIDENCE_CONFLICT``.

The contract is **phase-aware**, from v4. What a receipt must
contain depends on how far its ``(command, status)`` pair actually got, and that
mapping is the versioned table :data:`RECEIPT_PHASES` — tested against
:func:`~.activation.build_receipt` rather than inferred from whether a field
happens to be truthy. Under v3 the contract demanded a total market map and a
non-empty event tag from every non-``discover`` receipt, so six of the fifteen the
harness emits — every ``core`` outcome that fails *before* the markets are
classified — were declared ``malformed_current_schema``, and one honest
``AUTH_FAILED`` on disk parked `status` in ``EVIDENCE_CONFLICT`` for good.

What v2 changed, and why each change is a property rather than a preference:

* **Fixed.** The freshness threshold is the literal
  :data:`PROTOCOL_MAX_ODDS_AGE_SECONDS`. v1 read the product's runtime
  `max_odds_age_seconds`, so an operator's `.env` silently moved the
  "pre-registered" bound while the version number stayed at 1 — in the direction
  that matters, since raising it lets a stale quote support a freshness claim.
  This module reads no configuration at all, and since v6 nothing it calls does
  either.
* **Postdated.** Qualifying evidence must be recorded at or after
  :data:`QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC`, and must carry the protocol and
  adapter-evidence versions it was produced under. v1 accepted any signed v2/v3
  receipt whenever it was recorded, so observations made weeks before the
  criteria existed satisfied them — the exact thing pre-registration rules out.
* **Closed.** Admissibility is the positive table
  :data:`ADMISSIBLE_STATUSES_BY_COMMAND`, closed by default. v1 refused a
  blacklist and accepted everything else, so a status invented next year, or one
  belonging to the other command, produced positive evidence.
* **Symmetric.** :func:`contradictions` fails closed in both directions. v1
  caught "selections mapped with no mapped market" and not its converse, so a
  receipt saying the bookmaker was never returned still proved five markets
  mapped.
* **Really UTC.** :func:`utc_day` normalises before taking a date. v1 took the
  civil date as written, so an offset invented a second day.

And what v4 adds on top:

* **Phase-aware.** :data:`RECEIPT_PHASES` says which honest shapes each producible
  ``(command, status)`` pair may take. A pair absent from it is named
  ``unknown_command_status_pair`` rather than judged against a shape nobody chose.
  A status reachable both before and after classification — ``COVERAGE_MISSING``
  and ``SCHEMA_MISMATCH`` are — has both forms admitted, while an unclassified form
  can never be read as an observation because its market map is empty.
* **Agreed.** :func:`mapping_observation_is_sound` is the single reading the strict
  block and the five older ``activation status`` dimensions both use, so no
  dimension can print a positive label about evidence the protocol rejects for the
  same fact. It deliberately omits the version-and-date gate: bumping the protocol
  must not retroactively unmake a mapping that really was observed live.
* **Honest about the flags.** ``paid_calls_that_never_left`` now requires an exact
  ``False``. Under v3 an absent or mistyped ``may_have_reached_provider`` was
  reported as a call proven not to have left, which is a certainty nothing
  established.
* **Reconciled.** The populations partition the verified receipts exactly once and
  the equation is published — see :func:`evaluate`. A current receipt rejected for
  structure or contradiction is no longer filed under "historical".

Three properties are unchanged and still hold:

* **Pure.** :func:`evaluate` takes a batch of already-verified receipts and returns
  a document. No network, no key, no HMAC, no clock, no configuration, no file read
  and none written. v6 is where that became true rather than merely written down:
  the signature check moved to :func:`~.activation.audit_receipts`, and the type of
  the input is what proves it happened.
* **Bounded above.** The best conclusion available here is
  ``CRITERIA_MET_AWAITING_HUMAN_REVIEW``. ``adapter_state`` stays
  ``IMPLEMENTED_UNVERIFIED`` whatever the outcome.
* **Narrow.** What the criteria establish is that our parser read the provider's
  real payload for a named market, in a named sport, across enough independently
  generated events to distinguish the endpoint's shape from one lucky response.
  It says nothing about any bookmaker's coverage beyond the events observed.

The adapter-evidence version protects against one thing only: a proof produced by
a parser we have since changed being read as a proof about the parser we now
ship. It does not validate the provider's payload, and no version number can.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .activation import (
    ADDITIONAL_MARKETS,
    LOCAL_BOUNDS,
    STEP_CEILINGS,
    ActivationStatus,
    BookmakerState,
    MarketState,
)
from .receipt_store import AuditResult, BoundaryState, CountInvalid, require_audited

#: Bump this when a threshold, a scope, an admissibility rule or the effective
#: instant changes. Results computed under one version are not comparable with
#: another, which is the whole reason the number exists: a criterion quietly
#: relaxed after the fact is not a criterion.
PROVIDER_VALIDATION_PROTOCOL_VERSION = 8

#: Bump this when the parser, the mapping, the freshness reading or the cost
#: logic changes in a way that invalidates an earlier proof. A receipt stamped
#: with an older value stays a historical fact and stops being current evidence.
PROVIDER_ADAPTER_EVIDENCE_VERSION = 1

#: A quote older than this is not decision-usable, so a mapping observed on one
#: cannot support a freshness claim. A **literal**, on purpose: the product's own
#: runtime `max_odds_age_seconds` happens to default to the same 900 s, and the
#: two are meant to agree, but the protocol must not move when the runtime one is
#: reconfigured. If they ever diverge, the protocol keeps this number and no
#: receipt becomes more admissible than it was.
PROTOCOL_MAX_ODDS_AGE_SECONDS = 900

#: The instant this protocol took effect, chosen once and written identically in
#: D-077 and `docs/provider-validation-protocol.md`. Evidence recorded before it
#: is history, never qualification. Never recomputed at runtime, never read from
#: the environment: a date that moves is not an effective date.
QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC = "2026-08-25T00:00:00+00:00"

#: Only v4 receipts carry the two version stamps, so only v4 can qualify. v2 and
#: v3 stay readable, honoured as authority for chaining, and reported in the
#: historical block — they simply cannot say which protocol produced them.
QUALIFYING_SCHEMA_VERSION = 4

#: Which outcome, on which command, is positive evidence about the parser. Closed:
#: anything absent from this table is refused, including a status that does not
#: exist yet and one that belongs to the other command.
ADMISSIBLE_STATUSES_BY_COMMAND: dict[str, frozenset[str]] = {
    "core": frozenset({str(ActivationStatus.CORE_LIVE_VERIFIED)}),
    "additional": frozenset(
        {
            str(ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
            str(ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE),
        }
    ),
}

#: Outcomes that can never support a positive criterion. Kept as a second line of
#: defence behind the positive table above, never as the only barrier — which is
#: exactly what it was under protocol v1.
INADMISSIBLE_STATUSES = frozenset(
    {
        str(ActivationStatus.PLAN_ONLY),
        str(ActivationStatus.PREPARED_NOT_EXECUTED),
        str(ActivationStatus.COVERAGE_MISSING),
        str(ActivationStatus.SCHEMA_MISMATCH),
        str(ActivationStatus.COST_MISMATCH),
        str(ActivationStatus.COST_UNVERIFIED),
        str(ActivationStatus.AUTH_FAILED),
        str(ActivationStatus.PROVIDER_UNAVAILABLE),
        # Not an ActivationStatus at all, and that is the point: a fixture earns
        # OFFLINE_CONTRACT_VERIFIED, and no arrangement of fixtures becomes live.
        "OFFLINE_CONTRACT_VERIFIED",
    }
)

#: A paid call whose cost we can actually read. ``COVERAGE_MISSING`` belongs here
#: and nowhere else: it was billed and its cost headers were readable, so it says
#: something about billing while saying nothing about the parser.
COST_ESTABLISHING_STATUSES = frozenset(
    {
        str(ActivationStatus.CORE_LIVE_VERIFIED),
        str(ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
        str(ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE),
        str(ActivationStatus.COVERAGE_MISSING),
    }
)

#: A cost the provider itself contradicted. ``COST_UNVERIFIED`` is deliberately
#: **not** here: v4 filed it under "nonconforming", but a cost nobody could read is
#: not a cost that disagreed — it is a cost that was never established. Both block
#: ``COST_CONFORMITY``; conflating them made one receipt mean two things depending on
#: which block you read (D-075).
_NONCONFORMING_COST_STATUSES = frozenset({str(ActivationStatus.COST_MISMATCH)})

#: A status only reachable *after* the provider answered. Each of them is raised from
#: a code path that has already read a response — ``_settle_cost`` sets
#: ``reached_provider`` before it can raise, ``_event_of`` runs on a parsed payload,
#: and an authentication failure is itself an answer. So a signed receipt carrying one
#: of these together with ``may_have_reached_provider`` other than ``True`` disagrees
#: with itself, and v5 says so instead of reading it as evidence.
RESPONSE_ASSERTING_STATUSES = frozenset(
    {
        str(ActivationStatus.DISCOVERY_VERIFIED),
        str(ActivationStatus.CORE_LIVE_VERIFIED),
        str(ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
        str(ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE),
        str(ActivationStatus.COVERAGE_MISSING),
        str(ActivationStatus.SCHEMA_MISMATCH),
        str(ActivationStatus.COST_MISMATCH),
        str(ActivationStatus.COST_UNVERIFIED),
        str(ActivationStatus.AUTH_FAILED),
    }
)

_LIVE_STATUSES = frozenset(
    {
        str(ActivationStatus.DISCOVERY_VERIFIED),
        str(ActivationStatus.CORE_LIVE_VERIFIED),
        str(ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
        str(ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE),
    }
)

PAID_COMMANDS = frozenset({"core", "additional"})


class AttemptState(StrEnum):
    """What a receipt establishes about whether a request was actually issued.

    Three values, because v4's two-valued reading — ``network_attempted is not
    False`` — turned an *absent* flag into a positive fact. It reported
    ``CORE_ATTEMPTED`` and counted the receipt in a population it called "real paid
    attempts", from a field that said nothing at all. A missing measurement is not a
    measurement of zero, and it is not a measurement of one either.
    """

    #: The step stopped before any socket existed. Not a paid call, and not a defect.
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    #: A request really was issued: the flag is exactly ``True`` and the count agrees.
    CONFIRMED_ATTEMPT = "CONFIRMED_ATTEMPT"
    #: The receipt cannot say. Blocking, visible, and never called attempted.
    ATTEMPT_STATE_UNESTABLISHED = "ATTEMPT_STATE_UNESTABLISHED"


def attempt_state(receipt: Mapping[str, Any]) -> AttemptState:
    """Read the attempt state of a receipt, strictly and in three values.

    ``attempts`` is part of the reading, not a separate check: a receipt claiming a
    network attempt with zero requests, or none with two, cannot be believed about
    either field, so it is unestablished rather than arbitrated.
    """
    flag = receipt.get("network_attempted")
    count = _counted(receipt.get("attempts"))
    if flag is False and count == 0:
        return AttemptState.NOT_ATTEMPTED
    if flag is True and count is not None and count >= 1:
        return AttemptState.CONFIRMED_ATTEMPT
    return AttemptState.ATTEMPT_STATE_UNESTABLISHED


def provider_was_reached(receipt: Mapping[str, Any]) -> bool:
    """Whether this receipt establishes that the request reached the provider.

    The precondition v4 was missing on every path except the cost census. A claim
    about a response — a mapped market, an observed bookmaker, a freshness age — is a
    claim that a response arrived, and only these two exact booleans establish it.
    Under v4 an explicit ``may_have_reached_provider = False`` left a
    ``CORE_LIVE_VERIFIED`` receipt admissible, sound and reported ``OBTAINED_LIVE``,
    so a corpus asserting that nothing was ever served opened the review gate.
    """
    if attempt_state(receipt) is not AttemptState.CONFIRMED_ATTEMPT:
        return False
    return receipt.get("may_have_reached_provider") is True


#: The two closed vocabularies a current receipt must draw from. A value outside
#: them is not a nuance to interpret: it is a field we cannot read.
KNOWN_MARKET_STATES = frozenset(str(state) for state in MarketState)
KNOWN_BOOKMAKER_STATES = frozenset(str(state) for state in BookmakerState)

#: Each projection and the market states it must be the exact image of. v4 keeps
#: the total map authoritative; a projection that disagrees with it is a receipt
#: disagreeing with itself.
PROJECTIONS: dict[str, tuple[str, ...]] = {
    "markets_mapped": (str(MarketState.OBSERVED_MAPPED),),
    "markets_rejected": (str(MarketState.OBSERVED_REJECTED),),
    "markets_absent": (str(MarketState.NOT_RETURNED),),
    "markets_not_evaluated": (str(MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT),),
    "markets_observed": (str(MarketState.OBSERVED_MAPPED), str(MarketState.OBSERVED_REJECTED)),
}

#: The prepared campaign, declared here so the budget in the documentation is
#: derived from the harness's own bounds instead of retyped. Protocol v1's prose
#: said "12 requêtes" for a campaign that issues sixteen: `discover` makes two
#: requests per invocation, so invocations and requests are simply not the same
#: number.
CAMPAIGN_INVOCATIONS: dict[str, int] = {"discover": 4, "core": 6, "additional": 2}

#: The same three numbers under the name the guard and the published report use.
#: One definition, two readings: :func:`campaign_budget` turns them into traffic,
#: :func:`campaign_ledger` compares them with what is on disk.
CAMPAIGN_INVOCATION_LIMITS: dict[str, int] = dict(CAMPAIGN_INVOCATIONS)

#: The single bookmaker of the protocol 8 campaign, chosen from the provider's own
#: public bookmaker list on 2026-08-24 and dated in `docs/source-matrix.md`. Under v7
#: this choice was deferred — « ce document ne nomme pas encore ce bookmaker » — and
#: the one real discovery went out carrying the *other* track's bookmaker. A campaign
#: whose scope is decided after the first answer is not a pre-registered campaign.
CAMPAIGN_BOOKMAKER = "pinnacle"

#: The four competitions, two per family, fixed before any call. Two per family is
#: not a preference: ``min_competitions = 2`` makes a single competition unable to
#: satisfy a ``CORE_MAPPING_*`` criterion, so which two had to be named in advance.
#: v7 named none of them, which is exactly how the second one could have been picked
#: after seeing the first come back empty.
CAMPAIGN_SCOPES: dict[str, tuple[str, ...]] = {
    "soccer": ("soccer_epl", "soccer_spain_la_liga"),
    "tennis": ("tennis_atp_us_open", "tennis_wta_us_open"),
}

#: Flattened in manifest order, so two reports list the scopes the same way.
CAMPAIGN_COMPETITIONS: tuple[str, ...] = tuple(
    sport for scopes in CAMPAIGN_SCOPES.values() for sport in scopes
)

#: ``additional`` is football-only, as the budget table has always said: five markets
#: per event at five credits, on the two football competitions and nowhere else.
CAMPAIGN_ADDITIONAL_SCOPES: tuple[str, ...] = CAMPAIGN_SCOPES["soccer"]

#: The per-scope ceilings, from which the three totals above are derived rather than
#: retyped. Three ``core`` per family is what ``min_events = 3`` asks for; one
#: discovery per competition and one ``additional`` per football competition are what
#: « aucune substitution, aucune relance » means once it is a number.
CAMPAIGN_CORE_PER_FAMILY = 3
CAMPAIGN_DISCOVER_PER_COMPETITION = 1
CAMPAIGN_ADDITIONAL_PER_COMPETITION = 1

#: The status each campaign command must publish to have succeeded. Two of the three
#: are derived from :data:`ADMISSIBLE_STATUSES_BY_COMMAND` so the two tables cannot
#: drift apart; ``discover`` has no entry there because no criterion reads a discovery.
CAMPAIGN_SUCCESS_STATUSES: dict[str, frozenset[str]] = {
    "discover": frozenset({str(ActivationStatus.DISCOVERY_VERIFIED)}),
    "core": ADMISSIBLE_STATUSES_BY_COMMAND["core"],
    "additional": ADMISSIBLE_STATUSES_BY_COMMAND["additional"],
}

#: The commands the campaign counts. ``plan`` is not one: it opens no socket, spends
#: nothing and persists no receipt.
CAMPAIGN_COMMANDS: tuple[str, ...] = ("discover", "core", "additional")


def campaign_family(sport_key: object) -> str:
    """Which manifest family this competition belongs to, or ``""`` for none.

    Exact membership, never a prefix: ``soccer_france_ligue_one`` starts with
    ``soccer_`` and is still outside this campaign. The criteria read the family
    prefix — that is a question about the parser — while the campaign reads the
    manifest, which is a question about what we authorised.
    """
    if not isinstance(sport_key, str):
        return ""
    for family, scopes in CAMPAIGN_SCOPES.items():
        if sport_key in scopes:
            return family
    return ""


def campaign_scopes_for(command: str) -> tuple[str, ...]:
    """The competitions this command may address."""
    if command == "additional":
        return CAMPAIGN_ADDITIONAL_SCOPES
    return CAMPAIGN_COMPETITIONS


#: How each family's three ``core`` split across its two competitions. Dealt out in
#: manifest order, so the extra invocation lands on the competition named **first** on
#: 2026-08-24 — decided before any answer came back, not after one came back thin.
#:
#: The static preflight 03C-2F measured why this had to be written down: the guard
#: capped the family at three and nothing below that, so ``2+1``, ``1+2`` and ``3+0``
#: were all accepted, and the operator picked one at the keyboard with the first
#: discovery already on screen. That is the fault **D-082** recorded against protocol
#: 7 — a scope chosen after seeing the data — in a smaller place.
CAMPAIGN_CORE_BY_COMPETITION: dict[str, int] = {
    sport: CAMPAIGN_CORE_PER_FAMILY // len(scopes)
    + (1 if position < CAMPAIGN_CORE_PER_FAMILY % len(scopes) else 0)
    for scopes in CAMPAIGN_SCOPES.values()
    for position, sport in enumerate(scopes)
}


@dataclass(frozen=True)
class CampaignStep:
    """One pre-registered invocation, with nothing left to decide when it is reached.

    ``event_rank`` is a **rank in the canonical order** of the parent discovery, not an
    identifier: the register is written before any fixture exists, so it can name « the
    first event of the discovery » and never « Arsenal-Chelsea ». :func:`canonical_event_order`
    is what turns the provider's answer — whose order is not contractual — into that rank.
    """

    index: int
    command: str
    sport: str
    #: ``None`` for ``discover``, which addresses no single event.
    event_rank: int | None
    #: The step whose receipt authorises this one; ``None`` for ``discover``.
    parent_step: int | None


def _build_campaign_sequence() -> tuple[CampaignStep, ...]:
    """Deal the pre-registered quotas out into twelve ordered steps.

    Competition by competition, in manifest order: discover it, spend its ``core``
    quota on the first events of its canonical order, then — for the two football
    scopes — spend its one ``additional`` on the event the last of those ``core``
    already proved. Nothing here reads a receipt; the order exists before the campaign.
    """
    steps: list[CampaignStep] = []
    for sport in CAMPAIGN_COMPETITIONS:
        discovery_at = len(steps) + 1
        steps.append(CampaignStep(discovery_at, "discover", sport, None, None))
        last_core = discovery_at
        for rank in range(1, CAMPAIGN_CORE_BY_COMPETITION[sport] + 1):
            last_core = len(steps) + 1
            steps.append(CampaignStep(last_core, "core", sport, rank, discovery_at))
        if sport in CAMPAIGN_ADDITIONAL_SCOPES:
            for _ in range(CAMPAIGN_ADDITIONAL_PER_COMPETITION):
                steps.append(
                    CampaignStep(
                        len(steps) + 1,
                        "additional",
                        sport,
                        CAMPAIGN_CORE_BY_COMPETITION[sport],
                        last_core,
                    )
                )

    # Derived, then checked against the totals that were pre-registered separately. Two
    # tables that agree by construction still drift the day one of them is edited alone,
    # and the campaign's whole claim is that its size was fixed before the first call.
    derived = dict.fromkeys(CAMPAIGN_COMMANDS, 0)
    for step in steps:
        derived[step.command] += 1
    if derived != CAMPAIGN_INVOCATIONS:
        raise ValueError(
            f"Le registre dérivé {derived} ne reproduit pas les quotas préenregistrés "
            f"{CAMPAIGN_INVOCATIONS} : la campagne v8 n'a plus une seule définition."
        )
    return tuple(steps)


#: The twelve steps, in the only order the campaign may be run in. One source, read by
#: the guard, by the report and by the documentation.
CAMPAIGN_SEQUENCE: tuple[CampaignStep, ...] = _build_campaign_sequence()


def canonical_event_order(events: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Order a discovery's events the one way that does not depend on the provider.

    ``/v4/sports/{sport}/events`` promises no order, and « the first one the API
    returned » is therefore a preference dressed as a rule: replay the same call and the
    rank can move. The order here is the pair *(kick-off instant, identifier)*, the
    identifier compared as **UTF-8 bytes** so two runs on two machines with two locales
    cannot disagree about which of two simultaneous fixtures comes first. UTF-8 preserves
    code-point order, so the encode does not change today's result — it states which
    comparison is meant, and keeps the rank out of reach of any collation that is not it.

    An event whose ``commence_time`` cannot be read never outranks one whose can: it
    sorts last rather than being dropped, so a malformed instant costs a rank instead of
    silently renumbering every event after it. Repeated identifiers are kept once, in
    first position seen after ordering — a provider echoing an event must not create a rank.
    """

    def key(event: Mapping[str, Any]) -> tuple[int, float, bytes]:
        moment = _instant(event.get("commence_time"))
        identifier = str(event.get("id", ""))
        if moment is None:
            return (1, 0.0, identifier.encode("utf-8"))
        return (0, moment.astimezone(UTC).timestamp(), identifier.encode("utf-8"))

    ordered: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for event in sorted(events, key=key):
        identifier = str(event.get("id", ""))
        if identifier in seen:
            continue
        seen.add(identifier)
        ordered.append(event)
    return ordered


def discovery_is_sufficient(sport: object, unique_events: int) -> bool:
    """Whether a discovery of ``sport`` found enough events to serve its own steps.

    A competition whose register asks for two ``core`` is not served by a listing of
    one: the second step would have no event of rank 2 to address, and the only ways out
    would be re-running the discovery on a wider window or reusing the first event —
    both of them substitutions the campaign forbids. Saying so at the discovery, which
    costs nothing, is the difference between stopping for free and stopping one credit later.

    A competition outside the manifest is never sufficient, whatever it returned.
    """
    needed = CAMPAIGN_CORE_BY_COMPETITION.get(sport if isinstance(sport, str) else "")
    if needed is None:
        return False
    return unique_events >= needed


#: Every way a receipt can fail to be current evidence, aggregated. Counts only —
#: no path, no receipt, no tag, no identifier ever appears in a reason.
QUALIFICATION_REASONS: tuple[str, ...] = (
    "stale_schema",
    "malformed_current_schema",
    "duplicate_receipt_identifier",
    "other_protocol_version",
    "other_adapter_evidence_version",
    "before_effective_instant",
    "unusable_recorded_at",
    "self_contradictory",
    "unknown_command_status_pair",
)


class CommandState(StrEnum):
    """Which step a receipt is about, read as strictly as its attempt state.

    Five values, because four plus coercion is what v5 had: ``execution_state`` fell
    through to ``DISCOVERY_ATTEMPTED`` for any confirmed attempt whose command was not
    exactly ``core`` or ``additional``, so ``plan``, an absent field, an empty string,
    ``sync``, ``7``, ``["core"]``, ``Core`` and ``" core "`` all published a discovery
    nobody had made. Worse, ``Core`` and ``" core "`` carried no structural fault and
    escaped ``PAID_COMMANDS`` entirely, so a paid step vanished from the cost census.

    No case folding, no trimming, no coercion: a command is one of four exact strings
    or it is not established.
    """

    PLAN = "PLAN"
    DISCOVER = "DISCOVER"
    CORE = "CORE"
    ADDITIONAL = "ADDITIONAL"
    COMMAND_STATE_UNESTABLISHED = "COMMAND_STATE_UNESTABLISHED"


#: The only four spellings a receipt may carry, and what each one means.
COMMAND_NAMES: dict[str, CommandState] = {
    "plan": CommandState.PLAN,
    "discover": CommandState.DISCOVER,
    "core": CommandState.CORE,
    "additional": CommandState.ADDITIONAL,
}


def command_state(receipt: Mapping[str, Any]) -> CommandState:
    """Which step this receipt is about, or that it does not establish one."""
    value = receipt.get("command")
    if not isinstance(value, str):
        return CommandState.COMMAND_STATE_UNESTABLISHED
    return COMMAND_NAMES.get(value, CommandState.COMMAND_STATE_UNESTABLISHED)


class ReceiptPhase(StrEnum):
    """How far an attempt got before it wrote its receipt.

    The distinction v3 lacked. A ``core`` call that was refused by the provider
    before its markets were ever classified is not a malformed receipt: it is a
    complete, honest record of a call that got no further. Demanding a total market
    map from it turned the harness's own output into a permanent evidence conflict.
    """

    #: No socket was opened. Nothing is known about any market.
    PLANNED = "PLANNED"
    #: `discover` reached the two free endpoints. `/events` says nothing about a
    #: bookmaker, so a discovery receipt carries no bookmaker observation at all.
    DISCOVERED = "DISCOVERED"
    #: A paid request went out and came back — or did not — before any market was
    #: classified. The market map is empty *because nothing was looked at*, which
    #: is why such a receipt may never be read as an observation.
    ATTEMPTED_UNCLASSIFIED = "ATTEMPTED_UNCLASSIFIED"
    #: The bookmaker's state was recorded and every requested market classified.
    #: Only this phase can carry a mapping observation.
    CLASSIFIED = "CLASSIFIED"


#: Which shapes each producible ``(command, status)`` pair may honestly take.
#:
#: Versioned with the protocol and tested against :func:`~.activation.build_receipt`,
#: so the contract cannot drift away from its producer again. Two entries carry two
#: phases each, and that is a fact about the harness rather than a hedge:
#: ``COVERAGE_MISSING`` and ``SCHEMA_MISMATCH`` are both reachable from
#: :func:`~.activation._event_of` — before the bookmaker is observed — and from the
#: end of ``run_core`` / ``run_additional``, after every market has a state. Both
#: forms are honest; only the classified one can support an observation.
#:
#: ``plan`` appears because :func:`~.activation.build_receipt` accepts the command
#: and the contract must have an answer for it. No CLI path persists a
#: ``PLANNED``-phase receipt: ``plan`` writes none at all, and
#: :func:`~.activation._record_failure` writes nothing when the network was never
#: touched.
RECEIPT_PHASES: dict[tuple[str, str], frozenset[ReceiptPhase]] = {
    ("plan", str(ActivationStatus.PLAN_ONLY)): frozenset({ReceiptPhase.PLANNED}),
    ("plan", str(ActivationStatus.PREPARED_NOT_EXECUTED)): frozenset({ReceiptPhase.PLANNED}),
    ("discover", str(ActivationStatus.PREPARED_NOT_EXECUTED)): frozenset({ReceiptPhase.DISCOVERED}),
    ("discover", str(ActivationStatus.DISCOVERY_VERIFIED)): frozenset({ReceiptPhase.DISCOVERED}),
    ("discover", str(ActivationStatus.COVERAGE_MISSING)): frozenset({ReceiptPhase.DISCOVERED}),
    # `run_discovery` settles the cost of the two free endpoints like any other step,
    # so it raises COST_UNVERIFIED whenever the credit header is absent or unusable and
    # COST_MISMATCH above its nil ceiling. Both were missing from this table until v6,
    # which filed an honest receipt the harness had just written as an unknown couple and
    # drove the whole corpus to EVIDENCE_CONFLICT. `discover/SCHEMA_MISMATCH` went the
    # other way: it was declared here and no producer ever wrote it — `_event_of` and
    # `_check_start_time`, the two functions that raise it, are reached from `run_core`
    # and `run_additional` only.
    ("discover", str(ActivationStatus.COST_UNVERIFIED)): frozenset({ReceiptPhase.DISCOVERED}),
    ("discover", str(ActivationStatus.COST_MISMATCH)): frozenset({ReceiptPhase.DISCOVERED}),
    ("discover", str(ActivationStatus.AUTH_FAILED)): frozenset({ReceiptPhase.DISCOVERED}),
    ("discover", str(ActivationStatus.PROVIDER_UNAVAILABLE)): frozenset({ReceiptPhase.DISCOVERED}),
    ("core", str(ActivationStatus.PREPARED_NOT_EXECUTED)): frozenset({ReceiptPhase.PLANNED}),
    ("core", str(ActivationStatus.CORE_LIVE_VERIFIED)): frozenset({ReceiptPhase.CLASSIFIED}),
    ("core", str(ActivationStatus.COVERAGE_MISSING)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED, ReceiptPhase.CLASSIFIED}
    ),
    ("core", str(ActivationStatus.SCHEMA_MISMATCH)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED, ReceiptPhase.CLASSIFIED}
    ),
    ("core", str(ActivationStatus.COST_MISMATCH)): frozenset({ReceiptPhase.ATTEMPTED_UNCLASSIFIED}),
    ("core", str(ActivationStatus.COST_UNVERIFIED)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED}
    ),
    ("core", str(ActivationStatus.AUTH_FAILED)): frozenset({ReceiptPhase.ATTEMPTED_UNCLASSIFIED}),
    ("core", str(ActivationStatus.PROVIDER_UNAVAILABLE)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED}
    ),
    ("additional", str(ActivationStatus.PREPARED_NOT_EXECUTED)): frozenset({ReceiptPhase.PLANNED}),
    ("additional", str(ActivationStatus.ADDITIONAL_LIVE_VERIFIED)): frozenset(
        {ReceiptPhase.CLASSIFIED}
    ),
    ("additional", str(ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE)): frozenset(
        {ReceiptPhase.CLASSIFIED}
    ),
    ("additional", str(ActivationStatus.COVERAGE_MISSING)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED, ReceiptPhase.CLASSIFIED}
    ),
    ("additional", str(ActivationStatus.SCHEMA_MISMATCH)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED, ReceiptPhase.CLASSIFIED}
    ),
    ("additional", str(ActivationStatus.COST_MISMATCH)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED}
    ),
    ("additional", str(ActivationStatus.COST_UNVERIFIED)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED}
    ),
    ("additional", str(ActivationStatus.AUTH_FAILED)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED}
    ),
    ("additional", str(ActivationStatus.PROVIDER_UNAVAILABLE)): frozenset(
        {ReceiptPhase.ATTEMPTED_UNCLASSIFIED}
    ),
}


def admissible_phases(receipt: Mapping[str, Any]) -> frozenset[ReceiptPhase]:
    """The honest shapes this receipt's ``(command, status)`` pair may take.

    Empty when the pair is not in the table. That is not an error to be smoothed
    over: a status we have never produced is one whose shape nobody chose, and
    guessing a contract for it is how a future status would silently qualify.
    """
    command = _text(receipt.get("command")) or ""
    status = _text(receipt.get("status")) or ""
    return RECEIPT_PHASES.get((command, status), frozenset())


class QualificationState(StrEnum):
    """Everything this module is allowed to conclude.

    Deliberately three values and deliberately no ``VERIFIED``. Promotion is a
    human decision taken against a written record; a program that can write the
    word has already taken it.
    """

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    CRITERIA_MET_AWAITING_HUMAN_REVIEW = "CRITERIA_MET_AWAITING_HUMAN_REVIEW"


class CampaignCountsState(StrEnum):
    """Whether the campaign's invocation counts mean anything at all.

    Two values, and the second is the point. A count that could not be taken must
    not be published as a zero: « I cannot tell how many calls were made » and
    « no call was made » are opposite facts, and the second one authorises spending.
    """

    ESTABLISHED = "ESTABLISHED"
    UNESTABLISHED = "UNESTABLISHED"


class CampaignExecutionState(StrEnum):
    """How far the pre-registered campaign got, read from its own receipts.

    ``ABORTED`` and ``CONFLICT`` are different answers on purpose. A campaign that
    stopped on an honest failure consumed its invocation and may not continue; a
    corpus that disagrees with the manifest says something worse — that what is on
    disk was never the campaign we authorised.
    """

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    ABORTED = "ABORTED"
    COMPLETE = "COMPLETE"
    CONFLICT = "CONFLICT"
    UNESTABLISHED = "UNESTABLISHED"


def campaign_budget() -> dict[str, int]:
    """The five numbers of the prepared campaign, each derived, none retyped.

    They are five because they count five different things, and conflating two of
    them is how protocol v1 understated its own traffic by four requests while
    getting the credits right.
    """
    invocations = sum(CAMPAIGN_INVOCATIONS.values())
    return {
        "cli_invocations": invocations,
        # One authorisation per invocation: the operator is asked before each call.
        "human_authorisations": invocations,
        "http_requests": sum(
            LOCAL_BOUNDS[command]["max_requests"] * count
            for command, count in CAMPAIGN_INVOCATIONS.items()
        ),
        "paid_http_requests": sum(
            LOCAL_BOUNDS[command]["max_requests"] * count
            for command, count in CAMPAIGN_INVOCATIONS.items()
            if command in PAID_COMMANDS
        ),
        "contractual_credits": sum(
            STEP_CEILINGS[command] * count for command, count in CAMPAIGN_INVOCATIONS.items()
        ),
    }


@dataclass(frozen=True)
class Criterion:
    """One falsifiable claim, with its scope and its thresholds fixed in advance.

    ``requires_total_market_map`` says which fields the criterion reads, not which
    schema versions it accepts — under this protocol every qualifying receipt is a
    v4 one. A per-market criterion needs the total ``market_states`` map to know
    *one named market's* state; a core criterion reads ``selections_mapped``, because a
    `core` call requests a single market and mapped selections therefore *are*
    that market's mapping.
    """

    criterion_id: str
    sport_family: str
    command: str
    market: str
    min_events: int
    min_competitions: int
    min_utc_days: int
    requires_total_market_map: bool
    rationale: str
    limit: str

    @property
    def scope(self) -> str:
        return (
            f"{self.sport_family} · {self.command} · marché {self.market} · "
            f"bookmaker observé uniquement · âge ≤ {PROTOCOL_MAX_ODDS_AGE_SECONDS}s"
        )

    @property
    def required(self) -> dict[str, int]:
        return {
            "events": self.min_events,
            "competitions": self.min_competitions,
            "utc_days": self.min_utc_days,
        }


def _core(sport_family: str, criterion_id: str) -> Criterion:
    return Criterion(
        criterion_id=criterion_id,
        sport_family=sport_family,
        command="core",
        market="h2h",
        # Three, argued: one event cannot be told apart from a lucky payload, and
        # two cannot distinguish "the shape this competition sends" from "the
        # shape the endpoint sends". Three, spread over two competitions and two
        # UTC days, exercises the parser on independently generated responses.
        # Beyond three the marginal information about *our parser* falls away
        # while the cost stays linear at one credit per event.
        min_events=3,
        # Two competitions: a single one may use a uniform market template, so a
        # template-specific pass would look like a general one.
        min_competitions=2,
        # Two UTC days: the freshness path depends on the provider's update
        # cadence and on a `last_update` whose location differs by response
        # shape — precisely where this adapter was wrong before. A second day
        # catches a stamp that is only correct on the day it was generated. Two
        # *real* UTC days: see `utc_day`.
        min_utc_days=2,
        requires_total_market_map=False,
        rationale=(
            "Trois événements, deux compétitions, deux jours UTC : assez pour "
            "distinguer la forme de l'endpoint d'une réponse chanceuse, pas assez "
            "pour prétendre à une couverture."
        ),
        limit=(
            "Établit que le parser lit le marché h2h réel de ce sport sur les "
            "événements observés, chez le bookmaker observé sur ces événements "
            "uniquement. N'établit rien sur la couverture de ce bookmaker ailleurs, "
            "sur une compétition non observée, une autre date ou un autre marché."
        ),
    )


def _additional(market: str) -> Criterion:
    return Criterion(
        criterion_id=f"ADDITIONAL_MAPPING_FOOTBALL_{market.upper()}",
        sport_family="soccer",
        command="additional",
        market=market,
        # Two rather than three, and the reason is cost, stated rather than
        # hidden: one `additional` call is five credits and returns all five
        # markets at once, so two events cost ten credits and give two
        # independent observations per market. Two still separates a one-off
        # payload from the endpoint's shape; it is weaker than core's three, and
        # the limit below says so.
        min_events=2,
        min_competitions=2,
        # One day, deliberately: the day-diversity argument is about the freshness
        # stamp, which the core criteria already exercise across two days for the
        # same response shape. Paying ten more credits to repeat it here buys
        # little. The cost of that choice: a market quoted only at certain hours
        # could pass on a single day's evidence.
        min_utc_days=1,
        requires_total_market_map=True,
        rationale=(
            "Deux événements dans deux compétitions, chacun à cinq crédits. Seuil "
            "plus bas que core parce que l'endpoint coûte cinq fois plus, et la "
            "limite l'assume."
        ),
        limit=(
            f"Établit que le parser lit {market} tel que l'endpoint per-event "
            "l'envoie, sur deux événements. N'établit ni la disponibilité du "
            "marché chez un bookmaker, ni sa présence à d'autres heures."
        ),
    )


COST_CONFORMITY = Criterion(
    criterion_id="COST_CONFORMITY",
    sport_family="*",
    command="*",
    market="*",
    # Six conforming paid calls is exactly the core campaign (three events by two
    # sports). Requiring more would mean paying for cost evidence the campaign
    # already produces as a by-product; requiring fewer would let one or two
    # well-behaved calls stand for the billing behaviour of the whole endpoint.
    min_events=6,
    min_competitions=0,
    min_utc_days=0,
    requires_total_market_map=False,
    rationale=(
        "Six appels payants dont le coût est réellement établi — estimation sous "
        "plafond, observation lisible, comptabilisation égale à l'observation — et "
        "zéro appel non conforme. Un seul écart de coût suffit à faire échouer le "
        "critère."
    ),
    limit=(
        "Établit deux choses seulement : aucun appel n'a dépassé la borne annoncée, et "
        "ce que nous comptabilisons égale ce que le fournisseur a annoncé. **Pas** que "
        "le tarif contractuel a été appliqué exactement : un appel annoncé à 0 crédit "
        "reste conforme, ce qui prouve l'absence de dépassement et non le tarif. "
        "N'établit aucune garantie de facturation future. Un coût seulement supposé — "
        "en-tête illisible, requête peut-être jamais servie — ne compte pas, et un "
        "appel payant dont le coût n'est pas établi fait échouer le critère."
    ),
)


#: Stable order: the two core criteria, the five per-market ones in the
#: provider's own market order, then cost. Two runs of the evaluator must produce
#: the same sequence, so a diff of two reports is readable.
CRITERIA: tuple[Criterion, ...] = (
    _core("soccer", "CORE_MAPPING_FOOTBALL"),
    _core("tennis", "CORE_MAPPING_TENNIS"),
    *(_additional(market) for market in ADDITIONAL_MARKETS),
    COST_CONFORMITY,
)


# ---------------------------------------------------------------------------
# Reading receipt fields strictly. A signature proves bytes, not types.
# ---------------------------------------------------------------------------
def _plain_int(value: object) -> int | None:
    """An integer that really is one. ``True`` is not a credit count.

    Protocol v2 had a companion that coerced booleans and numeric strings, and a
    re-audit showed why that cannot exist on an evidence path: a signed receipt
    carrying ``selections_mapped = "3"`` proved three mapped selections. There is
    now one reader, and it is strict.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _instant(raw: object) -> datetime | None:
    """A timezone-aware instant, or ``None``. A naive stamp is unusable."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment


def utc_day(raw: object) -> str:
    """The **UTC** calendar day of an ISO instant, or an empty string.

    Normalised before the date is taken. Without that, ``00:30+02:00`` and
    ``23:30+00:00`` — the same UTC day, twenty-two minutes apart — counted as two
    days, and three observations inside one UTC day satisfied "two UTC days".
    """
    moment = _instant(raw)
    if moment is None:
        return ""
    return moment.astimezone(UTC).date().isoformat()


def _text(value: object) -> str | None:
    """A non-empty string, or ``None``. An identity field cannot be blank."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _market_list(value: object) -> list[str] | None:
    """A duplicate-free sequence of non-empty strings, or ``None``.

    Not a string — iterating one yields characters, which is how a mistyped
    ``markets_mapped`` used to sneak past a set comparison. A *sequence* rather than a
    ``list`` since protocol 7: an admitted receipt holds tuples, because the frozen
    containers that were ``list`` subclasses could still be written through
    ``list.append``. ``json.loads`` produces lists and never tuples, so nothing a file
    can carry is accepted here that was not accepted before.
    """
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return None
    out: list[str] = []
    for item in value:
        name = _text(item)
        if name is None or name in out:
            return None
        out.append(name)
    return out


def _counted(value: object, *, minimum: int = 0) -> int | None:
    number = _plain_int(value)
    if number is None or number < minimum:
        return None
    return number


# ---------------------------------------------------------------------------
# The structural contract every current receipt must satisfy
# ---------------------------------------------------------------------------
def _common_faults(receipt: Mapping[str, Any]) -> list[str]:
    """The contract every receipt owes, whatever its phase.

    A valid signature establishes that these bytes are ours and unaltered. It says
    nothing about whether ``network_attempted`` is a boolean or the string
    ``"false"``. So before any field is read as evidence, the receipt must satisfy
    a positive contract; a field outside it is named, and the receipt qualifies
    nothing and blocks the gate.
    """
    faults: list[str] = []

    def require(condition: object, field: str) -> None:
        if not condition:
            faults.append(field)

    # v6: the command itself. ``Core``, ``" core "``, ``sync``, ``7`` and an absent
    # field all used to pass the structural contract while escaping ``PAID_COMMANDS``,
    # so a paid step could be reported as unpaid and vanish from the cost census.
    require(command_state(receipt) is not CommandState.COMMAND_STATE_UNESTABLISHED, "command")

    # Versions are strictly positive: there is no version zero, and a counter's
    # rule is different — see below, where zero is accepted.
    for field in (
        "schema_version",
        "qualification_protocol_version",
        "provider_adapter_evidence_version",
    ):
        require(_counted(receipt.get(field), minimum=1) is not None, field)
    # Counters and credits are non-negative. Zero is a real answer: a `discover`
    # step is documented free, and a call proven never to have left is billed 0.
    for field in ("estimated_credits", "accounted_credits"):
        require(_counted(receipt.get(field)) is not None, field)
    for field in ("observed_credits", "quota_remaining"):
        value = receipt.get(field)
        require(value is None or _counted(value) is not None, field)
    # Mandatory, not "checked if present": a receipt that cannot say how many
    # requests it made cannot be reconciled with its own network flag.
    attempts = _counted(receipt.get("attempts"))
    require(attempts is not None, "attempts")
    for field in ("network_attempted", "may_have_reached_provider"):
        require(receipt.get(field) is True or receipt.get(field) is False, field)
    if attempts is not None:
        if receipt.get("network_attempted") is False:
            require(attempts == 0, "attempts")
        elif receipt.get("network_attempted") is True:
            require(attempts >= 1, "attempts")
    for field in ("receipt_id", "sport_key", "command", "status"):
        require(_text(receipt.get(field)) is not None, field)
    require(_instant(receipt.get("recorded_at")) is not None, "recorded_at")
    return faults


def _no_market_was_classified(receipt: Mapping[str, Any]) -> list[str]:
    """The shape of a receipt that never got as far as looking at a market.

    A *positive* contract rather than a waiver: the map, its projections, the
    freshness ages and the mapped-selection count must all be empty. That is what
    stops an unclassified form from being read as an observation, and it is why
    ``ATTEMPTED_UNCLASSIFIED`` is safe to admit at all.
    """
    faults: list[str] = []
    states = receipt.get("market_states")
    if not isinstance(states, Mapping) or states:
        faults.append("market_states")
    for field in PROJECTIONS:
        if field in receipt and _market_list(receipt.get(field)) != []:
            faults.append(field)
    freshness = receipt.get("freshness")
    if not isinstance(freshness, Mapping) or freshness:
        faults.append("freshness")
    if _counted(receipt.get("selections_mapped")) != 0:
        faults.append("selections_mapped")
    return faults


def _classified_faults(receipt: Mapping[str, Any]) -> list[str]:
    """The market block of a receipt whose markets really were classified."""
    faults: list[str] = []

    def require(condition: object, field: str) -> None:
        if not condition:
            faults.append(field)

    require(_counted(receipt.get("selections_mapped")) is not None, "selections_mapped")
    requested = _market_list(receipt.get("markets_requested"))
    require(requested is not None, "markets_requested")
    states = receipt.get("market_states")
    if not isinstance(states, Mapping) or any(
        _text(market) is None or str(state) not in KNOWN_MARKET_STATES
        for market, state in states.items()
    ):
        faults.append("market_states")
        states = None
    if requested is not None and states is not None:
        # v3's map is *total* over the markets the call requested. A key on either
        # side alone means the receipt cannot say what became of a market.
        require(set(states) == set(requested), "market_states")
    if states is not None:
        for field, wanted in PROJECTIONS.items():
            if field not in receipt:
                continue
            projection = _market_list(receipt.get(field))
            expected = {market for market, state in states.items() if str(state) in wanted}
            require(projection is not None and set(projection) == expected, field)
    freshness = receipt.get("freshness")
    if not isinstance(freshness, Mapping) or any(
        _text(market) is None or _counted(age) is None for market, age in freshness.items()
    ):
        faults.append("freshness")
    elif requested is not None:
        require(set(freshness) <= set(requested), "freshness")
    return faults


def _classified_status_faults(receipt: Mapping[str, Any]) -> list[str]:
    """What each classified status must positively contain, per status.

    v4 checked the market block's *shape* and not its content, and
    ``set(market_states) == set(markets_requested)`` is vacuously true when both are
    empty. So a ``CORE_LIVE_VERIFIED`` receipt with no requested market, no map, no
    freshness and zero selections was well formed, usable, and counted as a conforming
    paid call — a live verification that had classified nothing.

    Derived from the producer: ``_classify_markets`` is total over a non-empty
    ``requested``, ``_additional_status`` returns ``ADDITIONAL_LIVE_VERIFIED`` only when
    *every* state is ``OBSERVED_MAPPED`` and ``ADDITIONAL_PARTIAL_COVERAGE`` only when
    some are and some are not, and both ``COVERAGE_MISSING`` shapes carry no mapped
    market at all.
    """
    faults: list[str] = []
    status = _text(receipt.get("status")) or ""
    states = receipt.get("market_states")
    requested = _market_list(receipt.get("markets_requested"))
    if not isinstance(states, Mapping) or requested is None:
        return faults  # the shape contract already named it

    def named(state: MarketState) -> set[str]:
        return {str(m) for m, s in states.items() if str(s) == str(state)}

    mapped = named(MarketState.OBSERVED_MAPPED)
    rejected = named(MarketState.OBSERVED_REJECTED)
    absent = named(MarketState.NOT_RETURNED)
    not_evaluated = named(MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)
    selections = _counted(receipt.get("selections_mapped"))
    freshness = receipt.get("freshness")
    ages = freshness if isinstance(freshness, Mapping) else {}

    positive = status in {
        str(ActivationStatus.CORE_LIVE_VERIFIED),
        str(ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
        str(ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE),
    }
    if positive:
        # A classification of nothing is not a classification.
        if not requested:
            faults.append("markets_requested")
        if not mapped:
            faults.append("market_states")
        if selections is None or selections < 1:
            faults.append("selections_mapped")
        if str(receipt.get("bookmaker_state")) != str(BookmakerState.OBSERVED):
            faults.append("bookmaker_state")
        for market in sorted(mapped):
            if _counted(ages.get(market)) is None:
                faults.append("freshness")
                break
    if status == str(ActivationStatus.ADDITIONAL_LIVE_VERIFIED) and mapped != set(requested):
        # The producer reports this status only when every requested market mapped.
        faults.append("market_states")
    if status == str(ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE) and not (
        mapped and mapped != set(requested)
    ):
        # "Partial" means some mapped and some not. Both ends are a different finding.
        faults.append("market_states")
    if status == str(ActivationStatus.COVERAGE_MISSING):
        if mapped or (selections or 0) > 0:
            faults.append("market_states")
        # Either the bookmaker was never quoted, or it was quoted and offered nothing.
        if not (not_evaluated == set(requested) or absent == set(requested)):
            faults.append("market_states")
    if status == str(ActivationStatus.SCHEMA_MISMATCH):
        if mapped or (selections or 0) > 0:
            faults.append("market_states")
        if not rejected:
            faults.append("market_states")
    return faults


def _phase_faults(receipt: Mapping[str, Any], phase: ReceiptPhase) -> list[str]:
    """The fields this one phase requires, on top of the common contract."""
    faults: list[str] = []

    def require(condition: object, field: str) -> None:
        if not condition:
            faults.append(field)

    if phase is ReceiptPhase.DISCOVERED:
        # `/events` returns no bookmaker information at all, so demanding a
        # bookmaker observation here would flag a perfectly good discovery.
        require(_market_list(receipt.get("event_tags")) is not None, "event_tags")
        for field in ("events_returned", "events_in_window", "events_admissible"):
            require(_counted(receipt.get(field)) is not None, field)
        return faults

    require(_text(receipt.get("bookmaker")) is not None, "bookmaker")
    require(str(receipt.get("bookmaker_state")) in KNOWN_BOOKMAKER_STATES, "bookmaker_state")
    rejections = receipt.get("mapping_rejections")
    require(
        not isinstance(rejections, (str, bytes, bytearray)) and isinstance(rejections, Sequence),
        "mapping_rejections",
    )
    require(_market_list(receipt.get("markets_requested")) is not None, "markets_requested")

    if phase is ReceiptPhase.PLANNED:
        require(receipt.get("network_attempted") is False, "network_attempted")
        require(receipt.get("may_have_reached_provider") is False, "may_have_reached_provider")
        # No event was named, so the tag is legitimately absent or empty. Requiring
        # a non-empty one is what made `core/PREPARED_NOT_EXECUTED` malformed.
        require(isinstance(receipt.get("event_tag", ""), str), "event_tag")
        return faults + _no_market_was_classified(receipt)

    require(receipt.get("network_attempted") is True, "network_attempted")
    require(_text(receipt.get("event_tag")) is not None, "event_tag")
    if phase is ReceiptPhase.ATTEMPTED_UNCLASSIFIED:
        return faults + _no_market_was_classified(receipt)
    return faults + _classified_faults(receipt) + _classified_status_faults(receipt)


def structural_faults(receipt: Mapping[str, Any]) -> list[str]:
    """The **names** of the fields a current receipt gets wrong. Never their values.

    Phase-aware: the receipt is judged against every shape its ``(command, status)``
    pair may honestly take (:data:`RECEIPT_PHASES`) and the *best* verdict wins. A
    pair with two admissible phases therefore passes if either form fits, and a pair
    with one passes only in that form — which is how ``CORE_LIVE_VERIFIED`` still
    owes the whole market map while ``AUTH_FAILED`` owes none of it.

    An unknown pair is judged on the common contract alone; the pair itself is what
    :func:`classify` reports, and inventing a shape for it would be worse than
    naming it.
    """
    common = _common_faults(receipt)
    phases = admissible_phases(receipt)
    if not phases:
        return sorted(set(common))
    best = min(
        (_phase_faults(receipt, phase) for phase in sorted(phases)),
        key=lambda found: (len(found), sorted(set(found))),
    )
    return sorted(set(common + best))


# ---------------------------------------------------------------------------
# Contradictions — closed in both directions
# ---------------------------------------------------------------------------
def contradictions(receipt: Mapping[str, Any]) -> list[str]:
    """Internal inconsistencies that make a receipt unusable as evidence.

    A receipt that disagrees with itself is not weak evidence to be discounted —
    it means one of its fields is wrong and we cannot tell which. The protocol
    fails closed on it and names it, without naming any event.

    Assumes the structural contract already holds: these rules read the fields,
    they do not re-check their types.
    """
    found: list[str] = []
    # v6: `plan` builds no client and opens no socket, and the CLI persists no plan
    # receipt at all. A signed one claiming a confirmed attempt therefore disagrees with
    # itself, and v5 read it as a discovery instead.
    if command_state(receipt) is CommandState.PLAN and attempt_state(receipt) is not (
        AttemptState.NOT_ATTEMPTED
    ):
        found.append(
            "command = plan alors que l'état de tentative n'est pas « jamais tentée » ; "
            "aucun chemin de plan n'ouvre de socket"
        )
    mapped = _plain_int(receipt.get("selections_mapped")) or 0
    states = receipt.get("market_states")
    version = receipt.get("schema_version")
    total_map = version in {3, QUALIFYING_SCHEMA_VERSION} and isinstance(states, Mapping)
    absent = str(receipt.get("bookmaker_state")) == str(BookmakerState.NOT_RETURNED)
    listed = {str(m) for m in receipt.get("markets_mapped") or []}

    if total_map:
        assert isinstance(states, Mapping)  # narrowed by `total_map`
        observed = {
            str(market)
            for market, state in states.items()
            if str(state) == str(MarketState.OBSERVED_MAPPED)
        }
        if observed and mapped <= 0:
            found.append("des marchés sont OBSERVED_MAPPED alors que selections_mapped vaut 0")
        if mapped > 0 and not observed:
            found.append(
                "selections_mapped > 0 alors qu'aucun marché n'est OBSERVED_MAPPED (carte totale)"
            )
        if absent and observed:
            found.append("bookmaker_state = NOT_RETURNED alors qu'un marché est OBSERVED_MAPPED")
        # Only when the receipt actually carries the projection. An absent
        # `markets_mapped` is silence, not a disagreement, and the structural
        # contract already treats every projection as optional — reading the two
        # differently made a receipt that simply omits one look self-contradictory.
        if "markets_mapped" in receipt and listed != observed:
            found.append(
                "markets_mapped ne coïncide pas avec les marchés OBSERVED_MAPPED de market_states"
            )
        freshness = receipt.get("freshness")
        ages = freshness if isinstance(freshness, Mapping) else {}
        for market in sorted(observed):
            if _counted(ages.get(market)) is None:
                found.append(
                    "un marché OBSERVED_MAPPED n'a pas d'âge de fraîcheur entier non négatif"
                )
                break
    elif mapped > 0 and isinstance(states, Mapping) and not states:
        found.append("selections_mapped > 0 sans aucun état de marché")

    if absent and listed:
        found.append("bookmaker_state = NOT_RETURNED alors que markets_mapped n'est pas vide")
    if (
        str(receipt.get("status")) in _LIVE_STATUSES
        and receipt.get("network_attempted") is not True
    ):
        found.append("statut live sans tentative réseau enregistrée")
    # The reciprocal invariant v4 lacked, and the one the final re-audit exploited: a
    # status that can only be reached by reading a response, on a receipt that does not
    # establish the provider was ever reached. Both fields are ours and signed, so one
    # of them is wrong and we cannot tell which.
    if str(receipt.get("status")) in RESPONSE_ASSERTING_STATUSES and not provider_was_reached(
        receipt
    ):
        found.append(
            "statut impliquant une réponse du fournisseur alors que l'atteinte du "
            "fournisseur n'est pas établie"
        )
    observed_credits = _plain_int(receipt.get("observed_credits"))
    accounted = _plain_int(receipt.get("accounted_credits"))
    if observed_credits is not None and accounted is not None and accounted < observed_credits:
        found.append("accounted_credits inférieur à observed_credits")
    return found


# ---------------------------------------------------------------------------
# Admissibility: is this receipt current evidence at all?
# ---------------------------------------------------------------------------
def _verifiable(receipt: Mapping[str, Any]) -> bool:
    """Of a schema whose fields we can read, and verified **before** it got here.

    v6 removed the signature check from this module. It used to call
    ``verify_receipt``, which fetched the secret from the environment and created the
    key file if it was missing — inside a function documented as pure, reached from
    :func:`evaluate`. Verification now happens once, in
    :func:`~.activation.audit_receipts`, and :func:`evaluate` refuses at its own door
    anything that is not a :class:`~.receipt_store.VerifiedReceipt`. What is left here
    is what this predicate always should have been: can these fields be read at all.
    """
    from .activation import SUPPORTED_SCHEMA_VERSIONS

    version = _plain_int(receipt.get("schema_version"))
    return version is not None and version in SUPPORTED_SCHEMA_VERSIONS


def currency_reason(receipt: Mapping[str, Any]) -> str:
    """Why this receipt is not evidence *of this protocol*, or ``""``.

    Only the version-and-date gate. Structural validity is a separate question,
    and keeping them separate is what stops a malformed paid call from vanishing
    out of the cost census — the mistake protocol v2 made.
    """
    if not _verifiable(receipt):
        return "stale_schema"
    if _plain_int(receipt.get("schema_version")) != QUALIFYING_SCHEMA_VERSION:
        return "stale_schema"
    if (
        _plain_int(receipt.get("qualification_protocol_version"))
        != PROVIDER_VALIDATION_PROTOCOL_VERSION
    ):
        return "other_protocol_version"
    if (
        _plain_int(receipt.get("provider_adapter_evidence_version"))
        != PROVIDER_ADAPTER_EVIDENCE_VERSION
    ):
        return "other_adapter_evidence_version"
    moment = _instant(receipt.get("recorded_at"))
    if moment is None:
        return "unusable_recorded_at"
    if moment.astimezone(UTC) < datetime.fromisoformat(QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC):
        return "before_effective_instant"
    return ""


def classify(receipt: Mapping[str, Any]) -> str:
    """``""`` when the receipt is usable evidence, otherwise the reason it is not.

    One receipt, one reason, in a fixed order of severity: unreadable, then out of
    version, then premature, then a pair we have never produced, then malformed,
    then self-contradictory. The reason is a taxonomy key, never a description of
    the receipt.

    The unknown pair comes before the structural verdict on purpose. Calling such a
    receipt "malformed" would blame its fields for a vocabulary we do not have.
    """
    reason = currency_reason(receipt)
    if reason:
        return reason
    if not admissible_phases(receipt):
        return "unknown_command_status_pair"
    if structural_faults(receipt):
        return "malformed_current_schema"
    if contradictions(receipt):
        return "self_contradictory"
    return ""


def mapping_observation_is_sound(receipt: Mapping[str, Any]) -> bool:
    """Whether this receipt really observed our parser map a live market.

    The single reading shared by the strict block and by
    ``activation status``'s ``mapping_freshness_proof`` /
    ``paid_activation_state``. Before v4 those dimensions asked only whether
    ``selections_mapped`` was above zero, so an ``AUTH_FAILED`` receipt, one whose
    bookmaker was ``NOT_RETURNED``, and one carrying the string ``"3"`` all
    reported ``OBTAINED_LIVE``.

    Deliberately **without** the version-and-date gate of :func:`currency_reason`.
    Qualification asks "is this evidence for the criteria we pre-registered", which
    a protocol bump legitimately resets. This asks "did the parser ever read a live
    market here", which a protocol bump does not unmake. Keeping them apart is what
    lets the older dimension stay a historical fact while the sixth block stays a
    pre-registered judgement.
    """
    command = _text(receipt.get("command")) or ""
    if command not in PAID_COMMANDS:
        return False
    status = _text(receipt.get("status")) or ""
    if status not in ADMISSIBLE_STATUSES_BY_COMMAND.get(command, frozenset()):
        return False
    if ReceiptPhase.CLASSIFIED not in admissible_phases(receipt):
        return False
    if structural_faults(receipt) or contradictions(receipt):
        return False
    if not provider_was_reached(receipt):
        return False
    if str(receipt.get("bookmaker_state")) != str(BookmakerState.OBSERVED):
        return False
    if _counted(receipt.get("selections_mapped"), minimum=1) is None:
        return False
    states = receipt.get("market_states")
    if not isinstance(states, Mapping):
        return False
    mapped = [
        str(market)
        for market, state in states.items()
        if str(state) == str(MarketState.OBSERVED_MAPPED)
    ]
    if not mapped:
        return False
    freshness = receipt.get("freshness")
    if not isinstance(freshness, Mapping):
        return False
    return any(
        (age := _counted(freshness.get(market))) is not None
        and age <= PROTOCOL_MAX_ODDS_AGE_SECONDS
        for market in mapped
    )


def admissible_for(receipt: Mapping[str, Any], criterion: Criterion) -> bool:
    """Whether this receipt is admissible evidence for this mapping criterion."""
    if classify(receipt):
        return False
    if str(receipt.get("command")) != criterion.command:
        return False
    if str(receipt.get("status")) not in ADMISSIBLE_STATUSES_BY_COMMAND.get(
        criterion.command, frozenset()
    ):
        return False
    if str(receipt.get("status")) in INADMISSIBLE_STATUSES:
        return False
    if not str(receipt.get("sport_key", "")).startswith(f"{criterion.sport_family}_"):
        return False
    # An established reach, not merely an attempted one: a mapped market is a claim
    # about a payload, and a payload that never arrived cannot have been parsed.
    if not provider_was_reached(receipt):
        return False
    # The scope says "observed bookmaker only", so the receipt has to say it too.
    # Under protocol v2 nothing checked this and the scope was a claim about a
    # field nobody read.
    if str(receipt.get("bookmaker_state")) != str(BookmakerState.OBSERVED):
        return False
    requested = _market_list(receipt.get("markets_requested")) or []
    if criterion.market not in requested:
        return False
    states = receipt.get("market_states")
    if not isinstance(states, Mapping):
        return False
    if str(states.get(criterion.market)) != str(MarketState.OBSERVED_MAPPED):
        return False
    if not criterion.requires_total_market_map:
        # A `core` call requests one market, so mapped selections *are* that
        # market's mapping — read strictly, never coerced.
        selections = _counted(receipt.get("selections_mapped"), minimum=1)
        if selections is None:
            return False
        if receipt.get("mapping_rejections"):
            return False
    freshness = receipt.get("freshness")
    if not isinstance(freshness, Mapping):
        return False
    age = _counted(freshness.get(criterion.market))
    if age is None:
        return False
    return age <= PROTOCOL_MAX_ODDS_AGE_SECONDS


def cost_conforming(receipt: Mapping[str, Any]) -> bool:
    """Whether this receipt establishes a conforming cost, in its own terms.

    Not "any paid receipt that is not a mismatch". A cost is established when the
    request demonstrably went out, the provider's own count came back readable and
    within the command's contractual ceiling, and what we account for equals what
    was observed. A cost we merely assumed after a timeout is a spend record, not
    evidence about billing.
    """
    command = str(receipt.get("command"))
    if command not in PAID_COMMANDS:
        return False
    if structural_faults(receipt) or contradictions(receipt):
        return False
    if str(receipt.get("status")) not in COST_ESTABLISHING_STATUSES:
        return False
    if receipt.get("network_attempted") is not True:
        return False
    if receipt.get("may_have_reached_provider") is not True:
        return False
    ceiling = STEP_CEILINGS[command]
    estimated = _counted(receipt.get("estimated_credits"))
    observed = _counted(receipt.get("observed_credits"))
    accounted = _counted(receipt.get("accounted_credits"))
    if estimated is None or observed is None or accounted is None:
        return False
    if estimated > ceiling or observed > ceiling:
        return False
    return accounted == observed


#: The six cost buckets of protocol v6, and the four that gate the criterion. Named
#: after what they establish rather than after what the request did, because that is the
#: question ``COST_CONFORMITY`` asks — and named so that no population claims in its own
#: name a fact its members do not carry.
COST_BUCKETS: tuple[str, ...] = (
    "provider_reached_conforming_cost",
    "provider_reached_nonconforming_cost",
    # v6 splits v5's single unestablished bucket. Its name asserted that the provider
    # had been reached, and two of its three feeders were exactly the receipts where the
    # reach was *not* established — an absent or mistyped flag. A population may not
    # affirm in its own name a fact its members deny.
    "provider_reached_cost_unestablished",
    "provider_reach_unestablished",
    "paid_attempt_state_unestablished",
    "confirmed_attempts_not_sent",
)

#: The buckets that must be empty for the criterion to pass. ``confirmed_attempts_not_
#: sent`` is deliberately absent: a request confirmed never to have been issued did
#: not measure the provider's tariff, so it must neither help the threshold nor
#: invalidate six calls that really were served and really were conforming (D-075).
BLOCKING_COST_BUCKETS: tuple[str, ...] = (
    "provider_reached_nonconforming_cost",
    "provider_reached_cost_unestablished",
    "provider_reach_unestablished",
    "paid_attempt_state_unestablished",
)


#: Which couples a real command path actually persists, and which are answers the
#: contract owes without any producer writing them. v5 kept one hand-written list of
#: "producible" couples, checked against ``build_receipt`` called directly — which is
#: why it declared ``discover/SCHEMA_MISMATCH``, that nothing writes, and missed
#: ``discover/COST_UNVERIFIED`` and ``discover/COST_MISMATCH``, that ``run_discovery``
#: writes through ``_settle_cost``. The two lists are published so a test can compare
#: them with what the CLI really leaves on disk, in both directions.
#:
#: ``plan`` is the whole of the second list: :func:`~.activation.build_receipt` accepts
#: the command and the contract must have an answer for a planted plan receipt, but no
#: CLI path persists one — ``plan`` costs nothing, touches nothing and writes nothing.
NON_PERSISTED_COUPLES: tuple[tuple[str, str], ...] = (
    # `plan` computes and prints; no CLI path persists a receipt for it at all.
    ("plan", str(ActivationStatus.PLAN_ONLY)),
    ("plan", str(ActivationStatus.PREPARED_NOT_EXECUTED)),
    # A refusal *before* the wire writes nothing, deliberately: inventing a consumption
    # record for a call that never happened is the same error as losing the record of one
    # that did. So `PREPARED_NOT_EXECUTED` is a status the harness reports and never a
    # receipt it files — the contract still owes an answer for a planted one, and the
    # bidirectional test in the v6 suite is what proved this list wrong when it claimed
    # otherwise.
    ("discover", str(ActivationStatus.PREPARED_NOT_EXECUTED)),
    ("core", str(ActivationStatus.PREPARED_NOT_EXECUTED)),
    ("additional", str(ActivationStatus.PREPARED_NOT_EXECUTED)),
)

PERSISTED_COUPLES: tuple[tuple[str, str], ...] = tuple(
    couple for couple in RECEIPT_PHASES if couple not in NON_PERSISTED_COUPLES
)

#: Published because they are quoted in the protocol, the runbook and the pull request,
#: and a number quoted from memory is how "19 couples" survived three tranches.
RECEIPT_COUPLE_COUNT = len(RECEIPT_PHASES)
RECEIPT_FORM_COUNT = sum(len(phases) for phases in RECEIPT_PHASES.values())


def is_paid_command(receipt: Mapping[str, Any]) -> bool:
    """Whether this receipt belongs to a step that can be billed at all.

    Through :func:`command_state`, so ``" core "`` and ``Core`` are not paid steps that
    slipped out of the census — they are receipts whose command is not established, and
    the structural contract says so.
    """
    return command_state(receipt) in {CommandState.CORE, CommandState.ADDITIONAL}


def cost_category(receipt: Mapping[str, Any]) -> str:
    """Which single cost bucket a **current** paid step belongs to, or ``""``.

    Exhaustive and disjoint over paid steps, and derived from the three-valued
    :func:`attempt_state` rather than from ``is not False``. A step that was never
    attempted is outside the census — not a defect, just not a paid call. A step whose
    attempt state cannot be established stays *in* the census and blocks, because a
    receipt that cannot say whether it spent a credit is not evidence that it did not.
    """
    if not is_paid_command(receipt):
        return ""
    state = attempt_state(receipt)
    if state is AttemptState.NOT_ATTEMPTED:
        return ""
    if state is AttemptState.ATTEMPT_STATE_UNESTABLISHED:
        return "paid_attempt_state_unestablished"
    if receipt.get("may_have_reached_provider") is False:
        # Confirmed issued and confirmed *not* served. It observed no tariff, so it
        # neither helps the threshold nor invalidates six calls that were served —
        # which is only defensible because both flags are exact booleans (D-075).
        return "confirmed_attempts_not_sent"
    if receipt.get("may_have_reached_provider") is not True:
        # Issued, and unable to say whether it was served. Its own population, named for
        # what is missing: v5 filed it under a name beginning `provider_reached_`, which
        # asserted the very thing the flag failed to establish.
        return "provider_reach_unestablished"
    if str(receipt.get("status")) in _NONCONFORMING_COST_STATUSES:
        return "provider_reached_nonconforming_cost"
    if cost_conforming(receipt):
        return "provider_reached_conforming_cost"
    return "provider_reached_cost_unestablished"


def canonical(receipts: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """One entry per distinct signed receipt, in first-seen order.

    Every semantic reading runs over this collection. A receipt copied byte for byte
    into seven files is one observation, one paid call, one credit and one coverage
    answer — v4 deduplicated it for the mapping thresholds and for
    ``conforming_paid_calls`` only, so seven copies of a single ``COST_MISMATCH``
    reported sixty-three credits spent and seven nonconforming calls, and seven copies
    of one event produced seven coverage observations.

    Physical file counts remain available, under names that say they are physical.
    """
    from .activation import SIGNATURE_FIELD

    seen: set[tuple[str, str]] = set()
    out: list[Mapping[str, Any]] = []
    for receipt in receipts:
        identity = (str(receipt.get("receipt_id") or ""), str(receipt.get(SIGNATURE_FIELD)))
        if identity in seen:
            continue
        seen.add(identity)
        out.append(receipt)
    return out


# ---------------------------------------------------------------------------
# Diversity, deduplication and thresholds
# ---------------------------------------------------------------------------
def _observed_diversity(receipts: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Distinct events, competitions and UTC days, after deduplication.

    The same event looked at twice is one event — otherwise diversity is inflated
    by repetition, which is the cheapest way to fake a campaign.
    """
    events: set[str] = set()
    competitions: set[str] = set()
    days: set[str] = set()
    for receipt in receipts:
        tag = str(receipt.get("event_tag") or "")
        if tag:
            events.add(tag)
        sport = str(receipt.get("sport_key") or "")
        if sport:
            competitions.add(sport)
        day = utc_day(receipt.get("recorded_at"))
        if day:
            days.add(day)
    return {"events": len(events), "competitions": len(competitions), "utc_days": len(days)}


def _dedupe(receipts: Iterable[Mapping[str, Any]], market: str) -> list[Mapping[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    out: list[Mapping[str, Any]] = []
    for receipt in receipts:
        identity = (
            str(receipt.get("receipt_id") or ""),
            str(receipt.get("sport_key") or ""),
            str(receipt.get("event_tag") or ""),
            str(receipt.get("bookmaker") or ""),
            market,
            str(receipt.get("recorded_at") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        out.append(receipt)
    return out


def _missing(observed: Mapping[str, int], required: Mapping[str, int]) -> list[str]:
    labels = {
        "events": "événements distincts",
        "competitions": "compétitions distinctes",
        "utc_days": "jours UTC distincts",
    }
    return [
        f"{labels[key]} : {observed.get(key, 0)}/{need}"
        for key, need in required.items()
        if need and observed.get(key, 0) < need
    ]


def _cost_result(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Five buckets, one per paid step, and three of them must be empty.

    The census runs over the **canonical** current paid receipts — v4 schema, this
    protocol, this adapter, postdated, one entry per distinct signed receipt — whether
    or not they are well formed. Malformed included, deliberately: a malformed paid call
    is exactly one whose cost cannot be established, and letting it disappear is how v2
    reported "0 nonconforming" about a call nobody could account for.

    Deduplicated for **every** bucket, not just the conforming one. Under v4 the other
    three counted files, so seven copies of one receipt reported seven nonconforming
    calls against a threshold that must be zero.
    """
    buckets = dict.fromkeys(COST_BUCKETS, 0)
    for receipt in canonical(receipts):
        if category := cost_category(receipt):
            buckets[category] += 1

    required = {
        "provider_reached_conforming_cost": COST_CONFORMITY.min_events,
        **dict.fromkeys(BLOCKING_COST_BUCKETS, 0),
    }
    labels = {
        "provider_reached_nonconforming_cost": "appels servis au coût non conforme",
        "provider_reached_cost_unestablished": "appels servis au coût non établi",
        "provider_reach_unestablished": "pas payants dont l'atteinte n'est pas établie",
        "paid_attempt_state_unestablished": "pas payants à l'état de tentative non établi",
    }
    missing: list[str] = []
    if buckets["provider_reached_conforming_cost"] < COST_CONFORMITY.min_events:
        missing.append(
            "appels servis au coût établi et conforme : "
            f"{buckets['provider_reached_conforming_cost']}/{COST_CONFORMITY.min_events}"
        )
    for name in BLOCKING_COST_BUCKETS:
        if buckets[name]:
            missing.append(f"{labels[name]} : {buckets[name]} (maximum 0)")
    return {
        "criterion_id": COST_CONFORMITY.criterion_id,
        "passed": not missing,
        "observed": buckets,
        "required": required,
        "missing": missing,
        "scope": (
            "tous sports · pas payants du protocole courant, dédupliqués · coût observé "
            "et comptabilisé chez un fournisseur réellement atteint"
        ),
        "limit": COST_CONFORMITY.limit,
    }


def _divergent_identifiers(receipts: Sequence[Mapping[str, Any]]) -> set[str]:
    """Identifiers carried by two verified receipts whose signed bytes differ.

    A receipt id is meant to name one receipt. Two byte-identical copies are one
    observation and deduplicate cleanly; two *different* receipts under one id mean
    the corpus is inconsistent, and neither can be trusted to speak for it.

    Run over **every** verified receipt, not just the already-usable ones. Under v3
    it saw the usable sub-population only, so a usable receipt and a malformed,
    contradictory or historical one sharing an identifier looked like a single
    unambiguous fact — the narrower the population, the easier the collision was to
    miss.
    """
    from .activation import SIGNATURE_FIELD

    seen: dict[str, set[str]] = {}
    for receipt in receipts:
        identifier = str(receipt.get("receipt_id") or "")
        seen.setdefault(identifier, set()).add(str(receipt.get(SIGNATURE_FIELD)))
    return {identifier for identifier, signatures in seen.items() if len(signatures) > 1}


def observed_phases(receipt: Mapping[str, Any]) -> frozenset[ReceiptPhase]:
    """Which of its admissible phases this receipt's fields actually satisfy.

    Used to compare the catalogue against the producer: a couple may declare two
    honest forms, and a given receipt is in exactly one of them.
    """
    return frozenset(
        phase for phase in admissible_phases(receipt) if not _phase_faults(receipt, phase)
    )


def rejection_reason(receipt: Mapping[str, Any], *, divergent: frozenset[str] | set[str]) -> str:
    """Why this receipt may feed no semantic counter, or ``""``.

    Four ways to be unreadable, and they are all *shape*, not currency: a receipt from
    an earlier protocol is historical, which is a different thing — the money it
    records was really spent, so it still counts in the census and in the credit total
    while qualifying nothing.
    """
    if str(receipt.get("receipt_id") or "") in divergent:
        return "duplicate_receipt_identifier"
    if not admissible_phases(receipt):
        return "unknown_command_status_pair"
    if structural_faults(receipt):
        return "malformed_current_schema"
    if contradictions(receipt):
        return "self_contradictory"
    return ""


def semantic_receipts(receipts: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The receipts that may feed a published semantic counter.

    One reading, shared by :func:`evaluate` and
    :func:`~.activation.build_activation_state`, so the strict block and the five
    reported dimensions cannot disagree about which receipts are readable. Until v5 a
    rejected receipt still fed the cost census, the connectivity label,
    ``execution_state`` and ``paid_activation_state`` — while the pull request claimed
    it fed no semantic counter at all.
    """
    divergent = _divergent_identifiers(receipts)
    return [r for r in receipts if not rejection_reason(r, divergent=divergent)]


class QualificationInputInvalid(CountInvalid):
    """A scalar handed to :func:`evaluate` is not the count it claims to be."""


def _exact_qualification_count(value: object, field: str) -> int:
    """An exact, non-negative count, or a refusal naming the field and not the value."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QualificationInputInvalid(
            f"{field} est un compte : un entier Python exact, positif ou nul. Ni "
            "booléen, ni flottant, ni chaîne, ni None — « je ne sais pas combien » ne "
            "vaut pas « il n'y en a pas »."
        )
    return value


# ---------------------------------------------------------------------------
# The campaign ledger — what was really spent, against what was authorised
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CampaignLedger:
    """What the receipts on this boundary say about the pre-registered campaign.

    The static audit 03C-2D bis measured why this type exists. Until protocol 8 the
    campaign's bounds were a prose table and :func:`campaign_budget`, a pure
    derivation of constants that read no receipt: nine discoveries and a conforming
    nine-receipt corpus published *identical* values in every field that could have
    separated them. Nothing counted, so nothing could refuse.

    Every field is derived from verified receipts of **this** protocol. A receipt
    stamped with an earlier one — the empty Ligue 1 discovery of protocol 7, for
    instance — is history: it stays on disk, stays signed, and counts here in nothing.
    """

    counts_state: CampaignCountsState
    #: ``None`` whenever ``counts_state`` is ``UNESTABLISHED``. Never a zero standing
    #: in for a count nobody could take.
    counts: dict[str, int] | None
    execution_state: CampaignExecutionState
    #: Empty unless the campaign stopped; then, which command and which status.
    abort_reason: str
    #: Ways the corpus disagrees with the manifest. Each one is an evidence conflict.
    conflicts: tuple[str, ...]
    #: Why no count could be taken. Deliberately **not** an evidence conflict: « the
    #: count is not established » is already published as ``UNESTABLISHED``, and the
    #: pre-network guard refuses on it. Turning it into a conflict as well would make
    #: one unreadable file in a directory rewrite the verdict on every other receipt.
    unestablished_reason: str
    #: The scopes already consumed, so the guard can refuse a repeat without
    #: re-reading the directory.
    discovered: tuple[str, ...]
    #: Each discovered competition's event tags, **in the canonical order the discovery
    #: published them**. This is how a rank in the register becomes an event: the guard
    #: reads rank *r* of the competition rather than « the r-th core receipt found »,
    #: which would depend on a tie-break between two receipts of the same second.
    discovered_tags: dict[str, tuple[str, ...]]
    core_by_family: dict[str, int]
    additional_by_competition: dict[str, int]
    used_event_tags: dict[str, tuple[str, ...]]
    #: The ``(command, competition)`` of each campaign receipt, oldest first. This is
    #: what :func:`campaign_next_step` compares with :data:`CAMPAIGN_SEQUENCE`: the
    #: counts alone say *how many* invocations happened and never *in which order*, and
    #: the register is an order.
    recorded: tuple[tuple[str, str], ...] = ()

    @property
    def established(self) -> bool:
        return self.counts_state is CampaignCountsState.ESTABLISHED and self.counts is not None

    @property
    def stopped(self) -> bool:
        """Whether no further network command may be authorised on this boundary."""
        return self.execution_state in (
            CampaignExecutionState.ABORTED,
            CampaignExecutionState.CONFLICT,
            CampaignExecutionState.UNESTABLISHED,
        )


def _unestablished_ledger(reason: str) -> CampaignLedger:
    return CampaignLedger(
        counts_state=CampaignCountsState.UNESTABLISHED,
        counts=None,
        execution_state=CampaignExecutionState.UNESTABLISHED,
        abort_reason="",
        conflicts=(),
        unestablished_reason=reason,
        discovered=(),
        discovered_tags={},
        core_by_family={},
        additional_by_competition={},
        used_event_tags={},
    )


def campaign_receipts(receipts: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The deduplicated receipts of **this** protocol that name a campaign command.

    ``currency_reason`` is what separates them from history: it checks the schema, the
    protocol, the adapter-evidence version and the effective instant in one place, so
    the campaign and the criteria agree on which receipts belong to this campaign.
    """
    return [
        receipt
        for receipt in canonical(receipts)
        if currency_reason(receipt) == ""
        and (_text(receipt.get("command")) or "") in CAMPAIGN_COMMANDS
    ]


def campaign_ledger(audit: AuditResult, *, unresolved_intents: int = 0) -> CampaignLedger:
    """Count the campaign from its receipts, or say honestly that it cannot be counted.

    Pure: it reads the audit result it is given and nothing else — no clock, no
    environment, no file, no HMAC. The boundary state travels inside the result, so an
    unreadable directory produces ``UNESTABLISHED`` here rather than a confident zero.
    """
    receipts = require_audited(audit)
    unresolved_intents = _exact_qualification_count(unresolved_intents, "unresolved_intents")
    if audit.boundary is BoundaryState.UNAVAILABLE:
        return _unestablished_ledger(
            "La frontière du répertoire de reçus n'a pas pu être lue sans ambiguïté : "
            "aucune invocation de campagne n'est comptée, ni à la hausse ni à la baisse."
        )
    if audit.unverifiable:
        return _unestablished_ledger(
            f"{audit.unverifiable} fichier(s) du répertoire n'ont pas pu être vérifiés : "
            "le compte des invocations de campagne n'est pas établi."
        )
    if unresolved_intents:
        return _unestablished_ledger(
            f"{unresolved_intents} intent(s) de tentative non résolu(s) : une invocation a "
            "pu partir sans laisser de reçu, donc le compte n'est pas établi."
        )

    mine = campaign_receipts(receipts)
    unreadable = [receipt for receipt in mine if classify(receipt)]
    if unreadable:
        return _unestablished_ledger(
            f"{len(unreadable)} reçu(s) du protocole courant portent une commande de "
            "campagne sans être lisibles : le compte des invocations n'est pas établi."
        )

    counts = dict.fromkeys(CAMPAIGN_COMMANDS, 0)
    discovered: list[str] = []
    discovered_tags: dict[str, tuple[str, ...]] = {}
    core_by_family: dict[str, int] = {}
    additional_by_competition: dict[str, int] = {}
    used: dict[str, list[str]] = {command: [] for command in CAMPAIGN_COMMANDS}
    recorded: list[tuple[str, str]] = []
    conflicts: list[str] = []
    abort_reason = ""
    abort_at: datetime | None = None

    # Ordered by instant, then by the only order the steps can have happened in. Two
    # receipts can share a ``recorded_at`` — a same-second chain, a clock of one-second
    # resolution — and a plain sort then falls back to whatever order the directory was
    # listed in, which for ``…-core-…`` and ``…-discover-…`` at the same stamp is
    # alphabetical and therefore backwards. The register is read from this order, so an
    # arbitrary tie-break would report a conforming campaign as out of order.
    ordered = sorted(
        mine,
        key=lambda receipt: (
            str(receipt.get("recorded_at") or ""),
            CAMPAIGN_COMMANDS.index(_text(receipt.get("command")) or ""),
        ),
    )
    for receipt in ordered:
        command = _text(receipt.get("command")) or ""
        sport = _text(receipt.get("sport_key")) or ""
        status = _text(receipt.get("status")) or ""
        counts[command] += 1
        recorded.append((command, sport))

        if (_text(receipt.get("bookmaker")) or "") != CAMPAIGN_BOOKMAKER:
            conflicts.append(
                f"reçu {command} hors manifeste : la campagne v8 n'autorise que le "
                f"bookmaker {CAMPAIGN_BOOKMAKER}"
            )
        if sport not in campaign_scopes_for(command):
            conflicts.append(
                f"reçu {command} hors manifeste : {sport} n'est pas une compétition "
                f"autorisée pour cette commande"
            )

        if command == "discover":
            if sport in discovered:
                conflicts.append(
                    f"deuxième découverte de {sport} : une compétition ne se découvre "
                    "qu'une fois, et un échec ne rouvre pas sa place"
                )
            discovered.append(sport)
            # A tuple as readily as a list: a verified receipt freezes its sequences,
            # and a reader that only knew about lists would silently publish « this
            # competition discovered nothing » for every real receipt.
            raw_tags = receipt.get("event_tags")
            discovered_tags[sport] = (
                tuple(tag for tag in raw_tags if isinstance(tag, str))
                if isinstance(raw_tags, list | tuple)
                else ()
            )
        elif command == "core":
            family = campaign_family(sport)
            core_by_family[family] = core_by_family.get(family, 0) + 1
            if family and core_by_family[family] > CAMPAIGN_CORE_PER_FAMILY:
                conflicts.append(
                    f"{core_by_family[family]} appels core pour la famille {family} : "
                    f"le plafond préenregistré est {CAMPAIGN_CORE_PER_FAMILY}"
                )
        else:
            additional_by_competition[sport] = additional_by_competition.get(sport, 0) + 1
            if additional_by_competition[sport] > CAMPAIGN_ADDITIONAL_PER_COMPETITION:
                conflicts.append(
                    f"{additional_by_competition[sport]} appels additional sur {sport} : "
                    f"le plafond préenregistré est {CAMPAIGN_ADDITIONAL_PER_COMPETITION}"
                )

        tag = _text(receipt.get("event_tag"))
        if tag is not None and command in ("core", "additional"):
            if tag in used[command]:
                conflicts.append(
                    f"deux appels {command} sur le même événement : un événement déjà "
                    "utilisé ne rapproche d'aucun seuil et n'était pas autorisé deux fois"
                )
            used[command].append(tag)

        moment = _instant(receipt.get("recorded_at"))
        if abort_at is not None and moment is not None and moment.astimezone(UTC) > abort_at:
            conflicts.append(
                "reçu de campagne postérieur à l'abandon : la campagne v8 était arrêtée "
                "et aucune commande réseau ne pouvait plus être autorisée"
            )
        if status not in CAMPAIGN_SUCCESS_STATUSES[command] and not abort_reason:
            abort_reason = (
                f"la commande {command} a publié {status} au lieu du statut de succès "
                f"attendu ; la campagne v8 est abandonnée et ne se relance pas"
            )
            abort_at = moment.astimezone(UTC) if moment is not None else None

    for command, limit in CAMPAIGN_INVOCATION_LIMITS.items():
        if counts[command] > limit:
            conflicts.append(
                f"{counts[command]} invocations {command} : le plafond préenregistré est "
                f"{limit}, et un dépassement n'est pas un détail comptable"
            )

    if conflicts:
        execution = CampaignExecutionState.CONFLICT
    elif abort_reason:
        execution = CampaignExecutionState.ABORTED
    elif counts == CAMPAIGN_INVOCATION_LIMITS:
        execution = CampaignExecutionState.COMPLETE
    elif any(counts.values()):
        execution = CampaignExecutionState.IN_PROGRESS
    else:
        execution = CampaignExecutionState.NOT_STARTED

    return CampaignLedger(
        counts_state=CampaignCountsState.ESTABLISHED,
        counts=counts,
        execution_state=execution,
        abort_reason=abort_reason,
        conflicts=tuple(dict.fromkeys(conflicts)),
        unestablished_reason="",
        discovered=tuple(discovered),
        discovered_tags=discovered_tags,
        core_by_family=core_by_family,
        additional_by_competition=additional_by_competition,
        used_event_tags={command: tuple(tags) for command, tags in used.items()},
        recorded=tuple(recorded),
    )


def campaign_next_step(ledger: CampaignLedger) -> CampaignStep | None:
    """Which step of the register comes next, or ``None`` when nothing may be said.

    ``None`` is a real answer and never a synonym for « step one ». It is returned when
    the count is not established, when the campaign is stopped or finished, and — the
    case that matters — when what is on disk is **not a prefix of the register**: a
    corpus that ran the steps in another order is not a campaign that is somewhere in
    this one, and inventing a position for it would be the guard choosing on the
    operator's behalf from evidence that already contradicts the plan.
    """
    # Two reasons, each carried by exactly one check. An allow-list of NOT_STARTED and
    # IN_PROGRESS would have excluded ``UNESTABLISHED`` as well, and the count check
    # above it would then have been dead: a mutation run removed it and every test
    # stayed green, because the neighbour was answering in its place. One rule, one
    # guard, so that disabling either is visible.
    if not ledger.established:
        return None
    if ledger.execution_state in (
        CampaignExecutionState.COMPLETE,
        CampaignExecutionState.ABORTED,
        CampaignExecutionState.CONFLICT,
    ):
        return None
    done = len(ledger.recorded)
    if done >= len(CAMPAIGN_SEQUENCE):
        return None
    expected = tuple((step.command, step.sport) for step in CAMPAIGN_SEQUENCE[:done])
    if ledger.recorded != expected:
        return None
    return CAMPAIGN_SEQUENCE[done]


def campaign_block(ledger: CampaignLedger) -> dict[str, Any]:
    """The thirteen published fields, in one place so two reports cannot disagree."""
    step = campaign_next_step(ledger)
    return {
        "campaign_protocol_version": PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "campaign_counts_state": str(ledger.counts_state),
        "campaign_invocation_counts": dict(ledger.counts) if ledger.counts is not None else None,
        "campaign_invocation_limits": dict(CAMPAIGN_INVOCATION_LIMITS),
        "campaign_execution_state": str(ledger.execution_state),
        "campaign_abort_reason": ledger.abort_reason,
        "campaign_required_bookmaker": CAMPAIGN_BOOKMAKER,
        "campaign_required_scopes": {
            family: list(scopes) for family, scopes in CAMPAIGN_SCOPES.items()
        },
        # The next step, published rather than left to be worked out from the counts.
        # All five are ``None`` together: « the campaign is finished », « it is stopped »
        # and « what is on disk is not this campaign » are not a step, and must not be
        # readable as one.
        "campaign_next_step_index": step.index if step is not None else None,
        "campaign_next_command": step.command if step is not None else None,
        "campaign_next_scope": step.sport if step is not None else None,
        "campaign_next_event_rank": step.event_rank if step is not None else None,
        "campaign_next_parent_step": step.parent_step if step is not None else None,
    }


def evaluate(
    audit: AuditResult,
    *,
    unresolved_intents: int = 0,
) -> dict[str, Any]:
    """Judge one audit of the receipt directory against the pre-registered criteria. Pure.

    The argument is the **result of an audit**, not a list. v6 took a batch and a
    number, and any caller could supply both: ``[VerifiedReceipt(payload) for payload in
    forged]`` satisfied its ``isinstance`` check and reached
    ``CRITERIA_MET_AWAITING_HUMAN_REVIEW``, and the number could be anything at all.
    :class:`~.receipt_store.AuditResult` now has no public constructor and no subclass,
    and this function checks exact type identity, so in the supported pipeline the way
    to reach it is to have had a real directory read and its receipts' HMAC verified.

    Per **D-078**, that is a guard against ordinary misuse of the application code, not
    a barrier against arbitrary Python running in this process: whoever can execute code
    here can equally replace this function or read the signing secret. Authenticity is
    carried by the HMAC :func:`~.receipt_store.audit_directory` checks at ingestion.

    That result also carries the **boundary state**, which v6 dropped on the floor. An
    ``UNAVAILABLE`` boundary is an evidence conflict here: the counts it came with are
    not established, so nothing may be concluded from them in either direction.

    ``unresolved_intents`` is the number of attempts whose local intent — written and
    ``fsync``-ed *before* the request — has not been resolved by the durable
    publication of its receipt. Each one means a request may have left and may have
    been billed without leaving a proof, so each one is an evidence conflict. It is
    an exact, non-negative Python integer: ``True`` is not one, ``None`` and ``False``
    are not zero, and a string is not a count. « I do not know how many » must never
    read as « there are none » for a blocker.

    Pure, and provably so: no environment, no clock, no file, no HMAC, no network.
    """
    receipts = require_audited(audit)
    unverifiable = _exact_qualification_count(audit.unverifiable, "unverifiable")
    unresolved_intents = _exact_qualification_count(unresolved_intents, "unresolved_intents")
    reasons = dict.fromkeys(QUALIFICATION_REASONS, 0)
    current: list[Mapping[str, Any]] = []
    usable: list[Mapping[str, Any]] = []
    populations = dict.fromkeys(
        (
            "usable",
            "current_malformed",
            "current_contradictory",
            "unknown_pair",
            "historical_nonqualifying",
            "duplicate_excluded",
            "unverifiable",
        ),
        0,
    )
    conflicts: list[str] = []
    malformed_fields: set[str] = set()

    #: Computed over every verified receipt before anything is filed, so a
    #: collision between two *different* sub-populations is still a collision.
    divergent = _divergent_identifiers(receipts)

    #: Every semantic reading below — populations, criteria, cost census, reasons —
    #: runs over this collection, so a receipt copied into seven files is one
    #: observation everywhere rather than in some places only.
    distinct = canonical(receipts)
    physical_copies = len(receipts) - len(distinct)

    for receipt in distinct:
        if str(receipt.get("receipt_id") or "") in divergent:
            # Exclusive, and first: an identifier naming two different receipts
            # makes both unusable whatever else they are. Counting them under
            # their own reason as well would double-count them in the equation.
            reasons["duplicate_receipt_identifier"] += 1
            populations["duplicate_excluded"] += 1
            continue
        if currency_reason(receipt) == "":
            # Current for this protocol. Whether it is well formed is the next
            # question, and the cost census needs it either way.
            current.append(receipt)
        reason = classify(receipt)
        if not reason:
            usable.append(receipt)
            populations["usable"] += 1
            continue
        reasons[reason] += 1
        if reason == "unverified_or_unknown_schema":
            populations["unverifiable"] += 1
        elif reason == "malformed_current_schema":
            # Current, and wrong. Filing it under "historical" — as v3 did — read
            # as "produced under an older protocol", which is the opposite of true.
            populations["current_malformed"] += 1
            malformed_fields.update(structural_faults(receipt))
        elif reason == "self_contradictory":
            populations["current_contradictory"] += 1
            conflicts.extend(contradictions(receipt))
        elif reason == "unknown_command_status_pair":
            populations["unknown_pair"] += 1
            conflicts.append(
                "reçu courant portant un couple commande/statut absent de la table "
                "de phases du protocole ; sa forme n'a jamais été spécifiée"
            )
        else:
            populations["historical_nonqualifying"] += 1

    if malformed_fields:
        conflicts.append(
            "reçu courant structurellement invalide — champ(s) hors contrat : "
            + ", ".join(sorted(malformed_fields))
        )
    if divergent:
        conflicts.append(
            f"{len(divergent)} identifiant(s) de reçu portent des contenus signés différents ; "
            "tous les reçus concernés sont écartés des critères"
        )
    if audit.boundary is BoundaryState.UNAVAILABLE:
        conflicts.append(
            "La frontière du répertoire de reçus n'a pas pu être lue sans ambiguïté "
            f"(catégorie : {audit.reason}) : aucun compte de reçus n'est établi, donc "
            "aucune conclusion — ni positive ni négative — n'est tirée de cette lecture."
        )
    if unresolved_intents:
        conflicts.append(
            f"{unresolved_intents} intent(s) de tentative non résolu(s) : une requête a pu "
            "partir sans que sa preuve soit publiée durablement, donc le corpus est "
            "incomplet d'une manière que rien sur ce disque ne permet de chiffrer"
        )

    #: The campaign is evidence about itself. A corpus that exceeds a pre-registered
    #: ceiling, names a bookmaker nobody authorised or files a receipt after the
    #: campaign stopped is not weak evidence to be discounted: it disagrees with what
    #: we said we would do, and v7 could not even see it.
    ledger = campaign_ledger(audit, unresolved_intents=unresolved_intents)
    conflicts.extend(ledger.conflicts)

    results: list[dict[str, Any]] = []
    for criterion in CRITERIA:
        if criterion is COST_CONFORMITY:
            results.append(_cost_result(semantic_receipts(current)))
            continue
        evidence = _dedupe((r for r in usable if admissible_for(r, criterion)), criterion.market)
        observed = _observed_diversity(evidence)
        missing = _missing(observed, criterion.required)
        results.append(
            {
                "criterion_id": criterion.criterion_id,
                "passed": not missing,
                "observed": observed,
                "required": criterion.required,
                "missing": missing,
                "scope": criterion.scope,
                "limit": criterion.limit,
            }
        )

    if conflicts:
        state = QualificationState.EVIDENCE_CONFLICT
    elif all(entry["passed"] for entry in results):
        state = QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
    else:
        state = QualificationState.INSUFFICIENT_EVIDENCE

    return {
        "qualification_protocol_version": PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "qualification_adapter_evidence_version": PROVIDER_ADAPTER_EVIDENCE_VERSION,
        "qualification_evidence_not_before": QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC,
        "qualification_state": str(state),
        "criteria_results": results,
        # The gate, and only the gate. Reaching it authorises a conversation.
        "eligible_for_human_promotion_review": (
            state is QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        ),
        "evidence_conflicts": conflicts,
        # Kept under its original name as well: it is the number the runbook and
        # D-071 already publish, and renaming a counter mid-protocol makes two
        # reports incomparable for no gain.
        "qualification_admissible_receipts": len(usable),
        "qualification_usable_receipts": populations["usable"],
        "qualification_current_malformed_receipts": populations["current_malformed"],
        "qualification_current_contradictory_receipts": populations["current_contradictory"],
        "qualification_unknown_pair_receipts": populations["unknown_pair"],
        "qualification_historical_nonqualifying_receipts": populations["historical_nonqualifying"],
        "qualification_duplicate_excluded_receipts": populations["duplicate_excluded"],
        "qualification_unverifiable_receipts": unverifiable + populations["unverifiable"],
        # A crossed dimension, not a population: an exact copy stays in whichever
        # population its content belongs to. Stated so the equation above cannot be
        # read as if duplicates had been removed from it.
        "qualification_exact_duplicate_copies": physical_copies,
        "qualification_population_equation": (
            "reçus vérifiés + fichiers invérifiables = utilisables + courants malformés + "
            "courants contradictoires + couples inconnus + historiques non qualifiants + "
            "exclus pour identifiant divergent + invérifiables + copies exactes"
        ),
        "qualification_reasons": reasons,
        **campaign_block(ledger),
        "campaign_note": (
            "Les plafonds de la campagne v8 sont désormais comptés à partir des reçus "
            "vérifiés du protocole courant, et refusés avant réseau. Aucun compte n'est "
            "publié tant qu'il n'est pas établi ; un dépassement est un conflit de preuve, "
            "pas un détail comptable. Rien ici ne promeut l'adaptateur."
        ),
        "qualification_note": (
            "Aucun statut n'est promu ici. Le maximum atteignable est "
            "CRITERIA_MET_AWAITING_HUMAN_REVIEW ; la promotion de l'adaptateur reste "
            "une décision humaine distincte."
        ),
    }


def summary_lines(document: Mapping[str, Any]) -> list[str]:
    """The qualification block, rendered for a terminal. No colour, no ANSI."""
    lines = [
        "",
        f"Qualification (protocole v{document['qualification_protocol_version']}, "
        f"preuve adaptateur v{document['qualification_adapter_evidence_version']}) : "
        f"{document['qualification_state']}",
        f"Preuve admise à partir de {document['qualification_evidence_not_before']}",
        f"Reçus : {document['qualification_usable_receipts']} utilisables, "
        f"{document['qualification_current_malformed_receipts']} courants malformés, "
        f"{document['qualification_current_contradictory_receipts']} courants contradictoires, "
        f"{document['qualification_unknown_pair_receipts']} couples inconnus, "
        f"{document['qualification_historical_nonqualifying_receipts']} historiques non "
        f"qualifiants, {document['qualification_duplicate_excluded_receipts']} exclus pour "
        f"identifiant divergent, "
        f"{document['qualification_unverifiable_receipts']} non vérifiables",
        f"Équation : {document['qualification_population_equation']}",
        f"Copies byte-à-byte identiques (dimension croisée) : "
        f"{document['qualification_exact_duplicate_copies']}",
        f"Revue humaine de promotion : "
        f"{'ouverte' if document['eligible_for_human_promotion_review'] else 'non'}",
    ]
    for entry in document["criteria_results"]:
        mark = "ok " if entry["passed"] else "manque"
        detail = "; ".join(entry["missing"]) if entry["missing"] else "seuils atteints"
        lines.append(f"  · {entry['criterion_id']:<40} {mark:<6} {detail}")
    for reason, count in document["qualification_reasons"].items():
        if count:
            lines.append(f"  · non qualifiant — {reason:<34} {count}")
    for conflict in document["evidence_conflicts"]:
        lines.append(f"  ! conflit de preuve : {conflict}")
    return lines
