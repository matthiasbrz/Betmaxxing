"""Pre-registered criteria for deciding when live evidence would be *enough*.

The gap this closes is not a missing observation. It is that nothing said, in
advance, how much live evidence would justify asking a human to promote the
adapter. Without that, any result can be read as encouraging: two `core` calls
that found no coverage were once summarised as an activation that "worked".

So the thresholds live here, versioned, and they were written before the calls
they judge. Three properties make that claim checkable:

* **Pure.** :func:`evaluate` takes a list of already-verified receipts and returns
  a document. No network, no key, no clock, no receipt is written or modified.
* **Closed.** Evidence that is ambiguous, unsigned, of an unknown schema, or
  internally contradictory is refused and counted, never interpreted generously.
* **Bounded above.** The best conclusion available to this module is
  ``CRITERIA_MET_AWAITING_HUMAN_REVIEW``. There is no ``VERIFIED``, and
  ``adapter_state`` stays ``IMPLEMENTED_UNVERIFIED`` whatever the outcome.

What the criteria establish is narrow: that our parser read the provider's real
payload for a named market, in a named sport, across enough independently
generated events to distinguish the endpoint's shape from one lucky response. It
says nothing about any bookmaker's coverage beyond the events actually observed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from betmaxxing.config import Settings

from .activation import (
    ADDITIONAL_MARKETS,
    SUPPORTED_SCHEMA_VERSIONS,
    ActivationStatus,
    BookmakerState,
    MarketState,
    verify_receipt,
)

#: Bump this when a threshold, a scope or an admissibility rule changes. Results
#: computed under one version are not comparable with another, which is the whole
#: reason the number exists: a criterion quietly relaxed after the fact is not a
#: criterion.
PROVIDER_VALIDATION_PROTOCOL_VERSION = 1

#: A quote older than this is not decision-usable, so a mapping observed on one
#: cannot support a freshness claim. Anchored on the product's own staleness
#: threshold rather than invented here — if the scan calls a snapshot stale, the
#: qualification protocol must not call the same snapshot fresh.
MAX_QUALIFYING_AGE_SECONDS = Settings().max_odds_age_seconds

#: Live schema v3 only, for anything that reads `market_states`. See `Criterion`.
_TOTAL_MARKET_MAP_VERSION = 3


class QualificationState(StrEnum):
    """Everything this module is allowed to conclude.

    Deliberately three values and deliberately no ``VERIFIED``. Promotion is a
    human decision taken against a written record; a program that can write the
    word has already taken it.
    """

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    CRITERIA_MET_AWAITING_HUMAN_REVIEW = "CRITERIA_MET_AWAITING_HUMAN_REVIEW"


#: Outcomes that can never support a positive criterion. A failure is a fact
#: about the attempt, not evidence about the parser.
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

_PAID_COMMANDS = frozenset({"core", "additional"})


@dataclass(frozen=True)
class Criterion:
    """One falsifiable claim, with its scope and its thresholds fixed in advance.

    ``requires_total_market_map`` is what keeps v2 honest. A v2 receipt's
    ``market_states`` was partial — empty when the bookmaker was absent — so it
    cannot establish *one named market's* state. It can still establish that the
    parser mapped something, because ``selections_mapped`` means the same in both
    versions. So v2 counts for the core criteria and never for the per-market
    ones, which is narrower than refusing v2 outright and honest about why.
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
            f"bookmaker observé uniquement · âge ≤ {MAX_QUALIFYING_AGE_SECONDS}s"
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
        # catches a stamp that is only correct on the day it was generated.
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
        "Six appels payants conformes — le sous-produit exact de la campagne core "
        "— et zéro appel non conforme. Un seul écart de coût suffit à faire échouer "
        "le critère."
    ),
    limit=(
        "Établit que le coût observé a été conforme ou prudemment comptabilisé sur "
        "les appels faits. N'établit aucune garantie de facturation future."
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
# Admissibility
# ---------------------------------------------------------------------------
def _int(value: object) -> int:
    """A receipt field read as an integer, or zero. Never raises on odd input."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _utc_day(raw: object) -> str:
    """The UTC calendar day of an ISO instant, or an empty string if unusable."""
    if not isinstance(raw, str):
        return ""
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return ""
    if moment.tzinfo is None:
        return ""
    return moment.date().isoformat()


def contradictions(receipt: Mapping[str, Any]) -> list[str]:
    """Internal inconsistencies that make a receipt unusable as evidence.

    A receipt that disagrees with itself is not weak evidence to be discounted —
    it means one of its fields is wrong and we cannot tell which. The protocol
    fails closed on it and names it, rather than picking the convenient reading.
    """
    found: list[str] = []
    mapped = _int(receipt.get("selections_mapped"))
    states = receipt.get("market_states")
    version = receipt.get("schema_version")
    if (
        version == _TOTAL_MARKET_MAP_VERSION
        and mapped > 0
        and isinstance(states, Mapping)
        and str(MarketState.OBSERVED_MAPPED) not in {str(v) for v in states.values()}
    ):
        found.append(
            "selections_mapped > 0 alors qu'aucun marché n'est OBSERVED_MAPPED "
            "(schéma v3, carte totale)"
        )
    if str(receipt.get("bookmaker_state")) == str(BookmakerState.NOT_RETURNED) and mapped > 0:
        found.append("bookmaker_state = NOT_RETURNED alors que des sélections sont cartographiées")
    if str(receipt.get("status")) in _LIVE_STATUSES and not receipt.get("network_attempted"):
        found.append("statut live sans tentative réseau enregistrée")
    observed = receipt.get("observed_credits")
    if observed is not None and _int(receipt.get("accounted_credits")) < _int(observed):
        found.append("accounted_credits inférieur à observed_credits")
    return found


def _verifiable(receipt: Mapping[str, Any]) -> bool:
    """Signed with our secret, and of a schema whose fields we can read."""
    if receipt.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        return False
    return verify_receipt(receipt)


def _mapping_evidence(receipt: Mapping[str, Any], criterion: Criterion) -> bool:
    """Whether this receipt is admissible evidence for this mapping criterion."""
    if str(receipt.get("command")) != criterion.command:
        return False
    if not str(receipt.get("sport_key", "")).startswith(f"{criterion.sport_family}_"):
        return False
    if str(receipt.get("status")) in INADMISSIBLE_STATUSES:
        return False
    if not receipt.get("network_attempted"):
        return False
    if criterion.requires_total_market_map:
        if receipt.get("schema_version") != _TOTAL_MARKET_MAP_VERSION:
            return False
        states = receipt.get("market_states")
        if not isinstance(states, Mapping):
            return False
        if str(states.get(criterion.market)) != str(MarketState.OBSERVED_MAPPED):
            return False
    else:
        # A `core` call requests one market, so mapped selections *are* that
        # market's mapping — the one property v2 can still establish.
        if _int(receipt.get("selections_mapped")) <= 0:
            return False
        if receipt.get("mapping_rejections"):
            return False
    freshness = receipt.get("freshness")
    if not isinstance(freshness, Mapping):
        return False
    age = freshness.get(criterion.market)
    if not isinstance(age, int) or isinstance(age, bool):
        return False
    return 0 <= age <= MAX_QUALIFYING_AGE_SECONDS


def _observed_diversity(receipts: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Distinct events, competitions and UTC days, after deduplication.

    Deduplication is by the pre-registered identity: the receipt itself, then the
    tagged event, market scope, bookmaker, sport and instant of observation. The
    same event looked at twice is one event — otherwise diversity is inflated by
    repetition, which is the cheapest way to fake a campaign.
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
        day = _utc_day(receipt.get("recorded_at"))
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
    paid = [r for r in receipts if str(r.get("command")) in _PAID_COMMANDS]
    nonconforming = [r for r in paid if str(r.get("status")) in _NONCONFORMING_COST_STATUSES]
    conforming = [r for r in paid if r not in nonconforming and r.get("network_attempted")]
    observed = {
        "conforming_paid_calls": len(_dedupe(conforming, "*")),
        "nonconforming_paid_calls": len(nonconforming),
    }
    required = {
        "conforming_paid_calls": COST_CONFORMITY.min_events,
        "nonconforming_paid_calls": 0,
    }
    missing: list[str] = []
    if observed["conforming_paid_calls"] < required["conforming_paid_calls"]:
        missing.append(
            "appels payants conformes : "
            f"{observed['conforming_paid_calls']}/{required['conforming_paid_calls']}"
        )
    if observed["nonconforming_paid_calls"]:
        missing.append(
            f"appels au coût non conforme : {observed['nonconforming_paid_calls']} (maximum 0)"
        )
    return {
        "criterion_id": COST_CONFORMITY.criterion_id,
        "passed": not missing,
        "observed": observed,
        "required": required,
        "missing": missing,
        "scope": "tous sports · appels payants · coût observé et comptabilisé",
        "limit": COST_CONFORMITY.limit,
    }


def evaluate(receipts: Sequence[Mapping[str, Any]], unverifiable: int) -> dict[str, Any]:
    """Judge a list of receipts against the pre-registered criteria. Pure.

    ``unverifiable`` is passed in rather than recomputed: the caller already
    counted the files that failed signature or schema verification, and those
    must appear in the report without ever being read as evidence.
    """
    usable = [r for r in receipts if _verifiable(r)]
    refused = len(receipts) - len(usable)

    conflicts: list[str] = []
    for receipt in usable:
        conflicts.extend(contradictions(receipt))

    results: list[dict[str, Any]] = []
    admissible_total = 0
    for criterion in CRITERIA:
        if criterion is COST_CONFORMITY:
            results.append(_cost_result(usable))
            continue
        evidence = _dedupe((r for r in usable if _mapping_evidence(r, criterion)), criterion.market)
        admissible_total += len(evidence)
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
        "qualification_state": str(state),
        "criteria_results": results,
        # The gate, and only the gate. Reaching it authorises a conversation.
        "eligible_for_human_promotion_review": (
            state is QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        ),
        "evidence_conflicts": conflicts,
        "admissible_observations": admissible_total,
        "unverifiable_receipts": unverifiable + refused,
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
        f"Qualification (protocole v{document['qualification_protocol_version']}) : "
        f"{document['qualification_state']}",
        f"Revue humaine de promotion : "
        f"{'ouverte' if document['eligible_for_human_promotion_review'] else 'non'}",
    ]
    for entry in document["criteria_results"]:
        mark = "ok " if entry["passed"] else "manque"
        detail = "; ".join(entry["missing"]) if entry["missing"] else "seuils atteints"
        lines.append(f"  · {entry['criterion_id']:<40} {mark:<6} {detail}")
    for conflict in document["evidence_conflicts"]:
        lines.append(f"  ! conflit de preuve : {conflict}")
    return lines
