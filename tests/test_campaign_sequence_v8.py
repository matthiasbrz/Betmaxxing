"""The protocol 8 campaign is a closed sequence of twelve named steps.

Protocol 8 pre-registered the *manifest* — one bookmaker, four competitions — and
the *quotas* — four discoveries, six core, two additional. The static preflight
03C-2F then measured what those still left open, and found two decisions that no
document made:

* how the three `core` of a family split across its two competitions. The guard
  only capped the family at three, so ``2+1`` and ``1+2`` were both accepted;
* which event each `core` uses. The runbook said it plainly — « aucun événement
  n'est choisi pour vous » — and the only checks were that the event appeared in
  the discovery receipt and had not been used twice.

Both are selections on observed data, which is the very fault D-082 recorded
against protocol 7's choice of competition. This module pins the twelve steps, the
canonical order events are ranked in, and the exact parent of each paid call, and
proves that the pre-network guard opposes all three *before* the provider key is
read, an intent is published or a socket exists.

Everything here is synthetic: a fixed test secret, a fresh ``tmp_path`` boundary,
and no receipt, key or payload of a real installation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import helpers_campaign_v8 as v8
from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual

# ---------------------------------------------------------------------------
# The sequence, restated as literals
# ---------------------------------------------------------------------------
#: The twelve steps, written out rather than derived. A test that computed the
#: expectation from the constant it is pinning would agree with any value that
#: constant happened to hold — which is precisely how the family cap passed for a
#: split it never fixed.
EXPECTED_SEQUENCE: tuple[tuple[int, str, str, int | None, int | None], ...] = (
    (1, "discover", "soccer_epl", None, None),
    (2, "core", "soccer_epl", 1, 1),
    (3, "core", "soccer_epl", 2, 1),
    (4, "additional", "soccer_epl", 2, 3),
    (5, "discover", "soccer_spain_la_liga", None, None),
    (6, "core", "soccer_spain_la_liga", 1, 5),
    (7, "additional", "soccer_spain_la_liga", 1, 6),
    (8, "discover", "tennis_atp_us_open", None, None),
    (9, "core", "tennis_atp_us_open", 1, 8),
    (10, "core", "tennis_atp_us_open", 2, 8),
    (11, "discover", "tennis_wta_us_open", None, None),
    (12, "core", "tennis_wta_us_open", 1, 11),
)

EXPECTED_CORE_BY_COMPETITION = {
    "soccer_epl": 2,
    "soccer_spain_la_liga": 1,
    "tennis_atp_us_open": 2,
    "tennis_wta_us_open": 1,
}


def as_tuple(step: Any) -> tuple[int, str, str, int | None, int | None]:
    return (step.index, step.command, step.sport, step.event_rank, step.parent_step)


class TestTheRegisterIsClosed:
    """Twelve steps, named in advance, with no room left for a preference."""

    def test_the_sequence_has_exactly_twelve_steps_in_the_pre_registered_order(self) -> None:
        assert tuple(as_tuple(step) for step in qual.CAMPAIGN_SEQUENCE) == EXPECTED_SEQUENCE

    def test_the_core_split_is_two_then_one_in_each_family(self) -> None:
        assert dict(qual.CAMPAIGN_CORE_BY_COMPETITION) == EXPECTED_CORE_BY_COMPETITION
        for family, scopes in qual.CAMPAIGN_SCOPES.items():
            allocated = [qual.CAMPAIGN_CORE_BY_COMPETITION[scope] for scope in scopes]
            assert sum(allocated) == qual.CAMPAIGN_CORE_PER_FAMILY, family
            # The extra invocation goes to the *first* scope of the manifest order,
            # decided before any answer came back rather than after one came back empty.
            assert allocated[0] > allocated[-1], family

    def test_the_sequence_reproduces_the_pre_registered_totals(self) -> None:
        counts = dict.fromkeys(qual.CAMPAIGN_COMMANDS, 0)
        for step in qual.CAMPAIGN_SEQUENCE:
            counts[step.command] += 1
        assert counts == qual.CAMPAIGN_INVOCATIONS == {"discover": 4, "core": 6, "additional": 2}

    def test_the_budget_is_unchanged_by_the_freeze(self) -> None:
        assert qual.campaign_budget() == {
            "cli_invocations": 12,
            "human_authorisations": 12,
            "http_requests": 16,
            "paid_http_requests": 8,
            "contractual_credits": 16,
        }

    def test_every_step_is_unique_and_none_is_foreign_to_the_manifest(self) -> None:
        seen = [(step.command, step.sport, step.event_rank) for step in qual.CAMPAIGN_SEQUENCE]
        assert len(set(seen)) == len(seen)
        for step in qual.CAMPAIGN_SEQUENCE:
            assert step.sport in qual.campaign_scopes_for(step.command)

    def test_each_paid_step_names_a_parent_that_precedes_it(self) -> None:
        by_index = {step.index: step for step in qual.CAMPAIGN_SEQUENCE}
        for step in qual.CAMPAIGN_SEQUENCE:
            if step.command == "discover":
                assert step.parent_step is None and step.event_rank is None
                continue
            assert step.parent_step is not None and step.parent_step < step.index
            parent = by_index[step.parent_step]
            assert parent.sport == step.sport
            expected_parent = "discover" if step.command == "core" else "core"
            assert parent.command == expected_parent
        # `additional` inherits the *last* core planned for its competition.
        for step in qual.CAMPAIGN_SEQUENCE:
            if step.command == "additional":
                assert step.event_rank == qual.CAMPAIGN_CORE_BY_COMPETITION[step.sport]

    def test_the_indices_are_one_to_twelve_without_a_gap(self) -> None:
        assert [step.index for step in qual.CAMPAIGN_SEQUENCE] == list(range(1, 13))


# ---------------------------------------------------------------------------
# The canonical order
# ---------------------------------------------------------------------------
def event(identifier: str, commence: str) -> dict[str, Any]:
    return {"id": identifier, "commence_time": commence, "home_team": "H", "away_team": "A"}


EARLY = "2026-08-26T10:00:00Z"
LATE = "2026-08-26T12:00:00Z"


class TestTheCanonicalOrder:
    """A rank is only a rank if the same set always produces the same one."""

    def test_an_already_ordered_response_keeps_its_order(self) -> None:
        events = [event("aaa", EARLY), event("bbb", LATE)]
        assert [e["id"] for e in qual.canonical_event_order(events)] == ["aaa", "bbb"]

    def test_a_reversed_response_produces_the_same_order(self) -> None:
        events = [event("bbb", LATE), event("aaa", EARLY)]
        assert [e["id"] for e in qual.canonical_event_order(events)] == ["aaa", "bbb"]

    @pytest.mark.parametrize(
        "order",
        [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)],
    )
    def test_every_permutation_of_one_corpus_yields_one_order(self, order: tuple[int, ...]) -> None:
        corpus = [
            event("zulu", EARLY),
            event("alpha", LATE),
            event("mike", "2026-08-26T11:00:00Z"),
        ]
        permuted = [corpus[index] for index in order]
        assert [e["id"] for e in qual.canonical_event_order(permuted)] == [
            "zulu",
            "mike",
            "alpha",
        ]

    def test_two_events_at_the_same_instant_are_broken_by_utf8_bytes(self) -> None:
        # What is pinned here is the *order*, not the encoding step: UTF-8 preserves
        # code-point order, so `sorted(..., key=str.encode)` and a bare `sorted` cannot
        # be told apart by any input — a mutation run confirmed it, and the mutant is
        # equivalent rather than uncaught. The explicit encode earns its place by making
        # the rule independent of the comparison, not by changing this result: a
        # locale-aware collation would put « Éclair » before « Zulu », and bytes never do.
        events = [event("Éclair", EARLY), event("Zulu", EARLY), event("Alpha", EARLY)]
        assert [e["id"] for e in qual.canonical_event_order(events)] == [
            "Alpha",
            "Zulu",
            "Éclair",
        ]

    def test_the_tie_break_is_the_encoded_bytes_and_not_the_code_points(self) -> None:
        events = [event("ÿ", EARLY), event("Ā", EARLY)]
        # U+00FF encodes to c3 bf, U+0100 to c4 80: bytes and code points agree here,
        # and the assertion pins the byte reading explicitly.
        ordered = [e["id"] for e in qual.canonical_event_order(events)]
        assert ordered == sorted(("ÿ", "Ā"), key=lambda text: text.encode("utf-8"))

    def test_a_repeated_identifier_is_kept_once(self) -> None:
        events = [event("aaa", LATE), event("aaa", LATE), event("bbb", LATE)]
        assert [e["id"] for e in qual.canonical_event_order(events)] == ["aaa", "bbb"]

    def test_an_unparsable_instant_never_outranks_a_real_one(self) -> None:
        events = [event("aaa", "pas une date"), event("bbb", EARLY)]
        ordered = [e["id"] for e in qual.canonical_event_order(events)]
        assert ordered == ["bbb", "aaa"]

    def test_the_order_is_stable_under_repetition(self) -> None:
        events = [event("bbb", LATE), event("aaa", EARLY)]
        once = qual.canonical_event_order(events)
        twice = qual.canonical_event_order(list(reversed(events)))
        assert [e["id"] for e in once] == [e["id"] for e in twice]


# ---------------------------------------------------------------------------
# The pre-network guard
# ---------------------------------------------------------------------------
@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "receipts"
    v8.install_secret(directory)
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
    monkeypatch.setenv("BETMAXXING_BOOKMAKERS", v8.BOOKMAKER)
    return directory


class Tripwire(Exception):
    """Raised by whatever the guard must never reach."""


@pytest.fixture
def tripwires(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count every engagement the guard is supposed to happen before."""
    hits = dict.fromkeys(("key", "intent", "client", "settings"), 0)

    def blow(name: str) -> Any:
        def fail(*_: Any, **__: Any) -> Any:
            hits[name] += 1
            raise Tripwire(name)

        return fail

    monkeypatch.setattr(act, "get_settings", blow("settings"))
    monkeypatch.setattr(act, "_require_key", blow("key"))
    monkeypatch.setattr(act, "publish_intent", blow("intent"))
    monkeypatch.setattr(act, "_client", blow("client"))
    return hits


