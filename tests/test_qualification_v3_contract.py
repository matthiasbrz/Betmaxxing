"""Protocol v3: a valid signature proves bytes, not types.

The re-audit of protocol v2 found that a correctly signed receipt could still
manufacture a positive proof by being *wrongly typed* — `selections_mapped = "3"`
counted as three selections, and `network_attempted = "false"` counted as a
network attempt. It also found a paid call whose cost was never established
disappearing from the cost denominator, a `bookmaker_state` the scope claimed but
nobody checked, a `TypeError` reachable from a stray JSON file, and a documented
operator command that does not exist.

So protocol v3 adds one idea to v2: a receipt that claims to qualify must satisfy
a **positive structural contract** before any of its content is read as evidence.
Python truthiness and integer coercion are not part of that contract. A signed,
current, postdated but malformed receipt is not a quiet archive either — it blocks
eligibility and says so.

Every receipt here is synthetic and locally signed; nothing opens a socket, and no
real receipt or key is read.
"""

from __future__ import annotations

import json as jsonlib
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from helpers_activation import FAKE_RECEIPT_SECRET

#: The instant D-073 published, kept as the historical literal it is. This module
#: guards the v3 closures, which are unchanged; the *current* effective instant is
#: pinned exactly once, by ``tests/test_qualification_v4_contract.py``. Pinning it
#: here as well would make every authorised protocol bump edit two files to say the
#: same thing, and would say nothing extra about v3.
D073_EFFECTIVE_INSTANT = "2026-08-10T07:19:48+00:00"

#: The protocol 8 manifest. A corpus that is meant to reach the human-review gate
#: has to be inside the pre-registered campaign since v8: a receipt naming another
#: competition or another bookmaker is an evidence conflict, not weak evidence.
FOOTBALL = "soccer_epl"
FOOTBALL_2 = "soccer_spain_la_liga"
TENNIS = "tennis_atp_us_open"
TENNIS_2 = "tennis_wta_us_open"
BOOK = "pinnacle"
#: Three consecutive UTC days inside the current evidence window. Derived rather
#: than typed: they were three literals until protocol 8, so moving the effective
#: instant silently turned every corpus below into history and made the whole suite
#: assert nothing about the closures it guards.
_NOT_BEFORE = datetime.fromisoformat(qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC)
D1 = _NOT_BEFORE + timedelta(days=1)
D2 = _NOT_BEFORE + timedelta(days=2)
D3 = _NOT_BEFORE + timedelta(days=3)
MARKETS = list(act.ADDITIONAL_MARKETS)


_SIGNING = FAKE_RECEIPT_SECRET


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
    """A signed, current, well-formed `additional` receipt: five markets mapped."""
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
    """The minimal corpus that satisfies all eight criteria under protocol v3."""
    rows = [
        (FOOTBALL, D1, "a"),
        (FOOTBALL_2, D2, "b"),
        (FOOTBALL, D2, "c"),
        (TENNIS, D1, "d"),
        (TENNIS_2, D2, "f"),
        (TENNIS, D3, "0"),
    ]
    out = [
        core(receipt_id=f"{i:016x}", sport_key=key, moment=moment, event_tag=tag * 32, **over)
        for i, (key, moment, tag) in enumerate(rows, start=1)
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
        core(receipt_id=f"{i:016x}", sport_key=key, moment=moment, event_tag=tag * 32, **over)
        for i, (key, moment, tag) in enumerate(rows, start=1)
    ]


def entry(document: dict[str, Any], criterion_id: str) -> dict[str, Any]:
    for candidate in document["criteria_results"]:
        if candidate["criterion_id"] == criterion_id:
            return candidate
    raise AssertionError(criterion_id)


def passing(document: dict[str, Any]) -> list[str]:
    return [e["criterion_id"] for e in document["criteria_results"] if e["passed"]]


