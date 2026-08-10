"""Pre-registered criteria for deciding when live evidence would be *enough*.

The gap this closes is not a missing observation. It is that nothing said, in
advance, how much live evidence would justify asking a human to promote the
adapter. Without that, any result can be read as encouraging: two `core` calls
that found no coverage were once summarised as an activation that "worked".

Protocol **v2**. The first version of D-071 claimed three properties it did not
enforce, and an independent read-only audit reproduced all of them. What changed,
and why each change is a property rather than a preference:

* **Fixed.** The freshness threshold is the literal
  :data:`PROTOCOL_MAX_ODDS_AGE_SECONDS`. v1 read the product's runtime
  `max_odds_age_seconds`, so an operator's `.env` silently moved the
  "pre-registered" bound while the version number stayed at 1 — in the direction
  that matters, since raising it lets a stale quote support a freshness claim.
  This module now reads no configuration at all.
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

Three properties are unchanged and still hold:

* **Pure.** :func:`evaluate` takes a list of already-verified receipts and returns
  a document. No network, no key, no clock, no configuration, no receipt is
  written or modified.
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
    verify_receipt,
)

#: Bump this when a threshold, a scope, an admissibility rule or the effective
#: instant changes. Results computed under one version are not comparable with
#: another, which is the whole reason the number exists: a criterion quietly
#: relaxed after the fact is not a criterion.
PROVIDER_VALIDATION_PROTOCOL_VERSION = 3

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
#: D-073 and `docs/provider-validation-protocol.md`. Evidence recorded before it
#: is history, never qualification. Never recomputed at runtime, never read from
#: the environment: a date that moves is not an effective date.
QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC = "2026-08-10T07:19:48+00:00"

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

_NONCONFORMING_COST_STATUSES = frozenset(
    {str(ActivationStatus.COST_MISMATCH), str(ActivationStatus.COST_UNVERIFIED)}
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
    "unverified_or_unknown_schema",
)


class QualificationState(StrEnum):
    """Everything this module is allowed to conclude.

    Deliberately three values and deliberately no ``VERIFIED``. Promotion is a
    human decision taken against a written record; a program that can write the
    word has already taken it.
    """

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    CRITERIA_MET_AWAITING_HUMAN_REVIEW = "CRITERIA_MET_AWAITING_HUMAN_REVIEW"


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
    schema versions it accepts — under protocol v2 every qualifying receipt is
    v4. A per-market criterion needs the total ``market_states`` map to know *one
    named market's* state; a core criterion reads ``selections_mapped``, because a
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
            "événements observés. N'établit rien sur un bookmaker, une compétition "
            "non observée, une autre date ou un autre marché."
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
    """A duplicate-free list of non-empty strings, or ``None``.

    Not a string — iterating one yields characters, which is how a mistyped
    ``markets_mapped`` used to sneak past a set comparison.
    """
    if not isinstance(value, list):
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
def structural_faults(receipt: Mapping[str, Any]) -> list[str]:
    """The **names** of the fields a current receipt gets wrong. Never their values.

    A valid signature establishes that these bytes are ours and unaltered. It says
    nothing about whether ``network_attempted`` is a boolean or the string
    ``"false"``. So before any field is read as evidence, the receipt must satisfy
    a positive contract; a field outside it is named, and the receipt qualifies
    nothing and blocks the gate.

    Command-aware on purpose: ``discover`` carries ``event_tags`` and no bookmaker
    observation — demanding one would flag a perfectly good discovery receipt.
    """
    faults: list[str] = []

    def require(condition: object, field: str) -> None:
        if not condition:
            faults.append(field)

    for field in (
        "schema_version",
        "qualification_protocol_version",
        "provider_adapter_evidence_version",
    ):
        require(_counted(receipt.get(field)) is not None, field)
    for field in ("estimated_credits", "accounted_credits"):
        require(_counted(receipt.get(field)) is not None, field)
    for field in ("observed_credits", "quota_remaining"):
        value = receipt.get(field)
        require(value is None or _counted(value) is not None, field)
    if "attempts" in receipt:
        require(_counted(receipt.get("attempts")) is not None, "attempts")
    for field in ("network_attempted", "may_have_reached_provider"):
        require(receipt.get(field) is True or receipt.get(field) is False, field)
    for field in ("receipt_id", "sport_key", "command", "status"):
        require(_text(receipt.get(field)) is not None, field)
    require(_instant(receipt.get("recorded_at")) is not None, "recorded_at")

    command = str(receipt.get("command") or "")
    if command == "discover":
        require(_market_list(receipt.get("event_tags")) is not None, "event_tags")
        for field in ("events_returned", "events_in_window", "events_admissible"):
            if field in receipt:
                require(_counted(receipt.get(field)) is not None, field)
        return faults

    require(_text(receipt.get("bookmaker")) is not None, "bookmaker")
    require(_text(receipt.get("event_tag")) is not None, "event_tag")
    require(str(receipt.get("bookmaker_state")) in KNOWN_BOOKMAKER_STATES, "bookmaker_state")
    require(_counted(receipt.get("selections_mapped")) is not None, "selections_mapped")
    require(isinstance(receipt.get("mapping_rejections"), list), "mapping_rejections")

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
        # v4's map is *total* over the markets the call requested. A key on either
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
    return sorted(set(faults))


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
        if listed != observed:
            found.append(
                "markets_mapped ne coïncide pas avec les marchés OBSERVED_MAPPED de market_states"
            )
        freshness = receipt.get("freshness")
        ages = freshness if isinstance(freshness, Mapping) else {}
        for market in sorted(observed):
            if _counted(ages.get(market)) is None:
                found.append("un marché OBSERVED_MAPPED n'a pas d'âge de fraîcheur entier positif")
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
    observed_credits = _plain_int(receipt.get("observed_credits"))
    accounted = _plain_int(receipt.get("accounted_credits"))
    if observed_credits is not None and accounted is not None and accounted < observed_credits:
        found.append("accounted_credits inférieur à observed_credits")
    return found


# ---------------------------------------------------------------------------
# Admissibility: is this receipt current evidence at all?
# ---------------------------------------------------------------------------
def _verifiable(receipt: Mapping[str, Any]) -> bool:
    """Signed with our secret, and of a schema whose fields we can read."""
    from .activation import SUPPORTED_SCHEMA_VERSIONS

    version = _plain_int(receipt.get("schema_version"))
    if version is None or version not in SUPPORTED_SCHEMA_VERSIONS:
        return False
    return verify_receipt(receipt)


def currency_reason(receipt: Mapping[str, Any]) -> str:
    """Why this receipt is not evidence *of this protocol*, or ``""``.

    Only the version-and-date gate. Structural validity is a separate question,
    and keeping them separate is what stops a malformed paid call from vanishing
    out of the cost census — the mistake protocol v2 made.
    """
    if not _verifiable(receipt):
        return "unverified_or_unknown_schema"
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
    version, then premature, then malformed, then self-contradictory. The reason is
    a taxonomy key, never a description of the receipt.
    """
    reason = currency_reason(receipt)
    if reason:
        return reason
    if structural_faults(receipt):
        return "malformed_current_schema"
    if contradictions(receipt):
        return "self_contradictory"
    return ""


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
    if receipt.get("network_attempted") is not True:
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
    if structural_faults(receipt):
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


