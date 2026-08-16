"""Protocol v5: a proof of a response requires a response.

The final read-only re-audit of protocol v4 reproduced one P1 and five P2. The P1 is
the one that matters most: the human-review gate was reachable while *every* mapping
observation in the corpus carried ``may_have_reached_provider = False`` — a signed
assertion that the request demonstrably never reached the provider. v4 read that flag
for the cost census and nowhere else, so `OBTAINED_LIVE` and a passing
`CORE_MAPPING_FOOTBALL` could rest on receipts that said no response could have
arrived. The strictest-looking value was the only one that got through: an absent or
mistyped flag was caught as malformed, an explicit ``False`` was not.

The five P2 were: `additional` short-circuiting the inconclusive paid state; exact
byte-identical file copies inflating credits, the cost census, coverage observations
and blocking buckets; a ``*_LIVE_VERIFIED`` receipt with an empty market scope being
structurally valid and counting as a conforming cost; the words "real", "attempted"
and "executed" derived from an absent network flag; and an interrupted write leaving
an empty file that permanently blocked its own receipt id under a message that
misdescribed the cause.

So v5 adds three ideas to v4: **a reached provider is a precondition of every claim
about a response**, **the attempt state is a three-valued reading** rather than a
``is not False`` test, and **semantics are read from a canonical deduplicated
collection** while physical file counts live in their own named counters.

Every receipt here is synthetic and locally signed; nothing opens a socket, and no
real receipt or key is read.
"""

from __future__ import annotations

import json as jsonlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from betmaxxing.providers.the_odds_api import receipt_store as _store

#: Pinned literally, exactly as D-075 and the protocol publish it.
EFFECTIVE_INSTANT = "2026-08-10T14:00:37+00:00"

FOOTBALL = "soccer_france_ligue_one"
FOOTBALL_2 = "soccer_epl"
TENNIS = "tennis_atp_paris"
TENNIS_2 = "tennis_wta_madrid"
BOOK = "unibet"
D1 = datetime(2026, 8, 13, 12, tzinfo=UTC)
D2 = datetime(2026, 8, 14, 12, tzinfo=UTC)
D3 = datetime(2026, 8, 15, 12, tzinfo=UTC)
MARKETS = list(act.ADDITIONAL_MARKETS)
WINDOW = (D1, D1 + timedelta(hours=24))
SCRUB_SECRET = "ab" * 32

#: A value that is not a boolean, in every shape a JSON file can carry.
NOT_A_BOOLEAN: list[Any] = [None, "false", "true", 0, 1, [], {}]
ABSENT = object()


# `SCRUB_SECRET` is the *API key* this suite checks for redaction; the receipts are
# signed with the injected receipt secret the `workspace` fixture installs, which is what
# `audit_receipts` verifies them against.
from helpers_activation import FAKE_RECEIPT_SECRET as _SIGNING  # noqa: E402


# ---------------------------------------------------------------------------
# v6 provenance shim — see D-076
# ---------------------------------------------------------------------------
# `qualification.evaluate` and `build_activation_state` now require receipts whose
# signature has already been checked, because until v6 they checked it themselves and
# that dragged the secret — and a key file they created — into a module documented as
# pure. These two helpers mint that provenance the way `audit_receipts` does, so every
# assertion below keeps testing exactly what it tested before.
def _verify_with_secret(payload: Any) -> bool:
    """`verify_receipt` takes the secret explicitly since v6 (D-076)."""
    return act.verify_receipt(payload, _SIGNING)


def _tag_with_secret(event_id: str) -> str:
    """`event_tag` takes the secret explicitly since v6 (D-076)."""
    return act.event_tag(event_id, _SIGNING)


def _trusted(receipts: Any, unverifiable: int = 0) -> Any:
    """One real audit of a throwaway directory — see `helpers_receipt_boundary`.

    D-077: the provenance type has no public constructor and no key-taking factory, so
    a suite acquires evidence the way production does. Every assertion below is
    unchanged; only this function is.
    """
    from helpers_receipt_boundary import audited

    return audited(receipts, unverifiable, secret=_SIGNING)


def _evaluate(receipts: Any, unverifiable: int = 0, **kw: Any) -> Any:
    return qual.evaluate(_trusted(receipts, unverifiable), **kw)


def _state(receipts: Any, unverifiable: int = 0, **kw: Any) -> Any:
    return act.build_activation_state(_trusted(receipts, unverifiable), **kw)


@pytest.fixture(autouse=True)
def _signed_in_a_throwaway_directory(workspace: Path) -> Path:
    """Every receipt here is signed with the injected synthetic secret.

    Autouse because building a receipt signs it, and ``receipt_secret`` would
    otherwise create a signing key next to the working directory. A receipt signed
    under one secret and read under another is silently unverifiable, which would make
    every assertion below pass for the wrong reason.
    """
    return workspace


# ---------------------------------------------------------------------------
# Synthetic receipts
# ---------------------------------------------------------------------------
def core(**over: Any) -> dict[str, Any]:
    """A signed, current, well-formed `core` receipt: admissible by default."""
    moment: datetime = over.pop("moment", D1)
    drop: tuple[str, ...] = over.pop("drop", ())
    document: dict[str, Any] = {
        "schema_version": act.RECEIPT_SCHEMA_VERSION,
        "qualification_protocol_version": qual.PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "provider_adapter_evidence_version": qual.PROVIDER_ADAPTER_EVIDENCE_VERSION,
        "receipt_id": over.pop("receipt_id", "00" * 8),
        "command": "core",
        "status": str(act.ActivationStatus.CORE_LIVE_VERIFIED),
        "recorded_at": over.pop("recorded_at", moment.isoformat()),
        "expires_at": (moment + act.RECEIPT_TTL).isoformat(),
        "sport_key": FOOTBALL,
        "bookmaker": BOOK,
        "network_attempted": True,
        "may_have_reached_provider": True,
        "attempts": 1,
        "estimated_credits": 1,
        "observed_credits": 1,
        "accounted_credits": 1,
        "quota_remaining": 400,
        "markets_requested": ["h2h"],
        "market_states": {"h2h": str(act.MarketState.OBSERVED_MAPPED)},
        "markets_mapped": ["h2h"],
        "markets_observed": ["h2h"],
        "markets_rejected": [],
        "markets_absent": [],
        "markets_not_evaluated": [],
        "selections_mapped": 3,
        "freshness": {"h2h": 600},
        "mapping_rejections": [],
        "event_tag": over.pop("event_tag", "a" * 32),
        "bookmaker_state": str(act.BookmakerState.OBSERVED),
    }
    document.update(over)
    for name in drop:
        document.pop(name, None)
    document[act.SIGNATURE_FIELD] = act.sign_receipt(document, _SIGNING)
    return document


def extra(**over: Any) -> dict[str, Any]:
    """A signed `additional` receipt with all five markets mapped."""
    base: dict[str, Any] = {
        "command": "additional",
        "status": str(act.ActivationStatus.ADDITIONAL_LIVE_VERIFIED),
        "estimated_credits": 5,
        "observed_credits": 5,
        "accounted_credits": 5,
        "markets_requested": list(MARKETS),
        "market_states": dict.fromkeys(MARKETS, str(act.MarketState.OBSERVED_MAPPED)),
        "markets_mapped": list(MARKETS),
        "markets_observed": list(MARKETS),
        "selections_mapped": 11,
        "freshness": dict.fromkeys(MARKETS, 300),
    }
    base.update(over)
    return core(**base)


def partial(**over: Any) -> dict[str, Any]:
    """`ADDITIONAL_PARTIAL_COVERAGE`, exactly as `_additional_status` produces it."""
    base: dict[str, Any] = {
        "status": str(act.ActivationStatus.ADDITIONAL_PARTIAL_COVERAGE),
        "market_states": {
            **dict.fromkeys(MARKETS[:-1], str(act.MarketState.OBSERVED_MAPPED)),
            MARKETS[-1]: str(act.MarketState.NOT_RETURNED),
        },
        "markets_mapped": MARKETS[:-1],
        "markets_observed": MARKETS[:-1],
        "markets_absent": [MARKETS[-1]],
        "freshness": dict.fromkeys(MARKETS[:-1], 300),
        "selections_mapped": 9,
    }
    base.update(over)
    return extra(**base)