def write_all(directory: Path, receipts: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, receipt in enumerate(receipts, start=1):
        (directory / f"probe-{index:02d}.json").write_text(
            jsonlib.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
class TestTheProtocolIsVersionThree:
    def test_the_versioned_constants(self) -> None:
        """The v3 closures, not the current version number.

        The number itself is pinned exactly once, by the v4 contract. What this class
        owes is that the constants v3 introduced kept their meaning: the threshold is
        still the literal 900, the adapter-evidence version is still 1, and only a v4
        receipt can qualify.
        """
        assert qual.PROTOCOL_MAX_ODDS_AGE_SECONDS == 900
        assert qual.PROVIDER_ADAPTER_EVIDENCE_VERSION == 1
        assert qual.QUALIFYING_SCHEMA_VERSION == 4
        assert act.RECEIPT_SCHEMA_VERSION == 4
        assert isinstance(qual.PROVIDER_VALIDATION_PROTOCOL_VERSION, int)
        assert qual.PROVIDER_VALIDATION_PROTOCOL_VERSION >= 3

    def test_the_effective_instant_moved_forward_from_d073(self) -> None:
        """An effective instant only ever moves forward, and never back onto D-073's.

        Pinning the current value here would duplicate the v4 contract. What v3 owes
        is that its own instant was not quietly reused or rolled back, since evidence
        admitted under D-073 must not silently become current again.
        """
        current = datetime.fromisoformat(qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC)
        assert current >= datetime.fromisoformat(D073_EFFECTIVE_INSTANT)

    def test_protocol_two_evidence_is_now_historical(self) -> None:
        document = _evaluate(corpus(qualification_protocol_version=2), 0)
        assert passing(document) == []
        assert document["qualification_reasons"]["other_protocol_version"] == 8

    def test_a_current_well_formed_corpus_still_reaches_the_gate(self) -> None:
        """Well formed includes producible, since 03C-2F quater.

        ``corpus()`` is this module's paid evidence and stays what the rest of the suite
        reads. The gate now also asks that the receipts form the pre-registered register:
        the campaign position is recognised from them, and paid steps with no discovery
        behind them are attributed to no step at all. No criterion or threshold moved.
        """
        import helpers_campaign_v8 as v8

        document = _evaluate(v8.register_corpus(secret=_SIGNING), 0)
        assert sorted(passing(document)) == sorted(c.criterion_id for c in qual.CRITERIA)
        assert document["eligible_for_human_promotion_review"] is True


# ---------------------------------------------------------------------------
# P1-1 — a signature proves bytes, not types
# ---------------------------------------------------------------------------
MALFORMED: list[tuple[str, dict[str, Any]]] = [
    ("selections_mapped=True", {"selections_mapped": True}),
    ("selections_mapped='3'", {"selections_mapped": "3"}),
    ("selections_mapped=1.0", {"selections_mapped": 1.0}),
    ("selections_mapped='oops'", {"selections_mapped": "oops"}),
    ("selections_mapped=None", {"selections_mapped": None}),
    ("selections_mapped=-1", {"selections_mapped": -1}),
    ("network_attempted='false'", {"network_attempted": "false"}),
    ("network_attempted='0'", {"network_attempted": "0"}),
    ("network_attempted=1", {"network_attempted": 1}),
    ("network_attempted=[]", {"network_attempted": []}),
    ("network_attempted={}", {"network_attempted": {}}),
    ("network_attempted=None", {"network_attempted": None}),
    ("may_have_reached_provider='false'", {"may_have_reached_provider": "false"}),
    ("may_have_reached_provider='0'", {"may_have_reached_provider": "0"}),
    ("may_have_reached_provider=1", {"may_have_reached_provider": 1}),
    ("may_have_reached_provider=[]", {"may_have_reached_provider": []}),
    ("may_have_reached_provider={}", {"may_have_reached_provider": {}}),
    ("may_have_reached_provider=None", {"may_have_reached_provider": None}),
    ("market_states=[]", {"market_states": []}),
    ("market_states='OBSERVED_MAPPED'", {"market_states": "OBSERVED_MAPPED"}),
    ("market_states=None", {"market_states": None}),
    ("market_states={'h2h': 'WHATEVER'}", {"market_states": {"h2h": "WHATEVER"}}),
    ("markets_mapped='h2h'", {"markets_mapped": "h2h"}),
    ("markets_mapped={'h2h': True}", {"markets_mapped": {"h2h": True}}),
    ("markets_mapped=[3]", {"markets_mapped": [3]}),
    ("markets_mapped=[None]", {"markets_mapped": [None]}),
    ("freshness={'h2h': True}", {"freshness": {"h2h": True}}),
    ("freshness={'h2h': '600'}", {"freshness": {"h2h": "600"}}),
    ("freshness={'h2h': 600.0}", {"freshness": {"h2h": 600.0}}),
    ("freshness={'h2h': -1}", {"freshness": {"h2h": -1}}),
    ("freshness={'h2h': None}", {"freshness": {"h2h": None}}),
    ("estimated_credits=True", {"estimated_credits": True}),
    ("estimated_credits='1'", {"estimated_credits": "1"}),
    ("accounted_credits=True", {"accounted_credits": True}),
    ("observed_credits=True", {"observed_credits": True, "accounted_credits": True}),
    ("observed_credits='1'", {"observed_credits": "1", "accounted_credits": 1}),
    ("observed_credits=1.0", {"observed_credits": 1.0, "accounted_credits": 1}),
    ("attempts=True", {"attempts": True}),
    ("quota_remaining='400'", {"quota_remaining": "400"}),
    ("receipt_id=''", {"receipt_id": ""}),
    ("sport_key=''", {"sport_key": ""}),
    ("bookmaker=''", {"bookmaker": ""}),
    ("event_tag=''", {"event_tag": ""}),
    ("event_tag=17", {"event_tag": 17}),
    ("markets_requested='h2h'", {"markets_requested": "h2h"}),
    ("markets_requested=[3]", {"markets_requested": [3]}),
    ("markets_observed='h2h'", {"markets_observed": "h2h"}),
    ("markets_mapped duplicated", {"markets_mapped": ["h2h", "h2h"]}),
]


class TestAMalformedCurrentReceiptProvesNothing:
    """A signed, current, postdated receipt with one wrongly typed field."""

    @pytest.mark.parametrize(("label", "over"), MALFORMED, ids=[c[0] for c in MALFORMED])
    def test_it_is_not_admissible_evidence(self, label: str, over: dict[str, Any]) -> None:
        receipt = core(**over)
        assert qual.admissible_for(receipt, qual.CRITERIA[0]) is False
        assert qual.classify(receipt) != ""

    @pytest.mark.parametrize(("label", "over"), MALFORMED, ids=[c[0] for c in MALFORMED])
    def test_it_never_establishes_a_conforming_cost(self, label: str, over: dict[str, Any]) -> None:
        assert qual.cost_conforming(core(**over)) is False

    @pytest.mark.parametrize(("label", "over"), MALFORMED, ids=[c[0] for c in MALFORMED])
    def test_one_such_receipt_costs_the_whole_corpus_its_gate(
        self, label: str, over: dict[str, Any]
    ) -> None:
        seventh = {"receipt_id": "ff" * 8, "event_tag": "9" * 32, "moment": D2, **over}
        document = _evaluate([*corpus(), core(**seventh)], 0)
        assert document["eligible_for_human_promotion_review"] is False
        assert document["qualification_state"] == str(qual.QualificationState.EVIDENCE_CONFLICT)

    @pytest.mark.parametrize(("label", "over"), MALFORMED, ids=[c[0] for c in MALFORMED])
    def test_the_reason_is_named_without_leaking_anything(
        self, label: str, over: dict[str, Any]
    ) -> None:
        # A bookmaker of its own, not the manifest's: since protocol 8 the report
        # publishes `campaign_required_bookmaker`, a *constant* it is meant to state,
        # so asserting the manifest's name is absent would confuse « nothing of this
        # receipt is echoed » with « the campaign is not described ».
        sentinel = "leak-sentinel-book"
        document = _evaluate([core(**{"bookmaker": sentinel, **over})], 0)
        reasons = document["qualification_reasons"]
        assert sum(reasons.values()) == 1
        assert reasons["malformed_current_schema"] + reasons["unusable_recorded_at"] == 1
        rendered = jsonlib.dumps(document, ensure_ascii=False)
        assert "a" * 32 not in rendered
        assert sentinel not in rendered

    def test_status_survives_a_directory_of_malformed_receipts(self, workspace: Path) -> None:
        from helpers_activation import run

        write_all(
            workspace,
            [
                core(**{"receipt_id": f"{i:02x}" * 8, "event_tag": f"{i:x}" * 32, **over})
                for i, (_, over) in enumerate(MALFORMED, start=1)
            ],
        )
        result = run("status", "--json")
        assert result.exit_code == 0, result.output
        payload = jsonlib.loads(result.stdout)
        assert payload["eligible_for_human_promotion_review"] is False
        assert payload["adapter_state"] == "IMPLEMENTED_UNVERIFIED"
        assert run("status").exit_code == 0

    def test_a_well_formed_receipt_is_still_admissible(self) -> None:
        assert qual.admissible_for(core(), qual.CRITERIA[0]) is True
        assert qual.classify(core()) == ""


# ---------------------------------------------------------------------------
# P2-4 — the bookmaker the scope claims
# ---------------------------------------------------------------------------
class TestMappingRequiresAnObservedBookmaker:
    @pytest.mark.parametrize(
        ("label", "over", "drop"),
        [
            ("absent", {}, ("bookmaker_state",)),
            ("unknown", {"bookmaker_state": "MAYBE"}, ()),
            ("empty", {"bookmaker_state": ""}, ()),
            ("not returned", {"bookmaker_state": str(act.BookmakerState.NOT_RETURNED)}, ()),
        ],
    )
    def test_only_observed_qualifies(
        self, label: str, over: dict[str, Any], drop: tuple[str, ...]
    ) -> None:
        receipts = [
            core(
                receipt_id=f"{i:016x}",
                sport_key=key,
                moment=moment,
                event_tag=tag * 32,
                drop=drop,
                **over,
            )
            for i, (key, moment, tag) in enumerate(
                [(FOOTBALL, D1, "a"), (FOOTBALL_2, D2, "b"), (FOOTBALL, D2, "c")], start=1
            )
        ]
        document = _evaluate(receipts, 0)
        assert entry(document, "CORE_MAPPING_FOOTBALL")["passed"] is False
        assert document["eligible_for_human_promotion_review"] is False

    def test_observed_qualifies(self) -> None:
        receipts = [
            core(receipt_id=f"{i:016x}", sport_key=key, moment=moment, event_tag=tag * 32)
            for i, (key, moment, tag) in enumerate(
                [(FOOTBALL, D1, "a"), (FOOTBALL_2, D2, "b"), (FOOTBALL, D2, "c")], start=1
            )
        ]
        assert entry(_evaluate(receipts, 0), "CORE_MAPPING_FOOTBALL")["passed"] is True

    def test_the_scope_still_says_what_it_now_checks(self) -> None:
        for criterion in qual.CRITERIA:
            if criterion.command in {"core", "additional"}:
                assert "bookmaker observé" in criterion.scope


# ---------------------------------------------------------------------------
# P2-1 — a paid call whose cost is not established blocks the criterion
# ---------------------------------------------------------------------------
UNESTABLISHED: list[tuple[str, dict[str, Any]]] = [
    ("unknown paid status", {"status": "FUTURE_PAID_STATUS"}),
    (
        "PROVIDER_UNAVAILABLE after a possible hit",
        {
            "status": str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
            "observed_credits": None,
            "accounted_credits": 1,
            "market_states": {},
            "markets_requested": [],
            "markets_mapped": [],
            "markets_observed": [],
            "selections_mapped": 0,
            "freshness": {},
        },
    ),
    ("observation absent", {"observed_credits": None, "accounted_credits": 1}),
    ("observation boolean", {"observed_credits": True, "accounted_credits": True}),
    ("observation negative", {"observed_credits": -1, "accounted_credits": -1}),
    ("observation above the ceiling", {"observed_credits": 9, "accounted_credits": 9}),
    ("accounted differs from observed", {"observed_credits": 1, "accounted_credits": 3}),
    ("network flag mistyped", {"network_attempted": "false"}),
    ("estimate mistyped", {"estimated_credits": "1"}),
    ("estimate above the ceiling", {"estimated_credits": 9}),
    (
        "AUTH_FAILED after a response",
        {
            "status": str(act.ActivationStatus.AUTH_FAILED),
            "observed_credits": None,
            "accounted_credits": 1,
            "market_states": {},
            "markets_requested": [],
            "markets_mapped": [],
            "markets_observed": [],
            "selections_mapped": 0,
            "freshness": {},
        },
    ),
    ("COST_MISMATCH", {"status": str(act.ActivationStatus.COST_MISMATCH)}),
    ("COST_UNVERIFIED", {"status": str(act.ActivationStatus.COST_UNVERIFIED)}),
]


class TestAPaidCallWithUnestablishedCostBlocksTheCriterion:
    def test_six_conforming_calls_pass_on_their_own(self) -> None:
        result = entry(_evaluate(six_paid(), 0), "COST_CONFORMITY")
        assert result["passed"] is True
        assert result["observed"]["provider_reached_conforming_cost"] == 6
        assert result["observed"]["provider_reached_nonconforming_cost"] == 0
        assert result["observed"]["provider_reached_cost_unestablished"] == 0

    @pytest.mark.parametrize(("label", "over"), UNESTABLISHED, ids=[c[0] for c in UNESTABLISHED])
    def test_a_seventh_paid_call_never_passes_unnoticed(
        self, label: str, over: dict[str, Any]
    ) -> None:
        seventh = core(receipt_id="ff" * 8, event_tag="9" * 32, moment=D2, **over)
        document = _evaluate([*six_paid(), seventh], 0)
        result = entry(document, "COST_CONFORMITY")
        observed = result["observed"]
        # The property this test defends is that a seventh paid call which is not plainly
        # conforming never passes unnoticed. **Where** it is caught moved twice. v5 split
        # "the attempt state cannot be established" out of the unestablished-cost bucket.
        # v6 (D-076) goes further: a receipt the structural contract rejects feeds no
        # semantic counter at all, so a mistyped flag or an unknown status is now caught
        # as an evidence conflict rather than as a cost population — and a receipt that is
        # readable but not conforming is still caught by the cost criterion. Both roads
        # end at a shut gate, and the assertion below says exactly that.
        blocked_by_cost = sum(observed[name] for name in qual.BLOCKING_COST_BUCKETS)
        rejected = (
            document.get("qualification_current_malformed_receipts", 0)
            + document.get("qualification_unknown_pair_receipts", 0)
            + document.get("qualification_current_contradictory_receipts", 0)
        )
        assert blocked_by_cost >= 1 or rejected >= 1, (observed, document["qualification_reasons"])
        if blocked_by_cost:
            assert result["passed"] is False
            assert result["missing"], "the reader must be told why the cost criterion fails"
        else:
            assert document["qualification_state"] == "EVIDENCE_CONFLICT"
            assert document["evidence_conflicts"]
        assert document["eligible_for_human_promotion_review"] is False

    def test_a_call_that_never_left_is_counted_separately(self) -> None:
        never = core(
            receipt_id="ff" * 8,
            event_tag="9" * 32,
            moment=D2,
            may_have_reached_provider=False,
            observed_credits=None,
            accounted_credits=1,
            status=str(act.ActivationStatus.PROVIDER_UNAVAILABLE),
            market_states={},
            markets_requested=[],
            markets_mapped=[],
            markets_observed=[],
            selections_mapped=0,
            freshness={},
        )
        observed = entry(_evaluate([*six_paid(), never], 0), "COST_CONFORMITY")["observed"]
        assert observed["confirmed_attempts_not_sent"] == 1
        assert observed["provider_reached_cost_unestablished"] == 0

    def test_every_paid_receipt_lands_in_exactly_one_category(self) -> None:
        for _, over in UNESTABLISHED:
            seventh = core(receipt_id="ff" * 8, event_tag="9" * 32, moment=D2, **over)
            observed = entry(_evaluate([seventh], 0), "COST_CONFORMITY")["observed"]
            # Six buckets since v6, still exhaustive and still disjoint over the paid
            # steps the contract can read. A receipt the contract rejects is priced
            # nowhere semantic — D-076 — so for those the exhaustiveness is asserted on
            # the taxonomy itself, which is a pure function of the receipt.
            total = sum(observed.values())
            if qual.classify(seventh) == "":
                assert total == 1, (over, observed)
            else:
                assert total == 0, (over, observed)
                assert qual.cost_category(seventh) in qual.COST_BUCKETS, over

    def test_the_criterion_says_what_it_does_not_prove(self) -> None:
        limit = entry(_evaluate([], 0), "COST_CONFORMITY")["limit"]
        assert "tarif" in limit


# ---------------------------------------------------------------------------
# P3-4 — a market a receipt never requested proves nothing
# ---------------------------------------------------------------------------
class TestRequestedMarketsAndProjectionsAreCoherent:
    @pytest.mark.parametrize(
        ("label", "over", "drop"),
        [
            (
                "qualified market absent from markets_requested",
                {"markets_requested": ["totals"], "market_states": {"totals": "OBSERVED_MAPPED"}},
                (),
            ),
            ("markets_requested removed", {}, ("markets_requested",)),
            (
                "market_states misses a requested market",
                {"markets_requested": ["h2h", "totals"]},
                (),
            ),
            (
                "freshness carries a market never requested",
                {"freshness": {"h2h": 600, "btts": 1}},
                (),
            ),
            ("markets_observed disagrees with the map", {"markets_observed": []}, ()),
            ("markets_absent disagrees with the map", {"markets_absent": ["h2h"]}, ()),
        ],
    )
    def test_an_incoherent_market_map_qualifies_nothing(
        self, label: str, over: dict[str, Any], drop: tuple[str, ...]
    ) -> None:
        receipt = core(drop=drop, **over)
        assert qual.admissible_for(receipt, qual.CRITERIA[0]) is False


# ---------------------------------------------------------------------------
# P2-2 — no crash on a JSON value nobody expected
# ---------------------------------------------------------------------------
ODD_SCHEMA_VERSIONS: list[Any] = [{"deep": 4}, [4], True, 4.0, "4", None]


class TestNoUnexpectedJsonCanCrashTheAudit:
    @pytest.mark.parametrize(
        "value", ODD_SCHEMA_VERSIONS, ids=[repr(v) for v in ODD_SCHEMA_VERSIONS]
    )
    def test_audit_receipts_counts_it_without_raising(self, workspace: Path, value: Any) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "odd.json").write_text(
            jsonlib.dumps({"schema_version": value}), encoding="utf-8"
        )
        _audit = act.audit_receipts()
        receipts, unverifiable = _audit.batch, _audit.unverifiable
        assert list(receipts) == []
        assert unverifiable == 1

    @pytest.mark.parametrize(
        "value", ODD_SCHEMA_VERSIONS, ids=[repr(v) for v in ODD_SCHEMA_VERSIONS]
    )
    def test_status_still_returns_valid_json(self, workspace: Path, value: Any) -> None:
        from helpers_activation import run

        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "odd.json").write_text(
            jsonlib.dumps({"schema_version": value}), encoding="utf-8"
        )
        result = run("status", "--json")
        assert result.exit_code == 0, result.output
        payload = jsonlib.loads(result.stdout)
        assert payload["unverifiable_receipts"] == 1
        assert "deep" not in result.stdout

    @pytest.mark.parametrize(
        "value", ODD_SCHEMA_VERSIONS, ids=[repr(v) for v in ODD_SCHEMA_VERSIONS]
    )
    def test_load_parent_refuses_it_cleanly(self, workspace: Path, value: Any) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        path = workspace / "parent.json"
        path.write_text(jsonlib.dumps({"schema_version": value}), encoding="utf-8")
        with pytest.raises(act.Refused):
            act.load_parent(
                str(path),
                signing=_SIGNING,
                command="discover",
                status=act.ActivationStatus.DISCOVERY_VERIFIED,
                sport=FOOTBALL,
                bookmaker=BOOK,
                now=D1,
            )