def cost_category(receipt: Mapping[str, Any]) -> str:
    """Which single cost bucket a **current** paid receipt belongs to.

    Exactly one, deterministically, and never none: protocol v2 let a paid call
    that was neither conforming nor explicitly a mismatch fall out of the census
    entirely, so the report read "0 nonconforming" about a call whose cost nobody
    could establish.
    """
    if str(receipt.get("command")) not in PAID_COMMANDS:
        return ""
    if str(receipt.get("status")) in _NONCONFORMING_COST_STATUSES:
        return "nonconforming_paid_calls"
    if receipt.get("may_have_reached_provider") is not True:
        return "paid_calls_that_never_left"
    if cost_conforming(receipt):
        return "conforming_paid_calls"
    return "paid_calls_with_unestablished_cost"


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
    """Four buckets, one per paid receipt, and three of them must be empty.

    The census runs over every **current** paid receipt — v4, this protocol, this
    adapter, postdated — whether or not it is well formed. That is deliberate: a
    malformed paid call is exactly one whose cost cannot be established, and the
    v2 version of this function let it disappear instead.
    """
    buckets = {
        "conforming_paid_calls": 0,
        "nonconforming_paid_calls": 0,
        "paid_calls_with_unestablished_cost": 0,
        "paid_calls_that_never_left": 0,
    }
    conforming: list[Mapping[str, Any]] = []
    for receipt in receipts:
        category = cost_category(receipt)
        if not category:
            continue
        if category == "conforming_paid_calls":
            conforming.append(receipt)
            continue
        buckets[category] += 1
    buckets["conforming_paid_calls"] = len(_dedupe(conforming, "*"))

    required = {
        "conforming_paid_calls": COST_CONFORMITY.min_events,
        "nonconforming_paid_calls": 0,
        "paid_calls_with_unestablished_cost": 0,
    }
    missing: list[str] = []
    if buckets["conforming_paid_calls"] < required["conforming_paid_calls"]:
        missing.append(
            "appels payants au coût établi : "
            f"{buckets['conforming_paid_calls']}/{required['conforming_paid_calls']}"
        )
    if buckets["nonconforming_paid_calls"]:
        missing.append(
            f"appels au coût non conforme : {buckets['nonconforming_paid_calls']} (maximum 0)"
        )
    if buckets["paid_calls_with_unestablished_cost"]:
        missing.append(
            "appels payants au coût non établi : "
            f"{buckets['paid_calls_with_unestablished_cost']} (maximum 0)"
        )
    return {
        "criterion_id": COST_CONFORMITY.criterion_id,
        "passed": not missing,
        "observed": buckets,
        "required": required,
        "missing": missing,
        "scope": "tous sports · appels payants · coût observé et comptabilisé",
        "limit": COST_CONFORMITY.limit,
    }