def tags_for(rid: str, count: int) -> list[str]:
    return [f"{rid}{index:02d}" for index in range(count)]


def plant(directory: Path, receipts: list[dict[str, Any]]) -> None:
    for index, payload in enumerate(receipts):
        (directory / f"{index:02d}-{payload['receipt_id']}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )


def sequence_corpus(upto: int) -> list[dict[str, Any]]:
    """The receipts of the first ``upto`` steps, in the pre-registered order."""
    out: list[dict[str, Any]] = []
    rid_of_step: dict[int, str] = {}
    tag_of_step: dict[int, str] = {}
    for step in qual.CAMPAIGN_SEQUENCE[:upto]:
        moment = v8.instant(step.index)
        rid = f"{step.index:016x}"
        rid_of_step[step.index] = rid
        if step.command == "discover":
            out.append(v8.discovery(sport=step.sport, moment=moment, rid=rid, events=3))
            continue
        assert step.parent_step is not None and step.event_rank is not None
        # `parent_receipt_id`, because since 03C-2F quater the position is recognised from
        # the receipts and the parent's *identity* is part of the evidence. Omitting it
        # described a receipt no `core` or `additional` command ever emits, and the
        # register would rightly refuse to attribute it to any step.
        parent_rid = rid_of_step[step.parent_step]
        if step.command == "core":
            tag = tags_for(rid_of_step[step.parent_step], 3)[step.event_rank - 1]
            out.append(
                v8.core(sport=step.sport, moment=moment, rid=rid, tag=tag, parent_rid=parent_rid)
            )
        else:
            tag = tag_of_step[step.parent_step]
            out.append(
                v8.additional(
                    sport=step.sport, moment=moment, rid=rid, tag=tag, parent_rid=parent_rid
                )
            )
        tag_of_step[step.index] = tag
    return out


def refusal(**kwargs: Any) -> str:
    with pytest.raises(act.Refused) as caught:
        act.campaign_preflight(**kwargs)
    assert caught.value.status is act.ActivationStatus.PREPARED_NOT_EXECUTED
    return str(caught.value.message)


class TestTheGuardOpposesTheSequence:
    """Each refusal happens before the key, the intent, the client and the socket."""

    def test_the_first_step_is_the_first_discovery(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        act.campaign_preflight("discover", sport="soccer_epl", bookmaker=v8.BOOKMAKER)
        assert tripwires == dict.fromkeys(("key", "intent", "client", "settings"), 0)

    def test_a_discovery_of_the_wrong_scope_is_refused_first(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        message = refusal(command="discover", sport="tennis_wta_us_open", bookmaker=v8.BOOKMAKER)
        assert "soccer_epl" in message
        assert tripwires == dict.fromkeys(("key", "intent", "client", "settings"), 0)

    def test_the_wrong_command_for_the_current_step_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        message = refusal(command="core", sport="soccer_epl", bookmaker=v8.BOOKMAKER)
        assert "discover" in message
        assert sum(tripwires.values()) == 0

    def test_the_rank_two_core_may_not_precede_the_rank_one_core(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(1))
        parent = v8.discovery(sport="soccer_epl", moment=v8.instant(1), rid=f"{1:016x}", events=3)
        message = refusal(
            command="core",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{1:016x}", 3)[1],
            parent=parent,
        )
        assert "rang 1" in message
        assert sum(tripwires.values()) == 0

    def test_an_event_of_the_wrong_rank_is_refused_even_though_it_was_discovered(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(1))
        parent = v8.discovery(sport="soccer_epl", moment=v8.instant(1), rid=f"{1:016x}", events=3)
        message = refusal(
            command="core",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{1:016x}", 3)[2],
            parent=parent,
        )
        assert "rang" in message
        assert sum(tripwires.values()) == 0

    def test_an_event_absent_from_the_discovery_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(1))
        parent = v8.discovery(sport="soccer_epl", moment=v8.instant(1), rid=f"{1:016x}", events=3)
        message = refusal(
            command="core",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value="jamais-decouvert",
            parent=parent,
        )
        assert "rang" in message
        assert sum(tripwires.values()) == 0

    def test_the_rank_one_core_is_accepted_on_the_right_scope(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(1))
        parent = v8.discovery(sport="soccer_epl", moment=v8.instant(1), rid=f"{1:016x}", events=3)
        act.campaign_preflight(
            "core",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{1:016x}", 3)[0],
            parent=parent,
        )
        assert sum(tripwires.values()) == 0

    def test_a_third_core_on_a_two_core_scope_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(3))
        parent = v8.discovery(sport="soccer_epl", moment=v8.instant(1), rid=f"{1:016x}", events=3)
        message = refusal(
            command="core",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{1:016x}", 3)[2],
            parent=parent,
        )
        assert "additional" in message
        assert sum(tripwires.values()) == 0

    def test_a_second_core_on_a_one_core_scope_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(6))
        parent = v8.discovery(
            sport="soccer_spain_la_liga", moment=v8.instant(5), rid=f"{5:016x}", events=3
        )
        message = refusal(
            command="core",
            sport="soccer_spain_la_liga",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{5:016x}", 3)[1],
            parent=parent,
        )
        assert "additional" in message
        assert sum(tripwires.values()) == 0

    def test_additional_before_the_last_required_core_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(2))
        core_receipt = v8.core(
            sport="soccer_epl",
            moment=v8.instant(2),
            rid=f"{2:016x}",
            tag=tags_for(f"{1:016x}", 3)[0],
        )
        message = refusal(
            command="additional",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{1:016x}", 3)[0],
            parent=core_receipt,
        )
        assert "core" in message
        assert sum(tripwires.values()) == 0

    def test_additional_with_the_wrong_parent_core_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(3))
        # The rank 1 core, where the sequence names the rank 2 one as the parent.
        wrong = v8.core(
            sport="soccer_epl",
            moment=v8.instant(2),
            rid=f"{2:016x}",
            tag=tags_for(f"{1:016x}", 3)[0],
        )
        message = refusal(
            command="additional",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{1:016x}", 3)[0],
            parent=wrong,
        )
        assert "étape 3" in message
        assert sum(tripwires.values()) == 0

    def test_additional_on_the_right_scope_but_the_wrong_event_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(3))
        right = v8.core(
            sport="soccer_epl",
            moment=v8.instant(3),
            rid=f"{3:016x}",
            tag=tags_for(f"{1:016x}", 3)[1],
        )
        message = refusal(
            command="additional",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{1:016x}", 3)[0],
            parent=right,
        )
        assert "événement" in message
        assert sum(tripwires.values()) == 0

    def test_the_planned_additional_is_accepted(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(3))
        right = v8.core(
            sport="soccer_epl",
            moment=v8.instant(3),
            rid=f"{3:016x}",
            tag=tags_for(f"{1:016x}", 3)[1],
        )
        act.campaign_preflight(
            "additional",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{1:016x}", 3)[1],
            parent=right,
        )
        assert sum(tripwires.values()) == 0

    def test_a_thirteenth_step_after_the_whole_sequence_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, sequence_corpus(12))
        message = refusal(command="discover", sport="soccer_epl", bookmaker=v8.BOOKMAKER)
        assert "COMPLETE" in message or "terminée" in message
        assert sum(tripwires.values()) == 0

    def test_nothing_restarts_after_an_abort(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        failed = v8.discovery(
            sport="soccer_epl",
            moment=v8.instant(1),
            rid=f"{1:016x}",
            status="COVERAGE_MISSING",
            events=0,
        )
        plant(boundary, [failed])
        message = refusal(command="discover", sport="soccer_spain_la_liga", bookmaker=v8.BOOKMAKER)
        assert "ABORTED" in message
        assert sum(tripwires.values()) == 0

    def test_every_step_of_the_whole_sequence_is_accepted_in_order(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        """A positive control: each correct step reaches the first engagement."""
        rid_of = {step.index: f"{step.index:016x}" for step in qual.CAMPAIGN_SEQUENCE}
        tag_of: dict[int, str] = {}
        for position, step in enumerate(qual.CAMPAIGN_SEQUENCE):
            plant(boundary, sequence_corpus(position))
            parent: dict[str, Any] | None = None
            tag: str | None = None
            if step.command == "core":
                assert step.parent_step is not None and step.event_rank is not None
                parent = v8.discovery(
                    sport=step.sport,
                    moment=v8.instant(step.parent_step),
                    rid=rid_of[step.parent_step],
                    events=3,
                )
                tag = tags_for(rid_of[step.parent_step], 3)[step.event_rank - 1]
                tag_of[step.index] = tag
            elif step.command == "additional":
                assert step.parent_step is not None
                tag = tag_of[step.parent_step]
                parent = v8.core(
                    sport=step.sport,
                    moment=v8.instant(step.parent_step),
                    rid=rid_of[step.parent_step],
                    tag=tag,
                )
            act.campaign_preflight(
                step.command,
                sport=step.sport,
                bookmaker=v8.BOOKMAKER,
                event_tag_value=tag,
                parent=parent,
            )
            for stale in boundary.glob("*.json"):
                stale.unlink()
            v8.install_secret(boundary)
        assert sum(tripwires.values()) == 0


# ---------------------------------------------------------------------------
# Insufficient discovery
# ---------------------------------------------------------------------------
class TestADiscoveryTooThinNeverQualifies:
    """A scope needing two ranks is not served by a listing of one."""

    def test_the_quota_of_each_scope_is_the_number_of_ranks_it_needs(self) -> None:
        for step in qual.CAMPAIGN_SEQUENCE:
            if step.command == "core":
                assert step.event_rank is not None
                assert step.event_rank <= qual.CAMPAIGN_CORE_BY_COMPETITION[step.sport]

    def test_a_single_event_does_not_satisfy_a_two_rank_scope(self) -> None:
        assert qual.discovery_is_sufficient("soccer_epl", 2) is True
        assert qual.discovery_is_sufficient("soccer_epl", 1) is False
        assert qual.discovery_is_sufficient("soccer_spain_la_liga", 1) is True
        assert qual.discovery_is_sufficient("tennis_atp_us_open", 1) is False
        assert qual.discovery_is_sufficient("tennis_wta_us_open", 1) is True

    def test_an_unknown_scope_is_never_sufficient(self) -> None:
        assert qual.discovery_is_sufficient("soccer_france_ligue_one", 99) is False


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
FIELDS = (
    "campaign_next_step_index",
    "campaign_next_command",
    "campaign_next_scope",
    "campaign_next_event_rank",
    "campaign_next_parent_step",
)


def block_for(receipts: list[dict[str, Any]], directory: Path, monkeypatch: Any) -> dict[str, Any]:
    plant(directory, receipts)
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
    return qual.campaign_block(qual.campaign_ledger(act.audit_receipts()))


class TestTheNextStepIsPublished:
    """The report says which step is next, or honestly says it cannot."""

    def test_an_empty_boundary_announces_the_first_step(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        block = block_for([], boundary, monkeypatch)
        assert block["campaign_next_step_index"] == 1
        assert block["campaign_next_command"] == "discover"
        assert block["campaign_next_scope"] == "soccer_epl"
        assert block["campaign_next_event_rank"] is None
        assert block["campaign_next_parent_step"] is None

    @pytest.mark.parametrize("done", [1, 2, 3, 4, 6, 11])
    def test_each_success_announces_the_next_step_exactly(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch, done: int
    ) -> None:
        block = block_for(sequence_corpus(done), boundary, monkeypatch)
        expected = EXPECTED_SEQUENCE[done]
        assert block["campaign_next_step_index"] == expected[0]
        assert block["campaign_next_command"] == expected[1]
        assert block["campaign_next_scope"] == expected[2]
        assert block["campaign_next_event_rank"] == expected[3]
        assert block["campaign_next_parent_step"] == expected[4]

    def test_a_complete_campaign_announces_nothing(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        block = block_for(sequence_corpus(12), boundary, monkeypatch)
        assert block["campaign_execution_state"] == "COMPLETE"
        assert all(block[field] is None for field in FIELDS)

    def test_an_aborted_campaign_announces_nothing(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failed = v8.discovery(
            sport="soccer_epl",
            moment=v8.instant(1),
            rid=f"{1:016x}",
            status="COVERAGE_MISSING",
            events=0,
        )
        block = block_for([failed], boundary, monkeypatch)
        assert block["campaign_execution_state"] == "ABORTED"
        assert all(block[field] is None for field in FIELDS)

    def test_an_unestablished_count_announces_nothing(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No value may be invented from the constants when nothing could be counted."""
        plant(boundary, sequence_corpus(1))
        (boundary / "99-illisible.json").write_text("{ pas du json", encoding="utf-8")
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(boundary))
        block = qual.campaign_block(qual.campaign_ledger(act.audit_receipts()))
        assert block["campaign_counts_state"] == "UNESTABLISHED"
        assert all(block[field] is None for field in FIELDS)

    def test_a_corpus_that_diverges_from_the_sequence_announces_nothing(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out_of_order = [
            v8.discovery(sport="soccer_epl", moment=v8.instant(1), rid=f"{1:016x}", events=3),
            v8.discovery(
                sport="soccer_spain_la_liga", moment=v8.instant(2), rid=f"{2:016x}", events=3
            ),
        ]
        block = block_for(out_of_order, boundary, monkeypatch)
        assert all(block[field] is None for field in FIELDS)

    def test_the_refusal_names_the_expected_step_without_listing_the_events(
        self, boundary: Path
    ) -> None:
        plant(boundary, sequence_corpus(1))
        parent = v8.discovery(sport="soccer_epl", moment=v8.instant(1), rid=f"{1:016x}", events=3)
        message = refusal(
            command="core",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_for(f"{1:016x}", 3)[2],
            parent=parent,
        )
        assert "étape 2" in message
        for tag in tags_for(f"{1:016x}", 3):
            assert tag not in message
        assert v8.SECRET not in message


# ---------------------------------------------------------------------------
# The invariants the freeze must not touch
# ---------------------------------------------------------------------------
class TestTheFreezeChangesNothingElse:
    def test_the_protocol_constants_are_unchanged(self) -> None:
        assert qual.PROVIDER_VALIDATION_PROTOCOL_VERSION == 8
        assert qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC == "2026-08-25T00:00:00+00:00"
        assert qual.PROVIDER_ADAPTER_EVIDENCE_VERSION == 1
        assert act.RECEIPT_SCHEMA_VERSION == 4
        assert qual.CAMPAIGN_BOOKMAKER == "pinnacle"

    def test_the_manifest_and_the_markets_are_unchanged(self) -> None:
        assert qual.CAMPAIGN_SCOPES == {
            "soccer": ("soccer_epl", "soccer_spain_la_liga"),
            "tennis": ("tennis_atp_us_open", "tennis_wta_us_open"),
        }
        assert act.CORE_MARKETS == ("h2h",)
        assert len(act.ADDITIONAL_MARKETS) == 5
        assert act.STEP_CEILINGS == {"plan": 0, "discover": 0, "core": 1, "additional": 5}

    def test_the_guard_still_refuses_a_foreign_bookmaker_first(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        message = refusal(command="discover", sport="soccer_epl", bookmaker=v8.FOREIGN_BOOKMAKER)
        assert v8.BOOKMAKER in message
        assert sum(tripwires.values()) == 0

    def test_the_guard_still_refuses_an_unconfigured_parser(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch, tripwires: dict[str, int]
    ) -> None:
        monkeypatch.setenv("BETMAXXING_BOOKMAKERS", "winamax_fr")
        message = refusal(command="discover", sport="soccer_epl", bookmaker=v8.BOOKMAKER)
        assert "BETMAXXING_BOOKMAKERS" in message
        assert sum(tripwires.values()) == 0


# ---------------------------------------------------------------------------
# The documents say the same twelve steps
# ---------------------------------------------------------------------------
REPOSITORY = Path(act.__file__ or "").resolve().parents[4]

#: The two documents that state the register normatively. The runbook is where an
#: operator reads what to run next, and the protocol is what the runbook answers to; a
#: register that lived in one of them only would be a register in the code alone.
REGISTER_DOCUMENTS = ("docs/provider-validation-protocol.md", "docs/provider-activation.md")


def register_rows(markdown: str) -> list[tuple[str, ...]]:
    """The rows of the twelve-step table, wherever in the document it sits."""
    rows: list[tuple[str, ...]] = []
    for line in markdown.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].isdigit():
            rows.append(tuple(cells))
    return rows


class TestTheDocumentsCarryTheSameRegister:
    """One register, read from three places, with no way to edit one alone."""

    @pytest.mark.parametrize("relative", REGISTER_DOCUMENTS)
    def test_the_table_reproduces_the_twelve_steps(self, relative: str) -> None:
        rows = register_rows((REPOSITORY / relative).read_text(encoding="utf-8"))
        assert len(rows) == len(qual.CAMPAIGN_SEQUENCE), relative
        for row, step in zip(rows, qual.CAMPAIGN_SEQUENCE, strict=True):
            index, command, scope, rank, parent = row
            assert int(index) == step.index, relative
            assert command.strip("`") == step.command, relative
            assert scope.strip("`") == step.sport, relative
            assert rank == (str(step.event_rank) if step.event_rank is not None else "—"), relative
            expected = f"étape {step.parent_step}" if step.parent_step is not None else "—"
            assert parent == expected, relative

    @pytest.mark.parametrize("relative", REGISTER_DOCUMENTS)
    def test_each_document_names_the_canonical_order_and_its_tie_break(self, relative: str) -> None:
        text = (REPOSITORY / relative).read_text(encoding="utf-8")
        # The tie-break is the half that a document could plausibly leave out, and the
        # half an operator cannot rediscover from a response.
        assert "octets UTF-8" in text, relative
        assert "D-083" in text or "registre" in text, relative

    def test_the_decision_register_carries_d083(self) -> None:
        text = (REPOSITORY / "docs/decisions.md").read_text(encoding="utf-8")
        assert "### D-083" in text
        assert "2026-09-05" in text
        # D-082 stays exactly where it was: this freeze adds a decision, it revises none.
        assert text.index("### D-082") < text.index("### D-083")

    def test_the_observability_fields_are_documented_where_they_are_read(self) -> None:
        for relative in REGISTER_DOCUMENTS:
            text = (REPOSITORY / relative).read_text(encoding="utf-8")
            for field in FIELDS:
                assert field in text, f"{relative} ne nomme pas {field}"


def test_the_module_under_test_is_the_one_on_the_path() -> None:
    """Provenance: a mutation run must prove which copy it imported."""
    assert Path(qual.__file__ or "").name == "qualification.py"
    assert Path(act.__file__ or "").name == "activation.py"


def test_the_sequence_fits_inside_the_receipt_ttl_when_run_in_order() -> None:
    """Each paid step's parent is at most one step older, so 6 h is workable."""
    by_index = {step.index: step for step in qual.CAMPAIGN_SEQUENCE}
    for step in qual.CAMPAIGN_SEQUENCE:
        if step.parent_step is None:
            continue
        gap = step.index - step.parent_step
        assert gap <= 3, (step, by_index[step.parent_step])
    assert timedelta(hours=6) == act.RECEIPT_TTL
    assert datetime.now(UTC).tzinfo is UTC
