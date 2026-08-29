"""The protocol 8 campaign is pre-registered, and the machine enforces it.

Why this suite exists
---------------------
The static audit 03C-2D bis measured the defect this suite closes. Under protocol
7 the campaign's bounds — four ``discover``, six ``core``, two ``additional``,
sixteen credits — lived in a prose table and in :func:`campaign_budget`, a pure
derivation of constants that read no receipt at all. Nothing counted invocations,
and nothing published a count. Two corpora were built and compared field by field:
nine discoveries (more than double the four allocated) and a conforming nine-receipt
corpus produced **identical** values in every published field that could have told
them apart. An operator could have re-run ``discover`` until one came back non-empty
and presented the result as the prepared campaign; ``activation status`` would not
have contradicted them.

So the bounds are no longer documentary. This suite pins three things:

* the **manifest** — one bookmaker, four competitions, one instant of effect —
  identically in the code, the documents and the source matrix;
* the **guard**, which refuses before the provider key is read, before an intent
  is published and before a socket exists;
* the **ledger**, which counts what really happened from verified receipts, says
  ``UNESTABLISHED`` rather than zero when it cannot count, and turns an overrun
  into ``EVIDENCE_CONFLICT`` instead of into silence.

Everything is synthetic. No real boundary is opened, no real secret is read, and
the real protocol 7 receipt is never used as a fixture — where a v7 receipt is
needed, one is built from synthetic values.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

import helpers_campaign_v8 as v8
from betmaxxing import config as cfg
from betmaxxing.config import reset_settings_cache
from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual

REPOSITORY = Path(__file__).resolve().parents[1]
runner = CliRunner()

#: The manifest, restated as literals. A test that imported the constant it is
#: meant to pin would agree with whatever the module happened to hold.
BOOKMAKER = "pinnacle"
FOOTBALL = ("soccer_epl", "soccer_spain_la_liga")
TENNIS = ("tennis_atp_us_open", "tennis_wta_us_open")
COMPETITIONS = (*FOOTBALL, *TENNIS)
NOT_BEFORE = "2026-08-25T00:00:00+00:00"
LIMITS = {"discover": 4, "core": 6, "additional": 2}
#: The variable the adapter's parser is configured from. Named here rather than
#: imported, so a test cannot agree with a value the code happened to hold.
BOOKMAKERS_VARIABLE = "BETMAXXING_BOOKMAKERS"


def read(relative: str) -> str:
    return (REPOSITORY / relative).read_text(encoding="utf-8")


@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway receipt directory whose signing secret is injected, not stored."""
    directory = tmp_path / "receipts"
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
    monkeypatch.setenv(act.SECRET_VARIABLE, v8.SECRET)
    # What an operator must also configure: the parser keeps only the bookmakers this
    # variable names, and the guard refuses before the network when it omits the
    # campaign's. Set here so the tests below exercise the rule they are about rather
    # than all stopping at this one.
    monkeypatch.setenv(BOOKMAKERS_VARIABLE, BOOKMAKER)
    monkeypatch.delenv("BETMAXXING_THE_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("BETMAXXING_ODDS_API_KEY", raising=False)
    reset_settings_cache()
    return directory


def plant(directory: Path, receipts: list[dict[str, Any]], **over: Any) -> Path:
    return v8.write_corpus(directory, receipts, **over)


def published(directory: Path) -> dict[str, Any]:
    """What ``status --json`` publishes over this boundary."""
    result = runner.invoke(act.app, ["status", "--json"])
    assert result.exit_code == 0, result.output
    return dict(json.loads(result.stdout))


def evaluated(directory: Path) -> dict[str, Any]:
    """The evaluator's own verdict over this boundary, without the CLI."""
    return qual.evaluate(act.audit_receipts(), unresolved_intents=0)


# ---------------------------------------------------------------------------
# 1-4 — the manifest itself, in the code and in the documents
# ---------------------------------------------------------------------------
class TestTheManifestIsPreRegistered:
    """One bookmaker, four competitions, one instant, written once and agreed everywhere."""

    def test_the_protocol_version_is_eight(self) -> None:
        assert qual.PROVIDER_VALIDATION_PROTOCOL_VERSION == 8

    def test_the_instant_of_effect_is_exact(self) -> None:
        assert qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC == NOT_BEFORE

    def test_the_adapter_and_receipt_versions_are_unchanged(self) -> None:
        """A campaign boundary is not a schema change, and must not smuggle one in."""
        assert qual.PROVIDER_ADAPTER_EVIDENCE_VERSION == 1
        assert act.RECEIPT_SCHEMA_VERSION == 4
        assert qual.QUALIFYING_SCHEMA_VERSION == 4

    def test_the_bookmaker_is_pinnacle_and_only_pinnacle(self) -> None:
        assert qual.CAMPAIGN_BOOKMAKER == BOOKMAKER

    def test_the_four_competitions_are_exact(self) -> None:
        assert qual.CAMPAIGN_SCOPES == {"soccer": FOOTBALL, "tennis": TENNIS}
        assert qual.CAMPAIGN_COMPETITIONS == COMPETITIONS

    def test_additional_is_football_only(self) -> None:
        """Two `additional` calls, one per football competition — never tennis."""
        assert qual.CAMPAIGN_ADDITIONAL_SCOPES == FOOTBALL

    def test_the_family_of_each_competition_is_readable(self) -> None:
        for sport in FOOTBALL:
            assert qual.campaign_family(sport) == "soccer"
        for sport in TENNIS:
            assert qual.campaign_family(sport) == "tennis"
        assert qual.campaign_family(v8.FOREIGN_COMPETITION) == ""
        assert qual.campaign_family("") == ""

    def test_the_protocol_document_announces_version_eight(self) -> None:
        assert (
            "PROVIDER_VALIDATION_PROTOCOL_VERSION = 8"
            in read("docs/provider-validation-protocol.md").splitlines()[0]
        )

    @pytest.mark.parametrize(
        "relative",
        (
            "docs/provider-validation-protocol.md",
            "docs/provider-activation.md",
            "docs/source-matrix.md",
        ),
    )
    def test_every_document_names_the_same_manifest(self, relative: str) -> None:
        text = read(relative)
        assert BOOKMAKER in text, f"{relative} ne nomme pas le bookmaker de la campagne v8"
        for sport in COMPETITIONS:
            assert sport in text, f"{relative} ne nomme pas {sport}"

    def test_no_document_names_a_competition_outside_the_manifest_as_current(self) -> None:
        """Both directions, because « each one is present » passes on a *superset*.

        A throwaway mutation proved it: renaming one competition in the protocol's own
        manifest table left the old key elsewhere in the document, so the one-directional
        check stayed green while the document and the code disagreed. What is pinned here
        is the table itself — every sport key it names, and no other.
        """
        text = read("docs/provider-validation-protocol.md")
        rows = {
            "football": "| football | " + ", ".join(f"`{s}`" for s in FOOTBALL) + " |",
            "tennis": "| tennis | " + ", ".join(f"`{s}`" for s in TENNIS) + " |",
        }
        for family, row in rows.items():
            assert text.count(row) == 1, (
                f"la ligne de manifeste {family} doit apparaître exactement une fois, "
                f"à l'identique : {row}"
            )
        # And no key of the provider's namespace that is neither in the manifest nor a
        # named historical scope may appear anywhere in the protocol.
        historical = {"soccer_france_ligue_one", "soccer_spl"}
        found = set(re.findall(r"\b(?:soccer|tennis)_[a-z0-9_]+", text))
        unexpected = found - set(COMPETITIONS) - historical
        assert not unexpected, f"compétitions ni au manifeste ni historiques : {sorted(unexpected)}"

    def test_the_instant_is_the_same_literal_everywhere(self) -> None:
        for relative in (
            "docs/provider-validation-protocol.md",
            "docs/provider-activation.md",
            "docs/decisions.md",
        ):
            assert NOT_BEFORE in read(relative), f"{relative} n'annonce pas l'instant d'effet v8"

    def test_the_source_matrix_dates_the_choice(self) -> None:
        text = read("docs/source-matrix.md")
        assert "2026-08-24" in text, "la date de consultation des sources n'est pas inscrite"
        for url in (
            "https://the-odds-api.com/sports-odds-data/sports-apis.html",
            "https://the-odds-api.com/sports-odds-data/bookmaker-apis.html",
            "https://the-odds-api.com/liveapi/guides/v4/",
        ):
            assert url in text, f"la source {url} n'est pas inscrite"

    def test_the_documents_exclude_winamax_and_track_b(self) -> None:
        text = read("docs/provider-validation-protocol.md")
        assert "`winamax_fr` et la piste B sont exclus de la campagne v8" in text

    def test_the_decision_register_carries_d082(self) -> None:
        text = read("docs/decisions.md")
        assert "### D-082" in text
        # D-080 and D-081 stay exactly where they were.
        assert "### D-080" in text and "### D-081" in text


# ---------------------------------------------------------------------------
# 6-7 — the ceilings, stated once and derived everywhere
# ---------------------------------------------------------------------------
class TestTheCeilingsAreExact:
    def test_the_three_invocation_limits(self) -> None:
        assert qual.CAMPAIGN_INVOCATION_LIMITS == LIMITS

    def test_the_core_ceiling_is_three_per_family(self) -> None:
        assert qual.CAMPAIGN_CORE_PER_FAMILY == 3
        assert qual.CAMPAIGN_CORE_PER_FAMILY * len(qual.CAMPAIGN_SCOPES) == LIMITS["core"]

    def test_one_discovery_per_competition(self) -> None:
        assert qual.CAMPAIGN_DISCOVER_PER_COMPETITION == 1
        assert len(qual.CAMPAIGN_COMPETITIONS) * 1 == LIMITS["discover"]

    def test_one_additional_per_football_competition(self) -> None:
        assert qual.CAMPAIGN_ADDITIONAL_PER_COMPETITION == 1
        assert len(qual.CAMPAIGN_ADDITIONAL_SCOPES) * 1 == LIMITS["additional"]

    def test_the_budget_totals_are_unchanged(self) -> None:
        """Splitting the campaign never discounted it: 12 / 16 / 8 / 16 still."""
        assert qual.campaign_budget() == {
            "cli_invocations": 12,
            "human_authorisations": 12,
            "http_requests": 16,
            "paid_http_requests": 8,
            "contractual_credits": 16,
        }

    def test_the_documented_ceilings_match_the_code(self) -> None:
        text = read("docs/provider-validation-protocol.md")
        for command, limit in LIMITS.items():
            assert f"`{command}` : {limit} invocation" in text, (
                f"le protocole n'annonce pas le plafond {command} = {limit}"
            )


# ---------------------------------------------------------------------------
# 5, 10, 15, 16, 17, 18 — the ledger read from real receipts
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("boundary")
class TestTheLedgerCountsWhatHappened:
    def test_an_empty_boundary_has_not_started(self, boundary: Path) -> None:
        plant(boundary, [])
        document = published(boundary)
        assert document["campaign_protocol_version"] == 8
        assert document["campaign_counts_state"] == "ESTABLISHED"
        assert document["campaign_invocation_counts"] == {"discover": 0, "core": 0, "additional": 0}
        assert document["campaign_invocation_limits"] == LIMITS
        assert document["campaign_execution_state"] == "NOT_STARTED"
        assert document["campaign_abort_reason"] == ""
        assert document["campaign_required_bookmaker"] == BOOKMAKER
        assert document["campaign_required_scopes"] == {
            "soccer": list(FOOTBALL),
            "tennis": list(TENNIS),
        }

    def test_the_historical_v7_receipt_counts_in_nothing(self, boundary: Path) -> None:
        """It stays on disk, stays signed, and belongs to no v8 counter."""
        plant(boundary, [v8.historical_v7_discovery()])
        document = published(boundary)
        assert document["verified_receipts"] == 1
        assert document["qualification_historical_nonqualifying_receipts"] == 1
        assert document["campaign_invocation_counts"] == {"discover": 0, "core": 0, "additional": 0}
        assert document["campaign_execution_state"] == "NOT_STARTED"
        assert document["campaign_counts_state"] == "ESTABLISHED"
        assert document["qualification_state"] == "INSUFFICIENT_EVIDENCE"
        assert document["evidence_conflicts"] == []

    def test_a_failed_discovery_consumes_its_place_and_aborts(self, boundary: Path) -> None:
        plant(boundary, v8.discoveries(1, failed_last=True))
        document = published(boundary)
        assert document["campaign_invocation_counts"]["discover"] == 1
        assert document["campaign_execution_state"] == "ABORTED"
        assert "COVERAGE_MISSING" in document["campaign_abort_reason"]
        assert "discover" in document["campaign_abort_reason"]

    def test_three_successes_after_one_failure_stay_aborted(self, boundary: Path) -> None:
        plant(boundary, v8.discoveries(4, failed_last=True))
        document = published(boundary)
        assert document["campaign_invocation_counts"]["discover"] == 4
        assert document["campaign_execution_state"] == "ABORTED"
        assert document["qualification_state"] == "INSUFFICIENT_EVIDENCE"

    def test_a_fifth_discovery_is_an_evidence_conflict(self, boundary: Path) -> None:
        plant(boundary, v8.discoveries(5, failed_last=True))
        document = published(boundary)
        assert document["campaign_execution_state"] == "CONFLICT"
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert any("discover" in conflict for conflict in document["evidence_conflicts"])

    def test_the_nominal_campaign_reaches_the_human_gate_and_no_further(
        self, boundary: Path
    ) -> None:
        plant(boundary, v8.nominal_campaign())
        document = published(boundary)
        assert document["campaign_invocation_counts"] == LIMITS
        assert document["campaign_execution_state"] == "COMPLETE"
        assert document["campaign_counts_state"] == "ESTABLISHED"
        assert document["qualification_state"] == "CRITERIA_MET_AWAITING_HUMAN_REVIEW"
        assert document["eligible_for_human_promotion_review"] is True
        # The ceiling of the machine, unchanged by any of this.
        assert document["adapter_state"] == "IMPLEMENTED_UNVERIFIED"

    def test_an_unreadable_file_leaves_the_counts_unestablished(self, boundary: Path) -> None:
        """No false zero: a corpus that cannot be counted honestly says so."""
        plant(boundary, v8.discoveries(2), unreadable=1)
        document = published(boundary)
        assert document["campaign_counts_state"] == "UNESTABLISHED"
        assert document["campaign_invocation_counts"] is None
        assert document["campaign_execution_state"] == "UNESTABLISHED"

    def test_a_malformed_current_receipt_leaves_the_counts_unestablished(
        self, boundary: Path
    ) -> None:
        broken = v8.discovery(sport=FOOTBALL[0], moment=v8.instant(), rid="b" * 16)
        broken["attempts"] = "two"
        plant(boundary, [v8.sealed_again(broken)])
        document = published(boundary)
        assert document["campaign_counts_state"] == "UNESTABLISHED"
        assert document["campaign_invocation_counts"] is None

    def test_an_unavailable_boundary_publishes_no_count(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plant(boundary, v8.discoveries(2))
        monkeypatch.setattr(
            act, "audit_receipts", lambda: act.receipt_store.audit_unreadable("unreadable")
        )
        document = published(boundary)
        assert document["campaign_counts_state"] == "UNESTABLISHED"
        assert document["campaign_invocation_counts"] is None
        assert document["campaign_execution_state"] == "UNESTABLISHED"


# ---------------------------------------------------------------------------
# 14 — a forged or out-of-manifest corpus is a conflict, never a silent pass
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("boundary")
class TestAnOutOfManifestCorpusConflicts:
    def test_a_foreign_bookmaker_conflicts(self, boundary: Path) -> None:
        plant(
            boundary,
            [
                v8.discovery(
                    sport=FOOTBALL[0],
                    moment=v8.instant(),
                    rid="f" * 16,
                    bookmaker=v8.FOREIGN_BOOKMAKER,
                )
            ],
        )
        document = published(boundary)
        assert document["campaign_execution_state"] == "CONFLICT"
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert any(BOOKMAKER in conflict for conflict in document["evidence_conflicts"])

    def test_a_foreign_competition_conflicts(self, boundary: Path) -> None:
        plant(
            boundary,
            [v8.discovery(sport=v8.FOREIGN_COMPETITION, moment=v8.instant(), rid="9" * 16)],
        )
        document = published(boundary)
        assert document["campaign_execution_state"] == "CONFLICT"
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"

    def test_a_tennis_additional_conflicts(self, boundary: Path) -> None:
        """`additional` is football-only; a tennis one is outside the manifest."""
        plant(
            boundary,
            [v8.additional(sport=TENNIS[0], moment=v8.instant(), rid="7" * 16, tag="t" * 20)],
        )
        document = published(boundary)
        assert document["campaign_execution_state"] == "CONFLICT"

    def test_two_discoveries_of_one_competition_conflict(self, boundary: Path) -> None:
        plant(
            boundary,
            [
                v8.discovery(sport=FOOTBALL[0], moment=v8.instant(0), rid="1" * 16),
                v8.discovery(sport=FOOTBALL[0], moment=v8.instant(1), rid="2" * 16),
            ],
        )
        document = published(boundary)
        assert document["campaign_execution_state"] == "CONFLICT"
        assert any(FOOTBALL[0] in conflict for conflict in document["evidence_conflicts"])

    def test_a_seventh_core_conflicts(self, boundary: Path) -> None:
        corpus = v8.nominal_campaign()
        corpus.append(
            v8.core(sport=FOOTBALL[0], moment=v8.instant(9), rid="c" * 16, tag="core-tag-99")
        )
        plant(boundary, corpus)
        document = published(boundary)
        assert document["campaign_execution_state"] == "CONFLICT"
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"

    def test_a_third_additional_conflicts(self, boundary: Path) -> None:
        corpus = v8.nominal_campaign()
        corpus.append(
            v8.additional(sport=FOOTBALL[1], moment=v8.instant(9), rid="a" * 16, tag="add-tag-99")
        )
        plant(boundary, corpus)
        document = published(boundary)
        assert document["campaign_execution_state"] == "CONFLICT"
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"

    def test_a_receipt_after_the_abort_conflicts(self, boundary: Path) -> None:
        """The campaign stopped; anything filed afterwards contradicts the stop."""
        plant(
            boundary,
            [
                v8.discovery(
                    sport=FOOTBALL[0],
                    moment=v8.instant(0),
                    rid="0" * 16,
                    status="COVERAGE_MISSING",
                    events=0,
                ),
                v8.core(sport=FOOTBALL[1], moment=v8.instant(5), rid="5" * 16, tag="late-tag"),
            ],
        )
        document = published(boundary)
        assert document["campaign_execution_state"] == "CONFLICT"
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"


# ---------------------------------------------------------------------------
# 11-13, 19 — the guard, before the key, the intent and the socket
# ---------------------------------------------------------------------------
class Tripwire:
    """Records whether a forbidden step was reached, and stops it if it was.

    The three engaging steps, in the order the harness performs them: reading the
    provider key, publishing the durable intent, building the HTTP client. Sockets
    are blocked for the whole session by ``conftest``, so a client that is never
    built is a request that could never have left.
    """

    def __init__(self) -> None:
        self.key_reads = 0
        self.intents = 0
        self.clients = 0

    @property
    def engaged(self) -> dict[str, int]:
        return {"clé": self.key_reads, "intent": self.intents, "client": self.clients}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def key(*_: Any, **__: Any) -> str:
            self.key_reads += 1
            raise AssertionError("la clé fournisseur a été lue malgré le refus de la garde")

        def intent(*_: Any, **__: Any) -> str:
            self.intents += 1
            raise AssertionError("un intent a été publié malgré le refus de la garde")

        def client(*_: Any, **__: Any) -> Any:
            self.clients += 1
            raise AssertionError("un client HTTP a été construit malgré le refus de la garde")

        monkeypatch.setattr(act, "_require_key", key)
        monkeypatch.setattr(act, "publish_intent", intent)
        monkeypatch.setattr(act, "_client", client)


@pytest.mark.usefixtures("boundary")
class TestTheGuardRefusesBeforeAnythingIsSpent:
    """Every refusal below must leave 0 socket, 0 key read, 0 intent, 0 receipt, 0 credit."""

    def refuse(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
    ) -> tuple[Result, Tripwire]:
        def listing() -> list[str]:
            return sorted(p.name for p in boundary.iterdir()) if boundary.exists() else []

        before = listing()
        wire = Tripwire()
        wire.install(monkeypatch)
        result = runner.invoke(act.app, argv)
        assert result.exit_code != 0, result.output
        assert wire.key_reads == 0 and wire.intents == 0
        # Not one new file: no receipt, no intent, nothing partial.
        assert listing() == before, "la garde a laissé une trace sur la frontière"
        return result, wire

    def test_a_foreign_bookmaker_is_refused(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plant(boundary, [])
        result, _ = self.refuse(
            boundary,
            monkeypatch,
            [
                "discover",
                "--sport",
                FOOTBALL[0],
                "--bookmaker",
                v8.FOREIGN_BOOKMAKER,
                "--allow-network",
            ],
        )
        assert BOOKMAKER in result.output

    def test_a_foreign_competition_is_refused(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plant(boundary, [])
        result, _ = self.refuse(
            boundary,
            monkeypatch,
            [
                "discover",
                "--sport",
                v8.FOREIGN_COMPETITION,
                "--bookmaker",
                BOOKMAKER,
                "--allow-network",
            ],
        )
        assert v8.FOREIGN_COMPETITION in result.output

    def test_a_second_discovery_of_the_same_competition_is_refused(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plant(boundary, [v8.discovery(sport=FOOTBALL[0], moment=v8.instant(), rid="1" * 16)])
        self.refuse(
            boundary,
            monkeypatch,
            ["discover", "--sport", FOOTBALL[0], "--bookmaker", BOOKMAKER, "--allow-network"],
        )

    def test_a_fifth_discovery_is_refused(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And refused *for the ceiling*, not incidentally by a neighbouring rule.

        A throwaway mutation proved why the reason is asserted: with the ceiling check
        disabled, a fifth discovery was still refused — by the one-per-competition rule,
        which happens to cover the same case for this manifest. The command stopped, and
        the guard under test had stopped guarding.
        """
        plant(boundary, v8.discoveries(4))
        result, _ = self.refuse(
            boundary,
            monkeypatch,
            ["discover", "--sport", FOOTBALL[0], "--bookmaker", BOOKMAKER, "--allow-network"],
        )
        assert "plafond" in result.output.lower()
        assert str(LIMITS["discover"]) in result.output

    def test_no_command_runs_after_an_abort(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plant(boundary, v8.discoveries(1, failed_last=True))
        result, _ = self.refuse(
            boundary,
            monkeypatch,
            ["discover", "--sport", FOOTBALL[1], "--bookmaker", BOOKMAKER, "--allow-network"],
        )
        assert "ABORTED" in result.output

    def test_a_seventh_core_is_refused(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plant(boundary, v8.nominal_campaign())
        result, _ = self.refuse(
            boundary,
            monkeypatch,
            [
                "core",
                "--sport",
                FOOTBALL[0],
                "--bookmaker",
                BOOKMAKER,
                "--event-id",
                "evt-new-0001",
                "--discovery-receipt",
                "absent.json",
                "--max-credits",
                "1",
                "--acknowledge-credits",
                "1",
                "--allow-network",
            ],
        )
        # The ceiling, named — the per-family rule would refuse this case too.
        assert "plafond" in result.output.lower()
        assert str(LIMITS["core"]) in result.output

    def test_a_fourth_core_in_one_family_is_refused(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corpus = [
            v8.discovery(sport=sport, moment=v8.instant(index), rid=f"d{index:015x}")
            for index, sport in enumerate(COMPETITIONS)
        ]
        corpus += [
            v8.core(
                sport=FOOTBALL[index % 2],
                moment=v8.instant(10 + index),
                rid=f"c{index:015x}",
                tag=f"tag-{index}",
            )
            for index in range(3)
        ]
        plant(boundary, corpus)
        self.refuse(
            boundary,
            monkeypatch,
            [
                "core",
                "--sport",
                FOOTBALL[0],
                "--bookmaker",
                BOOKMAKER,
                "--event-id",
                "evt-new-0002",
                "--discovery-receipt",
                "absent.json",
                "--max-credits",
                "1",
                "--acknowledge-credits",
                "1",
                "--allow-network",
            ],
        )

    def test_a_second_additional_on_one_competition_is_refused(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corpus = [
            v8.discovery(sport=sport, moment=v8.instant(index), rid=f"d{index:015x}")
            for index, sport in enumerate(COMPETITIONS)
        ]
        corpus.append(
            v8.additional(sport=FOOTBALL[0], moment=v8.instant(9), rid="e" * 16, tag="add-0")
        )
        plant(boundary, corpus)
        self.refuse(
            boundary,
            monkeypatch,
            [
                "additional",
                "--sport",
                FOOTBALL[0],
                "--bookmaker",
                BOOKMAKER,
                "--event-id",
                "evt-new-0003",
                "--core-receipt",
                "absent.json",
                "--max-credits",
                "5",
                "--acknowledge-credits",
                "5",
                "--allow-network",
            ],
        )

    def test_counts_that_cannot_be_established_refuse_the_call(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """« I cannot count » must never read as « nothing has been spent »."""
        plant(boundary, v8.discoveries(1), unreadable=1)
        result, _ = self.refuse(
            boundary,
            monkeypatch,
            ["discover", "--sport", FOOTBALL[1], "--bookmaker", BOOKMAKER, "--allow-network"],
        )
        assert "UNESTABLISHED" in result.output

    def test_a_conflicting_corpus_refuses_the_call(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plant(boundary, v8.discoveries(5))
        self.refuse(
            boundary,
            monkeypatch,
            ["discover", "--sport", FOOTBALL[0], "--bookmaker", BOOKMAKER, "--allow-network"],
        )


# ---------------------------------------------------------------------------
# 20-21 — what `plan` says, and what nothing says
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("boundary")
class TestPlanSeparatesTheLocalSequenceFromTheCampaign:
    def invoke(self, *extra: str) -> Result:
        return runner.invoke(
            act.app,
            [
                "plan",
                "--sport",
                FOOTBALL[0],
                "--bookmaker",
                BOOKMAKER,
                "--max-credits",
                "6",
                *extra,
            ],
        )

    def test_the_two_figures_are_both_published_and_distinct(self) -> None:
        result = self.invoke("--json")
        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["total_max_credits"] == 6
        campaign = document["campaign"]
        assert campaign["contractual_credits"] == 16
        assert campaign["cli_invocations"] == 12
        assert campaign["http_requests"] == 16
        assert campaign["paid_http_requests"] == 8
        assert campaign["protocol_version"] == 8
        assert campaign["bookmaker"] == BOOKMAKER
        assert campaign["scopes"] == {"soccer": list(FOOTBALL), "tennis": list(TENNIS)}

    def test_the_human_rendering_names_both_figures(self) -> None:
        result = self.invoke()
        assert result.exit_code == 0, result.output
        assert "6 crédits" in result.output
        assert "16 crédits" in result.output
        assert BOOKMAKER in result.output

    def test_plan_still_opens_no_socket_and_reads_no_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire = Tripwire()
        wire.install(monkeypatch)
        assert self.invoke("--json").exit_code == 0
        assert wire.key_reads == 0 and wire.intents == 0


class TestNothingHerePromotesAnything:
    def test_the_qualification_vocabulary_is_unchanged(self) -> None:
        assert [str(state) for state in qual.QualificationState] == [
            "INSUFFICIENT_EVIDENCE",
            "EVIDENCE_CONFLICT",
            "CRITERIA_MET_AWAITING_HUMAN_REVIEW",
        ]

    def test_the_campaign_states_are_the_published_six(self) -> None:
        assert [str(state) for state in qual.CampaignExecutionState] == [
            "NOT_STARTED",
            "IN_PROGRESS",
            "ABORTED",
            "COMPLETE",
            "CONFLICT",
            "UNESTABLISHED",
        ]

    def test_the_counts_state_has_exactly_two_values(self) -> None:
        assert [str(state) for state in qual.CampaignCountsState] == [
            "ESTABLISHED",
            "UNESTABLISHED",
        ]

    def test_no_promotion_state_was_added(self) -> None:
        text = read("src/betmaxxing/providers/the_odds_api/qualification.py")
        assert "VERIFIED_BY_CAMPAIGN" not in text
        assert "PROMOTED" not in text

    @pytest.mark.usefixtures("boundary")
    def test_a_complete_campaign_still_leaves_the_adapter_unverified(self, boundary: Path) -> None:
        plant(boundary, v8.nominal_campaign())
        assert published(boundary)["adapter_state"] == "IMPLEMENTED_UNVERIFIED"


# ---------------------------------------------------------------------------
# The parser's own configuration, guarded before anything is engaged
# ---------------------------------------------------------------------------
class TestTheCampaignBookmakerMustBeConfiguredForTheParser:
    """The precondition that used to cost a credit and the whole campaign.

    The final re-audit measured it on the shipped default. The harness parses a paid
    response with the adapter's own parser, and that parser keeps only the bookmakers
    named by ``BETMAXXING_BOOKMAKERS`` — not the one passed on the command line. The two
    agreed by accident while both were ``winamax_fr``; under the protocol 8 manifest they
    do not. A `core` call made exactly as the manifest requires, with the variable simply
    absent, reached the paid endpoint, kept no selection, published ``SCHEMA_MISMATCH``,
    spent one credit and put the campaign in ``ABORTED`` — irreversibly, since restarting
    needs a new protocol. It was written in three documents and enforced by nothing.

    So the configuration is now read *by name* and checked before the provider key, the
    intent and the client. A refusal here consumes no invocation, aborts nothing and
    conflicts nothing: the campaign stays exactly as reusable as it was.
    """

    REFUSEES = (
        pytest.param(None, id="variable-absente"),
        pytest.param("", id="variable-vide"),
        pytest.param("winamax_fr", id="le-defaut-livre"),
        pytest.param("unibet", id="un-autre-bookmaker"),
        pytest.param("PINNACLE", id="casse-differente"),
    )
    ACCEPTEES = (
        pytest.param(BOOKMAKER, id="pinnacle-seul"),
        pytest.param(f"winamax_fr,{BOOKMAKER}", id="pinnacle-parmi-d-autres"),
    )

    def configure(self, monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
        if value is None:
            monkeypatch.delenv(BOOKMAKERS_VARIABLE, raising=False)
        else:
            monkeypatch.setenv(BOOKMAKERS_VARIABLE, value)
        reset_settings_cache()

    def plant_reachable(self, boundary: Path) -> tuple[str, str]:
        """A corpus that reaches this guard and nothing else, plus its two parents.

        Three discoveries and one `core`, so no ceiling, no duplicate scope, no abort
        and no conflict can refuse first — the fourth scope is deliberately left free so
        that a `discover` has somewhere to go. The parents named on the
        command line are files *of that corpus*: an extra receipt written beside it
        would be a second discovery of one competition, and the campaign would be in
        CONFLICT before this guard was ever consulted.

        Neither parent is ever read on these paths — the provider key, and therefore the
        tripwire, comes first — but the corpus has to be genuinely complete for the
        refusal to be attributable to this rule alone.
        """
        receipts = [
            v8.discovery(sport=sport, moment=v8.instant(index), rid=f"d{index:015x}")
            for index, sport in enumerate(COMPETITIONS[:3])
        ]
        receipts.append(
            v8.core(sport=FOOTBALL[0], moment=v8.instant(10), rid="c" * 16, tag="parent-tag")
        )
        plant(boundary, receipts)
        found: dict[str, str] = {}
        for path in boundary.glob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("sport_key") == FOOTBALL[0]:
                found[str(document["command"])] = str(path)
        return found["discover"], found["core"]

    def argv(self, command: str, boundary: Path) -> list[str]:
        discovery, core = self.plant_reachable(boundary)
        common = ["--sport", FOOTBALL[0], "--bookmaker", BOOKMAKER, "--allow-network"]
        if command == "discover":
            # The one scope the corpus above leaves undiscovered.
            return [
                "discover",
                "--sport",
                COMPETITIONS[3],
                "--bookmaker",
                BOOKMAKER,
                "--allow-network",
            ]
        if command == "core":
            return [
                "core",
                *common,
                "--event-id",
                "EV-GUARD-1",
                "--discovery-receipt",
                discovery,
                "--max-credits",
                "1",
                "--acknowledge-credits",
                "1",
            ]
        return [
            "additional",
            *common,
            "--event-id",
            "EV-GUARD-2",
            "--core-receipt",
            core,
            "--max-credits",
            "5",
            "--acknowledge-credits",
            "5",
        ]

    @pytest.mark.parametrize("configured", REFUSEES)
    @pytest.mark.parametrize("command", ("discover", "core", "additional"))
    def test_a_configuration_without_the_campaign_bookmaker_is_refused(
        self,
        boundary: Path,
        monkeypatch: pytest.MonkeyPatch,
        command: str,
        configured: str | None,
    ) -> None:
        argv = self.argv(command, boundary)
        before = sorted(p.name for p in boundary.iterdir())
        etat_avant = published(boundary)

        self.configure(monkeypatch, configured)
        wire = Tripwire()
        wire.install(monkeypatch)
        result = runner.invoke(act.app, argv)

        assert result.exit_code != 0, result.output
        assert wire.engaged == {"clé": 0, "intent": 0, "client": 0}, wire.engaged
        assert sorted(p.name for p in boundary.iterdir()) == before, (
            "la garde a laissé une trace sur la frontière"
        )
        # The reason names this rule, not a ceiling, a missing lineage or a credit flag.
        sortie = result.output.lower()
        assert "bookmaker de campagne non configuré pour le parser" in sortie, result.output
        assert f"bookmaker requis = {BOOKMAKER}" in sortie, result.output
        for etranger in ("plafond", "lignée", "acknowledge", "expiré"):
            assert etranger not in sortie, f"refus attribué à {etranger!r} : {result.output}"

        # Nothing was consumed: the campaign is exactly as reusable as before.
        self.configure(monkeypatch, BOOKMAKER)
        etat_apres = published(boundary)
        assert etat_apres["campaign_invocation_counts"] == etat_avant["campaign_invocation_counts"]
        assert etat_apres["campaign_execution_state"] == etat_avant["campaign_execution_state"]
        assert etat_apres["campaign_execution_state"] != "ABORTED"
        assert etat_apres["qualification_state"] != "EVIDENCE_CONFLICT"
        assert etat_apres["accounted_credits_total"] == etat_avant["accounted_credits_total"]

    @pytest.mark.parametrize("configured", ACCEPTEES)
    @pytest.mark.parametrize("command", ("discover", "core", "additional"))
    def test_a_configuration_naming_the_campaign_bookmaker_passes_this_guard(
        self,
        boundary: Path,
        monkeypatch: pytest.MonkeyPatch,
        command: str,
        configured: str,
    ) -> None:
        """It must reach the key tripwire — otherwise the test above proves nothing.

        Without this, every refusal above would be satisfied by *any* earlier guard, and
        a check that never runs would look exactly like a check that always passes.
        """
        argv = self.argv(command, boundary)
        self.configure(monkeypatch, configured)
        wire = Tripwire()
        wire.install(monkeypatch)
        result = runner.invoke(act.app, argv)
        assert wire.key_reads == 1, (
            f"la commande n'a pas atteint la lecture de clé : {result.output}"
        )
        assert wire.intents == 0 and wire.clients == 0

    def test_the_refusal_never_echoes_the_configured_value(
        self, boundary: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Naming the requirement is the job; reflecting the environment is not."""
        self.argv("discover", boundary)
        sentinelle = "sentinelle_de_configuration_a_ne_pas_refleter"
        self.configure(monkeypatch, sentinelle)
        Tripwire().install(monkeypatch)
        result = runner.invoke(
            act.app,
            ["discover", "--sport", COMPETITIONS[3], "--bookmaker", BOOKMAKER, "--allow-network"],
        )
        assert result.exit_code != 0
        # Asserted together, deliberately: without the second line the test passes on a
        # build that has no guard at all — nothing is echoed because nothing refuses.
        assert "bookmaker de campagne non configuré pour le parser" in result.output.lower()
        assert sentinelle not in result.output

    def test_the_documents_promise_a_guard_and_not_a_habit(self) -> None:
        for relative in (
            "docs/provider-validation-protocol.md",
            "docs/provider-activation.md",
            "docs/decisions.md",
        ):
            text = read(relative)
            assert BOOKMAKERS_VARIABLE in text, f"{relative} ne nomme pas la variable"
            # The guarantee itself, in the words that state it: the check happens before
            # the provider key. A document that only says « exportez la variable » is a
            # habit, and a habit is what cost a credit and the campaign.
            assert "avant la lecture de la clé fournisseur" in text, (
                f"{relative} présente encore la précondition comme opératoire"
            )


# ---------------------------------------------------------------------------
# The reader itself, guarded so the two ways of losing it cannot come back
# ---------------------------------------------------------------------------
#: Every file that must state the process-environment rule. `.env` is the project's
#: documented configuration channel and ships this very variable, so an operator who
#: sets it there and nowhere else is refused — cheaply and fail-closed, but silently
#: unless each of these says so.
FICHIERS_REGLE_ENV = (
    ".env.example",
    "docs/deployment.md",
    "docs/provider-activation.md",
    "docs/provider-validation-protocol.md",
    "docs/decisions.md",
)
#: The normative phrase all five carry, and the command an operator actually runs.
REGLE_ENV = "environnement du processus"
EXPORT = f"export {BOOKMAKERS_VARIABLE}={BOOKMAKER}"

#: Variables whose *name* alone marks them as a credential. The reader must consult
#: none of them; the test never uses a real value for any.
SENTINELLES_SECRETES = (
    "BETMAXXING_THE_ODDS_API_KEY",
    "BETMAXXING_ODDS_API_KEY",
    "BETMAXXING_SPORTSDATA_API_KEY",
    "BETMAXXING_TELEGRAM_BOT_TOKEN",
    "BETMAXXING_SMTP_PASSWORD",
    "BETMAXXING_API_TOKEN",
)


class _Espion:
    """Records every environment name the code under test looks at."""

    def __init__(self) -> None:
        self.noms: list[str] = []

    def installer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        classe = type(os.environ)
        vrai_gi, vrai_get, vrai_in = (
            classe.__getitem__,
            classe.get,
            classe.__contains__,
        )

        def noter(cle: object) -> None:
            if isinstance(cle, str):
                self.noms.append(cle)

        def gi(soi: Any, cle: Any) -> Any:
            noter(cle)
            return vrai_gi(soi, cle)

        def get(soi: Any, cle: Any, defaut: Any = None) -> Any:
            noter(cle)
            return vrai_get(soi, cle, defaut)

        def contient(soi: Any, cle: Any) -> bool:
            noter(cle)
            return bool(vrai_in(soi, cle))

        monkeypatch.setattr(classe, "__getitem__", gi)
        monkeypatch.setattr(classe, "get", get)
        monkeypatch.setattr(classe, "__contains__", contient)


class TestTheReaderStaysDedicatedAndShared:
    """Two ways to lose the guard silently, and one document rule, all pinned.

    The final re-audit ran ten mutations against the guard. Eight were killed by the
    suite; two were not, and both were security-relevant:

    * swapping the dedicated reader for ``get_settings().bookmaker_list`` yields the
      *same list* and leaves every test green, while reading the provider key before
      the guard has decided anything — the exact ordering the guard exists to hold;
    * letting ``Settings.bookmaker_list`` re-implement its own splitting leaves every
      test green and reopens the failure the guard prevents: with
      ``"winamax_fr , pinnacle"`` the guard reads ``pinnacle`` and admits the call
      while the parser reads ``" pinnacle"`` and drops it — one paid request, one
      credit, ``SCHEMA_MISMATCH``, campaign aborted.

    The audit's own probes killed both. Probes are not regression guards, so they are
    committed here.
    """

    def test_the_reader_consults_its_own_variable_and_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only ``BETMAXXING_BOOKMAKERS``, and no name that marks a credential."""
        for nom in SENTINELLES_SECRETES:
            monkeypatch.setenv(nom, "SENTINELLE-SYNTHETIQUE-SANS-VALEUR-REELLE")
        monkeypatch.setenv(BOOKMAKERS_VARIABLE, BOOKMAKER)
        reset_settings_cache()

        espion = _Espion()
        espion.installer(monkeypatch)
        espion.noms.clear()
        lu = cfg.configured_bookmakers()

        assert lu == [BOOKMAKER]
        assert sorted(set(espion.noms)) == [BOOKMAKERS_VARIABLE], espion.noms
        fuites = [n for n in espion.noms if n in SENTINELLES_SECRETES]
        assert fuites == [], f"le lecteur a consulté une variable de forme secrète : {fuites}"

    def test_the_reader_instantiates_no_general_configuration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tripwires on both doors into ``Settings``; neither may be opened.

        ``Settings`` is a pydantic-settings model: constructing it populates every
        field from the environment and from ``.env``, the provider key included. This
        is what makes « before the key » true rather than merely intended.
        """
        atteints: list[str] = []

        def piege(nom: str) -> Any:
            def _f(*_: Any, **__: Any) -> Any:
                atteints.append(nom)
                raise AssertionError(f"le lecteur a atteint {nom}")

            # ``reset_settings_cache`` empties the singleton through this same name;
            # a tripwire without the attribute would fail the test with an
            # ``AttributeError`` of its own making rather than with a real reading.
            _f.cache_clear = lambda: None  # type: ignore[attr-defined]
            return _f

        # The cache is emptied for real once, before the doors are wired shut.
        monkeypatch.setenv(BOOKMAKERS_VARIABLE, BOOKMAKER)
        reset_settings_cache()

        monkeypatch.setattr(cfg, "get_settings", piege("get_settings"))
        monkeypatch.setattr(cfg.Settings, "__init__", piege("Settings.__init__"))
        monkeypatch.setattr(act, "get_settings", piege("activation.get_settings"))

        # The reader itself.
        assert cfg.configured_bookmakers() == [BOOKMAKER]

        # And the guard's own call site, which is where the ordering actually holds.
        # Asserting only the reader lets a mutation swap `configured_bookmakers()` for
        # `get_settings().bookmaker_list` *at the call site*: the list is identical, the
        # reader stays pure, and the guard reads the provider key anyway.
        monkeypatch.setenv(BOOKMAKERS_VARIABLE, "winamax_fr")
        with pytest.raises(act.Refused) as refus:
            act.campaign_preflight("discover", sport=FOOTBALL[0], bookmaker=BOOKMAKER)
        assert "bookmaker de campagne non configuré pour le parser" in refus.value.message.lower()
        assert atteints == [], atteints

    def test_both_readers_delegate_to_the_one_splitting_function(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Structurally the same function, not two implementations that agree today.

        A spy rather than a comparison of outputs: two independent splitters can agree
        on every value a test happens to try and still diverge on a spaced list, which
        is precisely the case that costs a credit and the campaign.
        """
        vus: list[str] = []
        SENTINELLE = ["sentinelle-de-decoupage"]

        def espion(brut: str) -> list[str]:
            vus.append(brut)
            return list(SENTINELLE)

        monkeypatch.setattr(cfg, "split_bookmakers", espion)
        brut = "winamax_fr , pinnacle"
        monkeypatch.setenv(BOOKMAKERS_VARIABLE, brut)
        reset_settings_cache()

        assert cfg.configured_bookmakers() == SENTINELLE
        assert cfg.get_settings().bookmaker_list == SENTINELLE
        assert vus == [brut, brut], (
            "les deux lecteurs doivent passer la chaîne brute exacte à la même fonction"
        )

    def test_every_document_states_the_process_environment_rule(self) -> None:
        """`.env` alone is refused, and each document that configures says so."""
        for relative in FICHIERS_REGLE_ENV:
            texte = read(relative)
            assert BOOKMAKERS_VARIABLE in texte, f"{relative} ne nomme pas la variable"
            assert REGLE_ENV in texte, (
                f"{relative} n'énonce pas que la campagne v8 exige la variable dans "
                f"l'{REGLE_ENV}, et non seulement dans .env"
            )
            assert ".env" in texte, f"{relative} ne situe pas la règle par rapport à .env"
        for relative in FICHIERS_REGLE_ENV:
            if relative == "docs/decisions.md":
                continue
            assert EXPORT in read(relative), f"{relative} ne montre pas la commande {EXPORT}"