# ---------------------------------------------------------------------------
# P3-2 — a receipt file is never silently replaced
# ---------------------------------------------------------------------------
class TestReceiptWritingIsExclusive:
    def _payload(self, **over: Any) -> dict[str, Any]:
        return {k: v for k, v in core(**over).items() if k != act.SIGNATURE_FIELD}

    def test_the_file_name_carries_the_whole_receipt_id(self, workspace: Path) -> None:
        path = act.write_receipt(self._payload(receipt_id="aabbccdd00000001"))
        assert "aabbccdd00000001" in path.name

    def test_a_shared_prefix_no_longer_collides(self, workspace: Path) -> None:
        act.write_receipt(self._payload(receipt_id="aabbccdd00000001"))
        act.write_receipt(self._payload(receipt_id="aabbccdd00000002"))
        assert len(list(workspace.glob("*.json"))) == 2

    def test_rewriting_the_identical_receipt_is_idempotent(self, workspace: Path) -> None:
        first = act.write_receipt(self._payload(receipt_id="aabbccdd00000001"))
        before = first.read_text(encoding="utf-8")
        second = act.write_receipt(self._payload(receipt_id="aabbccdd00000001"))
        assert first == second
        assert first.read_text(encoding="utf-8") == before
        assert len(list(workspace.glob("*.json"))) == 1

    def test_a_divergent_receipt_never_replaces_the_stored_one(self, workspace: Path) -> None:
        path = act.write_receipt(self._payload(receipt_id="aabbccdd00000001"))
        before = path.read_text(encoding="utf-8")
        with pytest.raises(act.Refused):
            act.write_receipt(self._payload(receipt_id="aabbccdd00000001", selections_mapped=99))
        assert path.read_text(encoding="utf-8") == before
        assert len(list(workspace.glob("*.json"))) == 1

    def test_no_temporary_file_is_left_behind(self, workspace: Path) -> None:
        act.write_receipt(self._payload(receipt_id="aabbccdd00000001"))
        with pytest.raises(act.Refused):
            act.write_receipt(self._payload(receipt_id="aabbccdd00000001", selections_mapped=99))
        assert [p.name for p in workspace.iterdir() if p.suffix != ".json"] == []

    def test_the_file_is_private_to_its_owner(self, workspace: Path) -> None:
        path = act.write_receipt(self._payload(receipt_id="aabbccdd00000003"))
        assert oct(os.stat(path).st_mode)[-3:] == "600"