def coverage_missing(**over: Any) -> dict[str, Any]:
    """A `core` call that established a cost and no mapping whatsoever."""
    base: dict[str, Any] = {
        "status": str(act.ActivationStatus.COVERAGE_MISSING),
        "market_states": {"h2h": str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)},
        "markets_mapped": [],
        "markets_observed": [],
        "markets_not_evaluated": ["h2h"],
        "selections_mapped": 0,
        "freshness": {},
        "bookmaker_state": str(act.BookmakerState.NOT_RETURNED),
    }
    base.update(over)
    return core(**base)


def unclassified(**over: Any) -> dict[str, Any]:
    """A paid receipt whose markets were never classified."""
    base: dict[str, Any] = {
        "market_states": {},
        "markets_mapped": [],
        "markets_observed": [],
        "markets_rejected": [],
        "markets_absent": [],
        "markets_not_evaluated": [],
        "freshness": {},
        "selections_mapped": 0,
    }
    base.update(over)
    return core(**base)


MAPPING_ROWS = [
    (FOOTBALL, D1, "a"),
    (FOOTBALL_2, D2, "b"),
    (FOOTBALL, D2, "c"),
    (TENNIS, D1, "d"),
    (TENNIS_2, D2, "f"),
    (TENNIS, D3, "0"),
]


def threshold_corpus(**over: Any) -> list[dict[str, Any]]:
    """The minimal corpus that satisfies all eight criteria."""
    out = [
        core(receipt_id=f"{i:016x}", sport_key=k, moment=m, event_tag=t * 32, **over)
        for i, (k, m, t) in enumerate(MAPPING_ROWS, start=1)
    ]
    out.append(
        extra(receipt_id="aa" * 8, sport_key=FOOTBALL, moment=D1, event_tag="1" * 32, **over)
    )
    out.append(
        extra(receipt_id="bb" * 8, sport_key=FOOTBALL_2, moment=D2, event_tag="2" * 32, **over)
    )
    return out


def six_conforming_costs(**over: Any) -> list[dict[str, Any]]:
    """Six honest paid calls that establish a conforming cost and no mapping."""
    return [
        coverage_missing(receipt_id=f"c{i:015x}", moment=D1, event_tag=f"{i:032x}", **over)
        for i in range(1, 7)
    ]


def entry(document: dict[str, Any], criterion_id: str) -> dict[str, Any]:
    for candidate in document["criteria_results"]:
        if candidate["criterion_id"] == criterion_id:
            return candidate
    raise AssertionError(criterion_id)


def cost_of(document: dict[str, Any]) -> dict[str, Any]:
    return entry(document, "COST_CONFORMITY")


def passing(document: dict[str, Any]) -> list[str]:
    return sorted(e["criterion_id"] for e in document["criteria_results"] if e["passed"])


def write_all(
    directory: Path, receipts: list[dict[str, Any]], names: list[str] | None = None
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, receipt in enumerate(receipts, start=1):
        name = names[index - 1] if names else f"probe-{index:03d}.json"
        (directory / name).write_text(
            jsonlib.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )


def with_flag(make: Any, field: str, value: Any, **over: Any) -> dict[str, Any]:
    """One receipt with `field` set to `value`, or dropped when `value is ABSENT`."""
    fields = dict(over)
    if value is ABSENT:
        fields["drop"] = (*fields.get("drop", ()), field)
    else:
        fields[field] = value
    return make(**fields)


# ---------------------------------------------------------------------------
class TestTheProtocolIsVersionFive:
    def test_the_versioned_constants(self) -> None:
        """The pins that v5 introduced and v6 keeps. The protocol number itself is
        pinned exactly once, by the current suite, so a bump lands in one place."""
        assert qual.PROVIDER_VALIDATION_PROTOCOL_VERSION >= 5
        assert qual.PROVIDER_ADAPTER_EVIDENCE_VERSION == 1
        assert qual.QUALIFYING_SCHEMA_VERSION == 4
        assert act.RECEIPT_SCHEMA_VERSION == 4
        assert qual.PROTOCOL_MAX_ODDS_AGE_SECONDS == 900

    def test_the_effective_instant_has_advanced_since_this_protocol(self) -> None:
        """D-075's instant is history. What matters here is that it moved forward."""
        current = datetime.fromisoformat(qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC)
        assert current >= datetime.fromisoformat(EFFECTIVE_INSTANT)

    def test_protocol_four_evidence_is_now_historical(self) -> None:
        document = _evaluate(threshold_corpus(qualification_protocol_version=4), 0)
        assert passing(document) == []
        assert document["qualification_reasons"]["other_protocol_version"] == 8

    def test_a_current_well_formed_corpus_still_reaches_the_gate(self) -> None:
        document = _evaluate(threshold_corpus(), 0)
        assert passing(document) == sorted(c.criterion_id for c in qual.CRITERIA)
        assert document["eligible_for_human_promotion_review"] is True
        assert document["qualification_state"] == str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )


# ---------------------------------------------------------------------------
# P1-1 — no positive proof without an established provider reach
# ---------------------------------------------------------------------------
#: Every status that asserts a provider response was received and read.
RESPONSE_ASSERTING = [
    ("core/CORE_LIVE_VERIFIED", core, "CORE_MAPPING_FOOTBALL"),
    ("additional/ADDITIONAL_LIVE_VERIFIED", extra, "ADDITIONAL_MAPPING_FOOTBALL_DRAW_NO_BET"),
    ("additional/ADDITIONAL_PARTIAL_COVERAGE", partial, "ADDITIONAL_MAPPING_FOOTBALL_DRAW_NO_BET"),
    ("core/COVERAGE_MISSING classified", coverage_missing, None),
]


class TestPositiveProofRequiresAnEstablishedReach:
    """The P1 of the final re-audit: `may_have_reached_provider` was read for cost only."""

    @pytest.mark.parametrize(
        ("label", "make", "criterion_id"),
        RESPONSE_ASSERTING,
        ids=[r[0] for r in RESPONSE_ASSERTING],
    )
    def test_a_response_asserting_status_needs_reach_true(
        self, label: str, make: Any, criterion_id: str | None
    ) -> None:
        sound = make()
        assert qual.provider_was_reached(sound) is True, label
        for value in [False, ABSENT, *NOT_A_BOOLEAN]:
            receipt = with_flag(make, "may_have_reached_provider", value)
            assert qual.provider_was_reached(receipt) is False, (label, value)
            assert qual.classify(receipt) != "", (label, value)
            assert qual.mapping_observation_is_sound(receipt) is False, (label, value)
            if criterion_id:
                criterion = next(c for c in qual.CRITERIA if c.criterion_id == criterion_id)
                assert qual.admissible_for(receipt, criterion) is False, (label, value)

    def test_an_exact_false_is_a_contradiction_not_merely_non_qualifying(self) -> None:
        """v4 left this receipt well formed, usable, admissible and `OBTAINED_LIVE`."""
        receipt = core(may_have_reached_provider=False)
        assert qual.classify(receipt) == "self_contradictory"
        assert any("atteint" in c or "atteinte" in c for c in qual.contradictions(receipt))

    @pytest.mark.parametrize("value", [False, ABSENT, *NOT_A_BOOLEAN])
    def test_no_coverage_observation_is_attributed_without_reach(
        self, workspace: Path, value: Any
    ) -> None:
        write_all(workspace, [with_flag(core, "may_have_reached_provider", value)])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        document = _state(receipts, unverifiable)
        assert document["bookmaker_coverage_observations"] == []
        assert document["mapping_freshness_proof"] == str(act.MappingProof.NOT_OBTAINED_LIVE)
        assert document["paid_activation_state"] != str(
            act.PaidActivationState.CORE_EXECUTED_COVERAGE_OBSERVED
        )

    def test_the_p1_corpus_stays_under_the_gate(self, workspace: Path) -> None:
        """Eight mapping proofs saying the request never left, plus six honest costs.

        This exact corpus reached ``CRITERIA_MET_AWAITING_HUMAN_REVIEW`` under protocol
        v4: the mapping criteria read the flag not at all, and the cost criterion was
        satisfied by a separate, honest population.
        """
        corpus = [*threshold_corpus(may_have_reached_provider=False), *six_conforming_costs()]
        document = _evaluate(corpus, 0)
        assert document["eligible_for_human_promotion_review"] is False
        assert [
            c
            for c in qual.CRITERIA
            if entry(document, c.criterion_id)["passed"] and c.criterion_id != "COST_CONFORMITY"
        ] == []
        for criterion in qual.CRITERIA:
            if (
                criterion.criterion_id.endswith("_MAPPING_FOOTBALL")
                or "MAPPING" in criterion.criterion_id
            ):
                assert entry(document, criterion.criterion_id)["observed"]["events"] == 0
        write_all(workspace, corpus)
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        state = _state(receipts, unverifiable)
        assert state["eligible_for_human_promotion_review"] is False
        assert state["mapping_freshness_proof"] == str(act.MappingProof.NOT_OBTAINED_LIVE)

    def test_discovery_also_needs_a_reached_provider(self) -> None:
        discovered = {
            "command": "discover",
            "status": str(act.ActivationStatus.DISCOVERY_VERIFIED),
            "event_tags": ["d" * 32, "e" * 32],
            "events_returned": 5,
            "events_in_window": 3,
            "events_admissible": 2,
            "estimated_credits": 0,
            "observed_credits": 0,
            "accounted_credits": 0,
            "attempts": 2,
            "drop": ("event_tag", "bookmaker_state"),
        }
        assert qual.classify(core(**discovered)) == ""
        refused = dict(discovered)
        refused["may_have_reached_provider"] = False
        assert qual.classify(core(**refused)) == "self_contradictory"


