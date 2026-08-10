"""What the discovery actually saw, and what the activation has actually done.

Three claims stopped being true once real calls happened.

**A discovery could not say why it found nothing.** The Ligue 1 attempt reported
``COVERAGE_MISSING`` with ``event_tags: []`` and nothing else. That is compatible
with three different findings: the provider returned an empty list; it returned
fixtures that all fall outside the declared window; or it returned fixtures the
harness refused as unusable. Only the first is a calendar fact — the others would
point at our own filter. The receipt kept none of it, and re-running to find out
is not free of consequence, so the counters have to be there the first time.

**`PREPARED_NOT_EXECUTED` became false.** Two `core` calls were made and billed.
A label meaning "nothing has been executed" cannot keep being printed as the
current state of the activation. It survives only where it is still true: a
refusal that happened before any socket opened.

**Local receipt paths are not URLs.** ``.activation-receipts/`` is gitignored on
purpose. Rendering one of those paths as a link into the repository host invents a
remote artefact that does not and must not exist.

Every fixture here is synthetic. Nothing from the two real SPL operations — no
event id, no participant, no payload, no receipt — is reproduced.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from helpers_activation import (
    BOOKMAKER,
    EVENT_ID,
    NOW,
    OTHER_EVENT_ID,
    SPORT,
    Recorder,
    core_args,
    discover_args,
    install,
    iso_z,
    odds_payload,
    receipt_path,
    receipts_in,
    run,
    sports_payload,
)

FREE_HEADERS = {"x-requests-last": "0", "x-requests-remaining": "480"}
PAID_HEADERS = {"x-requests-last": "1", "x-requests-remaining": "479"}


def event(event_id: str, *, hours_ahead: float, **overrides: Any) -> dict[str, Any]:
    """One synthetic event descriptor, as `/events` returns them."""
    base = {
        "id": event_id,
        "sport_key": SPORT,
        "commence_time": iso_z(NOW + timedelta(hours=hours_ahead)),
        "home_team": "Synthetic Home",
        "away_team": "Synthetic Away",
    }
    base.update(overrides)
    return base


def discover_with(events: list[dict[str, Any]], *extra: str) -> Any:
    def routes(monkeypatch: pytest.MonkeyPatch) -> Recorder:
        recorder = Recorder(
            {
                "/sports/": lambda _r: httpx.Response(200, json=events, headers=FREE_HEADERS),
                "/sports": lambda _r: httpx.Response(
                    200, json=sports_payload(), headers=FREE_HEADERS
                ),
            }
        )
        install(monkeypatch, recorder)
        return recorder

    return routes


def run_discover(monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]], *extra: str) -> Any:
    discover_with(events)(monkeypatch)
    return run(*discover_args(extra=extra))


def discovery_receipt(receipts: Path) -> dict[str, Any]:
    matching = [r for r in receipts_in(receipts) if r["command"] == "discover"]
    assert matching, "no discovery receipt was written"
    return matching[-1]


# ---------------------------------------------------------------------------
# E2 — the discovery counters
# ---------------------------------------------------------------------------
class TestAnEmptyProviderListIsDistinguishable:
    def test_all_three_counters_are_zero(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_discover(monkeypatch, [])
        r = discovery_receipt(keyed)
        assert (r["events_returned"], r["events_in_window"], r["events_admissible"]) == (0, 0, 0)

    def test_the_status_is_coverage_missing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = run_discover(monkeypatch, [])
        assert "COVERAGE_MISSING" in result.stdout
        assert result.exit_code != 0


class TestEverythingOutOfWindowIsDistinguishable:
    """The reading the Ligue 1 receipt could not settle."""

    def test_returned_is_positive_while_in_window_is_zero(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_discover(
            monkeypatch,
            [event("evt-far-1", hours_ahead=48.0), event("evt-far-2", hours_ahead=72.0)],
        )
        r = discovery_receipt(keyed)
        assert r["events_returned"] == 2
        assert r["events_in_window"] == 0
        assert r["events_admissible"] == 0

    def test_an_already_started_event_counts_as_returned_not_in_window(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_discover(monkeypatch, [event("evt-past-1", hours_ahead=-1.0)])
        r = discovery_receipt(keyed)
        assert (r["events_returned"], r["events_in_window"]) == (1, 0)

    def test_it_reads_differently_from_an_empty_list(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        far = run_discover(monkeypatch, [event("evt-far-1", hours_ahead=48.0)]).stdout
        for path in keyed.glob("*.json"):
            path.unlink()
        empty = run_discover(monkeypatch, []).stdout
        assert far != empty, "an out-of-window list is indistinguishable from an empty one"


class TestInadmissibleEventsAreCountedSeparately:
    @pytest.mark.parametrize(
        ("label", "descriptor"),
        [
            ("no-id", {"sport_key": SPORT, "commence_time": iso_z(NOW + timedelta(hours=6))}),
            ("blank-id", {"id": "", "commence_time": iso_z(NOW + timedelta(hours=6))}),
            ("unparseable-time", {"id": "evt-bad-1", "commence_time": "not-a-date"}),
            ("no-time", {"id": "evt-bad-2"}),
        ],
    )
    def test_an_unusable_descriptor_never_becomes_admissible(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        label: str,
        descriptor: dict[str, Any],
    ) -> None:
        run_discover(monkeypatch, [descriptor])
        r = discovery_receipt(keyed)
        assert r["events_returned"] == 1, label
        assert r["events_admissible"] == 0, label
        assert r["event_tags"] == [], label

    def test_a_mixed_list_is_counted_at_each_stage(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """One far, one past, one unusable, two good."""
        run_discover(
            monkeypatch,
            [
                event("evt-far-1", hours_ahead=48.0),
                event("evt-past-1", hours_ahead=-2.0),
                {"id": "evt-bad-1", "commence_time": "not-a-date"},
                event(EVENT_ID, hours_ahead=6.0),
                event(OTHER_EVENT_ID, hours_ahead=8.0),
            ],
            "--json",
        )
        r = discovery_receipt(keyed)
        assert r["events_returned"] == 5
        assert r["events_in_window"] == 2
        assert r["events_admissible"] == 2


#: One case per shape of provider answer, reused by both invariant tests.
COUNTER_CASES: list[tuple[str, list[dict[str, Any]]]] = [
    ("empty", []),
    ("all-far", [{"id": "a", "commence_time": iso_z(NOW + timedelta(hours=48))}]),
    ("all-past", [{"id": "b", "commence_time": iso_z(NOW - timedelta(hours=1))}]),
    ("unusable", [{"id": "c", "commence_time": "nope"}]),
    (
        "good",
        [
            {
                "id": EVENT_ID,
                "commence_time": iso_z(NOW + timedelta(hours=6)),
                "home_team": "H",
                "away_team": "A",
            }
        ],
    ),
    (
        "mixed",
        [
            {"id": "d", "commence_time": iso_z(NOW + timedelta(hours=48))},
            {
                "id": EVENT_ID,
                "commence_time": iso_z(NOW + timedelta(hours=6)),
                "home_team": "H",
                "away_team": "A",
            },
        ],
    ),
]


class TestTheCountersRespectTheirInvariants:
    @pytest.mark.parametrize(("label", "events"), COUNTER_CASES, ids=[c[0] for c in COUNTER_CASES])
    def test_the_ordering_invariant_holds(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        label: str,
        events: list[dict[str, Any]],
    ) -> None:
        run_discover(monkeypatch, events)
        r = discovery_receipt(keyed)
        assert 0 <= r["events_admissible"] <= r["events_in_window"] <= r["events_returned"], label

    @pytest.mark.parametrize(("label", "events"), COUNTER_CASES, ids=[c[0] for c in COUNTER_CASES])
    def test_admissible_equals_the_number_of_unique_tags(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        label: str,
        events: list[dict[str, Any]],
    ) -> None:
        run_discover(monkeypatch, events)
        r = discovery_receipt(keyed)
        assert r["events_admissible"] == len(set(r["event_tags"])), label

    def test_a_duplicated_event_is_counted_once_as_admissible(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """The provider repeating itself must not inflate the count or the tags."""
        one = event(EVENT_ID, hours_ahead=6.0)
        run_discover(monkeypatch, [one, dict(one), dict(one)])
        r = discovery_receipt(keyed)
        assert r["events_returned"] == 3
        assert r["events_in_window"] == 3
        assert r["events_admissible"] == 1
        assert r["event_tags"] == list(dict.fromkeys(r["event_tags"]))
        assert len(r["event_tags"]) == 1


class TestTheCountersLeakNothing:
    def test_no_event_id_participant_or_time_reaches_the_receipt(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        run_discover(
            monkeypatch,
            [
                event(EVENT_ID, hours_ahead=6.0, home_team="Leaky Home", away_team="Leaky Away"),
                event("evt-far-1", hours_ahead=48.0),
            ],
        )
        blob = json.dumps(discovery_receipt(keyed))
        for forbidden in (
            EVENT_ID,
            "evt-far-1",
            "Leaky Home",
            "Leaky Away",
            "commence_time",
            iso_z(NOW + timedelta(hours=6)),
        ):
            assert forbidden not in blob, f"{forbidden!r} leaked into the discovery receipt"

    def test_the_counters_are_integers_not_structures(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """A per-event breakdown would smuggle the schedule back in."""
        run_discover(monkeypatch, [event(EVENT_ID, hours_ahead=6.0)])
        r = discovery_receipt(keyed)
        for name in ("events_returned", "events_in_window", "events_admissible"):
            assert isinstance(r[name], int)


# ---------------------------------------------------------------------------
# E3 — the activation state, in five separate dimensions
# ---------------------------------------------------------------------------
def approved(monkeypatch: pytest.MonkeyPatch, receipts: Path) -> str:
    run_discover(monkeypatch, [event(EVENT_ID, hours_ahead=6.0)])
    return str(receipt_path(receipts, "discover"))


def attempt_core(monkeypatch: pytest.MonkeyPatch, receipts: Path, payload: Any) -> Any:
    discovery = approved(monkeypatch, receipts)
    install(
        monkeypatch,
        Recorder({"/odds": lambda _r: httpx.Response(200, json=payload, headers=PAID_HEADERS)}),
    )
    return run(*core_args(discovery_receipt=discovery))


def no_bookmaker() -> list[dict[str, Any]]:
    payload = odds_payload()
    payload[0]["bookmakers"] = []
    return payload


class TestPlanNoLongerClaimsTheActivationState:
    ARGS = ("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")

    def test_plan_does_not_print_prepared_not_executed(self, workspace: Path) -> None:
        """It plans; it does not know, and must not assert, what has been run."""
        result = run(*self.ARGS)
        assert "PREPARED_NOT_EXECUTED" not in result.stdout

    def test_plan_reports_its_own_scope_only(self, workspace: Path) -> None:
        payload = json.loads(run(*self.ARGS, "--json").stdout)
        assert payload["status"] == "PLAN_ONLY"

    def test_plan_points_at_the_state_command(self, workspace: Path) -> None:
        assert "status" in run(*self.ARGS).stdout


class TestTheStateCommand:
    def test_it_runs_with_no_receipts_at_all(self, workspace: Path) -> None:
        result = run("status", "--json")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["execution_state"] == "NO_NETWORK_ATTEMPTED"

    def test_with_no_receipts_the_paid_activation_is_still_unexecuted(
        self, workspace: Path
    ) -> None:
        payload = json.loads(run("status", "--json").stdout)
        assert payload["paid_activation_state"] == "PREPARED_NOT_EXECUTED"

    def test_after_a_core_attempt_it_is_no_longer_prepared_not_executed(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """The single hard requirement: that label cannot survive a real attempt."""
        attempt_core(monkeypatch, keyed, no_bookmaker())
        payload = json.loads(run("status", "--json").stdout)
        assert payload["paid_activation_state"] != "PREPARED_NOT_EXECUTED"
        assert payload["execution_state"] == "CORE_ATTEMPTED"

    def test_the_human_output_never_shows_the_stale_label_either(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        attempt_core(monkeypatch, keyed, no_bookmaker())
        assert "PREPARED_NOT_EXECUTED" not in run("status").stdout

    def test_the_five_dimensions_are_separate_fields(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        attempt_core(monkeypatch, keyed, no_bookmaker())
        payload = json.loads(run("status", "--json").stdout)
        for field in (
            "adapter_state",
            "execution_state",
            "connectivity_and_cost_proof",
            "bookmaker_coverage_observations",
            "mapping_freshness_proof",
        ):
            assert field in payload, f"{field} is not reported separately"

    def test_connectivity_and_cost_are_proved_but_mapping_is_not(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """Exactly the situation the two real calls left us in."""
        attempt_core(monkeypatch, keyed, no_bookmaker())
        payload = json.loads(run("status", "--json").stdout)
        assert payload["connectivity_and_cost_proof"] == "EXERCISED_CONFORMING"
        assert payload["mapping_freshness_proof"] == "NOT_OBTAINED_LIVE"

    def test_the_adapter_is_never_promoted_by_the_state_command(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        attempt_core(monkeypatch, keyed, odds_payload())
        payload = json.loads(run("status", "--json").stdout)
        assert payload["adapter_state"] == "IMPLEMENTED_UNVERIFIED"

    def test_it_reports_the_credits_actually_accounted(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        attempt_core(monkeypatch, keyed, no_bookmaker())
        payload = json.loads(run("status", "--json").stdout)
        assert payload["accounted_credits_total"] == 1


class TestCoverageObservationsKeepTheirScope:
    def test_each_observation_names_provider_bookmaker_sport_event_and_instant(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        attempt_core(monkeypatch, keyed, no_bookmaker())
        payload = json.loads(run("status", "--json").stdout)
        observations = payload["bookmaker_coverage_observations"]
        assert len(observations) == 1
        one = observations[0]
        for field in ("sport_key", "bookmaker", "event_tag", "recorded_at", "bookmaker_state"):
            assert one[field], f"{field} missing from the observation's scope"

    def test_no_observation_is_generalised_into_a_verdict(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """Absence on the events we looked at is not absence at the provider."""
        attempt_core(monkeypatch, keyed, no_bookmaker())
        payload = json.loads(run("status", "--json").stdout)
        blob = json.dumps(payload).lower()
        for forbidden in ("globalement", "durablement", "definitively", "permanently"):
            assert forbidden not in blob

    def test_the_observations_carry_no_clear_event_id(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        attempt_core(monkeypatch, keyed, no_bookmaker())
        assert EVENT_ID not in json.dumps(json.loads(run("status", "--json").stdout))

    def test_an_unverifiable_receipt_is_reported_not_counted(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """A tampered file must not become evidence, nor be silently dropped."""
        attempt_core(monkeypatch, keyed, no_bookmaker())
        path = receipt_path(keyed, "core")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["accounted_credits"] = 99
        path.write_text(json.dumps(payload), encoding="utf-8")

        state = json.loads(run("status", "--json").stdout)
        assert state["unverifiable_receipts"] == 1
        assert state["accounted_credits_total"] == 0


# ---------------------------------------------------------------------------
# E5 — a local path is not a URL
# ---------------------------------------------------------------------------
RECEIPT_LINK = re.compile(r"https?://[^\s)`]*\.activation-receipts", re.IGNORECASE)


class TestLocalReceiptPathsAreNeverLinks:
    @pytest.mark.parametrize(
        "document",
        [
            "docs/provider-activation.md",
            "docs/source-matrix.md",
            "docs/deployment.md",
            "docs/decisions.md",
            "docs/roadmap.md",
            "README.md",
            ".env.example",
        ],
    )
    def test_no_document_links_to_a_receipt(self, document: str) -> None:
        text = Path(document).read_text(encoding="utf-8")
        assert not RECEIPT_LINK.search(text), (
            f"{document} builds a URL into the gitignored receipt directory"
        )

    def test_the_harness_never_emits_such_a_url(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        attempt_core(monkeypatch, keyed, odds_payload())
        assert not RECEIPT_LINK.search(run("status").stdout)

    def test_the_runbook_says_they_are_local_and_unversioned(self) -> None:
        text = Path("docs/provider-activation.md").read_text(encoding="utf-8")
        assert "`.activation-receipts/" in text, "the path is not rendered as code"
        assert "gitignore" in text.lower()

    def test_the_reported_path_is_relative_and_local(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = attempt_core(monkeypatch, keyed, odds_payload())
        assert "http://" not in result.stdout
        assert "https://" not in result.stdout


# ---------------------------------------------------------------------------
# Schema version and compatibility with the receipts already on disk
# ---------------------------------------------------------------------------
class TestTheSchemaIsVersionedForTheNewContract:
    def test_new_receipts_declare_the_new_version(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        attempt_core(monkeypatch, keyed, odds_payload())
        for receipt in receipts_in(keyed):
            assert receipt["schema_version"] == 4
            # v4's reason to exist: the receipt names the protocol that would
            # judge it and the parser that produced it, both under the signature.
            assert receipt["qualification_protocol_version"] == 3
            assert receipt["provider_adapter_evidence_version"] == 1

    def test_the_reader_accepts_every_supported_version(self) -> None:
        from betmaxxing.providers.the_odds_api.activation import SUPPORTED_SCHEMA_VERSIONS

        assert set(SUPPORTED_SCHEMA_VERSIONS) == {2, 3, 4}

    def test_an_unknown_version_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from helpers_activation import tamper

        discovery = approved(monkeypatch, keyed)
        tamper(Path(discovery), schema_version=99)
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=discovery))
        assert result.exit_code != 0
        assert recorder.requests == []


class TestAnExistingV2ReceiptStaysUsableAndUntouched:
    """The receipts already on an operator's disk were signed in good faith.

    Their chaining fields — event tags, observed cost, mapped selections, parent —
    keep the exact meaning v3 gives them. Only `market_states` and its projections
    changed, and those are not chaining preconditions. So a valid v2 receipt is
    still accepted as authority, is never rewritten, and never re-signed.
    """

    def _as_v2(self, path: Path) -> dict[str, Any]:
        """Re-sign a synthetic receipt *as v2*, dropping the v3-only fields.

        Signed here rather than copied from disk: a test may not depend on a real
        operational receipt, and the signature must match this installation.
        """
        from betmaxxing.providers.the_odds_api import activation as A

        payload = json.loads(path.read_text(encoding="utf-8"))
        for field in (
            "events_returned",
            "events_in_window",
            "events_admissible",
            "bookmaker_state",
            "markets_not_evaluated",
        ):
            payload.pop(field, None)
        payload["schema_version"] = 2
        payload.pop("signature", None)
        payload["signature"] = A.sign_receipt(payload)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def test_a_valid_v2_discovery_still_authorises_core(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        discovery = approved(monkeypatch, keyed)
        self._as_v2(Path(discovery))
        recorder = Recorder(
            {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)}
        )
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=discovery))
        assert result.exit_code == 0, result.stdout
        assert len(recorder.requests) == 1

    def test_the_child_records_the_parent_schema_it_trusted(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        discovery = approved(monkeypatch, keyed)
        self._as_v2(Path(discovery))
        install(
            monkeypatch,
            Recorder(
                {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)}
            ),
        )
        run(*core_args(discovery_receipt=discovery))
        core = [r for r in receipts_in(keyed) if r["command"] == "core"][-1]
        assert core["parent_schema_version"] == 2

    def test_the_v2_file_is_not_rewritten_or_upgraded(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        discovery = approved(monkeypatch, keyed)
        before = self._as_v2(Path(discovery))
        install(
            monkeypatch,
            Recorder(
                {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)}
            ),
        )
        run(*core_args(discovery_receipt=discovery))
        after = json.loads(Path(discovery).read_text(encoding="utf-8"))
        assert after == before, "an existing v2 receipt was modified"
        assert after["schema_version"] == 2

    def test_a_tampered_v2_receipt_is_still_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from helpers_activation import tamper

        discovery = approved(monkeypatch, keyed)
        self._as_v2(Path(discovery))
        tamper(Path(discovery), observed_credits=7)
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=discovery))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_an_expired_v2_receipt_is_still_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation as A

        discovery = approved(monkeypatch, keyed)
        self._as_v2(Path(discovery))
        monkeypatch.setattr(A, "_clock", lambda: NOW + timedelta(days=3))
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=discovery))
        assert result.exit_code != 0
        assert recorder.requests == []


class TestEveryNewFieldIsCoveredByTheSignature:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("bookmaker_state", "OBSERVED"),
            ("markets_not_evaluated", []),
            ("market_states", {"h2h": "OBSERVED_MAPPED"}),
            ("parent_schema_version", 2),
        ],
    )
    def test_altering_it_invalidates_the_receipt(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        field: str,
        value: Any,
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation as A

        attempt_core(monkeypatch, keyed, no_bookmaker())
        # The `core` receipt specifically: with a frozen clock both receipts share
        # the same filename stamp, so `[-1]` would pick `discover` (which sorts
        # after `core`) and several of these fields would be no-ops on it.
        core = [r for r in receipts_in(keyed) if r["command"] == "core"][-1]
        receipt = {k: v for k, v in core.items() if not k.startswith("_")}
        assert A.verify_receipt(receipt)
        assert not A.verify_receipt({**receipt, field: value})

    @pytest.mark.parametrize(
        ("field", "value"),
        [("events_returned", 42), ("events_in_window", 7), ("events_admissible", 3)],
    )
    def test_altering_a_discovery_counter_invalidates_the_receipt(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        field: str,
        value: Any,
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation as A

        run_discover(monkeypatch, [event(EVENT_ID, hours_ahead=6.0)])
        receipt = {k: v for k, v in discovery_receipt(keyed).items() if not k.startswith("_")}
        assert A.verify_receipt(receipt)
        assert not A.verify_receipt({**receipt, field: value})