# ---------------------------------------------------------------------------
# P3-3 — one identifier, one receipt
# ---------------------------------------------------------------------------
class TestADuplicateIdentifierIsAConflict:
    def test_byte_identical_copies_count_once(self) -> None:
        """An exact copy keeps the receipt's identity, and adds no evidence.

        The single ``core`` this used to build is the register's step 2 now, planted with
        the discovery it descends from: since 03C-2F quater a lone paid receipt matches no
        step and the corpus would be contradictory for a reason that has nothing to do
        with duplication. Three files, one identity, one event — unchanged.
        """
        import helpers_campaign_v8 as v8

        prefix = v8.register_corpus(2, secret=_SIGNING)
        one = prefix[-1]
        document = _evaluate([*prefix, dict(one), dict(one)], 0)
        assert entry(document, "CORE_MAPPING_FOOTBALL")["observed"]["events"] == 1
        assert document["evidence_conflicts"] == []

    def test_a_divergent_twin_wins_no_threshold(self) -> None:
        three = [
            core(receipt_id=f"{i:016x}", sport_key=key, moment=moment, event_tag=tag * 32)
            for i, (key, moment, tag) in enumerate(
                [(FOOTBALL, D1, "a"), (FOOTBALL_2, D2, "b"), (FOOTBALL, D2, "c")], start=1
            )
        ]
        twin = core(receipt_id=f"{1:016x}", sport_key=FOOTBALL, moment=D1, event_tag="x" * 32)
        document = _evaluate([*three, twin], 0)
        observed = entry(document, "CORE_MAPPING_FOOTBALL")["observed"]
        assert observed["events"] <= 2, observed
        assert document["qualification_state"] == str(qual.QualificationState.EVIDENCE_CONFLICT)
        assert document["eligible_for_human_promotion_review"] is False

    def test_the_conflict_names_no_content(self) -> None:
        one = core(receipt_id="cc" * 8, event_tag="a" * 32)
        twin = core(receipt_id="cc" * 8, event_tag="b" * 32)
        document = _evaluate([one, twin], 0)
        assert document["evidence_conflicts"]
        rendered = " ".join(document["evidence_conflicts"])
        for forbidden in ("a" * 32, "b" * 32, "cc" * 8, BOOK, FOOTBALL):
            assert forbidden not in rendered