# ---------------------------------------------------------------------------
# P2-4 — the attempt state is a three-valued reading
# ---------------------------------------------------------------------------
class TestTheAttemptStateHasThreeValues:
    def test_the_three_values_exist(self) -> None:
        values = {str(v) for v in qual.AttemptState}
        assert values == {"NOT_ATTEMPTED", "CONFIRMED_ATTEMPT", "ATTEMPT_STATE_UNESTABLISHED"}

    def test_a_confirmed_attempt_needs_a_true_flag_and_a_request(self) -> None:
        assert qual.attempt_state(core()) is qual.AttemptState.CONFIRMED_ATTEMPT
        assert qual.attempt_state(core(network_attempted=False, attempts=0)) is (
            qual.AttemptState.NOT_ATTEMPTED
        )

    @pytest.mark.parametrize("value", [ABSENT, *NOT_A_BOOLEAN])
    def test_an_absent_or_mistyped_flag_is_unestablished(self, value: Any) -> None:
        receipt = with_flag(core, "network_attempted", value)
        assert qual.attempt_state(receipt) is qual.AttemptState.ATTEMPT_STATE_UNESTABLISHED

    @pytest.mark.parametrize(
        ("network", "attempts"), [(True, 0), (False, 2), (True, "1"), (False, None)]
    )
    def test_an_incoherent_attempts_count_is_unestablished(
        self, network: Any, attempts: Any
    ) -> None:
        receipt = core(network_attempted=network, attempts=attempts)
        assert qual.attempt_state(receipt) is qual.AttemptState.ATTEMPT_STATE_UNESTABLISHED

    @pytest.mark.parametrize("value", [ABSENT, *NOT_A_BOOLEAN])
    def test_an_unestablished_state_is_never_called_attempted_or_executed(
        self, workspace: Path, value: Any
    ) -> None:
        write_all(workspace, [with_flag(core, "network_attempted", value)])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        document = _state(receipts, unverifiable)
        assert document["execution_state"] == str(
            act.ExecutionState.NETWORK_ATTEMPT_STATE_UNESTABLISHED
        )
        assert document["paid_activation_state"] == str(
            act.PaidActivationState.PAID_ATTEMPT_STATE_UNESTABLISHED
        )
        assert "ATTEMPTED" not in document["execution_state"].replace(
            "NETWORK_ATTEMPT_STATE_UNESTABLISHED", ""
        )
        assert "EXECUTED" not in document["paid_activation_state"]

    def test_the_published_population_never_says_a_real_attempt(self, workspace: Path) -> None:
        write_all(workspace, [core()])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        document = _state(receipts, unverifiable)
        label = document["paid_call_cost_census_population"]
        assert "réelle" not in label and "reelle" not in label
        assert "confirmée" in label or "confirmee" in label

    def test_an_unestablished_state_still_blocks_and_stays_visible(self) -> None:
        """It blocks and it is visible. D-076 moved *where* it is visible.

        An absent `network_attempted` is outside the structural contract, and since v6 a
        receipt the contract rejects feeds no semantic counter — so it is counted in the
        forensic census and named as an evidence conflict instead of being priced. It is
        still impossible to miss, and the gate is still shut.
        """
        unestablished = core(drop=("network_attempted",))
        document = _state([*six_conforming_costs(), unestablished], 0)
        assert document["rejected_paid_cost_census"]["paid_attempt_state_unestablished"] == 1
        assert document["rejected_paid_receipts"] == 1
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert document["eligible_for_human_promotion_review"] is False
        assert document["execution_state"] != "NO_NETWORK_ATTEMPTED"


# ---------------------------------------------------------------------------
# P2-1 — the paid state is symmetric between `core` and `additional`
# ---------------------------------------------------------------------------
def paid_state_rows(command: str) -> list[tuple[str, dict[str, Any]]]:
    """The eleven issues of the final re-audit table, for one paid command."""
    markets = list(MARKETS) if command == "additional" else ["h2h"]
    credits = 5 if command == "additional" else 1
    base: dict[str, Any] = {
        "command": command,
        "markets_requested": markets,
        "estimated_credits": credits,
        "observed_credits": credits,
        "accounted_credits": credits,
    }
    blank = dict(
        base,
        market_states={},
        markets_mapped=[],
        markets_observed=[],
        markets_rejected=[],
        markets_absent=[],
        markets_not_evaluated=[],
        freshness={},
        selections_mapped=0,
    )
    absent_book = dict(
        base,
        market_states=dict.fromkeys(markets, str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)),
        markets_mapped=[],
        markets_observed=[],
        markets_not_evaluated=markets,
        freshness={},
        selections_mapped=0,
        bookmaker_state=str(act.BookmakerState.NOT_RETURNED),
    )
    rejected = dict(
        base,
        market_states=dict.fromkeys(markets, str(act.MarketState.OBSERVED_REJECTED)),
        markets_mapped=[],
        markets_observed=markets,
        markets_rejected=markets,
        freshness=dict.fromkeys(markets, 300),
        selections_mapped=0,
        mapping_rejections=["motif generalise"],
    )
    mapped = dict(
        base,
        market_states=dict.fromkeys(markets, str(act.MarketState.OBSERVED_MAPPED)),
        markets_mapped=markets,
        markets_observed=markets,
        freshness=dict.fromkeys(markets, 300),
        selections_mapped=3,
        status=str(
            act.ActivationStatus.ADDITIONAL_LIVE_VERIFIED
            if command == "additional"
            else act.ActivationStatus.CORE_LIVE_VERIFIED
        ),
    )
    return [
        (
            "PREPARED_NOT_EXECUTED",
            dict(
                blank,
                status=str(act.ActivationStatus.PREPARED_NOT_EXECUTED),
                network_attempted=False,
                may_have_reached_provider=False,
                attempts=0,
                observed_credits=None,
                accounted_credits=0,
                drop=("event_tag",),
            ),
        ),
        (
            "PROVIDER_UNAVAILABLE not sent",
            dict(
                blank,
                status=str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
                may_have_reached_provider=False,
                observed_credits=None,
                accounted_credits=0,
            ),
        ),
        (
            "PROVIDER_UNAVAILABLE reached",
            dict(
                blank,
                status=str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
                observed_credits=None,
                accounted_credits=credits,
            ),
        ),
        (
            "AUTH_FAILED",
            dict(
                blank,
                status=str(act.ActivationStatus.AUTH_FAILED),
                observed_credits=None,
                accounted_credits=credits,
            ),
        ),
        (
            "COST_UNVERIFIED",
            dict(
                blank,
                status=str(act.ActivationStatus.COST_UNVERIFIED),
                observed_credits=None,
                accounted_credits=credits,
            ),
        ),
        (
            "COST_MISMATCH",
            dict(
                blank,
                status=str(act.ActivationStatus.COST_MISMATCH),
                observed_credits=credits + 4,
                accounted_credits=credits + 4,
            ),
        ),
        (
            "COVERAGE_MISSING unclassified",
            dict(blank, status=str(act.ActivationStatus.COVERAGE_MISSING)),
        ),
        (
            "COVERAGE_MISSING classified",
            dict(absent_book, status=str(act.ActivationStatus.COVERAGE_MISSING)),
        ),
        (
            "SCHEMA_MISMATCH unclassified",
            dict(blank, status=str(act.ActivationStatus.SCHEMA_MISMATCH)),
        ),
        (
            "SCHEMA_MISMATCH classified",
            dict(rejected, status=str(act.ActivationStatus.SCHEMA_MISMATCH)),
        ),
        ("mapping admissible", mapped),
    ]