def _divergent_identifiers(receipts: Sequence[Mapping[str, Any]]) -> set[str]:
    """Identifiers carried by two current receipts whose signed bytes differ.

    A receipt id is meant to name one receipt. Two byte-identical copies are one
    observation and deduplicate cleanly; two *different* receipts under one id mean
    the corpus is inconsistent, and neither can be trusted to speak for it.
    """
    from .activation import SIGNATURE_FIELD

    seen: dict[str, set[str]] = {}
    for receipt in receipts:
        identifier = str(receipt.get("receipt_id") or "")
        seen.setdefault(identifier, set()).add(str(receipt.get(SIGNATURE_FIELD)))
    return {identifier for identifier, signatures in seen.items() if len(signatures) > 1}


def evaluate(receipts: Sequence[Mapping[str, Any]], unverifiable: int) -> dict[str, Any]:
    """Judge a list of receipts against the pre-registered criteria. Pure.

    ``unverifiable`` is passed in rather than recomputed: the caller already
    counted the files that failed signature or schema verification, and those must
    appear in the report without ever being read as evidence. It is reported under
    a ``qualification_``-prefixed name so it can never overwrite the D-062 audit
    counter of the same meaning but different provenance.
    """
    reasons = dict.fromkeys(QUALIFICATION_REASONS, 0)
    current: list[Mapping[str, Any]] = []
    usable: list[Mapping[str, Any]] = []
    historical = 0
    refused = 0
    conflicts: list[str] = []
    malformed_fields: set[str] = set()

    for receipt in receipts:
        if currency_reason(receipt) == "":
            # Current for this protocol. Whether it is well formed is the next
            # question, and the cost census needs it either way.
            current.append(receipt)
        reason = classify(receipt)
        if not reason:
            usable.append(receipt)
            continue
        reasons[reason] += 1
        if reason == "unverified_or_unknown_schema":
            refused += 1
            continue
        historical += 1
        if reason == "self_contradictory":
            conflicts.extend(contradictions(receipt))
        elif reason == "malformed_current_schema":
            malformed_fields.update(structural_faults(receipt))

    if malformed_fields:
        conflicts.append(
            "reçu courant structurellement invalide — champ(s) hors contrat : "
            + ", ".join(sorted(malformed_fields))
        )

    divergent = _divergent_identifiers(usable)
    if divergent:
        excluded = [r for r in usable if str(r.get("receipt_id") or "") in divergent]
        reasons["duplicate_receipt_identifier"] += len(excluded)
        usable = [r for r in usable if str(r.get("receipt_id") or "") not in divergent]
        current = [r for r in current if str(r.get("receipt_id") or "") not in divergent]
        conflicts.append(
            f"{len(divergent)} identifiant(s) de reçu portent des contenus signés différents ; "
            "tous les reçus concernés sont écartés des critères"
        )

    results: list[dict[str, Any]] = []
    for criterion in CRITERIA:
        if criterion is COST_CONFORMITY:
            results.append(_cost_result(current))
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
        "qualification_admissible_receipts": len(usable),
        "qualification_historical_nonqualifying_receipts": historical,
        "qualification_unverifiable_receipts": unverifiable + refused,
        "qualification_reasons": reasons,
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
        f"Reçus : {document['qualification_admissible_receipts']} admissibles, "
        f"{document['qualification_historical_nonqualifying_receipts']} historiques non "
        f"qualifiants, {document['qualification_unverifiable_receipts']} non vérifiables",
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