# ---------------------------------------------------------------------------
# P2-3 — every documented operator command exists
# ---------------------------------------------------------------------------
RUNBOOKS = ("docs/provider-activation.md", "docs/provider-validation-protocol.md")


def declared_scripts() -> set[str]:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    block = text.split("[project.scripts]", 1)[1].split("[", 1)[0]
    return {line.split("=", 1)[0].strip() for line in block.splitlines() if "=" in line}


def shell_lines(markdown: str) -> list[str]:
    """Every line of every shell-flavoured fenced block, comments stripped."""
    out: list[str] = []
    fence: str | None = None
    for raw in markdown.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            info = stripped[3:].strip().lower()
            fence = info if fence is None else None
            continue
        if (
            fence in {"bash", "sh", "shell", "console"}
            and stripped
            and not stripped.startswith("#")
        ):
            out.append(stripped)
    return out


def commands_invited(markdown: str) -> set[str]:
    """The programs a reader would actually type, from those blocks."""
    invited: set[str] = set()
    for line in shell_lines(markdown):
        first = line.split()[0]
        if first in {"export", "sudo", "time", "env"} and len(line.split()) > 1:
            first = line.split()[1]
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", first):
            invited.add(first)
    return invited


#: Shells and coreutils a runbook may legitimately invoke.
ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "python",
        "python3",
        "pip",
        "git",
        "cd",
        "ls",
        "cat",
        "mkdir",
        "rm",
        "cp",
        "mv",
        "chmod",
        "createdb",
        "psql",
        "pg_ctl",
        "initdb",
        "alembic",
        "ruff",
        "mypy",
        "pytest",
        "curl",
        "docker",
        "make",
        "uvicorn",
        "echo",
        "test",
        "source",
    }
)