#: What each issue must report, identically for `core` and `additional`. Only the two
#: rows that genuinely establish something may differ, and they differ by command name
#: rather than by leniency.
EXPECTED_PAID_STATE = {
    "PREPARED_NOT_EXECUTED": "PREPARED_NOT_EXECUTED",
    "PROVIDER_UNAVAILABLE not sent": "PAID_ATTEMPT_INCONCLUSIVE",
    "PROVIDER_UNAVAILABLE reached": "PAID_ATTEMPT_INCONCLUSIVE",
    "AUTH_FAILED": "PAID_ATTEMPT_INCONCLUSIVE",
    "COST_UNVERIFIED": "PAID_ATTEMPT_INCONCLUSIVE",
    "COST_MISMATCH": "PAID_ATTEMPT_INCONCLUSIVE",
    "COVERAGE_MISSING unclassified": "PAID_ATTEMPT_INCONCLUSIVE",
    "COVERAGE_MISSING classified": "COVERAGE_ANSWERED",
    "SCHEMA_MISMATCH unclassified": "PAID_ATTEMPT_INCONCLUSIVE",
    "SCHEMA_MISMATCH classified": "COVERAGE_ANSWERED",
    "mapping admissible": "MAPPING_OBSERVED",
}


class TestThePaidStateIsSymmetric:
    @pytest.mark.parametrize("command", ["core", "additional"])
    @pytest.mark.parametrize("label", [row[0] for row in paid_state_rows("core")])
    def test_the_same_issue_reports_the_same_kind_of_state(
        self, workspace: Path, command: str, label: str
    ) -> None:
        over = dict(next(o for name, o in paid_state_rows(command) if name == label))
        write_all(workspace, [core(**over)])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        document = _state(receipts, unverifiable)
        observed = document["paid_activation_state"]
        expected = EXPECTED_PAID_STATE[label]
        if expected == "COVERAGE_ANSWERED":
            assert observed in {
                str(act.PaidActivationState.CORE_EXECUTED_NO_COVERAGE),
                str(act.PaidActivationState.ADDITIONAL_EXECUTED),
            }, (command, label, observed)
        elif expected == "MAPPING_OBSERVED":
            assert observed in {
                str(act.PaidActivationState.CORE_EXECUTED_COVERAGE_OBSERVED),
                str(act.PaidActivationState.ADDITIONAL_EXECUTED),
            }, (command, label, observed)
        else:
            assert observed == expected, (command, label, observed)

    def test_additional_executed_requires_established_evidence(self, workspace: Path) -> None:
        """v4 reported ADDITIONAL_EXECUTED for an `additional/AUTH_FAILED` receipt."""
        over = dict(next(o for name, o in paid_state_rows("additional") if name == "AUTH_FAILED"))
        write_all(workspace, [core(**over)])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        document = _state(receipts, unverifiable)
        assert document["paid_activation_state"] == str(
            act.PaidActivationState.PAID_ATTEMPT_INCONCLUSIVE
        )

    def test_the_presence_of_an_additional_receipt_is_not_evidence(self, workspace: Path) -> None:
        inconclusive = dict(
            next(o for name, o in paid_state_rows("additional") if name == "COST_MISMATCH")
        )
        write_all(workspace, [core(receipt_id="d1" * 8, **inconclusive)])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert _state(receipts, unverifiable)["paid_activation_state"] != str(
            act.PaidActivationState.ADDITIONAL_EXECUTED
        )


# ---------------------------------------------------------------------------
# P2-3 — a positive status is never vacuously satisfied
# ---------------------------------------------------------------------------
class TestAPositiveStatusIsNeverEmpty:
    @pytest.mark.parametrize(
        ("label", "make"),
        [
            ("CORE_LIVE_VERIFIED", core),
            ("ADDITIONAL_LIVE_VERIFIED", extra),
            ("ADDITIONAL_PARTIAL_COVERAGE", partial),
        ],
    )
    def test_an_empty_market_scope_is_refused(self, label: str, make: Any) -> None:
        receipt = make(
            markets_requested=[],
            market_states={},
            markets_mapped=[],
            markets_observed=[],
            markets_absent=[],
            markets_rejected=[],
            markets_not_evaluated=[],
            freshness={},
            selections_mapped=0,
        )
        assert qual.structural_faults(receipt) != [], label
        assert qual.cost_category(receipt) != "provider_reached_conforming_cost", label

    def test_a_live_status_needs_a_mapped_market(self) -> None:
        receipt = core(
            market_states={"h2h": str(act.MarketState.OBSERVED_REJECTED)},
            markets_mapped=[],
            markets_observed=["h2h"],
            markets_rejected=["h2h"],
            selections_mapped=0,
        )
        assert qual.classify(receipt) != ""

    def test_a_live_status_needs_a_selection_and_a_freshness(self) -> None:
        assert qual.structural_faults(core(selections_mapped=0)) != [] or qual.contradictions(
            core(selections_mapped=0)
        )
        assert qual.structural_faults(core(freshness={})) != []

    def test_additional_live_verified_needs_every_market_mapped(self) -> None:
        receipt = extra(
            market_states={
                **dict.fromkeys(MARKETS[:-1], str(act.MarketState.OBSERVED_MAPPED)),
                MARKETS[-1]: str(act.MarketState.NOT_RETURNED),
            },
            markets_mapped=MARKETS[:-1],
            markets_observed=MARKETS[:-1],
            markets_absent=[MARKETS[-1]],
            freshness=dict.fromkeys(MARKETS[:-1], 300),
        )
        assert qual.structural_faults(receipt) != []

    def test_additional_partial_coverage_needs_a_gap(self) -> None:
        receipt = partial(
            market_states=dict.fromkeys(MARKETS, str(act.MarketState.OBSERVED_MAPPED)),
            markets_mapped=list(MARKETS),
            markets_observed=list(MARKETS),
            markets_absent=[],
            freshness=dict.fromkeys(MARKETS, 300),
        )
        assert qual.structural_faults(receipt) != []

    def test_a_malformed_receipt_feeds_no_conforming_cost(self) -> None:
        document = _evaluate([core(selections_mapped="3")], 0)
        assert cost_of(document)["observed"]["provider_reached_conforming_cost"] == 0


# ---------------------------------------------------------------------------
# P2-2 — exact copies change nothing semantic
# ---------------------------------------------------------------------------
COPY_NATURES: list[tuple[str, Any]] = [
    ("conforming", lambda: core()),
    (
        "COST_MISMATCH",
        lambda: unclassified(
            status=str(act.ActivationStatus.COST_MISMATCH), observed_credits=9, accounted_credits=9
        ),
    ),
    (
        "COST_UNVERIFIED",
        lambda: unclassified(
            status=str(act.ActivationStatus.COST_UNVERIFIED),
            observed_credits=None,
            accounted_credits=1,
        ),
    ),
    (
        "confirmed attempt not sent",
        lambda: unclassified(
            status=str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
            may_have_reached_provider=False,
            observed_credits=None,
            accounted_credits=0,
        ),
    ),
    ("historical protocol 4", lambda: core(qualification_protocol_version=4)),
    ("malformed", lambda: core(selections_mapped="3")),
    ("contradictory", lambda: core(bookmaker_state=str(act.BookmakerState.NOT_RETURNED))),
]

