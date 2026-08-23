"""Protocol v4: the contract must accept what the harness honestly produces.

Protocol v3 made the evidence contract strict, and a final read-only re-audit found
that strictness had been applied without asking what the producer actually writes.
Six of the fifteen receipts the harness emits — every `core` outcome that fails
*before* the markets are classified, and `plan` — were declared
``malformed_current_schema``, so a single genuine `AUTH_FAILED` on disk parked
`status` in ``EVIDENCE_CONFLICT`` for good. The same re-audit found the five older
dimensions still speaking in positive labels about evidence the strict block
rejects, a cost bucket asserting a certainty nobody had, an audit reading through
symlinks out of its own directory, and a protocol document publishing two
different protocol numbers.

So v4 adds one idea to v3: the contract is **phase-aware**. What a receipt must
contain depends on how far its (command, status) pair actually got — planned,
discovered, attempted-but-never-classified, or classified — and that mapping is a
versioned table tested against the producer, not inferred from whether a field
happens to be truthy.

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

#: The instant D-074 published, kept as the historical literal it is. This module
#: guards the v4 closures, which are unchanged; the *current* effective instant is
#: pinned exactly once, by ``tests/test_qualification_v5_contract.py``.
D074_EFFECTIVE_INSTANT = "2026-08-10T09:11:48+00:00"

#: Every term on the right-hand side of the reconciliation equation, in the order the
#: protocol publishes them. Seven are exclusive semantic populations plus the count of
#: files this installation could not verify; the eighth,
#: ``qualification_exact_duplicate_copies``, is **not** a population — it is the
#: adjustment between the number of verified *files* and the deduplicated canon the
#: semantic populations are computed over. The sexdecies re-audit found the protocol
#: document publishing only seven of the eight, so the documented equation did not
#: balance as soon as one receipt file was filed twice.
EQUATION_TERMS = (
    "qualification_usable_receipts",
    "qualification_current_malformed_receipts",
    "qualification_current_contradictory_receipts",
    "qualification_unknown_pair_receipts",
    "qualification_historical_nonqualifying_receipts",
    "qualification_duplicate_excluded_receipts",
    "qualification_unverifiable_receipts",
    "qualification_exact_duplicate_copies",
)

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
SECRET = "ab" * 32


# ---------------------------------------------------------------------------
# Synthetic receipts
# ---------------------------------------------------------------------------
# `SECRET` is the API-key sentinel this suite checks for redaction. Receipts are
# signed with the injected receipt secret the `workspace` fixture installs, which is
# what `audit_receipts` verifies them against.
from helpers_activation import FAKE_RECEIPT_SECRET as _SIGNING  # noqa: E402

#: Every test in this module reads the receipt directory through
#: ``activation.receipt_dir()``. Without this, an unrelated
#: ``.activation-receipts`` in the working directory would be picked up and could
#: close the qualification gate for the whole module — see the fixture's docstring.
pytestmark = pytest.mark.usefixtures("isolated_receipt_directory")


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


def corpus(**over: Any) -> list[dict[str, Any]]:
    rows = [
        (FOOTBALL, D1, "a"),
        (FOOTBALL_2, D2, "b"),
        (FOOTBALL, D2, "c"),
        (TENNIS, D1, "d"),
        (TENNIS_2, D2, "f"),
        (TENNIS, D3, "0"),
    ]
    out = [
        core(receipt_id=f"{i:016x}", sport_key=k, moment=m, event_tag=t * 32, **over)
        for i, (k, m, t) in enumerate(rows, start=1)
    ]
    out.append(
        extra(receipt_id="aa" * 8, sport_key=FOOTBALL, moment=D1, event_tag="1" * 32, **over)
    )
    out.append(
        extra(receipt_id="bb" * 8, sport_key=FOOTBALL_2, moment=D2, event_tag="2" * 32, **over)
    )
    return out


def six_paid(**over: Any) -> list[dict[str, Any]]:
    rows = [
        (FOOTBALL, D1, "a"),
        (FOOTBALL_2, D2, "b"),
        (FOOTBALL, D2, "c"),
        (TENNIS, D1, "d"),
        (TENNIS_2, D2, "f"),
        (TENNIS, D3, "0"),
    ]
    return [
        core(receipt_id=f"{i:016x}", sport_key=k, moment=m, event_tag=t * 32, **over)
        for i, (k, m, t) in enumerate(rows, start=1)
    ]


def entry(document: dict[str, Any], criterion_id: str) -> dict[str, Any]:
    for candidate in document["criteria_results"]:
        if candidate["criterion_id"] == criterion_id:
            return candidate
    raise AssertionError(criterion_id)


def cost_of(document: dict[str, Any]) -> dict[str, Any]:
    return entry(document, "COST_CONFORMITY")


def write_all(directory: Path, receipts: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, receipt in enumerate(receipts, start=1):
        (directory / f"probe-{index:03d}.json").write_text(
            jsonlib.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )


@pytest.fixture(autouse=True)
def _signed_in_a_throwaway_directory(workspace: Path) -> Path:
    """Every receipt in this module is signed with the injected synthetic secret.

    Autouse because *building* a receipt signs it, and :func:`activation.receipt_secret`
    falls back to creating ``.activation-receipts/signing-key.secret`` next to the
    working directory when no secret is injected. A test module must never write a
    signing key into the repository, and a receipt signed under one secret and read
    under another would be silently unverifiable — every assertion here would then
    pass for the wrong reason.
    """
    return workspace


def attempt_for(command: str, **over: Any) -> Any:
    attempt = act.Attempt(
        command=command,
        sport=FOOTBALL,
        bookmaker=BOOK,
        window=WINDOW,
        ceiling=act.STEP_CEILINGS[command],
        now=D1,
    )
    for key, value in over.items():
        setattr(attempt, key, value)
    return attempt


#: Every (command, terminal status) pair the harness can actually write, with the
#: attempt shape that produces it. This is the matrix the re-audit built by hand;
#: pinning it here is what stops the contract from drifting away from its producer.
PRODUCER_MATRIX: list[tuple[str, str, dict[str, Any]]] = [
    ("plan", "PLAN_ONLY", {}),
    ("discover", "PREPARED_NOT_EXECUTED", {}),
    (
        "discover",
        "DISCOVERY_VERIFIED",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 2,
            "endpoints": ["/v4/sports", "/v4/sports/{sport}/events"],
            "event_tags": ["a" * 32, "b" * 32],
            "events_returned": 5,
            "events_in_window": 3,
            "events_admissible": 2,
            "observed": 0,
            "quota_remaining": 400,
        },
    ),
    (
        "discover",
        "PROVIDER_UNAVAILABLE",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "endpoints": ["/v4/sports"],
            "observed": None,
        },
    ),
    (
        "discover",
        "AUTH_FAILED",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "endpoints": ["/v4/sports"],
            "observed": None,
        },
    ),
    # D-076 removed `discover/SCHEMA_MISMATCH`: the two functions that raise it,
    # `_event_of` and `_check_start_time`, are reached from `run_core` and
    # `run_additional` only, so no discovery ever wrote this receipt. In its place the
    # table gained the two couples `run_discovery` really does write, through
    # `_settle_cost`.
    (
        "discover",
        "COST_UNVERIFIED",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 2,
            "endpoints": ["/v4/sports", "/v4/sports/{sport}/events"],
            "observed": None,
        },
    ),
    (
        "core",
        "CORE_LIVE_VERIFIED",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 1,
            "observed": 1,
            "endpoints": ["/v4/sports/{sport}/odds"],
            "event_tags": ["c" * 32],
            "markets_requested": ["h2h"],
            "market_states": {"h2h": "OBSERVED_MAPPED"},
            "freshness": {"h2h": 600},
            "selections_mapped": 3,
            "bookmaker_state": "OBSERVED",
            "quota_remaining": 399,
        },
    ),
    (
        "core",
        "COVERAGE_MISSING",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 1,
            "observed": 1,
            "endpoints": ["/v4/sports/{sport}/odds"],
            "event_tags": ["d" * 32],
            "markets_requested": ["h2h"],
            "market_states": {"h2h": "NOT_EVALUATED_BOOKMAKER_ABSENT"},
            "bookmaker_state": "NOT_RETURNED",
            "quota_remaining": 398,
        },
    ),
    (
        "core",
        "COST_UNVERIFIED",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 1,
            "observed": None,
            "endpoints": ["/v4/sports/{sport}/odds"],
            "event_tags": ["e" * 32],
            "markets_requested": ["h2h"],
        },
    ),
    (
        "core",
        "COST_MISMATCH",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 1,
            "observed": 4,
            "endpoints": ["/v4/sports/{sport}/odds"],
            "event_tags": ["f" * 32],
            "markets_requested": ["h2h"],
        },
    ),
    (
        "core",
        "AUTH_FAILED",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 1,
            "observed": None,
            "endpoints": ["/v4/sports/{sport}/odds"],
            "event_tags": ["0" * 32],
            "markets_requested": ["h2h"],
        },
    ),
    (
        "core",
        "SCHEMA_MISMATCH",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 1,
            "observed": 1,
            "endpoints": ["/v4/sports/{sport}/odds"],
            "event_tags": ["1" * 32],
            "markets_requested": ["h2h"],
        },
    ),
    (
        "core",
        "PROVIDER_UNAVAILABLE",
        {
            "network_attempted": True,
            "reached_provider": False,
            "attempts": 1,
            "estimated": 1,
            "observed": None,
            "endpoints": ["/v4/sports/{sport}/odds"],
            "event_tags": ["2" * 32],
            "markets_requested": ["h2h"],
        },
    ),
    ("core", "PREPARED_NOT_EXECUTED", {"markets_requested": ["h2h"]}),
    (
        "additional",
        "ADDITIONAL_LIVE_VERIFIED",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 5,
            "observed": 5,
            "endpoints": ["/v4/sports/{sport}/events/{event}/odds"],
            "event_tags": ["3" * 32],
            "markets_requested": list(MARKETS),
            "market_states": dict.fromkeys(MARKETS, "OBSERVED_MAPPED"),
            "freshness": dict.fromkeys(MARKETS, 300),
            "selections_mapped": 11,
            "bookmaker_state": "OBSERVED",
            "quota_remaining": 390,
        },
    ),
    (
        "additional",
        "ADDITIONAL_PARTIAL_COVERAGE",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 5,
            "observed": 5,
            "endpoints": ["/v4/sports/{sport}/events/{event}/odds"],
            "event_tags": ["4" * 32],
            "markets_requested": list(MARKETS),
            "market_states": {
                **dict.fromkeys(MARKETS[:-1], "OBSERVED_MAPPED"),
                MARKETS[-1]: "NOT_RETURNED",
            },
            "freshness": dict.fromkeys(MARKETS[:-1], 300),
            "selections_mapped": 9,
            "bookmaker_state": "OBSERVED",
            "quota_remaining": 385,
        },
    ),
    (
        "additional",
        "COVERAGE_MISSING",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 5,
            "observed": 5,
            "endpoints": ["/v4/sports/{sport}/events/{event}/odds"],
            "event_tags": ["5" * 32],
            "markets_requested": list(MARKETS),
            "market_states": dict.fromkeys(MARKETS, "NOT_EVALUATED_BOOKMAKER_ABSENT"),
            "bookmaker_state": "NOT_RETURNED",
            "quota_remaining": 380,
        },
    ),
    (
        "additional",
        "COST_MISMATCH",
        {
            "network_attempted": True,
            "reached_provider": True,
            "attempts": 1,
            "estimated": 5,
            "observed": 9,
            "endpoints": ["/v4/sports/{sport}/events/{event}/odds"],
            "event_tags": ["6" * 32],
            "markets_requested": list(MARKETS),
        },
    ),
    ("additional", "PREPARED_NOT_EXECUTED", {"markets_requested": list(MARKETS)}),
]


def produced(command: str, status: str, over: dict[str, Any]) -> dict[str, Any]:
    """Exactly what the harness would write for this pair, signed as it would be.

    ``build_receipt`` assembles and ``write_receipt`` signs, so a document straight
    out of the former carries no signature and every consumer would file it under
    ``unverified_or_unknown_schema`` — making a corpus of honest receipts look
    conflict-free for the wrong reason. The signature is added here so these tests
    exercise the consumer rather than its rejection path.
    """
    document = act.build_receipt(attempt_for(command, **over), act.ActivationStatus(status), SECRET)
    document[act.SIGNATURE_FIELD] = act.sign_receipt(document, _SIGNING)
    return document


# ---------------------------------------------------------------------------
class TestTheProtocolIsVersionFour:
    def test_the_versioned_constants(self) -> None:
        """The v4 closures, not the current version number.

        The number itself is pinned exactly once, by the v5 contract. What this module
        owes is that v4's own constants kept their meaning: the adapter-evidence version
        is still 1 and only a v4 *schema* can qualify — the receipt schema did not move
        when the protocol did.
        """
        assert qual.PROVIDER_ADAPTER_EVIDENCE_VERSION == 1
        assert qual.QUALIFYING_SCHEMA_VERSION == 4
        assert act.RECEIPT_SCHEMA_VERSION == 4
        assert isinstance(qual.PROVIDER_VALIDATION_PROTOCOL_VERSION, int)
        assert qual.PROVIDER_VALIDATION_PROTOCOL_VERSION >= 4

    def test_the_effective_instant_moved_forward_from_d074(self) -> None:
        """An effective instant only ever moves forward, and never back onto D-074's.

        Pinning the current value here would duplicate the v5 contract. What v4 owes is
        that its own instant was not quietly reused or rolled back, since evidence
        admitted under D-074 must not silently become current again.
        """
        current = datetime.fromisoformat(qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC)
        assert current >= datetime.fromisoformat(D074_EFFECTIVE_INSTANT)

    def test_protocol_three_evidence_is_now_historical(self) -> None:
        document = _evaluate(corpus(qualification_protocol_version=3), 0)
        assert [e for e in document["criteria_results"] if e["passed"]] == []
        assert document["qualification_reasons"]["other_protocol_version"] == 8

    def test_a_current_well_formed_corpus_still_reaches_the_gate(self) -> None:
        document = _evaluate(corpus(), 0)
        assert all(e["passed"] for e in document["criteria_results"])
        assert document["eligible_for_human_promotion_review"] is True


# ---------------------------------------------------------------------------
# P2-1 — the contract accepts what the producer honestly writes
# ---------------------------------------------------------------------------
class TestTheContractAcceptsItsOwnProducer:
    @pytest.mark.parametrize(
        ("command", "status", "over"),
        PRODUCER_MATRIX,
        ids=[f"{c}-{s}" for c, s, _ in PRODUCER_MATRIX],
    )
    def test_an_honestly_produced_receipt_is_never_malformed(
        self, command: str, status: str, over: dict[str, Any]
    ) -> None:
        assert qual.structural_faults(produced(command, status, over)) == []

    @pytest.mark.parametrize(
        ("command", "status", "over"),
        PRODUCER_MATRIX,
        ids=[f"{c}-{s}" for c, s, _ in PRODUCER_MATRIX],
    )
    def test_it_is_never_a_structural_conflict(
        self, command: str, status: str, over: dict[str, Any]
    ) -> None:
        document = _evaluate([produced(command, status, over)], 0)
        assert document["qualification_reasons"]["malformed_current_schema"] == 0
        assert document["qualification_reasons"]["unknown_command_status_pair"] == 0

    def test_a_corpus_of_every_honest_outcome_is_not_a_conflict(self, workspace: Path) -> None:
        from helpers_activation import run

        receipts = [produced(c, s, o) for c, s, o in PRODUCER_MATRIX]
        write_all(workspace, receipts)
        result = run("status", "--json")
        assert result.exit_code == 0, result.output
        payload = jsonlib.loads(result.stdout)
        assert payload["qualification_state"] != str(qual.QualificationState.EVIDENCE_CONFLICT)
        assert payload["qualification_reasons"]["malformed_current_schema"] == 0
        assert run("status").exit_code == 0

    def test_the_phase_table_covers_every_producible_pair(self) -> None:
        for command, status, _ in PRODUCER_MATRIX:
            assert (command, status) in qual.RECEIPT_PHASES, (command, status)

    def test_an_unknown_pair_is_named_rather_than_guessed(self) -> None:
        receipt = core(status="FUTURE_UNKNOWN_STATUS")
        assert qual.classify(receipt) == "unknown_command_status_pair"
        document = _evaluate([receipt], 0)
        assert document["eligible_for_human_promotion_review"] is False

    def test_an_error_receipt_stays_current_but_proves_nothing(self) -> None:
        receipt = produced("core", "AUTH_FAILED", dict(PRODUCER_MATRIX[10][2]))
        document = _evaluate([receipt], 0)
        assert qual.classify(receipt) == ""
        assert [e["criterion_id"] for e in document["criteria_results"] if e["passed"]] == []
        assert document["qualification_state"] != str(qual.QualificationState.EVIDENCE_CONFLICT)

    def test_an_incomplete_positive_status_is_still_refused(self) -> None:
        """A positive mapping status still owes the whole map and its projections."""
        receipt = core(market_states={}, markets_mapped=[], markets_observed=[])
        assert qual.structural_faults(receipt) != []
        assert qual.admissible_for(receipt, qual.CRITERIA[0]) is False


# ---------------------------------------------------------------------------
# §6.2 — common types
# ---------------------------------------------------------------------------
class TestCommonTypeContract:
    @pytest.mark.parametrize("version", [0, -1, True, "4", 4.0, None])
    def test_a_version_must_be_a_real_positive_integer(self, version: Any) -> None:
        assert qual.structural_faults(core(qualification_protocol_version=version)) != []

    @pytest.mark.parametrize("value", [-1, True, "1", 1.0, None])
    def test_a_credit_must_be_a_real_non_negative_integer(self, value: Any) -> None:
        assert qual.structural_faults(core(estimated_credits=value)) != []

    def test_zero_credits_are_accepted(self) -> None:
        assert (
            qual.structural_faults(
                core(estimated_credits=0, observed_credits=0, accounted_credits=0)
            )
            == []
        )

    def test_attempts_is_mandatory(self) -> None:
        assert qual.structural_faults(core(drop=("attempts",))) != []

    def test_no_network_means_no_attempt(self) -> None:
        assert qual.structural_faults(core(network_attempted=False, attempts=1)) != []
        assert (
            qual.structural_faults(
                core(
                    network_attempted=False,
                    may_have_reached_provider=False,
                    attempts=0,
                    status=str(act.ActivationStatus.PREPARED_NOT_EXECUTED),
                    market_states={},
                    markets_mapped=[],
                    markets_observed=[],
                    freshness={},
                    selections_mapped=0,
                    drop=("event_tag",),
                )
            )
            == []
        )

    def test_a_network_attempt_means_at_least_one_request(self) -> None:
        assert qual.structural_faults(core(network_attempted=True, attempts=0)) != []

    @pytest.mark.parametrize("flag", ["network_attempted", "may_have_reached_provider"])
    @pytest.mark.parametrize("value", ["true", "false", 1, 0, [], {}, None])
    def test_a_flag_must_be_an_exact_boolean(self, flag: str, value: Any) -> None:
        assert qual.structural_faults(core(**{flag: value})) != []

    @pytest.mark.parametrize("field", ["receipt_id", "sport_key", "bookmaker", "event_tag"])
    def test_an_identity_must_be_a_non_empty_string(self, field: str) -> None:
        assert qual.structural_faults(core(**{field: ""})) != []
        assert qual.structural_faults(core(**{field: 17})) != []

    @pytest.mark.parametrize("value", ["2026-08-11T12:00:00", "not-a-date", 17, None])
    def test_the_instant_must_carry_a_timezone(self, value: Any) -> None:
        assert qual.classify(core(recorded_at=value)) != ""

    def test_a_duplicated_projection_entry_is_refused(self) -> None:
        assert qual.structural_faults(core(markets_mapped=["h2h", "h2h"])) != []


# ---------------------------------------------------------------------------
# P2-2 — the five older dimensions never contradict the strict block
# ---------------------------------------------------------------------------
#: Built inside a test, never at decoration time: signing a receipt needs the
#: injected secret, which only exists once the autouse fixture has run.
DIMENSION_LABELS = [
    "conforming corpus",
    "six conforming + PROVIDER_UNAVAILABLE",
    "COST_UNVERIFIED",
    "COST_MISMATCH",
    'network_attempted = "false"',
    'may_have_reached_provider = "false"',
    "negative status with selections",
    "NOT_RETURNED with selections",
    "malformed current receipt",
    "contradictory current receipt",
    "historical v3 schema",
]


def dimension_corpus(label: str) -> list[dict[str, Any]]:
    for candidate, receipts in dimension_corpora():
        if candidate == label:
            return receipts
    raise AssertionError(label)


def dimension_corpora() -> list[tuple[str, list[dict[str, Any]]]]:
    unavailable = core(
        receipt_id="ff" * 8,
        event_tag="9" * 32,
        moment=D2,
        status=str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
        observed_credits=None,
        accounted_credits=1,
        market_states={},
        markets_requested=[],
        markets_mapped=[],
        markets_observed=[],
        selections_mapped=0,
        freshness={},
    )
    return [
        ("conforming corpus", corpus()),
        ("six conforming + PROVIDER_UNAVAILABLE", [*six_paid(), unavailable]),
        (
            "COST_UNVERIFIED",
            [
                *six_paid(),
                core(
                    receipt_id="ff" * 8,
                    event_tag="9" * 32,
                    moment=D2,
                    status=str(act.ActivationStatus.COST_UNVERIFIED),
                    observed_credits=None,
                    accounted_credits=1,
                    market_states={},
                    markets_requested=[],
                    markets_mapped=[],
                    markets_observed=[],
                    selections_mapped=0,
                    freshness={},
                ),
            ],
        ),
        (
            "COST_MISMATCH",
            [
                *six_paid(),
                core(
                    receipt_id="ff" * 8,
                    event_tag="9" * 32,
                    moment=D2,
                    status=str(act.ActivationStatus.COST_MISMATCH),
                    market_states={},
                    markets_requested=[],
                    markets_mapped=[],
                    markets_observed=[],
                    selections_mapped=0,
                    freshness={},
                ),
            ],
        ),
        ('network_attempted = "false"', six_paid(network_attempted="false")),
        ('may_have_reached_provider = "false"', six_paid(may_have_reached_provider="false")),
        (
            "negative status with selections",
            six_paid(
                status=str(act.ActivationStatus.COVERAGE_MISSING),
                market_states={"h2h": str(act.MarketState.NOT_EVALUATED_BOOKMAKER_ABSENT)},
                markets_mapped=[],
                markets_observed=[],
                markets_not_evaluated=["h2h"],
                freshness={},
                bookmaker_state=str(act.BookmakerState.NOT_RETURNED),
            ),
        ),
        (
            "NOT_RETURNED with selections",
            six_paid(bookmaker_state=str(act.BookmakerState.NOT_RETURNED)),
        ),
        ("malformed current receipt", six_paid(selections_mapped="3")),
        ("contradictory current receipt", six_paid(selections_mapped=0)),
        ("historical v3 schema", six_paid(schema_version=3)),
    ]


class TestTheOlderDimensionsAgreeWithTheStrictBlock:
    @pytest.mark.parametrize("label", DIMENSION_LABELS)
    def test_conforming_cost_never_hides_an_unestablished_one(self, label: str) -> None:
        """The label and the census it is derived from speak about one population.

        Checked against ``paid_call_cost_census`` rather than ``COST_CONFORMITY``'s
        ``observed``: the criterion counts the *current protocol's* paid calls,
        deduplicated, while the label speaks about every real paid attempt on disk. A
        corpus of protocol-3 receipts legitimately has six conforming attempts and
        zero current ones, and comparing those two numbers is a population error, not
        a contradiction. Both are asserted, each against its own population.
        """
        document = _state(dimension_corpus(label), 0)
        census = document["paid_call_cost_census"]
        criterion = cost_of(document)["observed"]
        if document["connectivity_and_cost_proof"] == str(act.CostProof.EXERCISED_CONFORMING):
            assert census["provider_reached_nonconforming_cost"] == 0, label
            assert census["provider_reached_cost_unestablished"] == 0, label
            assert census["provider_reached_conforming_cost"] >= 1, label
            # The criterion's population is a subset, so it cannot show a defect the
            # broader census does not.
            assert criterion["provider_reached_nonconforming_cost"] == 0, label
            assert criterion["provider_reached_cost_unestablished"] == 0, label

    @pytest.mark.parametrize("label", DIMENSION_LABELS)
    def test_obtained_live_never_rests_on_rejected_evidence(self, label: str) -> None:
        receipts = dimension_corpus(label)
        document = _state(receipts, 0)
        if document["mapping_freshness_proof"] == str(act.MappingProof.OBTAINED_LIVE):
            assert any(qual.mapping_observation_is_sound(r) for r in receipts), label

    @pytest.mark.parametrize("label", DIMENSION_LABELS)
    def test_coverage_observed_needs_an_observed_bookmaker(self, label: str) -> None:
        receipts = dimension_corpus(label)
        document = _state(receipts, 0)
        if document["paid_activation_state"] == str(
            act.PaidActivationState.CORE_EXECUTED_COVERAGE_OBSERVED
        ):
            assert any(qual.mapping_observation_is_sound(r) for r in receipts), label

    @pytest.mark.parametrize("label", DIMENSION_LABELS)
    def test_coverage_observations_only_carry_sound_receipts(self, label: str) -> None:
        document = _state(dimension_corpus(label), 0)
        for observation in document["bookmaker_coverage_observations"]:
            assert observation["bookmaker_state"] in {
                str(act.BookmakerState.OBSERVED),
                str(act.BookmakerState.NOT_RETURNED),
            }, label
            assert isinstance(observation["event_tag"], str) and observation["event_tag"], label

    def test_an_unestablished_cost_has_its_own_label(self) -> None:
        values = {str(v) for v in act.CostProof}
        assert "EXERCISED_UNESTABLISHED" in values
        receipts = [
            *six_paid(),
            core(
                receipt_id="ff" * 8,
                event_tag="9" * 32,
                moment=D2,
                status=str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
                observed_credits=None,
                accounted_credits=1,
                market_states={},
                markets_requested=[],
                markets_mapped=[],
                markets_observed=[],
                selections_mapped=0,
                freshness={},
            ),
        ]
        document = _state(receipts, 0)
        assert document["connectivity_and_cost_proof"] == str(act.CostProof.EXERCISED_UNESTABLISHED)

    def test_a_paid_attempt_that_proves_nothing_has_its_own_label(self) -> None:
        values = {str(v) for v in act.PaidActivationState}
        assert "PAID_ATTEMPT_INCONCLUSIVE" in values
        # `selections_mapped="3"` is outside the structural contract, so since D-076 the
        # receipts are rejected and the paid state says the attempt state is not
        # established rather than claiming an inconclusive *attempt*. Both labels exist
        # and neither is a positive proof, which is the property; the sound-but-useless
        # case below is the one that still reads `PAID_ATTEMPT_INCONCLUSIVE`.
        document = _state(six_paid(selections_mapped="3"), 0)
        assert document["paid_activation_state"] == str(
            act.PaidActivationState.PAID_ATTEMPT_STATE_UNESTABLISHED
        )
        sound = _state(
            [
                produced(
                    "core",
                    "AUTH_FAILED",
                    {
                        "network_attempted": True,
                        "reached_provider": True,
                        "attempts": 1,
                        "estimated": 1,
                        "observed": None,
                        "markets_requested": ["h2h"],
                        "event_id": "evt-v4-inconclusive",
                        "event_tags": ["e" * 32],
                    },
                )
            ],
            0,
        )
        assert sound["paid_activation_state"] == str(
            act.PaidActivationState.PAID_ATTEMPT_INCONCLUSIVE
        )

    def test_a_free_discovery_alone_leaves_the_paid_cost_unexercised(self) -> None:
        discovery = produced("discover", "DISCOVERY_VERIFIED", dict(PRODUCER_MATRIX[2][2]))
        document = _state([discovery], 0)
        assert document["connectivity_and_cost_proof"] == str(act.CostProof.NOT_EXERCISED)

    def test_accounted_credits_total_ignores_anything_that_is_not_a_count(self) -> None:
        document = _state(
            [
                core(accounted_credits=True),
                core(receipt_id="11" * 8, accounted_credits="7"),
                core(receipt_id="22" * 8, accounted_credits=-5),
                core(receipt_id="33" * 8, accounted_credits=2),
            ],
            0,
        )
        assert document["accounted_credits_total"] == 2


# ---------------------------------------------------------------------------
# P2-3 — `never left` means a certain False
# ---------------------------------------------------------------------------
class TestTheCostCategoriesSayWhatTheyKnow:
    def test_never_left_requires_an_exact_false(self) -> None:
        # A `CORE_LIVE_VERIFIED` that says it never left is self-contradictory since v5,
        # so the population is exercised on the status a provider error really writes.
        receipt = produced(
            "core",
            "PROVIDER_UNAVAILABLE",
            {
                "network_attempted": True,
                "reached_provider": False,
                "attempts": 1,
                "estimated": 1,
                "observed": None,
                "markets_requested": ["h2h"],
                "event_id": "evt-v4-never-left",
                "event_tags": ["f" * 32],
            },
        )
        assert qual.classify(receipt) == "", qual.structural_faults(receipt)
        observed = cost_of(_evaluate([receipt], 0))["observed"]
        assert observed["confirmed_attempts_not_sent"] == 1

    @pytest.mark.parametrize("flag", ["network_attempted", "may_have_reached_provider"])
    @pytest.mark.parametrize("value", ["false", "true", 1, 0, [], {}])
    def test_a_mistyped_flag_is_an_unestablished_cost(self, flag: str, value: Any) -> None:
        """Blocking, and never filed as a certainty.

        Protocol v5 split "the attempt state cannot be established" from "the request
        was confirmed not to have been served", so a mistyped flag now names which of
        the two is unknown. The property this test defends is unchanged: it counts, it
        blocks, and it is never reported as a call proven not to have left.
        """
        receipt = core(**{flag: value})
        document = _state([receipt], 0)
        result = cost_of(document)
        observed = result["observed"]
        # D-076: a mistyped flag is outside the structural contract, and a receipt the
        # contract rejects is no longer priced — it is counted in the forensic census and
        # named as an evidence conflict. The three properties this test defends survive
        # unchanged: it counts, it blocks, and it is never called a call proven not to
        # have left.
        if qual.classify(receipt) != "":
            assert sum(document["rejected_paid_cost_census"].values()) == 1
            assert document["rejected_paid_cost_census"]["confirmed_attempts_not_sent"] == 0
            assert document["qualification_state"] == "EVIDENCE_CONFLICT"
            assert document["eligible_for_human_promotion_review"] is False
            return
        assert observed["confirmed_attempts_not_sent"] == 0
        assert sum(observed[name] for name in qual.BLOCKING_COST_BUCKETS) == 1
        assert result["passed"] is False

    @pytest.mark.parametrize("flag", ["network_attempted", "may_have_reached_provider"])
    def test_an_absent_flag_is_an_unestablished_cost(self, flag: str) -> None:
        receipt = core(drop=(flag,))
        document = _state([receipt], 0)
        result = cost_of(document)
        observed = result["observed"]
        if qual.classify(receipt) != "":
            # See above: rejected receipts are counted forensically, never priced.
            assert sum(document["rejected_paid_cost_census"].values()) == 1
            assert document["rejected_paid_cost_census"]["confirmed_attempts_not_sent"] == 0
            assert document["qualification_state"] == "EVIDENCE_CONFLICT"
            return
        assert sum(observed[name] for name in qual.BLOCKING_COST_BUCKETS) == 1
        assert observed["confirmed_attempts_not_sent"] == 0
        assert result["passed"] is False

    def test_a_step_refused_before_the_network_is_not_a_paid_call(self) -> None:
        refused = produced("core", "PREPARED_NOT_EXECUTED", {"markets_requested": ["h2h"]})
        observed = cost_of(_evaluate([refused], 0))["observed"]
        assert sum(observed.values()) == 0

    def test_every_real_paid_attempt_lands_in_exactly_one_category(self) -> None:
        flags: list[Any] = [True, False, "false", 1, "__absent__"]
        statuses = [
            str(act.ActivationStatus.CORE_LIVE_VERIFIED),
            str(act.ActivationStatus.COVERAGE_MISSING),
            str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
            str(act.ActivationStatus.AUTH_FAILED),
            str(act.ActivationStatus.COST_MISMATCH),
            str(act.ActivationStatus.COST_UNVERIFIED),
        ]
        costs: list[dict[str, Any]] = [
            {},
            {"observed_credits": None, "accounted_credits": 1},
            {"observed_credits": True, "accounted_credits": True},
            {"observed_credits": 9, "accounted_credits": 9},
            {"observed_credits": 1, "accounted_credits": 3},
        ]
        for network in flags:
            for reached in flags:
                for status in statuses:
                    for cost in costs:
                        over: dict[str, Any] = {"status": status, **cost}
                        drop: list[str] = []
                        for name, value in (
                            ("network_attempted", network),
                            ("may_have_reached_provider", reached),
                        ):
                            if value == "__absent__":
                                drop.append(name)
                            else:
                                over[name] = value
                        receipt = core(
                            receipt_id="ff" * 8, event_tag="9" * 32, drop=tuple(drop), **over
                        )
                        observed = cost_of(_evaluate([receipt], 0))["observed"]
                        total = sum(observed.values())
                        if qual.classify(receipt) != "":
                            # Rejected: priced nowhere semantic, but the taxonomy itself
                            # still names exactly one population for it (D-076).
                            assert total == 0
                            assert (
                                qual.cost_category(receipt) in qual.COST_BUCKETS
                                or qual.attempt_state(receipt) is qual.AttemptState.NOT_ATTEMPTED
                            )
                            continue
                        # The denominator as protocol v5 documents it: a paid step whose
                        # attempt state is anything other than "never attempted". v4
                        # wrote this as `network_attempted is not False`, which put an
                        # absent flag and a confirmed request in the same population;
                        # the three-valued reading names them apart while keeping the
                        # property this test defends — exactly one bucket, or none.
                        counted = qual.attempt_state(receipt) is not qual.AttemptState.NOT_ATTEMPTED
                        assert total == (1 if counted else 0), (over, drop, observed)

    def test_the_pass_rule(self) -> None:
        assert cost_of(_evaluate(six_paid(), 0))["passed"] is True
        assert cost_of(_evaluate(six_paid()[:5], 0))["passed"] is False


# ---------------------------------------------------------------------------
# P2-4 — the audit stays inside its own directory
# ---------------------------------------------------------------------------
class TestTheAuditNeverLeavesItsDirectory:
    def _outside(self, workspace: Path) -> Path:
        elsewhere = workspace.parent / "outside-the-receipts"
        elsewhere.mkdir(parents=True, exist_ok=True)
        path = elsewhere / "foreign.json"
        path.write_text(
            jsonlib.dumps(core(receipt_id="ee" * 8, event_tag="e" * 32), default=str),
            encoding="utf-8",
        )
        return path

    def test_a_regular_file_is_read(self, workspace: Path) -> None:
        write_all(workspace, [core()])
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert len(receipts) == 1
        assert unverifiable == 0

    def test_an_internal_symlink_is_not_followed(self, workspace: Path) -> None:
        write_all(workspace, [core()])
        os.symlink(workspace / "probe-001.json", workspace / "link.json")
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert len(receipts) == 1
        assert unverifiable == 1

    def test_an_external_symlink_contributes_nothing(self, workspace: Path) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        os.symlink(self._outside(workspace), workspace / "link.json")
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert list(receipts) == []
        assert unverifiable == 1
        document = _state(receipts, unverifiable)
        assert entry(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0

    def test_a_broken_symlink_is_counted_not_opened(self, workspace: Path) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        os.symlink(workspace / "nothing-here.json", workspace / "broken.json")
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert list(receipts) == []
        assert unverifiable == 1

    def test_a_directory_named_json_is_counted(self, workspace: Path) -> None:
        (workspace / "folder.json").mkdir(parents=True, exist_ok=True)
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert list(receipts) == []
        assert unverifiable == 1

    def test_no_foreign_path_or_content_is_exposed(self, workspace: Path) -> None:
        from helpers_activation import run

        workspace.mkdir(parents=True, exist_ok=True)
        os.symlink(self._outside(workspace), workspace / "link.json")
        result = run("status", "--json")
        assert result.exit_code == 0
        assert "outside-the-receipts" not in result.stdout
        assert "ee" * 8 not in result.stdout


# ---------------------------------------------------------------------------
# P3 — write_receipt cannot leave the directory
# ---------------------------------------------------------------------------
class TestWriteReceiptStaysInside:
    def _payload(self, **over: Any) -> dict[str, Any]:
        return {k: v for k, v in core(**over).items() if k != act.SIGNATURE_FIELD}

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("receipt_id", "../outside"),
            ("receipt_id", "/tmp/absolute"),
            ("receipt_id", "aa/bb"),
            ("command", "../other"),
            ("command", "co/re"),
            ("recorded_at", "../../2026-08-11T12:00:00+00:00"),
        ],
    )
    def test_a_hostile_component_is_refused(self, workspace: Path, field: str, value: str) -> None:
        before = set(workspace.parent.iterdir())
        with pytest.raises(act.Refused):
            act.write_receipt(self._payload(**{field: value}))
        assert set(workspace.parent.iterdir()) == before

    def test_a_symbolic_target_is_refused_before_being_read(self, workspace: Path) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        elsewhere = workspace.parent / "victim.json"
        elsewhere.write_text("untouched\n", encoding="utf-8")
        payload = self._payload(receipt_id="cc" * 8)
        stamp = str(payload["recorded_at"]).replace(":", "").replace("-", "")[:15]
        os.symlink(elsewhere, workspace / f"{stamp}-core-{payload['receipt_id']}.json")
        with pytest.raises(act.Refused):
            act.write_receipt(dict(payload))
        assert elsewhere.read_text(encoding="utf-8") == "untouched\n"

    def test_an_identical_rewrite_is_idempotent(self, workspace: Path) -> None:
        first = act.write_receipt(self._payload(receipt_id="dd" * 8))
        before = first.read_text(encoding="utf-8")
        assert act.write_receipt(self._payload(receipt_id="dd" * 8)) == first
        assert first.read_text(encoding="utf-8") == before

    def test_a_divergent_rewrite_is_refused(self, workspace: Path) -> None:
        path = act.write_receipt(self._payload(receipt_id="dd" * 8))
        before = path.read_text(encoding="utf-8")
        with pytest.raises(act.Refused):
            act.write_receipt(self._payload(receipt_id="dd" * 8, selections_mapped=9))
        assert path.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# P3 — populations, their equation, and duplicate identifiers
# ---------------------------------------------------------------------------
class TestThePopulationsReconcile:
    def _mixed(self) -> list[dict[str, Any]]:
        return [
            core(receipt_id="1" * 16, event_tag="a" * 32),
            core(receipt_id="2" * 16, event_tag="b" * 32, selections_mapped="3"),
            core(receipt_id="3" * 16, event_tag="c" * 32, selections_mapped=0),
            core(receipt_id="4" * 16, event_tag="d" * 32),
            core(receipt_id="4" * 16, event_tag="e" * 32),
            core(receipt_id="5" * 16, event_tag="f" * 32, qualification_protocol_version=3),
            core(receipt_id="6" * 16, event_tag="0" * 32, schema_version=3),
            core(receipt_id="7" * 16, event_tag="1" * 32, schema_version=99),
        ]

    def test_every_receipt_is_in_exactly_one_population(self) -> None:
        """All eight terms, not the six this test used to sum.

        Its fixture has neither an unknown pair nor an exact copy, so omitting those two
        terms left the sum right by accident. ``TestThePublishedEquationIsComplete``
        below carries a corpus where both are non-zero.
        """
        receipts = self._mixed()
        document = _evaluate(receipts, 0)
        total = sum(document[field] for field in EQUATION_TERMS)
        assert total == len(receipts)

    def test_a_current_malformed_receipt_is_not_called_historical(self) -> None:
        document = _evaluate([core(selections_mapped="3")], 0)
        assert document["qualification_current_malformed_receipts"] == 1
        assert document["qualification_historical_nonqualifying_receipts"] == 0

    def test_the_published_equation_names_all_eight_terms(self) -> None:
        """The string `status` prints must not describe a shorter sum than it computes."""
        published = _evaluate(self._mixed(), 0)["qualification_population_equation"]
        left, _, right = published.partition("=")
        assert "invérifiables" in left, published
        assert len(right.split("+")) == len(EQUATION_TERMS), published
        assert "copies exactes" in right, published

    def test_a_current_contradictory_receipt_is_not_called_historical(self) -> None:
        """A contradiction the structural contract does not already catch.

        The original fixture was ``selections_mapped=0`` on a ``CORE_LIVE_VERIFIED``
        receipt. Protocol v5 refuses that earlier, as *malformed*: a positive mapping
        status owes at least one mapped selection. So the example moves to a receipt that
        is structurally impeccable and still disagrees with itself — accounting for fewer
        credits than the provider reported — which is what this test is about.
        """
        document = _evaluate([core(observed_credits=1, accounted_credits=0)], 0)
        assert document["qualification_current_contradictory_receipts"] == 1
        assert document["qualification_historical_nonqualifying_receipts"] == 0

    def test_an_exact_copy_is_one_observation(self) -> None:
        one = core(receipt_id="cc" * 8)
        document = _evaluate([one, dict(one), dict(one)], 0)
        assert entry(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 1
        assert document["qualification_duplicate_excluded_receipts"] == 0


class TestThePublishedEquationIsComplete:
    """One corpus, four agreements: the sum, the fields, the string, the protocol.

    The sexdecies re-audit found the equation right in the code and wrong in the
    document that publishes it as normative. ``docs/provider-validation-protocol.md``
    §3.1 listed seven terms; the calculation uses eight. Eight honest receipts plus two
    byte-identical copies made the documented form read ``10 = 8``, so an operator
    reconciling `status` by hand against the protocol saw a gap and could not tell a
    silently dropped receipt from a documentation error.

    The corpus below deliberately makes the two previously omitted terms non-zero — an
    unknown command/status pair and an exact copy — because a fixture where they are
    zero is exactly how the omission survived.
    """

    PROTOCOL = Path(qual.__file__).resolve().parents[4] / "docs" / "provider-validation-protocol.md"

    def _corpus(self) -> list[dict[str, Any]]:
        twin = core(receipt_id="a1" * 8, event_tag="a" * 32)
        return [
            twin,
            dict(twin),  # byte-for-byte copy -> qualification_exact_duplicate_copies
            core(receipt_id="b2" * 8, event_tag="b" * 32),
            core(receipt_id="c3" * 8, event_tag="c" * 32, command="discover"),  # unknown pair
            core(receipt_id="d4" * 8, event_tag="d" * 32, selections_mapped="3"),  # malformed
            core(receipt_id="e5" * 8, event_tag="e" * 32, observed_credits=1, accounted_credits=0),
            core(receipt_id="f6" * 8, event_tag="f" * 32, qualification_protocol_version=3),
            core(receipt_id="07" * 8, event_tag="0" * 32),
            core(receipt_id="07" * 8, event_tag="1" * 32),  # divergent identifier
        ]

    def _document(self) -> Any:
        return _evaluate(self._corpus(), 2)

    def test_the_corpus_exercises_the_two_previously_omitted_terms(self) -> None:
        """Guard the guard: a corpus where these are zero proves nothing."""
        document = self._document()
        assert document["qualification_unknown_pair_receipts"] >= 1
        assert document["qualification_exact_duplicate_copies"] >= 1
        assert document["qualification_unverifiable_receipts"] >= 1

    def test_the_sum_is_exact_on_a_non_trivial_corpus(self) -> None:
        corpus = self._corpus()
        document = self._document()
        assert sum(document[field] for field in EQUATION_TERMS) == len(corpus) + 2

    def test_every_term_of_the_equation_is_published_as_a_field(self) -> None:
        document = self._document()
        for field in EQUATION_TERMS:
            assert field in document, f"{field} is summed but never published"
            assert isinstance(document[field], int) and not isinstance(document[field], bool)
            assert document[field] >= 0

    def test_the_published_string_and_the_fields_agree(self) -> None:
        """As many named terms on the right of the string as there are summed fields."""
        document = self._document()
        _, _, right = document["qualification_population_equation"].partition("=")
        assert len(right.split("+")) == len(EQUATION_TERMS)
        assert "copies exactes" in right

    def test_the_protocol_publishes_exactly_the_terms_the_code_sums(self) -> None:
        """The normative block must name the eight fields — no more, no fewer.

        Red on ``76ef6d6``: the block named seven, omitting
        ``qualification_exact_duplicate_copies``.
        """
        text = self.PROTOCOL.read_text(encoding="utf-8")
        section = text.split("### 3.1", 1)[1].split("### 3.2", 1)[0]
        block = section.split("```text", 1)[1].split("```", 1)[0]
        named = {line.strip(" +=\t") for line in block.splitlines()}
        named = {item for item in named if item.startswith("qualification_")}
        assert named == set(EQUATION_TERMS), (
            "the normative equation and the calculation disagree; "
            f"missing from the document: {sorted(set(EQUATION_TERMS) - named)}; "
            f"documented but not summed: {sorted(named - set(EQUATION_TERMS))}"
        )

    def test_the_protocol_says_exact_copies_are_an_adjustment_not_a_population(self) -> None:
        """The eighth term must not read as a ninth kind of receipt."""
        section = (
            self.PROTOCOL.read_text(encoding="utf-8").split("### 3.1", 1)[1].split("### 3.2", 1)[0]
        )
        # Prose is hard-wrapped, so a phrase may straddle a newline.
        flat = " ".join(section.split())
        assert "pas une population" in flat
        assert "ajustement" in flat
        assert "dédupliqué" in flat, "the canon the populations are computed over must be named"

    @pytest.mark.parametrize(
        ("label", "first", "second"),
        [
            ("usable + usable", {}, {"event_tag": "z" * 32}),
            ("usable + malformed", {}, {"event_tag": "z" * 32, "selections_mapped": "3"}),
            ("usable + contradictory", {}, {"event_tag": "z" * 32, "selections_mapped": 0}),
            (
                "usable + historical",
                {},
                {"event_tag": "z" * 32, "qualification_protocol_version": 3},
            ),
            (
                "historical + historical",
                {"qualification_protocol_version": 3},
                {"event_tag": "z" * 32, "qualification_protocol_version": 3},
            ),
        ],
    )
    def test_a_divergent_identifier_contributes_nothing(
        self, label: str, first: dict[str, Any], second: dict[str, Any]
    ) -> None:
        receipts = [
            core(receipt_id="dd" * 8, event_tag="a" * 32, **first),
            core(receipt_id="dd" * 8, **second),
        ]
        document = _evaluate(receipts, 0)
        assert entry(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 0, label
        assert document["qualification_duplicate_excluded_receipts"] == 2, label
        assert document["evidence_conflicts"], label


# ---------------------------------------------------------------------------
# P3 — no malformed value is ever reflected
# ---------------------------------------------------------------------------
# A plain sentinel string in `sport_key` or `bookmaker` is a perfectly well-formed value, so it
# cannot be used on its own: the receipt would not be malformed and the field would legitimately
# appear in the output. The two "beside a fault" rows therefore carry a well-typed sentinel next to
# an unrelated structural fault, which is the property that matters — a receipt rejected for one
# field must not have any of its other fields echoed either.
SENTINELS: list[tuple[str, dict[str, Any]]] = [
    ("sport_key beside a fault", {"sport_key": "SENTINEL_SPORT_SECRET", "selections_mapped": "3"}),
    ("sport_key mistyped", {"sport_key": {"x": "SENTINEL_SPORT_SECRET"}}),
    (
        "bookmaker beside a fault",
        {"bookmaker": "SENTINEL_BOOKMAKER_SECRET", "selections_mapped": "3"},
    ),
    ("bookmaker mistyped", {"bookmaker": ["SENTINEL_BOOKMAKER_SECRET"]}),
    ("event_tag mistyped", {"event_tag": {"t": "SENTINEL_EVENT_SECRET"}}),
    ("market_states value", {"market_states": {"h2h": "SENTINEL_MARKET_SECRET"}}),
    (
        "market_states key",
        {
            "market_states": {"SENTINEL_MARKET_SECRET": "OBSERVED_MAPPED"},
            "markets_requested": ["SENTINEL_MARKET_SECRET"],
        },
    ),
    ("markets_mapped", {"markets_mapped": ["SENTINEL_MARKET_SECRET"]}),
    ("mapping_rejections mistyped", {"mapping_rejections": "SENTINEL_REJECTION_SECRET"}),
    ("freshness key", {"freshness": {"SENTINEL_MARKET_SECRET": 600}}),
]


class TestAMalformedValueIsNeverReflected:
    @pytest.mark.parametrize(("label", "over"), SENTINELS, ids=[s[0] for s in SENTINELS])
    def test_no_sentinel_reaches_any_output(
        self, workspace: Path, label: str, over: dict[str, Any]
    ) -> None:
        from helpers_activation import run

        receipt = core(receipt_id="ff" * 8, **over)
        assert qual.structural_faults(receipt) != [], "the fixture must be malformed"
        write_all(workspace, [receipt])
        js = run("status", "--json")
        human = run("status")
        assert js.exit_code == 0, js.output
        assert human.exit_code == 0, human.output
        for sentinel in (
            "SENTINEL_SPORT_SECRET",
            "SENTINEL_BOOKMAKER_SECRET",
            "SENTINEL_EVENT_SECRET",
            "SENTINEL_MARKET_SECRET",
            "SENTINEL_REJECTION_SECRET",
        ):
            assert sentinel not in js.stdout, (label, sentinel)
            assert sentinel not in human.stdout, (label, sentinel)

    def test_the_reason_still_names_the_field(self) -> None:
        document = _evaluate([core(selections_mapped="3")], 0)
        assert document["qualification_reasons"]["malformed_current_schema"] == 1
        assert any("selections_mapped" in c for c in document["evidence_conflicts"])