class TestEveryDocumentedCommandExists:
    def test_no_runbook_invites_a_command_that_is_not_installed(self) -> None:
        allowed = ALLOWED_COMMANDS | declared_scripts()
        offenders: list[str] = []
        for name in RUNBOOKS:
            for command in sorted(commands_invited(Path(name).read_text(encoding="utf-8"))):
                if command not in allowed:
                    offenders.append(f"{name}: {command}")
        assert offenders == [], offenders

    def test_the_canonical_status_command_is_the_documented_one(self) -> None:
        canonical = "python -m betmaxxing.providers.the_odds_api.activation status"
        for name in RUNBOOKS:
            text = Path(name).read_text(encoding="utf-8")
            if "status" in text and "activation status" in text:
                assert canonical in text, name

    def test_the_canonical_command_runs_and_returns_json(self, workspace: Path) -> None:
        import subprocess
        import sys

        package_root = str(Path(act.__file__).resolve().parents[3])
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "betmaxxing.providers.the_odds_api.activation",
                "status",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": package_root,
                "BETMAXXING_ACTIVATION_RECEIPTS": str(workspace),
                "BETMAXXING_ACTIVATION_RECEIPT_SECRET": "ab" * 32,
            },
        )
        assert proc.returncode == 0, proc.stderr[-500:]
        payload = jsonlib.loads(proc.stdout)
        # The number the module holds, not a second copy of it: what this test owes
        # is that the documented command exists and reports the protocol it ran under.
        assert (
            payload["qualification_protocol_version"] == qual.PROVIDER_VALIDATION_PROTOCOL_VERSION
        )
        assert payload["adapter_state"] == "IMPLEMENTED_UNVERIFIED"