#: Every field a copy must not move. The physical count is deliberately excluded.
SEMANTIC_KEYS = [
    "accounted_credits_total",
    "connectivity_and_cost_proof",
    "paid_activation_state",
    "execution_state",
    "qualification_state",
    "qualification_usable_receipts",
    "qualification_current_malformed_receipts",
    "qualification_current_contradictory_receipts",
    "qualification_historical_nonqualifying_receipts",
]


class TestExactCopiesChangeNothingSemantic:
    @pytest.mark.parametrize(("label", "make"), COPY_NATURES, ids=[n[0] for n in COPY_NATURES])
    def test_one_two_and_seven_copies_agree(self, workspace: Path, label: str, make: Any) -> None:
        snapshots = []
        for count in (1, 2, 7):
            write_all(
                workspace,
                [make() for _ in range(count)],
                names=[f"copy-{i:02d}.json" for i in range(count)],
            )
            _audit = act.audit_receipts()
            receipts, unverifiable = _audit.batch, _audit.unverifiable
            document = _state(receipts, unverifiable)
            snapshots.append(
                {
                    **{k: document[k] for k in SEMANTIC_KEYS},
                    "census": dict(document["paid_call_cost_census"]),
                    "cost_observed": dict(cost_of(document)["observed"]),
                    "observations": len(document["bookmaker_coverage_observations"]),
                    "events": entry(document, "CORE_MAPPING_FOOTBALL")["observed"],
                }
            )
        assert snapshots[0] == snapshots[1] == snapshots[2], label

    @pytest.mark.parametrize(("label", "make"), COPY_NATURES, ids=[n[0] for n in COPY_NATURES])
    def test_only_the_physical_counters_move(self, workspace: Path, label: str, make: Any) -> None:
        seen = []
        for count in (1, 2, 7):
            write_all(
                workspace,
                [make() for _ in range(count)],
                names=[f"copy-{i:02d}.json" for i in range(count)],
            )
            _audit = act.audit_receipts()
            receipts, unverifiable = _audit.batch, _audit.unverifiable
            document = _state(receipts, unverifiable)
            seen.append(
                (
                    document["verified_receipts"],
                    document["qualification_exact_duplicate_copies"],
                )
            )
        assert seen == [(1, 0), (2, 1), (7, 6)], label

    def test_copies_never_reach_a_threshold(self, workspace: Path) -> None:
        one = core(receipt_id="cc" * 8)
        write_all(workspace, [dict(one) for _ in range(9)], names=[f"c-{i}.json" for i in range(9)])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        document = _state(receipts, unverifiable)
        assert entry(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 1
        assert cost_of(document)["observed"]["provider_reached_conforming_cost"] == 1
        assert document["accounted_credits_total"] == 1


# ---------------------------------------------------------------------------
# §6.6 — the version 5 cost taxonomy
# ---------------------------------------------------------------------------
COST_KEYS = [
    "provider_reached_conforming_cost",
    "provider_reached_nonconforming_cost",
    "provider_reached_cost_unestablished",
    "paid_attempt_state_unestablished",
    "confirmed_attempts_not_sent",
]


class TestTheCostTaxonomyIsVersionFive:
    def test_the_buckets_v5_introduced_are_still_published(self) -> None:
        """Four of v5's five names survive verbatim; the fifth was split by D-076.

        `provider_reached_unestablished_cost` asserted an established reach that two of
        its three feeders denied, so it became `provider_reached_cost_unestablished` and
        `provider_reach_unestablished`. Both block, which is what v5 required of it.
        """
        document = _evaluate([core()], 0)
        published = set(cost_of(document)["observed"])
        for kept in (
            "provider_reached_conforming_cost",
            "provider_reached_nonconforming_cost",
            "paid_attempt_state_unestablished",
            "confirmed_attempts_not_sent",
        ):
            assert kept in published
        assert {"provider_reached_cost_unestablished", "provider_reach_unestablished"} <= published
        assert "provider_reached_unestablished_cost" not in published
        assert {"provider_reached_cost_unestablished", "provider_reach_unestablished"} <= set(
            qual.BLOCKING_COST_BUCKETS
        )

    def test_cost_unverified_is_unestablished_not_nonconforming(self) -> None:
        receipt = unclassified(
            status=str(act.ActivationStatus.COST_UNVERIFIED),
            observed_credits=None,
            accounted_credits=1,
        )
        assert qual.cost_category(receipt) == "provider_reached_cost_unestablished"

    def test_cost_mismatch_is_nonconforming(self) -> None:
        receipt = unclassified(
            status=str(act.ActivationStatus.COST_MISMATCH), observed_credits=9, accounted_credits=9
        )
        assert qual.cost_category(receipt) == "provider_reached_nonconforming_cost"

    def test_a_confirmed_attempt_not_sent_has_its_own_bucket(self) -> None:
        receipt = unclassified(
            status=str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
            may_have_reached_provider=False,
            observed_credits=None,
            accounted_credits=0,
        )
        assert qual.cost_category(receipt) == "confirmed_attempts_not_sent"

    def test_a_step_never_attempted_is_outside_the_census(self) -> None:
        receipt = unclassified(
            status=str(act.ActivationStatus.PREPARED_NOT_EXECUTED),
            network_attempted=False,
            may_have_reached_provider=False,
            attempts=0,
            observed_credits=None,
            accounted_credits=0,
            drop=("event_tag",),
        )
        assert qual.cost_category(receipt) == ""

    def test_a_confirmed_attempt_not_sent_is_not_blocking(self) -> None:
        corpus = [
            *six_conforming_costs(),
            unclassified(
                receipt_id="e1" * 8,
                event_tag="z" * 32,
                status=str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
                may_have_reached_provider=False,
                observed_credits=None,
                accounted_credits=0,
            ),
        ]
        result = cost_of(_evaluate(corpus, 0))
        assert result["observed"]["confirmed_attempts_not_sent"] == 1
        assert result["passed"] is True

    @pytest.mark.parametrize(
        ("label", "make"),
        [
            (
                "nonconforming",
                lambda: unclassified(
                    receipt_id="e2" * 8,
                    event_tag="y" * 32,
                    status=str(act.ActivationStatus.COST_MISMATCH),
                    observed_credits=9,
                    accounted_credits=9,
                ),
            ),
            (
                "unestablished",
                lambda: unclassified(
                    receipt_id="e3" * 8,
                    event_tag="x" * 32,
                    status=str(act.ActivationStatus.COST_UNVERIFIED),
                    observed_credits=None,
                    accounted_credits=1,
                ),
            ),
            (
                "attempt unestablished",
                lambda: core(receipt_id="e4" * 8, event_tag="w" * 32, drop=("network_attempted",)),
            ),
        ],
    )
    def test_each_blocking_bucket_blocks(self, label: str, make: Any) -> None:
        receipt = make()
        document = _state([*six_conforming_costs(), receipt], 0)
        # Two roads to the same shut gate since D-076: a receipt the contract can read is
        # priced into a blocking bucket, one it rejects is an evidence conflict. What may
        # never happen is that it passes.
        if qual.classify(receipt) == "":
            assert cost_of(document)["passed"] is False, label
        else:
            assert document["qualification_state"] == "EVIDENCE_CONFLICT", label
        assert document["eligible_for_human_promotion_review"] is False, label

    def test_exactly_one_bucket_per_paid_step(self) -> None:
        statuses = [
            act.ActivationStatus.CORE_LIVE_VERIFIED,
            act.ActivationStatus.COVERAGE_MISSING,
            act.ActivationStatus.PROVIDER_UNAVAILABLE,
            act.ActivationStatus.AUTH_FAILED,
            act.ActivationStatus.COST_MISMATCH,
            act.ActivationStatus.COST_UNVERIFIED,
        ]
        flags: list[Any] = [True, False, ABSENT, "false", 1]
        for status in statuses:
            for network in flags:
                for reach in flags:
                    fields: dict[str, Any] = {"status": str(status), "receipt_id": "ff" * 8}
                    drop: list[str] = []
                    for name, value in (
                        ("network_attempted", network),
                        ("may_have_reached_provider", reach),
                    ):
                        if value is ABSENT:
                            drop.append(name)
                        else:
                            fields[name] = value
                    fields["drop"] = tuple(drop)
                    receipt = unclassified(**fields)
                    document = _evaluate([receipt], 0)
                    observed = cost_of(document)["observed"]
                    total = sum(observed.values())
                    state = qual.attempt_state(receipt)
                    readable = qual.classify(receipt) == ""
                    expected = 0 if state is qual.AttemptState.NOT_ATTEMPTED or not readable else 1
                    assert total == expected, (status, network, reach, observed)
                    # Exhaustive and disjoint remains a property of the taxonomy itself,
                    # which is a pure function of the receipt — D-076 only changed which
                    # receipts the *census* is allowed to speak about.
                    if state is not qual.AttemptState.NOT_ATTEMPTED:
                        assert qual.cost_category(receipt) in qual.COST_BUCKETS

    def test_a_response_asserting_status_not_sent_is_contradictory(self) -> None:
        for status in (
            act.ActivationStatus.COST_MISMATCH,
            act.ActivationStatus.AUTH_FAILED,
            act.ActivationStatus.COVERAGE_MISSING,
        ):
            receipt = unclassified(
                status=str(status),
                may_have_reached_provider=False,
                observed_credits=None,
                accounted_credits=0,
            )
            if status is act.ActivationStatus.COST_MISMATCH:
                receipt = unclassified(
                    status=str(status),
                    may_have_reached_provider=False,
                    observed_credits=9,
                    accounted_credits=9,
                )
            assert qual.classify(receipt) == "self_contradictory", status

    def test_the_pass_rule(self) -> None:
        assert cost_of(_evaluate(six_conforming_costs(), 0))["passed"] is True
        assert cost_of(_evaluate(six_conforming_costs()[:5], 0))["passed"] is False


# ---------------------------------------------------------------------------
# §3.6 — mapping and cost are independent axes, and the gate needs both
# ---------------------------------------------------------------------------
class TestMappingAndCostAreIndependentAxes:
    def test_an_out_of_ceiling_cost_keeps_a_sound_mapping(self) -> None:
        receipt = core(observed_credits=9, accounted_credits=9)
        assert qual.mapping_observation_is_sound(receipt) is True
        assert qual.cost_category(receipt) != "provider_reached_conforming_cost"

    def test_an_out_of_ceiling_cost_blocks_the_gate(self) -> None:
        document = _evaluate(threshold_corpus(observed_credits=9, accounted_credits=9), 0)
        assert document["eligible_for_human_promotion_review"] is False
        assert cost_of(document)["passed"] is False


# ---------------------------------------------------------------------------
# P2-5 — publication is atomic, and a retry is exact
# ---------------------------------------------------------------------------
def unsigned(**over: Any) -> dict[str, Any]:
    return {k: v for k, v in core(**over).items() if k != act.SIGNATURE_FIELD}


class TestPublicationIsAtomic:
    def test_a_normal_write_leaves_exactly_one_complete_file(self, workspace: Path) -> None:
        path = act.write_receipt(unsigned(receipt_id="d0" * 8))
        assert path.exists() and path.stat().st_size > 0
        assert sorted(p.name for p in workspace.iterdir()) == [path.name]

    def test_an_interruption_leaves_no_final_file(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Boom(RuntimeError):
            pass

        real_write = os.write

        def exploding_write(fd: int, data: bytes) -> int:
            raise Boom("interrupted before publication")

        monkeypatch.setattr(os, "write", exploding_write)
        with pytest.raises(Boom):
            act.write_receipt(unsigned(receipt_id="d1" * 8))
        monkeypatch.setattr(os, "write", real_write)
        assert [p.name for p in workspace.iterdir() if p.suffix == ".json"] == []
        # And the same receipt can still be written afterwards.
        path = act.write_receipt(unsigned(receipt_id="d1" * 8))
        assert path.stat().st_size > 0

    def test_an_identical_rewrite_is_idempotent(self, workspace: Path) -> None:
        first = act.write_receipt(unsigned(receipt_id="d2" * 8))
        body = first.read_text(encoding="utf-8")
        assert act.write_receipt(unsigned(receipt_id="d2" * 8)) == first
        assert first.read_text(encoding="utf-8") == body

    def test_a_divergent_signed_receipt_is_an_explicit_collision(self, workspace: Path) -> None:
        path = act.write_receipt(unsigned(receipt_id="d3" * 8))
        body = path.read_text(encoding="utf-8")
        with pytest.raises(act.Refused) as caught:
            act.write_receipt(unsigned(receipt_id="d3" * 8, selections_mapped=9))
        assert "signé différent" in str(caught.value)
        assert path.read_text(encoding="utf-8") == body

    @pytest.mark.parametrize(("label", "body"), [("empty", ""), ("truncated", '{"schema_ver')])
    def test_an_incomplete_target_is_not_called_a_divergent_receipt(
        self, workspace: Path, label: str, body: str
    ) -> None:
        payload = unsigned(receipt_id="d4" * 8)
        first = act.write_receipt(dict(payload))
        first.write_text(body, encoding="utf-8")
        with pytest.raises(act.Refused) as caught:
            act.write_receipt(dict(payload))
        message = str(caught.value)
        assert "signé différent" not in message, label
        assert "incomplet" in message or "illisible" in message, label

    def test_an_incomplete_target_can_be_recovered_without_losing_bytes(
        self, workspace: Path
    ) -> None:
        payload = unsigned(receipt_id="d5" * 8)
        first = act.write_receipt(dict(payload))
        first.write_text("", encoding="utf-8")
        # D-076: a basename of the authorised directory, never a path.
        quarantined = act.quarantine_incomplete_receipt(first.name)
        assert (workspace / quarantined).exists()
        again = act.write_receipt(dict(payload))
        assert again.stat().st_size > 0
        assert act.audit_receipts().batch[0]["receipt_id"] == "d5" * 8


# ---------------------------------------------------------------------------
# P3-1/P3-2 — no link is followed at open time, even under a race
# ---------------------------------------------------------------------------
def foreign_file(workspace: Path, name: str, body: str) -> Path:
    outside = workspace.parent / "outside-the-receipt-directory"
    outside.mkdir(parents=True, exist_ok=True)
    path = outside / name
    path.write_text(body, encoding="utf-8")
    return path


SENTINEL = "V5_FOREIGN_SENTINEL_e17b"


class TestNoLinkIsFollowedAtOpenTime:
    def test_a_regular_internal_file_is_read(self, workspace: Path) -> None:
        write_all(workspace, [core()])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert len(receipts) == 1 and unverifiable == 0

    @pytest.mark.parametrize("kind", ["internal", "external", "broken"])
    def test_a_link_is_never_followed(self, workspace: Path, kind: str) -> None:
        write_all(workspace, [core()])
        if kind == "internal":
            target = workspace / "probe-001.json"
        elif kind == "external":
            target = foreign_file(
                workspace, "foreign.json", jsonlib.dumps(core(sport_key=f"soccer_{SENTINEL}"))
            )
        else:
            target = workspace / "nothing-here.json"
        os.symlink(target, workspace / "link.json")
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert len(receipts) == 1
        assert unverifiable == 1
        assert SENTINEL not in jsonlib.dumps(receipts, default=str)

    def test_a_swap_after_every_check_still_does_not_follow(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The narrowest window: replaced after the directory is opened, before the file is.

        Under protocol v4 the guard ran ``is_symlink``/``is_file``/``resolve`` on the
        path and then read the path *again*, so a regular receipt swapped for a link in
        between was read through it and became a verified receipt carrying foreign
        content. The swap is armed here on the directory open — the last thing that
        happens before the file open — so the only thing that can refuse it is the open
        itself.
        """
        write_all(workspace, [core()])
        foreign = foreign_file(
            workspace, "swap.json", jsonlib.dumps(core(sport_key=f"soccer_{SENTINEL}"))
        )
        target = workspace / "probe-001.json"
        real_open = os.open
        fired: dict[str, int] = {"n": 0}

        def racing_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            handle = real_open(path, flags, *args, **kwargs)
            if flags & getattr(os, "O_DIRECTORY", 0) and not fired["n"] and target.exists():
                fired["n"] = 1
                target.unlink()
                os.symlink(foreign, target)
            return handle

        monkeypatch.setattr(os, "open", racing_open)
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        monkeypatch.undo()
        assert fired["n"] == 1
        assert target.is_symlink()
        assert SENTINEL not in jsonlib.dumps(receipts, default=str)
        assert list(receipts) == []
        assert unverifiable == 1

    def test_a_directory_named_json_is_counted(self, workspace: Path) -> None:
        (workspace / "folder.json").mkdir(parents=True, exist_ok=True)
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert list(receipts) == [] and unverifiable == 1

    def test_write_refuses_a_symbolic_target_without_reading_it(self, workspace: Path) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        victim = foreign_file(workspace, "victim.json", f"{SENTINEL}\n")
        payload = unsigned(receipt_id="cc" * 8)
        stamp = str(payload["recorded_at"]).replace(":", "").replace("-", "")[:15]
        os.symlink(victim, workspace / f"{stamp}-core-{payload['receipt_id']}.json")
        with pytest.raises(act.Refused) as caught:
            act.write_receipt(dict(payload))
        assert SENTINEL not in str(caught.value)
        assert victim.read_text(encoding="utf-8").strip() == SENTINEL

    def test_the_secret_is_never_read_through_a_link(self, workspace: Path) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        planted = foreign_file(workspace, "planted.secret", "ff" * 32)
        os.symlink(planted, workspace / act.SECRET_FILENAME)
        # The environment wins when it is set, so it is removed: the property under test
        # is about the *file*, and D-076 reads it through the same guarded primitive.
        os.environ.pop(act.SECRET_VARIABLE, None)
        with pytest.raises(_store.StoreRefused):
            act.load_receipt_secret()

    def test_no_foreign_path_or_content_reaches_the_output(self, workspace: Path) -> None:
        from helpers_activation import run

        workspace.mkdir(parents=True, exist_ok=True)
        foreign = foreign_file(
            workspace, "elsewhere.json", jsonlib.dumps(core(sport_key=f"soccer_{SENTINEL}"))
        )
        os.symlink(foreign, workspace / "link.json")
        result = run("status", "--json")
        assert result.exit_code == 0
        assert SENTINEL not in result.stdout
        assert "outside-the-receipt-directory" not in result.stdout


# ---------------------------------------------------------------------------
# P3-3 — the table, the producer and the tests agree
# ---------------------------------------------------------------------------
def attempt_for(command: str, **over: Any) -> Any:
    attempt = act.Attempt(
        command=command,
        sport=FOOTBALL,
        bookmaker=BOOK,
        window=WINDOW,
        ceiling=act.STEP_CEILINGS.get(command, 0),
        now=D1,
    )
    for key, value in over.items():
        setattr(attempt, key, value)
    return attempt


NET = {"network_attempted": True, "reached_provider": True, "attempts": 1}
DISC = {
    **NET,
    "attempts": 2,
    "endpoints": ["/v4/sports", "/v4/sports/{s}/events"],
    "event_tags": ["d1" * 16, "d2" * 16],
    "events_returned": 5,
    "events_in_window": 3,
    "events_admissible": 2,
    "observed": 0,
    "quota_remaining": 400,
}
CORE_UNCLASS = {
    **NET,
    "estimated": 1,
    "observed": 1,
    "event_tags": ["u" * 32],
    "markets_requested": ["h2h"],
    "endpoints": ["/v4/sports/{s}/odds"],
}
ADD_UNCLASS = {
    **NET,
    "estimated": 5,
    "observed": 5,
    "event_tags": ["j" * 32],
    "markets_requested": list(MARKETS),
    "endpoints": ["/v4/e/odds"],
}


def classified(
    markets: list[str], state: str, *, book: str, mapped: int, fresh: bool
) -> dict[str, Any]:
    return {
        "market_states": dict.fromkeys(markets, state),
        "freshness": dict.fromkeys(markets, 300) if fresh else {},
        "selections_mapped": mapped,
        "bookmaker_state": book,
    }


#: Every honest shape the producer can emit, derived from the call sites of
#: `build_receipt` and `_record_failure` rather than restated as a count.
PRODUCIBLE: list[tuple[str, str, str, dict[str, Any]]] = [
    ("plan", "PLAN_ONLY", "PLANNED", {}),
    ("plan", "PREPARED_NOT_EXECUTED", "PLANNED", {}),
    ("discover", "PREPARED_NOT_EXECUTED", "DISCOVERED", {}),
    ("discover", "DISCOVERY_VERIFIED", "DISCOVERED", DISC),
    (
        "discover",
        "COVERAGE_MISSING",
        "DISCOVERED",
        {**DISC, "event_tags": [], "events_admissible": 0},
    ),
    # `discover/SCHEMA_MISMATCH` was declared producible here and no producer wrote it:
    # `_event_of` and `_check_start_time`, the two functions that raise it, are reached
    # from `run_core` and `run_additional` only. D-076 removed it from the table and added
    # the two couples `run_discovery` really does write through `_settle_cost`.
    (
        "discover",
        "COST_UNVERIFIED",
        "DISCOVERED",
        {**DISC, "observed": None},
    ),
    (
        "discover",
        "COST_MISMATCH",
        "DISCOVERED",
        {**DISC, "observed": 3},
    ),
    (
        "discover",
        "AUTH_FAILED",
        "DISCOVERED",
        {**NET, "endpoints": ["/v4/sports"], "observed": None},
    ),
    (
        "discover",
        "PROVIDER_UNAVAILABLE",
        "DISCOVERED",
        {**NET, "endpoints": ["/v4/sports"], "observed": None},
    ),
    ("core", "PREPARED_NOT_EXECUTED", "PLANNED", {"markets_requested": ["h2h"]}),
    (
        "core",
        "CORE_LIVE_VERIFIED",
        "CLASSIFIED",
        {
            **CORE_UNCLASS,
            **classified(["h2h"], "OBSERVED_MAPPED", book="OBSERVED", mapped=3, fresh=True),
        },
    ),
    (
        "core",
        "COVERAGE_MISSING",
        "CLASSIFIED",
        {
            **CORE_UNCLASS,
            **classified(
                ["h2h"],
                "NOT_EVALUATED_BOOKMAKER_ABSENT",
                book="NOT_RETURNED",
                mapped=0,
                fresh=False,
            ),
        },
    ),
    ("core", "COVERAGE_MISSING", "ATTEMPTED_UNCLASSIFIED", CORE_UNCLASS),
    (
        "core",
        "SCHEMA_MISMATCH",
        "CLASSIFIED",
        {
            **CORE_UNCLASS,
            **classified(["h2h"], "OBSERVED_REJECTED", book="OBSERVED", mapped=0, fresh=True),
            "rejections": ["motif"],
        },
    ),
    ("core", "SCHEMA_MISMATCH", "ATTEMPTED_UNCLASSIFIED", CORE_UNCLASS),
    ("core", "COST_MISMATCH", "ATTEMPTED_UNCLASSIFIED", {**CORE_UNCLASS, "observed": 4}),
    ("core", "COST_UNVERIFIED", "ATTEMPTED_UNCLASSIFIED", {**CORE_UNCLASS, "observed": None}),
    ("core", "AUTH_FAILED", "ATTEMPTED_UNCLASSIFIED", {**CORE_UNCLASS, "observed": None}),
    (
        "core",
        "PROVIDER_UNAVAILABLE",
        "ATTEMPTED_UNCLASSIFIED",
        {**CORE_UNCLASS, "observed": None, "reached_provider": False},
    ),
    ("additional", "PREPARED_NOT_EXECUTED", "PLANNED", {"markets_requested": list(MARKETS)}),
    (
        "additional",
        "ADDITIONAL_LIVE_VERIFIED",
        "CLASSIFIED",
        {
            **ADD_UNCLASS,
            **classified(list(MARKETS), "OBSERVED_MAPPED", book="OBSERVED", mapped=9, fresh=True),
        },
    ),
    (
        "additional",
        "ADDITIONAL_PARTIAL_COVERAGE",
        "CLASSIFIED",
        {
            **ADD_UNCLASS,
            "market_states": {
                **dict.fromkeys(MARKETS[:-1], "OBSERVED_MAPPED"),
                MARKETS[-1]: "NOT_RETURNED",
            },
            "freshness": dict.fromkeys(MARKETS[:-1], 300),
            "selections_mapped": 7,
            "bookmaker_state": "OBSERVED",
        },
    ),
    (
        "additional",
        "COVERAGE_MISSING",
        "CLASSIFIED",
        {
            **ADD_UNCLASS,
            **classified(
                list(MARKETS),
                "NOT_EVALUATED_BOOKMAKER_ABSENT",
                book="NOT_RETURNED",
                mapped=0,
                fresh=False,
            ),
        },
    ),
    ("additional", "COVERAGE_MISSING", "ATTEMPTED_UNCLASSIFIED", ADD_UNCLASS),
    (
        "additional",
        "SCHEMA_MISMATCH",
        "CLASSIFIED",
        {
            **ADD_UNCLASS,
            **classified(list(MARKETS), "OBSERVED_REJECTED", book="OBSERVED", mapped=0, fresh=True),
            "rejections": ["motif"],
        },
    ),
    ("additional", "SCHEMA_MISMATCH", "ATTEMPTED_UNCLASSIFIED", ADD_UNCLASS),
    ("additional", "COST_MISMATCH", "ATTEMPTED_UNCLASSIFIED", {**ADD_UNCLASS, "observed": 9}),
    ("additional", "COST_UNVERIFIED", "ATTEMPTED_UNCLASSIFIED", {**ADD_UNCLASS, "observed": None}),
    ("additional", "AUTH_FAILED", "ATTEMPTED_UNCLASSIFIED", {**ADD_UNCLASS, "observed": None}),
    (
        "additional",
        "PROVIDER_UNAVAILABLE",
        "ATTEMPTED_UNCLASSIFIED",
        {**ADD_UNCLASS, "observed": None, "reached_provider": False},
    ),
]


def produced(command: str, status: str, over: dict[str, Any]) -> dict[str, Any]:
    document = act.build_receipt(
        attempt_for(command, **over), act.ActivationStatus(status), SCRUB_SECRET
    )
    document[act.SIGNATURE_FIELD] = act.sign_receipt(document, _SIGNING)
    return document


class TestTheTableIsFullyExercised:
    @pytest.mark.parametrize(
        ("command", "status", "phase", "over"),
        PRODUCIBLE,
        ids=[f"{c}-{s}-{p}" for c, s, p, _ in PRODUCIBLE],
    )
    def test_every_producible_form_is_accepted(
        self, command: str, status: str, phase: str, over: dict[str, Any]
    ) -> None:
        receipt = produced(command, status, over)
        assert qual.structural_faults(receipt) == [], (command, status, phase)
        assert qual.classify(receipt) == "", (command, status, phase)

    def test_every_table_entry_is_exercised(self) -> None:
        exercised = {(c, s) for c, s, _, _ in PRODUCIBLE}
        assert set(qual.RECEIPT_PHASES) == exercised

    def test_every_dual_phase_pair_is_exercised_in_both_forms(self) -> None:
        dual = {pair for pair, phases in qual.RECEIPT_PHASES.items() if len(phases) > 1}
        for command, status in dual:
            phases = {p for c, s, p, _ in PRODUCIBLE if (c, s) == (command, status)}
            assert len(phases) == len(qual.RECEIPT_PHASES[(command, status)]), (command, status)

    def test_the_published_inventory_matches(self) -> None:
        # D-076 removed `discover/SCHEMA_MISMATCH`, which no producer wrote, and added
        # the two cost couples `run_discovery` really does write.
        assert len(qual.RECEIPT_PHASES) == 26
        assert len(PRODUCIBLE) == 30
        assert (qual.RECEIPT_COUPLE_COUNT, qual.RECEIPT_FORM_COUNT) == (26, 30)

    def test_an_unknown_producible_status_is_named_not_guessed(self) -> None:
        receipt = core(status="FUTURE_UNKNOWN_STATUS")
        assert qual.classify(receipt) == "unknown_command_status_pair"
        assert qual.admissible_for(receipt, qual.CRITERIA[0]) is False

    def test_a_corpus_of_every_honest_outcome_is_not_a_conflict(self, workspace: Path) -> None:
        from helpers_activation import run

        receipts = []
        for index, (command, status, _, over) in enumerate(PRODUCIBLE):
            document = produced(command, status, over)
            document["receipt_id"] = f"{index:016x}"
            document[act.SIGNATURE_FIELD] = act.sign_receipt(
                {k: v for k, v in document.items() if k != act.SIGNATURE_FIELD}, _SIGNING
            )
            receipts.append(document)
        write_all(workspace, receipts)
        result = run("status", "--json")
        assert result.exit_code == 0, result.output
        payload = jsonlib.loads(result.stdout)
        assert payload["qualification_current_malformed_receipts"] == 0
        assert payload["qualification_unknown_pair_receipts"] == 0
        assert payload["qualification_state"] != str(qual.QualificationState.EVIDENCE_CONFLICT)
        assert run("status").exit_code == 0


# ---------------------------------------------------------------------------
# P3-8 — a malformed receipt feeds no semantic counter
# ---------------------------------------------------------------------------
class TestMalformedReceiptsFeedNoSemanticCounter:
    def test_a_malformed_receipt_contributes_no_business_credit(self, workspace: Path) -> None:
        write_all(
            workspace,
            [
                core(receipt_id="11" * 8, accounted_credits=7, selections_mapped="3"),
                core(receipt_id="22" * 8, event_tag="b" * 32, accounted_credits=2),
            ],
        )
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        document = _state(receipts, unverifiable)
        assert document["accounted_credits_total"] == 2
        assert document["rejected_receipt_credits_not_counted"] == 7

    def test_the_two_credit_fields_are_named_apart(self, workspace: Path) -> None:
        write_all(workspace, [core()])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        document = _state(receipts, unverifiable)
        assert "rejected" in "rejected_receipt_credits_not_counted"
        assert document["accounted_credits_total"] == 1
        assert document["rejected_receipt_credits_not_counted"] == 0

    @pytest.mark.parametrize("value", [True, "7", -5, 1.5, None])
    def test_a_mistyped_credit_is_never_summed(self, workspace: Path, value: Any) -> None:
        write_all(workspace, [core(accounted_credits=value)])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        document = _state(receipts, unverifiable)
        assert document["accounted_credits_total"] == 0


# ---------------------------------------------------------------------------
# §8 — the documents publish one norm, and keep their history readable
# ---------------------------------------------------------------------------
#: The sections of the protocol document that exist to *record* what an earlier version
#: claimed and what it actually did. An old version number and an old effective instant
#: belong in them, so a global grep would make the project's own history unwritable —
#: the opposite of what annotating a superseded decision is for. This class lives with
#: the current contract and moves with it: exactly one suite asserts the current norm.
HISTORICAL_HEADINGS = (
    "## 0. Ce que la v1",
    "### 0.1 Puis la v2",
    "### 0.2 Puis la v3",
    "### 0.3 Puis la v4",
)

#: Every instant a superseded protocol published. None may appear in current text.
SUPERSEDED_INSTANTS = (
    "2026-08-09T19:38:29+00:00",
    "2026-08-10T07:19:48+00:00",
    "2026-08-10T09:11:48+00:00",
)

CURRENT_DOCUMENTS = (
    "docs/provider-validation-protocol.md",
    "docs/provider-activation.md",
    "docs/data-dictionary.md",
    "docs/roadmap.md",
)


def current_sections(path: Path) -> str:
    """The document minus the sections that exist to record its own history."""
    out: list[str] = []
    historical = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            historical = line.startswith(HISTORICAL_HEADINGS)
        if not historical:
            out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# `TestTheDocumentsPublishOneNorm` **moved** to `test_qualification_v6_contract.py`.
# It asserts the norm of the *current* protocol: exactly one suite may do that, and it
# must be the current one. The same move happened from v4 to v5 under D-075.
# ---------------------------------------------------------------------------
