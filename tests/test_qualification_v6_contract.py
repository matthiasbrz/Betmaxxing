"""Protocol v6: closed commands, six cost populations, one honest catalogue.

Why this suite exists
---------------------
The fifth independent read-only audit of `e43851e` reproduced, besides the secret
and the directory, four defects the earlier suites could not see because they all
asked the question the implementation asked.

* ``execution_state`` rounded **any** confirmed attempt that was not exactly
  ``core`` or ``additional`` up to ``DISCOVERY_ATTEMPTED`` — ``plan``, an absent
  command, an empty string, ``sync``, ``7``, ``["core"]``, ``Core`` and
  ``" core "``. The two-valued reading D-075 removed from ``network_attempted``
  was still there, applied to ``command``; worse, ``Core`` and ``" core "`` carry
  no structural fault, escape ``PAID_COMMANDS``, and take a paid step out of the
  cost census entirely.
* ``provider_reached_unestablished_cost`` asserted in its own name that the
  provider had been reached, while two of its three feeders were exactly the cases
  where the reach was **not** established.
* a receipt the contract rejects still fed the census, the connectivity label,
  ``execution_state`` and ``paid_activation_state`` — against the claim, in the
  body of the pull request, that it feeds no semantic counter.
* ``run_discovery`` calls ``_settle_cost``, which raises ``COST_UNVERIFIED``
  whenever the free endpoints omit the credit header and ``COST_MISMATCH`` above
  the ceiling. Neither couple was in ``RECEIPT_PHASES``, so an **honest** receipt
  written by the harness itself was filed as ``unknown_command_status_pair`` and
  drove a whole corpus to ``EVIDENCE_CONFLICT``. Meanwhile
  ``discover/SCHEMA_MISMATCH`` was declared producible with no producer at all.

The last one is why the catalogue is now checked **in both directions**, against
the real command paths driven through a fake transport rather than against
``build_receipt`` called by hand. A hand-written list of "producible" couples is
exactly what drifted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from betmaxxing.providers.the_odds_api import receipt_store as store
from helpers_activation import (
    ADDITIONAL_MARKET_KEYS,
    FAKE_RECEIPT_SECRET,
    Recorder,
    additional_args,
    core_args,
    discover_args,
    event_odds_payload,
    events_payload,
    install,
    odds_payload,
    plan_args,
    receipts_in,
    run,
    sports_payload,
)

EFFECTIVE_INSTANT = "2026-08-11T04:50:40+00:00"
FREE = {"x-requests-last": "0", "x-requests-remaining": "487"}
PAID = {"x-requests-last": "1", "x-requests-remaining": "486"}
FIVE = {"x-requests-last": "5", "x-requests-remaining": "482"}
NO_HEADER: dict[str, str] = {}


def trusted(payloads: list[dict[str, Any]], unverifiable: int = 0) -> store.VerifiedReceiptBatch:
    """The provenance the evaluator requires, minted the way the audit mints it."""
    return store.VerifiedReceiptBatch(
        tuple(store.trust(p, secret=FAKE_RECEIPT_SECRET) for p in payloads), unverifiable
    )


def receipt(**over: Any) -> dict[str, Any]:
    """One synthetic receipt, signed last so a dropped field stays signed."""
    from helpers_qualification_corpus import effective_instant, sign_with
    from helpers_qualification_corpus import receipt as build

    drop = over.pop("drop", ())
    document = build(
        command=over.pop("command", "core"),
        status=over.pop("status", "CORE_LIVE_VERIFIED"),
        sport=over.pop("sport", "soccer_v6_one"),
        moment=over.pop("moment", effective_instant()),
        tag=over.pop("tag", "a1" * 16),
        markets=over.pop("markets", ["h2h"]),
        credits=over.pop("credits", 1),
        secret=FAKE_RECEIPT_SECRET,
        **over,
    )
    for field in drop:
        document.pop(field, None)
    if drop:
        document.pop(act.SIGNATURE_FIELD, None)
        document[act.SIGNATURE_FIELD] = sign_with(document, FAKE_RECEIPT_SECRET)
    return document


def state_of(payloads: list[dict[str, Any]], unverifiable: int = 0) -> dict[str, Any]:
    return act.build_activation_state(trusted(payloads, unverifiable), unverifiable)


UNCLASSIFIED: dict[str, Any] = {
    "markets": [],
    "markets_requested": ["h2h"],
    "market_states": {},
    "markets_mapped": [],
    "markets_observed": [],
    "markets_rejected": [],
    "markets_absent": [],
    "markets_not_evaluated": [],
    "selections_mapped": 0,
    "freshness": {},
    "bookmaker_state": "NOT_RETURNED",
}


def unclassified(**over: Any) -> dict[str, Any]:
    """The shape the harness really writes when a step fails before classification.

    ``COST_MISMATCH``, ``COST_UNVERIFIED``, ``AUTH_FAILED`` and
    ``PROVIDER_UNAVAILABLE`` are all settled before a single market has a state, so
    their receipts carry an empty map. Building them with a classified map would test a
    document no producer emits — the mistake v3 made in the other direction.
    """
    return receipt(**{**UNCLASSIFIED, **over})


NEVER_SENT = {
    "status": "PREPARED_NOT_EXECUTED",
    "may_have_reached_provider": False,
    "network_attempted": False,
    "attempts": 0,
    "markets": [],
    "credits": 0,
    "market_states": {},
    "markets_mapped": [],
    "markets_observed": [],
    "markets_requested": ["h2h"],
    "markets_not_evaluated": ["h2h"],
    "selections_mapped": 0,
    "freshness": {},
    "bookmaker_state": "NOT_RETURNED",
    "observed_credits": None,
    "accounted_credits": 0,
    "estimated_credits": 1,
}


# ---------------------------------------------------------------------------
# D1 — the protocol this suite pins
# ---------------------------------------------------------------------------
class TestTheProtocolIsVersionSix:
    def test_the_three_version_numbers(self) -> None:
        assert qual.PROVIDER_VALIDATION_PROTOCOL_VERSION == 6
        assert qual.PROVIDER_ADAPTER_EVIDENCE_VERSION == 1
        assert qual.QUALIFYING_SCHEMA_VERSION == 4
        assert act.RECEIPT_SCHEMA_VERSION == 4

    def test_the_effective_instant_is_literal_and_written_once(self) -> None:
        assert qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC == EFFECTIVE_INSTANT
        source = Path(qual.__file__).read_text(encoding="utf-8")
        assert source.count(EFFECTIVE_INSTANT) == 1
        for stale in (
            "2026-08-10T14:00:37+00:00",
            "2026-08-10T09:11:48+00:00",
            "2026-08-10T07:19:48+00:00",
            "2026-08-09T19:38:29+00:00",
        ):
            assert stale not in source

    def test_a_protocol_five_receipt_is_historical_not_current(self) -> None:
        old = receipt(qualification_protocol_version=5)
        assert qual.currency_reason(old) == "other_protocol_version"
        document = state_of([old])
        assert document["qualification_historical_nonqualifying_receipts"] == 1
        assert document["qualification_usable_receipts"] == 0

    def test_the_machine_ceiling_is_still_a_request_for_human_review(self) -> None:
        from helpers_qualification_corpus import threshold_corpus

        document = state_of(threshold_corpus(FAKE_RECEIPT_SECRET))
        assert document["qualification_state"] == str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )
        assert document["eligible_for_human_promotion_review"] is True
        assert document["adapter_state"] == "IMPLEMENTED_UNVERIFIED"
        assert set(qual.QualificationState) == {
            qual.QualificationState.INSUFFICIENT_EVIDENCE,
            qual.QualificationState.EVIDENCE_CONFLICT,
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW,
        }


# ---------------------------------------------------------------------------
# D6 — the command is a closed domain
# ---------------------------------------------------------------------------
CONFIRMED: list[tuple[str, dict[str, Any], str]] = [
    ("plan", {"command": "plan", "status": "PLAN_ONLY"}, "PLAN"),
    (
        "discover",
        {
            "command": "discover",
            "status": "DISCOVERY_VERIFIED",
            **UNCLASSIFIED,
            "markets_requested": [],
            "credits": 0,
            "observed_credits": 0,
            "accounted_credits": 0,
            "estimated_credits": 0,
            "events_returned": 1,
            "events_in_window": 1,
            "events_admissible": 1,
            "event_tags": ["a" * 32],
            "event_tag": "",
        },
        "DISCOVER",
    ),
    ("core", {"command": "core"}, "CORE"),
    (
        "additional",
        {
            "command": "additional",
            "status": "ADDITIONAL_LIVE_VERIFIED",
            "markets": list(ADDITIONAL_MARKET_KEYS),
            "credits": 5,
        },
        "ADDITIONAL",
    ),
    ("absent", {"drop": ("command",)}, "COMMAND_STATE_UNESTABLISHED"),
    ("empty string", {"command": ""}, "COMMAND_STATE_UNESTABLISHED"),
    ("None", {"command": None}, "COMMAND_STATE_UNESTABLISHED"),
    ("7", {"command": 7}, "COMMAND_STATE_UNESTABLISHED"),
    ('["core"]', {"command": ["core"]}, "COMMAND_STATE_UNESTABLISHED"),
    ("sync", {"command": "sync"}, "COMMAND_STATE_UNESTABLISHED"),
    ("Core", {"command": "Core"}, "COMMAND_STATE_UNESTABLISHED"),
    ("' core '", {"command": " core "}, "COMMAND_STATE_UNESTABLISHED"),
]


class TestTheCommandIsReadStrictly:
    @pytest.mark.parametrize(
        ("label", "over", "expected"), CONFIRMED, ids=[c[0] for c in CONFIRMED]
    )
    def test_command_state_has_five_values_and_no_coercion(
        self, label: str, over: dict[str, Any], expected: str
    ) -> None:
        assert str(qual.command_state(receipt(**over))) == expected

    def test_the_five_values_are_the_whole_domain(self) -> None:
        assert {str(value) for value in qual.CommandState} == {
            "PLAN",
            "DISCOVER",
            "CORE",
            "ADDITIONAL",
            "COMMAND_STATE_UNESTABLISHED",
        }

    @pytest.mark.parametrize(
        ("label", "over"),
        [
            (label, over)
            for label, over, expected in CONFIRMED
            if expected == "COMMAND_STATE_UNESTABLISHED"
        ],
        ids=[c[0] for c in CONFIRMED if c[2] == "COMMAND_STATE_UNESTABLISHED"],
    )
    def test_an_unestablished_command_is_a_structural_fault(
        self, label: str, over: dict[str, Any]
    ) -> None:
        assert "command" in qual.structural_faults(receipt(**over))

    @pytest.mark.parametrize(
        ("label", "over", "expected"), CONFIRMED, ids=[c[0] for c in CONFIRMED]
    )
    def test_only_a_real_discover_reports_discovery_attempted(
        self, label: str, over: dict[str, Any], expected: str
    ) -> None:
        document = state_of([receipt(**over)])
        if expected == "DISCOVER":
            assert document["execution_state"] == "DISCOVERY_ATTEMPTED"
        else:
            assert document["execution_state"] != "DISCOVERY_ATTEMPTED", (
                f"{label} reported a discovery it never made"
            )

    def test_a_plan_receipt_claiming_a_confirmed_attempt_is_contradictory(self) -> None:
        planned = unclassified(
            command="plan",
            status="PLAN_ONLY",
            markets_requested=[],
            credits=0,
            observed_credits=0,
            accounted_credits=0,
            estimated_credits=0,
            # The PLANNED phase already demands `network_attempted is False`, so the
            # shape below is the one the contradiction rule exists for: a plan receipt
            # that respects the phase and still counts an attempt.
            network_attempted=False,
            attempts=1,
            may_have_reached_provider=False,
        )
        # Two guards, and they agree. The PLANNED phase requires both `network_attempted
        # is False` **and** `attempts == 0`, so this receipt is malformed as well as
        # self-contradictory; the semantic rule is stated in `contradictions` so the
        # invariant survives a change to the phase table.
        assert any("plan" in reason for reason in qual.contradictions(planned))
        assert qual.classify(planned) == "malformed_current_schema"
        document = state_of([planned])
        assert document["execution_state"] != "DISCOVERY_ATTEMPTED"
        assert document["qualification_current_malformed_receipts"] == 1
        assert document["qualification_usable_receipts"] == 0
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"

    def test_a_sound_plan_receipt_reports_no_network(self) -> None:
        document = state_of(
            [
                receipt(
                    command="plan",
                    status="PLAN_ONLY",
                    **{
                        k: v
                        for k, v in NEVER_SENT.items()
                        if k
                        not in {"status", "markets", "markets_requested", "markets_not_evaluated"}
                    },
                )
            ]
        )
        assert document["execution_state"] == "NO_NETWORK_ATTEMPTED"
        assert document["paid_activation_state"] == "PREPARED_NOT_EXECUTED"

    @pytest.mark.parametrize("command", ["Core", " core ", "sync", "", "CORE"])
    def test_a_lookalike_command_is_never_paid_and_never_priced(self, command: str) -> None:
        document = receipt(command=command, accounted_credits=7)
        assert qual.is_paid_command(document) is False
        assert qual.cost_category(document) == ""
        assert "command" in qual.structural_faults(document)
        state = state_of([document])
        assert state["paid_call_cost_census"] == dict.fromkeys(qual.COST_BUCKETS, 0)
        assert state["accounted_credits_total"] == 0
        assert state["rejected_receipt_credits_not_counted"] == 7
        # The unknown couple comes first, deliberately: naming the fields would blame
        # them for a command vocabulary the protocol does not have.
        assert state["qualification_reasons"]["unknown_command_status_pair"] == 1


# ---------------------------------------------------------------------------
# D7 — six cost populations, and none of them over-asserts
# ---------------------------------------------------------------------------
class TestTheCostTaxonomyIsSix:
    def test_the_six_names(self) -> None:
        assert qual.COST_BUCKETS == (
            "provider_reached_conforming_cost",
            "provider_reached_nonconforming_cost",
            "provider_reached_cost_unestablished",
            "provider_reach_unestablished",
            "paid_attempt_state_unestablished",
            "confirmed_attempts_not_sent",
        )
        assert "provider_reached_unestablished_cost" not in qual.COST_BUCKETS

    def test_the_four_blocking_ones(self) -> None:
        assert qual.BLOCKING_COST_BUCKETS == (
            "provider_reached_nonconforming_cost",
            "provider_reached_cost_unestablished",
            "provider_reach_unestablished",
            "paid_attempt_state_unestablished",
        )
        assert "confirmed_attempts_not_sent" not in qual.BLOCKING_COST_BUCKETS
        assert "provider_reached_conforming_cost" not in qual.BLOCKING_COST_BUCKETS

    def test_an_established_reach_with_an_unestablished_cost_is_named_for_the_cost(self) -> None:
        unverified = receipt(status="COST_UNVERIFIED", observed_credits=None, accounted_credits=1)
        assert qual.provider_was_reached(unverified) is True
        assert qual.cost_category(unverified) == "provider_reached_cost_unestablished"

    @pytest.mark.parametrize(
        ("label", "over"),
        [
            ("mistyped", {"may_have_reached_provider": "yes"}),
            ("absent", {"drop": ("may_have_reached_provider",)}),
            ("integer", {"may_have_reached_provider": 1}),
        ],
    )
    def test_an_unestablished_reach_is_never_named_as_reached(
        self, label: str, over: dict[str, Any]
    ) -> None:
        document = receipt(**over)
        assert qual.provider_was_reached(document) is False
        category = qual.cost_category(document)
        assert category in {"provider_reach_unestablished", ""}
        assert "provider_reached" not in category

    def test_exactly_one_category_per_paid_step_or_none(self) -> None:
        for label, over, _ in CONFIRMED:
            document = receipt(**over)
            categories = [
                name for name in qual.COST_BUCKETS if qual.cost_category(document) == name
            ]
            assert len(categories) <= 1, label

    def test_the_census_and_the_label_agree_on_every_population(self) -> None:
        cases: list[tuple[str, dict[str, Any], str, str]] = [
            ("conforming", {}, "provider_reached_conforming_cost", "EXERCISED_CONFORMING"),
            (
                "nonconforming",
                {
                    "status": "COST_MISMATCH",
                    "observed_credits": 4,
                    "accounted_credits": 4,
                    "estimated_credits": 1,
                },
                "provider_reached_nonconforming_cost",
                "EXERCISED_NONCONFORMING",
            ),
            (
                "cost unestablished",
                {
                    "status": "COST_UNVERIFIED",
                    "observed_credits": None,
                    "accounted_credits": 1,
                    "estimated_credits": 1,
                },
                "provider_reached_cost_unestablished",
                "EXERCISED_UNESTABLISHED",
            ),
            (
                "never sent",
                {
                    "status": "PROVIDER_UNAVAILABLE",
                    "may_have_reached_provider": False,
                    "observed_credits": None,
                    "accounted_credits": 0,
                    "estimated_credits": 1,
                },
                "confirmed_attempts_not_sent",
                "NOT_EXERCISED",
            ),
        ]
        for label, over, bucket, proof in cases:
            document = receipt() if label == "conforming" else unclassified(**over)
            state = state_of([document])
            assert qual.classify(document) == "", (
                label,
                qual.structural_faults(document),
                qual.contradictions(document),
            )
            assert qual.cost_category(document) == bucket, label
            assert state["paid_call_cost_census"][bucket] == 1, label
            assert state["connectivity_and_cost_proof"] == proof, label

    def test_the_two_populations_no_sound_receipt_can_reach_are_named_as_such(self) -> None:
        """An honest consequence of D-076, stated rather than hidden.

        ``may_have_reached_provider`` is a boolean and ``attempts`` a counter, so a
        receipt that leaves either unestablished is outside the structural contract —
        and a rejected receipt feeds no semantic counter. The two populations therefore
        stay nought in the census and are counted in the forensic one instead, which is
        where a receipt the contract refuses to read belongs.
        """
        for over, bucket in (
            ({"may_have_reached_provider": "yes"}, "provider_reach_unestablished"),
            ({"drop": ("attempts",)}, "paid_attempt_state_unestablished"),
        ):
            document = unclassified(status="COST_UNVERIFIED", observed_credits=None, **over)
            assert qual.cost_category(document) == bucket
            assert qual.classify(document) == "malformed_current_schema"
            state = state_of([document])
            assert state["paid_call_cost_census"][bucket] == 0
            assert state["rejected_paid_cost_census"][bucket] == 1
            assert state["rejected_paid_receipts"] == 1
            assert state["qualification_state"] == "EVIDENCE_CONFLICT"


class TestARejectedReceiptFeedsNoSemanticCounter:
    REJECTED: ClassVar[list[tuple[str, dict[str, Any], str]]] = [
        ("malformed", {"selections_mapped": "3"}, "malformed_current_schema"),
        (
            "contradictory",
            {"accounted_credits": 1, "observed_credits": 4},
            "self_contradictory",
        ),
        ("unknown pair", {"command": "core", "status": "PLAN_ONLY"}, "unknown_command_status_pair"),
    ]

    @pytest.mark.parametrize(("label", "over", "reason"), REJECTED, ids=[c[0] for c in REJECTED])
    def test_it_reaches_only_the_forensic_counters(
        self, label: str, over: dict[str, Any], reason: str
    ) -> None:
        document = receipt(**{"credits": 9, "accounted_credits": 9, **over})
        state = state_of([document])
        assert qual.classify(document) == reason
        # semantic counters, all silent
        assert state["paid_call_cost_census"] == dict.fromkeys(qual.COST_BUCKETS, 0)
        assert state["connectivity_and_cost_proof"] == "NOT_EXERCISED"
        # No **positive** counter, and no false negative either: `NO_NETWORK_ATTEMPTED`
        # would claim that nothing was attempted, which a document the contract refuses
        # to read cannot establish.
        assert state["execution_state"] == "NETWORK_ATTEMPT_STATE_UNESTABLISHED"
        assert state["paid_activation_state"] == "PAID_ATTEMPT_STATE_UNESTABLISHED"
        assert state["bookmaker_coverage_observations"] == []
        assert state["accounted_credits_total"] == 0
        assert state["mapping_freshness_proof"] == "NOT_OBTAINED_LIVE"
        # forensic counters, all speaking
        assert state["rejected_receipt_credits_not_counted"] >= 1
        assert state["rejected_paid_receipts"] == 1
        assert state["qualification_reasons"][reason] == 1
        assert state["verified_receipts"] == 1
        assert state["qualification_state"] == "EVIDENCE_CONFLICT"

    def test_a_divergent_identifier_is_rejected_the_same_way(self) -> None:
        one = receipt(tag="b2" * 16)
        two = receipt(tag="c3" * 16, quota_remaining=399)
        two["receipt_id"] = one["receipt_id"]
        from helpers_qualification_corpus import sign_with

        two[act.SIGNATURE_FIELD] = sign_with(
            {k: v for k, v in two.items() if k != act.SIGNATURE_FIELD}, FAKE_RECEIPT_SECRET
        )
        state = state_of([one, two])
        assert state["qualification_duplicate_excluded_receipts"] == 2
        assert state["paid_call_cost_census"] == dict.fromkeys(qual.COST_BUCKETS, 0)
        assert state["accounted_credits_total"] == 0
        assert state["bookmaker_coverage_observations"] == []

    def test_a_sound_receipt_beside_a_rejected_one_is_still_counted(self) -> None:
        state = state_of([receipt(tag="d4" * 16), receipt(tag="e5" * 16, selections_mapped="3")])
        assert state["paid_call_cost_census"]["provider_reached_conforming_cost"] == 1
        assert state["accounted_credits_total"] == 1
        assert state["rejected_paid_receipts"] == 1
        assert state["qualification_state"] == "EVIDENCE_CONFLICT"

    def test_copies_of_a_rejected_receipt_are_one_rejection(self) -> None:
        broken = receipt(selections_mapped="3")
        state = state_of([broken, broken, broken])
        assert state["rejected_paid_receipts"] == 1
        assert state["qualification_exact_duplicate_copies"] == 2


class TestTheGateRequiresBothAxes:
    def test_a_blocking_bucket_keeps_the_gate_shut(self) -> None:
        from helpers_qualification_corpus import threshold_corpus

        corpus = threshold_corpus(FAKE_RECEIPT_SECRET)
        assert state_of(corpus)["eligible_for_human_promotion_review"] is True
        blocked = state_of(
            [
                *corpus,
                unclassified(
                    tag="f6" * 16,
                    status="COST_MISMATCH",
                    observed_credits=4,
                    accounted_credits=4,
                    estimated_credits=1,
                ),
            ]
        )
        assert blocked["eligible_for_human_promotion_review"] is False
        assert blocked["paid_call_cost_census"]["provider_reached_nonconforming_cost"] == 1

    def test_confirmed_attempts_not_sent_neither_helps_nor_blocks(self) -> None:
        from helpers_qualification_corpus import threshold_corpus

        corpus = threshold_corpus(FAKE_RECEIPT_SECRET)
        never = unclassified(
            tag="a7" * 16,
            status="PROVIDER_UNAVAILABLE",
            may_have_reached_provider=False,
            observed_credits=None,
            accounted_credits=0,
            estimated_credits=1,
        )
        state = state_of([*corpus, never])
        assert state["paid_call_cost_census"]["confirmed_attempts_not_sent"] == 1
        assert state["eligible_for_human_promotion_review"] is True

    def test_cost_conformity_needs_six_established_conforming_calls(self) -> None:
        from helpers_qualification_corpus import threshold_corpus

        corpus = threshold_corpus(FAKE_RECEIPT_SECRET)
        entry = next(
            item
            for item in state_of(corpus)["criteria_results"]
            if item["criterion_id"] == "COST_CONFORMITY"
        )
        assert entry["passed"] is True
        short = state_of(corpus[:5])
        entry = next(
            item for item in short["criteria_results"] if item["criterion_id"] == "COST_CONFORMITY"
        )
        assert entry["passed"] is False


# ---------------------------------------------------------------------------
# §10 — the human rendering carries the same material facts as the JSON
# ---------------------------------------------------------------------------
class TestTheTwoRenderingsCarryTheSameFacts:
    MATERIAL = (
        "paid_call_cost_census",
        "paid_call_cost_census_population",
        "accounted_credits_total",
        "rejected_receipt_credits_not_counted",
        "rejected_paid_receipts",
        "unresolved_attempt_intents",
        "execution_state",
        "connectivity_and_cost_proof",
        "paid_activation_state",
        "qualification_state",
    )

    def _document(self) -> dict[str, Any]:
        from helpers_qualification_corpus import threshold_corpus

        return state_of(
            [
                *threshold_corpus(FAKE_RECEIPT_SECRET),
                receipt(
                    tag="b8" * 16, status="COST_MISMATCH", observed_credits=4, accounted_credits=4
                ),
                receipt(tag="c9" * 16, selections_mapped="3"),
            ]
        )

    def test_every_material_key_is_published_in_json(self) -> None:
        document = self._document()
        for key in self.MATERIAL:
            assert key in document, key

    def test_every_material_fact_appears_in_the_human_rendering(self) -> None:
        document = self._document()
        rendered = "\n".join(act.status_lines(document))
        for bucket, count in document["paid_call_cost_census"].items():
            if count:
                assert bucket in rendered or bucket.replace("_", " ") in rendered, bucket
        assert str(document["accounted_credits_total"]) in rendered
        assert str(document["rejected_receipt_credits_not_counted"]) in rendered
        assert str(document["rejected_paid_receipts"]) in rendered
        assert str(document["unresolved_attempt_intents"]) in rendered
        assert document["execution_state"] in rendered
        assert document["connectivity_and_cost_proof"] in rendered
        assert document["qualification_state"] in rendered

    def test_the_human_rendering_carries_no_ansi_and_no_path_outside_the_directory(self) -> None:
        rendered = "\n".join(act.status_lines(self._document()))
        assert "\x1b" not in rendered
        assert "github.com" not in rendered


# ---------------------------------------------------------------------------
# D8 — the catalogue, checked against the real producers in both directions
# ---------------------------------------------------------------------------
def _harvest(monkeypatch: pytest.MonkeyPatch, receipts: Path) -> set[tuple[str, str]]:
    """Every (command, status) the real command paths actually persist.

    Drives the CLI over a fake transport, one scenario per branch, and reads the
    receipts each run leaves. Nothing is constructed by hand: the point of this
    function is to be an independent witness of what the producer writes.
    """

    def reply(payload: Any, headers: dict[str, str], code: int = 200) -> Any:
        return lambda _r: httpx.Response(code, json=payload, headers=headers)

    def free(**over: Any) -> dict[str, Any]:
        return {
            "/sports/": reply(events_payload(**over), FREE),
            "/sports": reply(sports_payload(), FREE),
        }

    seen: set[tuple[str, str]] = set()

    def sweep() -> None:
        for document in receipts_in(receipts):
            seen.add((str(document.get("command")), str(document.get("status"))))
        for path in receipts.glob("*.json"):
            path.unlink()

    def discovery(routes: dict[str, Any]) -> str | None:
        install(monkeypatch, Recorder(routes))
        run(*discover_args())
        found = [d for d in receipts_in(receipts) if d.get("command") == "discover"]
        return str(receipts / found[0]["_filename"]) if found else None

    # ---- plan: no receipt at all, by design
    install(monkeypatch, Recorder({}))
    run(*plan_args())
    assert not receipts_in(receipts), "plan must persist nothing"

    # ---- discover, every branch
    scenarios: list[dict[str, Any]] = [
        free(),
        {"/sports/": reply([], FREE), "/sports": reply(sports_payload(), FREE)},
        {"/sports": reply({"message": "no"}, FREE, 401)},
        {"/sports": reply({"message": "boom"}, FREE, 500)},
        {"/sports/": reply(events_payload(), NO_HEADER), "/sports": reply(sports_payload(), FREE)},
        {
            "/sports/": reply(events_payload(), {"x-requests-last": "3"}),
            "/sports": reply(sports_payload(), FREE),
        },
        {"/sports/": reply({"unexpected": True}, FREE), "/sports": reply(sports_payload(), FREE)},
    ]
    for routes in scenarios:
        install(monkeypatch, Recorder(routes))
        run(*discover_args())
        sweep()

    # ---- core, every branch, each on a fresh valid discovery
    core_scenarios: list[dict[str, Any]] = [
        {"/odds": reply(odds_payload(), PAID)},
        {"/odds": reply(odds_payload(bookmaker="someone_else"), PAID)},
        {"/odds": reply([], PAID)},
        {"/odds": reply({"unexpected": True}, PAID)},
        {"/odds": reply({"message": "no"}, PAID, 401)},
        {"/odds": reply({"message": "boom"}, PAID, 500)},
        {"/odds": reply(odds_payload(), {"x-requests-last": "9"})},
        {"/odds": reply(odds_payload(), NO_HEADER)},
    ]
    for routes in core_scenarios:
        parent = discovery(free())
        if parent is None:
            continue
        install(monkeypatch, Recorder(routes))
        run(*core_args(discovery_receipt=parent))
        sweep()

    # ---- additional, every branch, each on a fresh valid core
    additional_scenarios: list[dict[str, Any]] = [
        {"/odds": reply(event_odds_payload(), FIVE)},
        {"/odds": reply(event_odds_payload(markets=ADDITIONAL_MARKET_KEYS[:3]), FIVE)},
        {"/odds": reply(event_odds_payload(bookmaker="someone_else"), FIVE)},
        {"/odds": reply({"unexpected": True}, FIVE)},
        {"/odds": reply({"message": "no"}, FIVE, 401)},
        {"/odds": reply({"message": "boom"}, FIVE, 500)},
        {"/odds": reply(event_odds_payload(), {"x-requests-last": "40"})},
        {"/odds": reply(event_odds_payload(), NO_HEADER)},
    ]
    for routes in additional_scenarios:
        parent = discovery(free())
        if parent is None:
            continue
        install(monkeypatch, Recorder({"/odds": reply(odds_payload(), PAID)}))
        run(*core_args(discovery_receipt=parent))
        core_receipts = [d for d in receipts_in(receipts) if d.get("command") == "core"]
        if not core_receipts:
            sweep()
            continue
        core_receipt = str(receipts / core_receipts[0]["_filename"])
        install(monkeypatch, Recorder(routes))
        run(*additional_args(core_receipt=core_receipt))
        sweep()

    return seen


class TestTheProducerAndTheContractAgree:
    def test_in_both_directions_over_the_real_command_paths(
        self, workspace: Path, keyed: Path, frozen_clock: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        produced = _harvest(monkeypatch, workspace)
        declared = {(str(command), str(status)) for command, status in qual.PERSISTED_COUPLES}

        assert produced - declared == set(), (
            "the producer writes couples the contract does not declare"
        )
        assert declared - produced == set(), "the contract declares couples no producer writes"
        # Every produced couple is phased, and none is filed as unknown.
        for command, status in sorted(produced):
            document = receipt(command=command, status=status)
            assert qual.admissible_phases(document), f"{command}/{status} has no phase"

    def test_the_non_persisted_forms_are_named_as_such(self) -> None:
        assert qual.NON_PERSISTED_COUPLES, "the theoretical forms must be listed explicitly"
        for couple in qual.NON_PERSISTED_COUPLES:
            assert couple in qual.RECEIPT_PHASES, couple
            assert couple not in qual.PERSISTED_COUPLES
        # Two families: `plan`, which writes nothing at all, and `PREPARED_NOT_EXECUTED`,
        # which is a status the harness reports before the wire and never files.
        assert {str(command) for command, _ in qual.NON_PERSISTED_COUPLES} == {
            "plan",
            "discover",
            "core",
            "additional",
        }
        assert {
            str(status) for command, status in qual.NON_PERSISTED_COUPLES if command != "plan"
        } == {"PREPARED_NOT_EXECUTED"}

    def test_the_two_couples_the_fifth_audit_found_are_declared(self) -> None:
        for status in ("COST_MISMATCH", "COST_UNVERIFIED"):
            couple = ("discover", getattr(act.ActivationStatus, status))
            assert couple in qual.RECEIPT_PHASES
            assert (str(couple[0]), str(couple[1])) in {
                (str(c), str(s)) for c, s in qual.PERSISTED_COUPLES
            }

    def test_the_couple_with_no_producer_is_gone(self) -> None:
        assert ("discover", act.ActivationStatus.SCHEMA_MISMATCH) not in qual.RECEIPT_PHASES

    def test_an_honest_discover_cost_receipt_does_not_poison_a_corpus(self) -> None:
        from helpers_qualification_corpus import threshold_corpus

        honest = receipt(
            command="discover",
            status="COST_UNVERIFIED",
            markets=[],
            credits=0,
            markets_requested=[],
            market_states={},
            markets_mapped=[],
            markets_observed=[],
            selections_mapped=0,
            freshness={},
            observed_credits=None,
            accounted_credits=0,
            estimated_credits=0,
            bookmaker_state="NOT_RETURNED",
            events_returned=1,
            events_in_window=1,
            events_admissible=1,
            event_tags=["a" * 32],
            event_tag="",
        )
        assert qual.classify(honest) != "unknown_command_status_pair"
        state = state_of([*threshold_corpus(FAKE_RECEIPT_SECRET), honest])
        assert state["qualification_unknown_pair_receipts"] == 0
        assert state["eligible_for_human_promotion_review"] is True

    def test_the_published_counts_match_the_table(self) -> None:
        entries = len(qual.RECEIPT_PHASES)
        forms = sum(len(phases) for phases in qual.RECEIPT_PHASES.values())
        assert (entries, forms) == (qual.RECEIPT_COUPLE_COUNT, qual.RECEIPT_FORM_COUNT)
        protocol = Path(qual.__file__).parents[4] / "docs" / "provider-validation-protocol.md"
        text = protocol.read_text(encoding="utf-8")
        assert f"{entries} couples" in text or f"**{entries}** couples" in text
        assert f"{forms} formes" in text or f"**{forms}** formes" in text

    def test_every_declared_form_is_exercised_by_the_table_walk(self) -> None:
        for (command, status), phases in qual.RECEIPT_PHASES.items():
            for phase in phases:
                assert phase in qual.ReceiptPhase
            assert phases, f"{command}/{status} declares no phase"


# ---------------------------------------------------------------------------
# The documents publish one norm, and it is this one
# ---------------------------------------------------------------------------
class TestTheDocumentsPublishOneNorm:
    ROOT = Path(qual.__file__).parents[4]

    def _read(self, name: str) -> str:
        return (self.ROOT / "docs" / name).read_text(encoding="utf-8")

    def test_the_protocol_document_is_version_six(self) -> None:
        text = self._read("provider-validation-protocol.md")
        assert "PROVIDER_VALIDATION_PROTOCOL_VERSION = 6" in text.splitlines()[0]
        assert "PROVIDER_VALIDATION_PROTOCOL_VERSION = 5" not in text.splitlines()[0]
        assert EFFECTIVE_INSTANT in text
        assert "2026-08-10T14:00:37+00:00" not in text, "the retired instant is history, not norm"

    def test_the_decision_d076_exists_and_supersedes_only_what_it_replaces(self) -> None:
        text = self._read("decisions.md")
        assert "D-076" in text
        assert "D-075" in text
        head = text[text.index("D-075") : text.index("D-076")]
        assert "supersédée" in head.lower() or "supersedee" in head.lower()

    @pytest.mark.parametrize(
        "notion",
        [
            "CommandState",
            "COMMAND_STATE_UNESTABLISHED",
            "provider_reach_unestablished",
            "provider_reached_cost_unestablished",
            "rejected_paid_receipts",
            "unresolved_attempt_intents",
            "VerifiedReceipt",
        ],
    )
    def test_every_new_notion_is_documented(self, notion: str) -> None:
        corpus = "\n".join(
            self._read(name)
            for name in (
                "provider-validation-protocol.md",
                "decisions.md",
                "data-dictionary.md",
                "provider-activation.md",
            )
        )
        assert notion in corpus, notion

    def test_the_retired_bucket_name_is_gone_from_the_active_norm(self) -> None:
        for name in ("provider-validation-protocol.md", "data-dictionary.md"):
            text = self._read(name)
            occurrences = text.count("provider_reached_unestablished_cost")
            if occurrences:
                # only ever inside the annotated history of v5
                assert "v5" in text or "D-075" in text

    def test_no_document_promises_an_automatic_promotion(self) -> None:
        corpus = "\n".join(
            self._read(name)
            for name in (
                "provider-validation-protocol.md",
                "decisions.md",
                "provider-activation.md",
                "roadmap.md",
            )
        )
        for forbidden in ("promotion automatique", "automatiquement promu", "VERIFIED_GLOBAL"):
            assert forbidden not in corpus

    def test_the_module_docstrings_do_not_claim_what_the_code_does_not_do(self) -> None:
        source = Path(qual.__file__).read_text(encoding="utf-8")
        docstring = source[: source.index('"""', 3) + 3]
        # The history may name v4; the module may not still *be* v4.
        assert "Protocol **v4**" not in docstring
        assert "Protocol **v6**" in docstring
        # The purity claim is now true, and it says why.
        assert "no HMAC" in docstring or "aucun HMAC" in docstring or "VerifiedReceipt" in docstring

    def test_the_phase_table_comment_counts_its_own_entries(self) -> None:
        source = Path(qual.__file__).read_text(encoding="utf-8")
        dual = [couple for couple, phases in qual.RECEIPT_PHASES.items() if len(phases) > 1]
        assert f"{len(dual)}" in source[: source.index("RECEIPT_PHASES: ")], (
            "the comment above the table must state how many entries carry two phases"
        )

    def test_the_census_comment_does_not_deny_the_deduplication(self) -> None:
        """The claim is gone; naming it as a corrected mistake is not the claim."""
        source = Path(act.__file__).read_text(encoding="utf-8")
        assert "one entry per real paid attempt found on disk, no deduplication" not in source
        census = source[source.index('"paid_call_cost_census": dict(census)') - 900 :]
        assert "deduplicated by identifier" in census
