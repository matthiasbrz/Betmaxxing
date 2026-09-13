"""The register is read from the receipts, and the next step is published.

The independent re-audit 03C-2F ter reproduced four defects on one chain — verified
receipts → campaign position → qualification → operator output — and this module is the
closure proof for all four:

* **D1** the five ``campaign_next_*`` fields existed in ``qualification.evaluate()`` and
  were absent from ``status --json`` and from its human rendering. The runbook told the
  operator to read five fields the command did not emit;
* **D2** the ledger's tie-break ordered equal instants by *command* rank, which is not the
  register's order. At the three boundaries where a paid step precedes a ``discover`` —
  4/5, 7/8, 10/11 — a conforming campaign whose two steps fell in the same second was
  reported as unlocatable, and every later command refused;
* **D3** a corpus with the right totals but an incompatible order reached ``COMPLETE`` and
  ``CRITERIA_MET_AWAITING_HUMAN_REVIEW``;
* **D4** the position was read from ``(command, competition)`` alone, so a ``core`` on an
  event the register never names, or an ``additional`` attached to the wrong ``core``,
  advanced it silently.

The oracle here is the register as the **protocol document** states it, written out as
literals independently of the constructor that builds it in production. Everything is
synthetic: a fixed test secret, throwaway ``tmp_path`` boundaries, a fake transport, and
no receipt, key or payload of a real installation.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import helpers_campaign_v8 as v8
from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual

# ---------------------------------------------------------------------------
# The register, restated from the normative document
# ---------------------------------------------------------------------------
#: ``(index, command, competition, event rank, parent step)``. Literals, not a read of
#: ``CAMPAIGN_SEQUENCE``: a probe that derived its oracle from the object under test would
#: agree with whatever that object happened to hold.
REGISTER: tuple[tuple[int, str, str, int | None, int | None], ...] = (
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

FIELDS = (
    "campaign_next_step_index",
    "campaign_next_command",
    "campaign_next_scope",
    "campaign_next_event_rank",
    "campaign_next_parent_step",
)

#: How many events each synthetic discovery lists. Three, so a rank the register never
#: names (the third) exists and can be aimed at deliberately.
DISCOVERED = 3

REPOSITORY = Path(act.__file__).resolve().parents[4]
#: The interpreter running this suite, **unresolved**: a virtual environment's
#: ``bin/python`` is a symlink to the system interpreter, and following it would run the
#: subprocess outside the environment the dependencies are installed in.
INTERPRETER = Path(sys.executable)


# ---------------------------------------------------------------------------
# Corpus construction, from the literal register only
# ---------------------------------------------------------------------------
def rid_of(index: int) -> str:
    return f"{index:016x}"


def tags_of(index: int, count: int = DISCOVERED) -> list[str]:
    """The event tags a synthetic discovery for step ``index`` publishes, in rank order."""
    return [f"{rid_of(index)}{position:02d}" for position in range(count)]


def instant_of(step: int, *, day: int = 0) -> datetime:
    """A distinct instant per step, optionally pushed onto a later UTC day."""
    return v8.instant(step + 24 * day)


def receipt_for(
    step: tuple[int, str, str, int | None, int | None],
    *,
    day: int = 0,
    events: int = DISCOVERED,
    rank: int | None = None,
    parent: int | None = None,
    status: str | None = None,
    moment: Any = None,
) -> dict[str, Any]:
    """One receipt for a register step, with every deviation named explicitly.

    ``rank`` and ``parent`` override the event rank and the parent *step* the receipt
    points at, which is how the out-of-register corpora below are built without ever
    hand-writing a receipt the producer could not have emitted.
    """
    index, command, sport, own_rank, own_parent = step
    when = moment if moment is not None else instant_of(index, day=day)
    if command == "discover":
        if status is None:
            return v8.discovery(sport=sport, moment=when, rid=rid_of(index), events=events)
        return v8.discovery(
            sport=sport, moment=when, rid=rid_of(index), events=events, status=status
        )
    parent_step = own_parent if parent is None else parent
    assert parent_step is not None
    wanted = own_rank if rank is None else rank
    assert wanted is not None
    # `core` numbers ranks in its parent discovery; `additional` inherits the event its
    # parent `core` proved, so both resolve the tag through the discovery of the family.
    discovery_step = parent_step if command == "core" else REGISTER[parent_step - 1][4]
    assert discovery_step is not None
    maker = v8.core if command == "core" else v8.additional
    return maker(
        sport=sport,
        moment=when,
        rid=rid_of(index),
        tag=tags_of(discovery_step)[wanted - 1],
        parent_rid=rid_of(parent_step),
        **({"status": status} if status else {}),
    )


#: A UTC day per step, chosen so that **each family's** three ``core`` span two days while
#: the register's own order stays chronologically increasing. Football's cores are steps
#: 2, 3 and 6; tennis's are 9, 10 and 12, so the two day boundaries fall between 5 and 6
#: and between 10 and 11. ``CORE_MAPPING_*`` asks for two UTC days, and a single boundary
#: anywhere would leave one of the two families inside a single day.
QUALIFYING_DAYS: dict[int, int] = {
    **dict.fromkeys(range(1, 6), 0),
    **dict.fromkeys(range(6, 11), 1),
    **dict.fromkeys(range(11, 13), 2),
}


def conforming(upto: int, *, days: dict[int, int] | None = None) -> list[dict[str, Any]]:
    """The first ``upto`` steps, conforming, optionally spread over several UTC days."""
    schedule = days or {}
    return [receipt_for(step, day=schedule.get(step[0], 0)) for step in REGISTER[:upto]]


@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "receipts"
    v8.install_secret(directory)
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
    monkeypatch.setenv(act.SECRET_VARIABLE, v8.SECRET)
    monkeypatch.setenv("BETMAXXING_BOOKMAKERS", v8.BOOKMAKER)
    return directory


def plant(
    directory: Path, receipts: list[dict[str, Any]], *, names: list[str] | None = None
) -> None:
    for position, payload in enumerate(receipts):
        name = names[position] if names else f"{position:02d}-{payload['receipt_id']}.json"
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def block() -> dict[str, Any]:
    return qual.campaign_block(qual.campaign_ledger(act.audit_receipts()))


def verdict() -> dict[str, Any]:
    return qual.evaluate(act.audit_receipts())


def next_five(document: dict[str, Any]) -> list[Any]:
    missing = [field for field in FIELDS if field not in document]
    assert not missing, f"champs absents plutôt que null : {missing}"
    return [document[field] for field in FIELDS]


# ---------------------------------------------------------------------------
# T-D1 — the real CLI publishes the next step
# ---------------------------------------------------------------------------
def run_status(boundary: Path, *extra: str) -> tuple[int, str, str]:
    """The real `status` command, in a subprocess, stdout and stderr kept apart."""
    environment = {
        "PATH": f"{INTERPRETER.parent}:/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/root"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": f"{REPOSITORY / 'src'}:{REPOSITORY / 'tests'}",
        "BETMAXXING_ACTIVATION_RECEIPTS": str(boundary),
        "BETMAXXING_ACTIVATION_RECEIPT_SECRET": v8.SECRET,
        "BETMAXXING_BOOKMAKERS": v8.BOOKMAKER,
        "BETMAXXING_MODE": "paper",
        "BETMAXXING_NOTIFICATIONS_ENABLED": "false",
        "NO_COLOR": "1",
    }
    finished = subprocess.run(
        [
            str(INTERPRETER),
            "-m",
            "betmaxxing.providers.the_odds_api.activation",
            "status",
            *extra,
        ],
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return finished.returncode, finished.stdout, finished.stderr


#: The eight corpora of the ter re-audit, with the value the operator must be able to read.
CLI_CASES: list[tuple[str, int, int, list[Any]]] = [
    ("vide vérifiable", 0, 0, [1, "discover", "soccer_epl", None, None]),
    ("première découverte", 1, 0, [2, "core", "soccer_epl", 1, 1]),
    ("trois étapes conformes", 3, 0, [4, "additional", "soccer_epl", 2, 3]),
    ("complet conforme", 12, 0, [None, None, None, None, None]),
    ("compte non établi", 1, 1, [None, None, None, None, None]),
]


@pytest.mark.slow
class TestTheRealCommandPublishesTheNextStep:
    """D1. Measured through the CLI, because that is where the runbook sends the operator."""

    @pytest.mark.parametrize(("label", "upto", "unreadable", "expected"), CLI_CASES)
    def test_the_five_fields_are_present_with_the_right_values(
        self, boundary: Path, label: str, upto: int, unreadable: int, expected: list[Any]
    ) -> None:
        plant(boundary, conforming(upto))
        for index in range(unreadable):
            (boundary / f"9{index}-illisible.json").write_text("{ pas du json", encoding="utf-8")
        code, stdout, stderr = run_status(boundary, "--json")
        assert stdout.strip(), f"{label} : aucune sortie ({code}) {stderr[-200:]}"
        document = json.loads(stdout)
        assert next_five(document) == expected, label

    def test_an_aborted_campaign_publishes_five_nulls(self, boundary: Path) -> None:
        plant(boundary, [receipt_for(REGISTER[0], events=0, status="COVERAGE_MISSING")])
        document = json.loads(run_status(boundary, "--json")[1])
        assert document["campaign_execution_state"] == "ABORTED"
        assert next_five(document) == [None, None, None, None, None]

    def test_a_conflicting_campaign_publishes_five_nulls(self, boundary: Path) -> None:
        # The third event of the discovery: a rank the register never names.
        plant(boundary, [*conforming(1), receipt_for(REGISTER[1], rank=3)])
        document = json.loads(run_status(boundary, "--json")[1])
        assert document["campaign_execution_state"] == "CONFLICT"
        assert next_five(document) == [None, None, None, None, None]

    def test_status_opens_no_socket_and_reads_no_provider_key(self, boundary: Path) -> None:
        """`status` must stay a reader: no key, no intent, no receipt of its own."""
        plant(boundary, conforming(1))
        before = sorted(path.name for path in boundary.iterdir())
        code, stdout, stderr = run_status(boundary, "--json")
        assert code == 0, stderr[-200:]
        assert sorted(path.name for path in boundary.iterdir()) == before
        assert "BETMAXXING_THE_ODDS_API_KEY" not in stdout + stderr

    @pytest.mark.parametrize(
        ("label", "upto", "needles"),
        [
            ("étape à venir", 1, ("2", "core", "soccer_epl")),
            ("campagne finie", 12, ("COMPLETE",)),
        ],
    )
    def test_the_human_rendering_says_the_same_thing(
        self, boundary: Path, label: str, upto: int, needles: tuple[str, ...]
    ) -> None:
        plant(boundary, conforming(upto))
        rendered = run_status(boundary)[1]
        for needle in needles:
            assert needle in rendered, f"{label} : {needle!r} absent du rendu humain"
        # It reports; it never authorises.
        for forbidden in ("--allow-network", "vous pouvez lancer", "autorisé à lancer"):
            assert forbidden not in rendered, forbidden


# ---------------------------------------------------------------------------
# T-POS — the thirteen conforming prefixes
# ---------------------------------------------------------------------------
class TestEveryConformingPrefixIsLocated:
    """T-POS. Zero to twelve steps: state, counters and next step, all exact."""

    @pytest.mark.parametrize("done", list(range(13)))
    def test_the_position_is_exact(self, boundary: Path, done: int) -> None:
        plant(boundary, conforming(done))
        published = block()
        counts = {"discover": 0, "core": 0, "additional": 0}
        for step in REGISTER[:done]:
            counts[step[1]] += 1
        assert published["campaign_invocation_counts"] == counts, done
        expected_state = "NOT_STARTED" if done == 0 else "COMPLETE" if done == 12 else "IN_PROGRESS"
        assert published["campaign_execution_state"] == expected_state, done
        if done == 12:
            assert next_five(published) == [None, None, None, None, None]
        else:
            index, command, scope, rank, parent = REGISTER[done]
            assert next_five(published) == [index, command, scope, rank, parent], done

    def test_no_conforming_prefix_is_ever_a_conflict(self, boundary: Path) -> None:
        for done in range(13):
            for stale in boundary.glob("*.json"):
                stale.unlink()
            plant(boundary, conforming(done))
            assert qual.campaign_ledger(act.audit_receipts()).conflicts == (), done


# ---------------------------------------------------------------------------
# T-D2 — chronology first, the register only at equal instants
# ---------------------------------------------------------------------------
BOUNDARIES = [(4, 5), (7, 8), (10, 11)]


class TestEqualInstantsDoNotLoseThePosition:
    """D2. The three frontiers where a paid step precedes a `discover`."""

    @pytest.mark.parametrize(("left", "right"), BOUNDARIES)
    def test_a_conforming_corpus_keeps_its_position(
        self, boundary: Path, left: int, right: int
    ) -> None:
        shared = instant_of(left)
        receipts = [
            receipt_for(step, moment=shared if step[0] in (left, right) else None)
            for step in REGISTER[:right]
        ]
        plant(boundary, receipts)
        published = block()
        assert published["campaign_execution_state"] == "IN_PROGRESS", (left, right)
        assert qual.campaign_ledger(act.audit_receipts()).conflicts == (), (left, right)
        index, command, scope, rank, parent = REGISTER[right]
        assert next_five(published) == [index, command, scope, rank, parent], (left, right)

    @pytest.mark.parametrize(
        "names",
        [
            None,
            ["a-discover.json", "b-core-un.json", "c-core-deux.json"],
            ["zzz-discover.json", "mmm-core-un.json", "aaa-core-deux.json"],
            ["aaa-core-deux.json", "aab-core-un.json", "zzz-discover.json"],
        ],
        ids=["par-defaut", "croissant", "decroissant", "core-avant-discover"],
    )
    def test_the_file_listing_never_decides(self, boundary: Path, names: list[str] | None) -> None:
        shared = instant_of(1)
        receipts = [receipt_for(step, moment=shared) for step in REGISTER[:3]]
        plant(boundary, receipts, names=names)
        assert next_five(block()) == [4, "additional", "soccer_epl", 2, 3]

    def test_equal_instants_written_with_different_offsets_agree(self, boundary: Path) -> None:
        """The same instant, two texts. What is compared is the instant."""
        shared = instant_of(1)
        elsewhere = shared.astimezone(timezone(timedelta(hours=2)))
        assert shared.isoformat() != elsewhere.isoformat()
        assert shared == elsewhere
        receipts = [
            receipt_for(REGISTER[0], moment=shared),
            receipt_for(REGISTER[1], moment=elsewhere),
        ]
        plant(boundary, receipts)
        assert next_five(block()) == [3, "core", "soccer_epl", 2, 1]

    def test_the_reading_order_is_not_part_of_the_recognition(self) -> None:
        """Why no tie-break can decide anything any more: there is nothing left to decide.

        ``recognise_register`` resolves each step from that receipt's own evidence, so every
        permutation of the sequence it is handed yields the same steps, the same
        contradictions and the same position. Stated rather than left to be noticed: a
        mutation that puts the v8 `bis` ordering by command back into the ledger's sort
        changes no published field, and the reason is this property and not a weak test.
        """
        receipts = [receipt_for(step, moment=instant_of(1)) for step in REGISTER[:4]]
        wanted = qual.recognise_register(receipts)
        expected = ({index: rid_of(index) for index in wanted[0]}, wanted[1], wanted[2])
        assert expected[2] == 4, "le préfixe conforme doit d'abord être reconnu"
        for permutation in itertools.permutations(receipts):
            found = qual.recognise_register(list(permutation))
            assert (
                {index: found[0][index]["receipt_id"] for index in found[0]},
                found[1],
                found[2],
            ) == expected

    @pytest.mark.parametrize(("left", "right"), BOUNDARIES)
    def test_a_strict_inversion_is_never_repaired_by_the_register(
        self, boundary: Path, left: int, right: int
    ) -> None:
        """The tie-break applies to equal instants only: it may not sort time away."""
        receipts = [
            receipt_for(
                step,
                moment=instant_of(right)
                if step[0] == left
                else instant_of(left)
                if step[0] == right
                else None,
            )
            for step in REGISTER[:right]
        ]
        plant(boundary, receipts)
        published = block()
        assert published["campaign_execution_state"] == "CONFLICT", (left, right)
        assert next_five(published) == [None, None, None, None, None]


# ---------------------------------------------------------------------------
# T-D4 — ranks and parent identity are read from the receipts
# ---------------------------------------------------------------------------
class TestRanksAndParentsAreVerified:
    """D4. A receipt the register does not name never advances the position."""

    def test_two_core_in_inverted_rank_order_conflict(self, boundary: Path) -> None:
        receipts = [
            receipt_for(REGISTER[0]),
            # the rank 2 event recorded first, the rank 1 event second
            receipt_for(REGISTER[1], rank=2, moment=instant_of(2)),
            receipt_for(REGISTER[2], rank=1, moment=instant_of(3)),
        ]
        plant(boundary, receipts)
        published = block()
        assert published["campaign_execution_state"] == "CONFLICT"
        assert next_five(published) == [None, None, None, None, None]

    def test_a_core_on_an_unnamed_rank_conflicts(self, boundary: Path) -> None:
        plant(boundary, [*conforming(1), receipt_for(REGISTER[1], rank=3)])
        published = block()
        assert published["campaign_execution_state"] == "CONFLICT"
        assert next_five(published) == [None, None, None, None, None]

    def test_an_additional_on_the_wrong_core_conflicts(self, boundary: Path) -> None:
        # Step 4 names the rank 2 event and the step 3 receipt; this one takes rank 1.
        plant(boundary, [*conforming(3), receipt_for(REGISTER[3], rank=1, parent=2)])
        published = block()
        assert published["campaign_execution_state"] == "CONFLICT"
        assert next_five(published) == [None, None, None, None, None]

    def test_a_parent_identity_that_is_not_the_recognised_receipt_conflicts(
        self, boundary: Path
    ) -> None:
        """Same event, another parent receipt: the tag alone does not prove lineage."""
        plant(boundary, [*conforming(3), receipt_for(REGISTER[3], parent=2)])
        published = block()
        assert published["campaign_execution_state"] == "CONFLICT"
        assert next_five(published) == [None, None, None, None, None]

    def test_a_step_executed_out_of_sequence_conflicts(self, boundary: Path) -> None:
        """Step 3 present while step 2 is missing: a gap is not a prefix."""
        plant(boundary, [receipt_for(REGISTER[0]), receipt_for(REGISTER[2])])
        published = block()
        assert published["campaign_execution_state"] == "CONFLICT"
        assert next_five(published) == [None, None, None, None, None]

    def test_a_second_discovery_before_its_turn_conflicts(self, boundary: Path) -> None:
        """Four discoveries in a row is not this register, whatever the totals say."""
        plant(boundary, [receipt_for(step) for step in (REGISTER[0], REGISTER[4])])
        published = block()
        assert published["campaign_execution_state"] == "CONFLICT"
        assert next_five(published) == [None, None, None, None, None]


# ---------------------------------------------------------------------------
# T-D3 — the register is opposed to the qualification verdict
# ---------------------------------------------------------------------------
def out_of_order_twelve() -> list[dict[str, Any]]:
    """Right totals — 4 / 6 / 2 — and an order the register does not contain.

    Every discovery first, then every `core`, then the two `additional`: the shape a
    campaign run on the counts alone would have, and the one the ter re-audit found
    reaching the human gate.
    """
    receipts = [receipt_for(step) for step in REGISTER if step[1] == "discover"]
    receipts += [
        receipt_for(step, moment=instant_of(20 + position), day=position % 2)
        for position, step in enumerate(step for step in REGISTER if step[1] == "core")
    ]
    receipts += [
        receipt_for(step, moment=instant_of(40 + position))
        for position, step in enumerate(step for step in REGISTER if step[1] == "additional")
    ]
    return receipts


class TestAnIncompatibleRegisterNeverReachesTheGate:
    """D3. `COMPLETE` and the promotion gate both require the register, not the totals."""

    def test_right_totals_in_the_wrong_order_are_a_conflict(self, boundary: Path) -> None:
        plant(boundary, out_of_order_twelve())
        published = block()
        assert published["campaign_invocation_counts"] == {
            "discover": 4,
            "core": 6,
            "additional": 2,
        }
        assert published["campaign_execution_state"] == "CONFLICT"
        assert next_five(published) == [None, None, None, None, None]

    def test_right_totals_in_the_wrong_order_do_not_qualify(self, boundary: Path) -> None:
        plant(boundary, out_of_order_twelve())
        document = verdict()
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert document["eligible_for_human_promotion_review"] is False

    def test_the_conflict_names_no_event_and_no_secret(self, boundary: Path) -> None:
        plant(boundary, out_of_order_twelve())
        blob = json.dumps(qual.campaign_ledger(act.audit_receipts()).conflicts, ensure_ascii=False)
        assert blob != "[]"
        assert v8.SECRET not in blob
        for step in REGISTER:
            if step[1] == "discover":
                for tag in tags_of(step[0]):
                    assert tag not in blob

    def test_the_spent_invocations_are_still_counted(self, boundary: Path) -> None:
        """A conflict does not erase what was spent."""
        plant(boundary, out_of_order_twelve())
        assert block()["campaign_counts_state"] == "ESTABLISHED"
        assert block()["campaign_invocation_counts"]["core"] == 6

    def test_an_unestablished_count_is_not_a_conflict(self, boundary: Path) -> None:
        """D3 must not swallow « I cannot count » into « the corpus contradicts itself »."""
        plant(boundary, conforming(1))
        (boundary / "99-illisible.json").write_text("{ pas du json", encoding="utf-8")
        published = block()
        assert published["campaign_counts_state"] == "UNESTABLISHED"
        assert published["campaign_execution_state"] == "UNESTABLISHED"
        assert published["campaign_invocation_counts"] is None
        assert verdict()["qualification_state"] != "EVIDENCE_CONFLICT"

    def test_a_complete_conforming_campaign_is_not_a_conflict(self, boundary: Path) -> None:
        plant(boundary, conforming(12))
        assert block()["campaign_execution_state"] == "COMPLETE"
        assert qual.campaign_ledger(act.audit_receipts()).conflicts == ()


class TestTheGateStillNeedsTheOtherCriteria:
    """T-CRIT. Two positive witnesses, so « conflict » is not the only way to fail."""

    def test_a_conforming_campaign_over_two_utc_days_reaches_the_gate(self, boundary: Path) -> None:
        plant(boundary, conforming(12, days=QUALIFYING_DAYS))
        document = verdict()
        assert document["evidence_conflicts"] == []
        assert document["qualification_state"] == "CRITERIA_MET_AWAITING_HUMAN_REVIEW"
        assert document["eligible_for_human_promotion_review"] is True
        # The gate is a conversation, never a promotion.
        assert document["campaign_execution_state"] == "COMPLETE"

    def test_a_conforming_campaign_inside_one_utc_day_does_not(self, boundary: Path) -> None:
        plant(boundary, conforming(12))
        document = verdict()
        assert document["evidence_conflicts"] == []
        assert document["campaign_execution_state"] == "COMPLETE"
        assert document["qualification_state"] == "INSUFFICIENT_EVIDENCE"
        assert document["eligible_for_human_promotion_review"] is False


# ---------------------------------------------------------------------------
# T-FAIL — a readable failure consumes its place
# ---------------------------------------------------------------------------
def failed_core() -> dict[str, Any]:
    """Step 2's `core`, failed for coverage, with the fields its phase really carries.

    A success's market map is not exigible on a failure that happened before that phase:
    a ``COVERAGE_MISSING`` core still claiming ``OBSERVED_MAPPED`` would be a
    self-contradictory receipt, which is a different fault with its own rules.
    """
    receipt = receipt_for(REGISTER[1], status="COVERAGE_MISSING")
    receipt.update(
        {
            "market_states": {"h2h": "NOT_RETURNED"},
            "markets_mapped": [],
            "markets_observed": [],
            "markets_absent": ["h2h"],
            "selections_mapped": 0,
        }
    )
    return v8.sealed_again(receipt)


class TestAFailureConsumesItsPlaceAndIsNotAConflict:
    """T-FAIL. An abort is not a contradiction, and its cost is not erased."""

    def test_a_failed_discovery_aborts_without_conflicting(self, boundary: Path) -> None:
        plant(boundary, [receipt_for(REGISTER[0], events=0, status="COVERAGE_MISSING")])
        published = block()
        assert published["campaign_execution_state"] == "ABORTED"
        assert published["campaign_invocation_counts"] == {
            "discover": 1,
            "core": 0,
            "additional": 0,
        }
        assert qual.campaign_ledger(act.audit_receipts()).conflicts == ()
        assert next_five(published) == [None, None, None, None, None]

    def test_a_failed_core_aborts_without_conflicting(self, boundary: Path) -> None:
        plant(boundary, [*conforming(1), failed_core()])
        published = block()
        assert published["campaign_execution_state"] == "ABORTED"
        assert published["campaign_invocation_counts"]["core"] == 1
        assert qual.campaign_ledger(act.audit_receipts()).conflicts == ()

    def test_a_receipt_filed_after_the_abort_is_a_conflict(self, boundary: Path) -> None:
        plant(
            boundary,
            [
                receipt_for(REGISTER[0], events=0, status="COVERAGE_MISSING"),
                receipt_for(REGISTER[4], moment=instant_of(30)),
            ],
        )
        assert block()["campaign_execution_state"] == "CONFLICT"


# ---------------------------------------------------------------------------
# T-LOCAL — the guard refuses before anything is spent
# ---------------------------------------------------------------------------
class Tripwire(Exception):
    pass


@pytest.fixture
def tripwires(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    hits = dict.fromkeys(("settings", "key", "intent", "client"), 0)

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


class TestTheGuardUsesTheSameReading:
    """T-LOCAL. Rank *and* parent identity, opposed before the first engagement."""

    def guard(self, **kwargs: Any) -> str:
        with pytest.raises(act.Refused) as caught:
            act.campaign_preflight(**kwargs)
        assert caught.value.status is act.ActivationStatus.PREPARED_NOT_EXECUTED
        return str(caught.value.message)

    def test_the_planned_core_is_accepted(self, boundary: Path, tripwires: dict[str, int]) -> None:
        plant(boundary, conforming(1))
        act.campaign_preflight(
            "core",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_of(1)[0],
            parent=receipt_for(REGISTER[0]),
        )
        assert sum(tripwires.values()) == 0

    def test_a_rank_the_register_does_not_name_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, conforming(1))
        message = self.guard(
            command="core",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_of(1)[2],
            parent=receipt_for(REGISTER[0]),
        )
        assert "rang 1" in message
        assert sum(tripwires.values()) == 0

    def test_a_parent_receipt_that_is_not_the_recognised_one_is_refused(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        """Only the parameter under test changes: same event, another parent receipt."""
        plant(boundary, conforming(3))
        impostor = receipt_for(REGISTER[2], moment=instant_of(3))
        impostor["receipt_id"] = "f" * 16
        v8.sealed_again(impostor)
        message = self.guard(
            command="additional",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_of(1)[1],
            parent=impostor,
        )
        assert "étape 3" in message
        assert sum(tripwires.values()) == 0

    def test_the_planned_additional_is_accepted(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, conforming(3))
        act.campaign_preflight(
            "additional",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_of(1)[1],
            parent=receipt_for(REGISTER[2]),
        )
        assert sum(tripwires.values()) == 0

    def test_a_conflicting_corpus_refuses_every_command(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        plant(boundary, [*conforming(1), receipt_for(REGISTER[1], rank=3)])
        message = self.guard(command="discover", sport="soccer_epl", bookmaker=v8.BOOKMAKER)
        assert "CONFLICT" in message
        assert sum(tripwires.values()) == 0

    def test_a_thin_parent_discovery_is_refused_by_the_guard(
        self, boundary: Path, tripwires: dict[str, int]
    ) -> None:
        """The guard's own sufficiency check, exercised directly for the first time.

        `run_discovery` already refuses to publish `DISCOVERY_VERIFIED` over a listing too
        thin, so on the nominal path this is a second line. It is kept — and now tested —
        because the parent is a file the operator names, and the register indexes a rank
        in it: reading `tags[rank - 1]` on a list that has no such rank must be a refusal,
        not an index error.
        """
        plant(boundary, conforming(1))
        message = self.guard(
            command="core",
            sport="soccer_epl",
            bookmaker=v8.BOOKMAKER,
            event_tag_value=tags_of(1, 1)[0],
            parent=receipt_for(REGISTER[0], events=1),
        )
        assert "1 événement" in message
        assert sum(tripwires.values()) == 0
