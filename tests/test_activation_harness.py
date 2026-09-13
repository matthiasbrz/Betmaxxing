"""The activation harness: what each command may spend, and what it may touch.

The script this replaced had one boolean of consent and then called
``provider.collect([FOOTBALL, TENNIS], window)`` — a fan-out across every
configured sport key, followed by a per-event call for every football event it
found, bounded only by the *scan* budget. "I consent" is not a spending limit;
it is a mood. With a real key that script could quietly cost tens of credits,
and nobody could have said in advance how many.

The replacement is four commands, separately authorised, each bounded twice: by
what the program will actually do, and by what the published contract says that
should cost.

===========  ========  ===========================  ==========================
command      network   local bound                  estimated contractual cost
===========  ========  ===========================  ==========================
plan         no        no client is even built      0
discover     yes       2 requests, free endpoints   0
core         yes       1 request, 1 event, 1 market 1
additional   yes       1 request, 1 event, 5 markets 5
===========  ========  ===========================  ==========================

This file covers the mechanics: consent, scope, endpoints, requests and leaks.
Its siblings cover the cost model (``test_activation_cost_model.py``), the signed
receipt chain (``test_activation_receipts.py``) and the terminal outcomes
(``test_activation_outcomes.py``).

Every payload here comes from an ``httpx.MockTransport``. The suite also installs
a session-wide socket guard (``tests/conftest.py``), so a command that tried to
reach a provider would raise rather than connect.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from helpers_activation import (
    BOOKMAKER,
    EVENT_ID,
    FAKE_KEY,
    NOW,
    OTHER_EVENT_ID,
    SECOND_EVENT_ID,
    SPORT,
    Recorder,
    additional_args,
    cli,
    core_args,
    discover_args,
    event_odds_payload,
    events_payload,
    install,
    iso_z,
    odds_payload,
    receipt_path,
    receipts_in,
    run,
    runner,
    spend_the_second_core,
    sports_payload,
)

FREE_HEADERS = {"x-requests-last": "0", "x-requests-remaining": "487", "x-requests-used": "13"}
PAID_HEADERS = {"x-requests-last": "1", "x-requests-remaining": "486", "x-requests-used": "14"}


def free_routes(**kwargs: Any) -> dict[str, Any]:
    return {
        "/sports/": lambda _r: httpx.Response(
            200, json=events_payload(**kwargs), headers=FREE_HEADERS
        ),
        "/sports": lambda _r: httpx.Response(200, json=sports_payload(), headers=FREE_HEADERS),
    }


def approved(monkeypatch: pytest.MonkeyPatch, receipts: Path) -> str:
    """Run a clean discovery and return the path of its receipt."""
    install(monkeypatch, Recorder(free_routes()))
    result = run(*discover_args())
    assert result.exit_code == 0, result.stdout
    return str(receipt_path(receipts, "discover"))


def verified_core(monkeypatch: pytest.MonkeyPatch, receipts: Path) -> str:
    """Run discover then core cleanly, and return the core receipt's path."""
    discovery = approved(monkeypatch, receipts)
    install(
        monkeypatch,
        Recorder(
            {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)}
        ),
    )
    result = run(*core_args(discovery_receipt=discovery))
    assert result.exit_code == 0, result.stdout
    return str(receipt_path(receipts, "core"))


def verified_core_for_additional(monkeypatch: pytest.MonkeyPatch, receipts: Path) -> str:
    """Walk the register as far as its `additional`, and return the parent it names.

    Two `core` on `soccer_epl`, then the five-market step on the second of them: the
    order is the register's, and the guard refuses any other.
    """
    discovery = approved(monkeypatch, receipts)
    install(
        monkeypatch,
        Recorder(
            {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)}
        ),
    )
    assert run(*core_args(discovery_receipt=discovery)).exit_code == 0
    return spend_the_second_core(monkeypatch, receipts, discovery, headers=PAID_HEADERS)


# ---------------------------------------------------------------------------
# plan — no key, no client, no network, no credit
# ---------------------------------------------------------------------------
class TestPlan:
    ARGS = ("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")

    def test_it_runs_without_a_key(self, workspace: Path) -> None:
        result = run(*self.ARGS)
        assert result.exit_code == 0, result.stdout

    def test_it_never_reads_the_key(self, keyed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even with a key present, `plan` must not touch it."""
        from betmaxxing import config

        reads: list[str] = []
        original = config.Settings.resolved_the_odds_api_key.fget  # type: ignore[attr-defined]

        def spy(self: Any) -> str:
            reads.append("read")
            return original(self)

        monkeypatch.setattr(
            config.Settings, "resolved_the_odds_api_key", property(spy), raising=False
        )
        result = run(*self.ARGS)
        assert result.exit_code == 0, result.stdout
        assert reads == [], "plan read the API key"

    def test_it_builds_no_http_client(self, keyed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        built: list[str] = []
        original = httpx.Client.__init__

        def spy(self: Any, *args: Any, **kwargs: Any) -> None:
            built.append("client")
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.Client, "__init__", spy)
        run(*self.ARGS)
        assert built == [], "plan constructed an HTTP client"

    def test_it_makes_no_request(self, keyed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = Recorder()
        install(monkeypatch, recorder)
        run(*self.ARGS)
        assert recorder.requests == []

    def test_it_reports_plan_only(self, workspace: Path) -> None:
        """It used to report `PREPARED_NOT_EXECUTED`, which became false.

        Two real `core` calls were made. A label meaning "nothing has been
        executed", printed by a command that has no idea what has been executed,
        is a claim it cannot support. `plan` now reports its own scope and defers
        the activation's actual state to `status` (E3).
        """
        assert "PLAN_ONLY" in run(*self.ARGS).stdout
        assert "PREPARED_NOT_EXECUTED" not in run(*self.ARGS).stdout

    def test_it_states_the_per_step_and_total_ceilings(self, workspace: Path) -> None:
        plan = json.loads(run(*self.ARGS, "--json").stdout)
        assert plan["status"] == "PLAN_ONLY"
        assert plan["total_max_credits"] == 6
        by_step = {step["command"]: step for step in plan["steps"]}
        assert by_step["plan"]["max_credits"] == 0
        assert by_step["discover"]["max_credits"] == 0
        assert by_step["core"]["max_credits"] == 1
        assert by_step["additional"]["max_credits"] == 5

    def test_it_states_the_effective_regional_units(self, workspace: Path) -> None:
        assert json.loads(run(*self.ARGS, "--json").stdout)["effective_region_units"] == 1

    def test_it_lists_the_exact_markets_of_each_paid_step(self, workspace: Path) -> None:
        by_step = {s["command"]: s for s in json.loads(run(*self.ARGS, "--json").stdout)["steps"]}
        assert by_step["core"]["markets"] == ["h2h"]
        assert by_step["additional"]["markets"] == [
            "draw_no_bet",
            "double_chance",
            "h2h_3_way_h1",
            "totals_h1",
            "double_chance_h1",
        ]

    def test_it_states_the_local_bound_of_each_step(self, workspace: Path) -> None:
        """Requests, events, bookmakers and markets — what the program enforces."""
        by_step = {s["command"]: s for s in json.loads(run(*self.ARGS, "--json").stdout)["steps"]}
        assert by_step["core"]["local_bound"]["max_requests"] == 1
        assert by_step["additional"]["local_bound"]["max_requests"] == 1
        assert by_step["discover"]["local_bound"]["max_requests"] == 2

    def test_it_prints_no_key_in_the_planned_endpoints(self, keyed: Path) -> None:
        result = run(*self.ARGS, "--json")
        assert FAKE_KEY not in result.stdout
        assert "apiKey" not in result.stdout

    def test_it_is_deterministic(self, workspace: Path) -> None:
        first = json.loads(run(*self.ARGS, "--json").stdout)
        second = json.loads(run(*self.ARGS, "--json").stdout)
        for plan in (first, second):
            plan.pop("generated_at", None)
        assert first == second

    def test_a_wrong_total_ceiling_is_refused(self, workspace: Path) -> None:
        result = run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "7")
        assert result.exit_code != 0

    def test_it_writes_no_receipt(self, workspace: Path) -> None:
        run(*self.ARGS)
        assert receipts_in(workspace) == []

    def test_the_runbook_announces_the_status_the_command_actually_prints(
        self, workspace: Path
    ) -> None:
        """The operating document must not name a status the command no longer emits.

        `plan` reported `PREPARED_NOT_EXECUTED` until E3 separated the two: a label
        meaning « nothing has been executed », printed by a command that has no idea
        what has been executed, is a claim it cannot support. The code moved to
        `PLAN_ONLY`; the runbook's step 1 kept the old word, so an operator following
        the document would wait for a status the program never prints — and would have
        no way to tell a stale document from a broken command.

        The document is read from this file's own location rather than the working
        directory: a guard that only holds when pytest happens to run from the
        repository root is a guard that stops holding without anyone noticing.

        The bounds are checked before they are used, and that is the other half of
        the same idea. Splitting on a heading that has moved returns the rest of the
        file rather than an error, so a renamed step 2 would silently widen this
        section from a paragraph to the remainder of the document — and the two
        assertions below would still hold, on text that has nothing to do with step 1.
        A guard whose scope can quietly grow is a guard that stops guarding. Each
        bound must therefore appear exactly once, and in the right order.
        """
        runbook = Path(__file__).resolve().parents[1] / "docs" / "provider-activation.md"
        text = runbook.read_text(encoding="utf-8")

        debut = "### 1. `plan`"
        fin = "### 2. `discover`"
        assert text.count(debut) == 1, (
            "la borne initiale de l'étape plan doit apparaître exactement une fois"
        )
        assert text.count(fin) == 1, (
            "la borne finale de l'étape plan doit apparaître exactement une fois"
        )
        debut_index = text.index(debut) + len(debut)
        fin_index = text.index(fin)
        assert debut_index < fin_index, "les bornes de l'étape plan sont inversées"
        step = text[debut_index:fin_index]

        published = json.loads(run(*self.ARGS, "--json").stdout)["status"]
        assert published == "PLAN_ONLY", published

        assert f"`{published}`" in step, "l'étape 1 n'annonce pas le statut réellement publié"
        assert "PREPARED_NOT_EXECUTED" not in step, "l'étape 1 annonce encore l'ancien statut"


# ---------------------------------------------------------------------------
# Network consent, keys and exact acknowledgement
# ---------------------------------------------------------------------------
class TestConsentGates:
    def _args(self, command: str, receipt: str) -> tuple[str, ...]:
        if command == "discover":
            return discover_args()
        if command == "core":
            return core_args(discovery_receipt=receipt)
        return additional_args(core_receipt=receipt)

    @pytest.mark.parametrize("command", ["discover", "core", "additional"])
    def test_every_networked_command_refuses_without_allow_network(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, command: str, frozen_clock: None
    ) -> None:
        receipt = "" if command == "discover" else self._receipt_for(monkeypatch, keyed, command)
        recorder = Recorder()
        install(monkeypatch, recorder)
        args = [a for a in self._args(command, receipt) if a != "--allow-network"]
        result = run(*args)
        assert result.exit_code != 0
        assert recorder.requests == []

    @pytest.mark.parametrize("command", ["discover", "core", "additional"])
    def test_every_networked_command_refuses_without_a_key(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, command: str, frozen_clock: None
    ) -> None:
        receipt = "" if command == "discover" else self._receipt_for(monkeypatch, keyed, command)
        monkeypatch.delenv("BETMAXXING_THE_ODDS_API_KEY", raising=False)
        from betmaxxing.config import reset_settings_cache

        reset_settings_cache()

        recorder = Recorder()
        install(monkeypatch, recorder)
        result = run(*self._args(command, receipt))
        assert result.exit_code != 0
        assert recorder.requests == []

    def _receipt_for(self, monkeypatch: pytest.MonkeyPatch, keyed: Path, command: str) -> str:
        return (
            approved(monkeypatch, keyed)
            if command == "core"
            else verified_core_for_additional(monkeypatch, keyed)
        )

    @pytest.mark.parametrize(
        ("max_credits", "ack"),
        [("1", "2"), ("2", "1"), ("2", "2"), ("0", "0")],
        ids=["ack-too-high", "ack-too-low", "ceiling-raised", "ceiling-zeroed"],
    )
    def test_a_mismatched_core_ceiling_fails_before_the_network(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        max_credits: str,
        ack: str,
    ) -> None:
        discovery = approved(monkeypatch, keyed)
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(
            *core_args(discovery_receipt=discovery, max_credits=max_credits, acknowledge=ack)
        )
        assert result.exit_code != 0
        assert recorder.requests == [], "a request was made despite an invalid ceiling"

    @pytest.mark.parametrize(
        ("max_credits", "ack"),
        [("5", "4"), ("4", "5"), ("6", "6"), ("1", "1")],
        ids=["ack-too-low", "ceiling-lowered", "ceiling-raised", "ceiling-one"],
    )
    def test_a_mismatched_additional_ceiling_fails_before_the_network(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        max_credits: str,
        ack: str,
    ) -> None:
        core = verified_core_for_additional(monkeypatch, keyed)
        recorder = Recorder({"/events/": event_odds_payload()})
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=core, max_credits=max_credits, acknowledge=ack))
        assert result.exit_code != 0
        assert recorder.requests == []

    @pytest.mark.parametrize("command", ["core", "additional"])
    def test_the_acknowledgement_is_mandatory(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None, command: str
    ) -> None:
        receipt = self._receipt_for(monkeypatch, keyed, command)
        recorder = Recorder({"/odds": odds_payload(), "/events/": event_odds_payload()})
        install(monkeypatch, recorder)
        args = (
            core_args(discovery_receipt=receipt, acknowledge=None)
            if command == "core"
            else additional_args(core_receipt=receipt, acknowledge=None)
        )
        result = run(*args)
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_the_key_cannot_be_passed_as_an_argument(self, workspace: Path) -> None:
        """There is no `--api-key`, by construction.

        An argument lands in shell history, in `ps`, and in CI logs. Click emits
        the usage error on **stderr**, so this reads `result.output` (both
        streams) rather than `result.stdout`.
        """
        result = run("discover", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--api-key", FAKE_KEY)
        assert result.exit_code != 0
        combined = result.output.lower()
        assert "no such option" in combined or "unexpected" in combined


class TestScopeIsSingular:
    def test_two_sports_are_refused_by_discover(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(free_routes())
        install(monkeypatch, recorder)
        result = run(*discover_args(sport=f"{SPORT},tennis_atp_aus_open_singles"))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_two_bookmakers_are_refused_by_discover(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(free_routes())
        install(monkeypatch, recorder)
        result = run(*discover_args(bookmaker="winamax_fr,unibet"))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_two_events_are_refused_by_core(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        discovery = approved(monkeypatch, keyed)
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(
            *core_args(discovery_receipt=discovery, event_id=f"{EVENT_ID},{OTHER_EVENT_ID}")
        )
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_window_over_24_hours_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(free_routes())
        install(monkeypatch, recorder)
        result = run(*discover_args(extra=("--window-hours", "48")))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_plan_also_refuses_a_window_over_24_hours(self, workspace: Path) -> None:
        result = run(
            "plan",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--window-hours",
            "48",
            "--max-credits",
            "6",
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# discover — free endpoints only
# ---------------------------------------------------------------------------
class TestDiscover:
    def _run(self, monkeypatch: pytest.MonkeyPatch, recorder: Recorder, *extra: str) -> Any:
        install(monkeypatch, recorder)
        return run(*discover_args(extra=extra))

    def test_it_calls_exactly_the_two_free_endpoints(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(free_routes())
        result = self._run(monkeypatch, recorder)
        assert result.exit_code == 0, result.stdout
        assert len(recorder.paths) == 2
        assert recorder.paths[0].endswith("/v4/sports")
        assert recorder.paths[1].endswith(f"/v4/sports/{SPORT}/events")

    def test_it_never_touches_a_paid_endpoint(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(free_routes())
        self._run(monkeypatch, recorder)
        assert not any("/odds" in path for path in recorder.paths)
        assert not any("historical" in path for path in recorder.paths)

    def test_it_spends_nothing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.config import get_settings
        from betmaxxing.providers.budget import ProviderBudgetLedger

        self._run(monkeypatch, Recorder(free_routes()))
        assert ProviderBudgetLedger(get_settings()).spent_today("the_odds_api", NOW) == 0

    def test_an_inactive_sport_stops_before_the_events_call(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(
            {
                "/sports": lambda _r: httpx.Response(
                    200, json=sports_payload(active=False), headers=FREE_HEADERS
                )
            }
        )
        result = self._run(monkeypatch, recorder)
        assert len(recorder.paths) == 1
        assert result.exit_code != 0
        assert "COVERAGE_MISSING" in result.stdout

    def test_no_event_in_the_window_is_coverage_missing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(free_routes(hours_ahead=48.0))
        result = self._run(monkeypatch, recorder)
        assert "COVERAGE_MISSING" in result.stdout
        assert len(recorder.paths) == 2, "it widened the search after finding nothing"

    def test_an_event_already_started_is_excluded(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = self._run(monkeypatch, Recorder(free_routes(hours_ahead=-1.0)))
        assert "COVERAGE_MISSING" in result.stdout

    def test_it_selects_no_event_automatically(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        two = [
            *events_payload(),
            {
                "id": OTHER_EVENT_ID,
                "sport_key": SPORT,
                "commence_time": iso_z(NOW.replace(hour=20)),
                "home_team": "A",
                "away_team": "B",
            },
        ]
        recorder = Recorder(
            {
                "/sports/": lambda _r: httpx.Response(200, json=two, headers=FREE_HEADERS),
                "/sports": lambda _r: httpx.Response(
                    200, json=sports_payload(), headers=FREE_HEADERS
                ),
            }
        )
        payload = json.loads(self._run(monkeypatch, recorder, "--json").stdout)
        assert payload["status"] == "DISCOVERY_VERIFIED"
        # Every admissible event is listed and none is chosen — counted against the
        # listing itself, so the shared payload can grow without the claim weakening.
        assert len(payload["events"]) == len(two)
        assert "selected_event_id" not in payload

    def test_a_nonzero_reported_cost_is_a_mismatch(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """These endpoints are documented free; a charge means the contract moved."""
        recorder = Recorder(
            {
                "/sports": lambda _r: httpx.Response(
                    200, json=sports_payload(), headers={"x-requests-last": "3"}
                )
            }
        )
        result = self._run(monkeypatch, recorder)
        assert result.exit_code != 0
        assert "COST_MISMATCH" in result.stdout

    def test_it_does_not_retry(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/sports": lambda _r: httpx.Response(503, json={})})
        result = self._run(monkeypatch, recorder)
        assert len(recorder.paths) == 1, f"{len(recorder.paths)} attempts — retries are on"
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# core — one event, one bookmaker, one market, one credit
# ---------------------------------------------------------------------------
class TestCore:
    def _run(self, monkeypatch: pytest.MonkeyPatch, keyed: Path, routes: Any, *extra: str) -> Any:
        discovery = approved(monkeypatch, keyed)
        recorder = Recorder(routes)
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=discovery, extra=extra))
        self.recorder = recorder
        return result

    def test_it_makes_exactly_one_request(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = self._run(
            monkeypatch,
            keyed,
            {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)},
        )
        assert result.exit_code == 0, result.stdout
        assert len(self.recorder.requests) == 1

    def test_it_uses_the_grouped_endpoint_filtered_by_event(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._run(
            monkeypatch,
            keyed,
            {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)},
        )
        assert self.recorder.paths[0].endswith(f"/v4/sports/{SPORT}/odds")
        assert self.recorder.query(0)["eventIds"] == [EVENT_ID]

    def test_it_requests_exactly_one_market_and_one_bookmaker(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._run(
            monkeypatch,
            keyed,
            {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)},
        )
        query = self.recorder.query(0)
        assert query["markets"] == ["h2h"]
        assert query["bookmakers"] == [BOOKMAKER]

    def test_it_never_calls_the_general_collector(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import TheOddsApiProvider

        discovery = approved(monkeypatch, keyed)
        calls: list[str] = []
        monkeypatch.setattr(
            TheOddsApiProvider,
            "collect",
            lambda *a, **k: calls.append("collect") or [],  # type: ignore[func-returns-value]
        )
        install(
            monkeypatch,
            Recorder(
                {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)}
            ),
        )
        run(*core_args(discovery_receipt=discovery))
        assert calls == [], "the activation path fanned out through collect()"

    def test_it_does_not_retry(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._run(monkeypatch, keyed, {"/odds": lambda _r: httpx.Response(503, json={})})
        assert len(self.recorder.requests) == 1

    def test_an_empty_response_is_coverage_missing_not_a_failure(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = self._run(
            monkeypatch,
            keyed,
            {"/odds": lambda _r: httpx.Response(200, json=[], headers=PAID_HEADERS)},
        )
        assert "COVERAGE_MISSING" in result.stdout
        assert len(self.recorder.requests) == 1, "it called again after an empty response"

    def test_a_missing_bookmaker_is_coverage_missing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        payload = odds_payload()
        payload[0]["bookmakers"] = []
        result = self._run(
            monkeypatch,
            keyed,
            {"/odds": lambda _r: httpx.Response(200, json=payload, headers=PAID_HEADERS)},
        )
        assert "COVERAGE_MISSING" in result.stdout

    def test_a_reported_cost_above_the_ceiling_is_a_mismatch(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = self._run(
            monkeypatch,
            keyed,
            {
                "/odds": lambda _r: httpx.Response(
                    200, json=odds_payload(), headers={"x-requests-last": "4"}
                )
            },
        )
        assert "COST_MISMATCH" in result.stdout
        assert result.exit_code != 0

    def test_an_event_outside_the_window_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        payload = odds_payload()
        payload[0]["commence_time"] = iso_z(NOW.replace(day=6))
        result = self._run(
            monkeypatch,
            keyed,
            {"/odds": lambda _r: httpx.Response(200, json=payload, headers=PAID_HEADERS)},
        )
        assert result.exit_code != 0

    def test_it_writes_a_receipt_marked_core_live_verified(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._run(
            monkeypatch,
            keyed,
            {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID_HEADERS)},
        )
        core = [r for r in receipts_in(keyed) if r["command"] == "core"]
        assert core and core[-1]["status"] == "CORE_LIVE_VERIFIED"

    def test_a_malformed_payload_is_a_schema_mismatch(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = self._run(
            monkeypatch,
            keyed,
            {
                "/odds": lambda _r: httpx.Response(
                    200, json=[{"unexpected": True}], headers=PAID_HEADERS
                )
            },
        )
        assert "SCHEMA_MISMATCH" in result.stdout


# ---------------------------------------------------------------------------
# additional — same event, five markets, five credits, separate authorisation
# ---------------------------------------------------------------------------
class TestAdditional:
    def _run(self, monkeypatch: pytest.MonkeyPatch, keyed: Path, routes: Any, *extra: str) -> Any:
        core = verified_core_for_additional(monkeypatch, keyed)
        recorder = Recorder(routes)
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=core, extra=extra))
        self.recorder = recorder
        return result

    @staticmethod
    def _ok(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event_odds_payload(), headers={"x-requests-last": "5"})

    def test_it_makes_exactly_one_request_to_the_event_endpoint(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = self._run(monkeypatch, keyed, {"/events/": self._ok})
        assert result.exit_code == 0, result.stdout
        assert len(self.recorder.requests) == 1
        assert self.recorder.paths[0].endswith(f"/v4/sports/{SPORT}/events/{SECOND_EVENT_ID}/odds")

    def test_it_requests_exactly_the_five_markets(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._run(monkeypatch, keyed, {"/events/": self._ok})
        assert self.recorder.query(0)["markets"][0].split(",") == [
            "draw_no_bet",
            "double_chance",
            "h2h_3_way_h1",
            "totals_h1",
            "double_chance_h1",
        ]

    def test_it_reads_market_level_timestamps(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        result = self._run(monkeypatch, keyed, {"/events/": self._ok}, "--json")
        payload = json.loads(result.stdout)
        assert payload["status"] == "ADDITIONAL_LIVE_VERIFIED"
        assert len(set(payload["freshness"].values())) == 5

    def test_a_partially_missing_market_is_reported_not_compensated(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        def partial(_r: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=event_odds_payload(markets=("draw_no_bet", "double_chance")),
                headers={"x-requests-last": "5"},
            )

        result = self._run(monkeypatch, keyed, {"/events/": partial}, "--json")
        payload = json.loads(result.stdout)
        assert set(payload["markets_requested"]) > set(payload["markets_observed"])
        assert payload["markets_observed"] == ["draw_no_bet", "double_chance"]

    def test_it_does_not_retry(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._run(monkeypatch, keyed, {"/events/": lambda _r: httpx.Response(503, json={})})
        assert len(self.recorder.requests) == 1

    def test_it_never_touches_another_sport(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._run(monkeypatch, keyed, {"/events/": self._ok})
        assert all("tennis" not in path for path in self.recorder.paths)


# ---------------------------------------------------------------------------
# Secrets and raw payloads
# ---------------------------------------------------------------------------
class TestNoLeak:
    @pytest.mark.parametrize(
        "status", [503, 500, 401, 403, 404, 422, 429], ids=lambda s: f"http-{s}"
    )
    def test_the_key_never_appears_in_an_error_path(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None, status: int
    ) -> None:
        install(
            monkeypatch,
            Recorder({"/sports": lambda _r: httpx.Response(status, json={"m": "x"})}),
        )
        result = run(*discover_args())
        assert FAKE_KEY not in result.output
        assert FAKE_KEY not in str(result.exception or "")

    def test_the_key_never_appears_on_a_transport_failure(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"failed connecting with {FAKE_KEY}", request=request)

        install(monkeypatch, Recorder({"/sports": boom}))
        result = run(*discover_args())
        assert FAKE_KEY not in result.output

    def test_no_receipt_carries_the_key(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        verified_core(monkeypatch, keyed)
        for receipt in keyed.glob("*.json"):
            text = receipt.read_text(encoding="utf-8")
            assert FAKE_KEY not in text
            assert "apiKey" not in text

    def test_no_receipt_carries_the_event_id_in_clear(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        verified_core(monkeypatch, keyed)
        for receipt in receipts_in(keyed):
            assert EVENT_ID not in json.dumps(receipt)
            assert receipt.get("event_tag") or receipt.get("event_tags")

    def test_no_receipt_carries_odds_or_participants(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        core = verified_core(monkeypatch, keyed)
        install(
            monkeypatch,
            Recorder(
                {
                    "/events/": lambda _r: httpx.Response(
                        200, json=event_odds_payload(), headers={"x-requests-last": "5"}
                    )
                }
            ),
        )
        run(*additional_args(core_receipt=core))

        for receipt in receipts_in(keyed):
            text = json.dumps(receipt)
            for forbidden in ("Olympique", "Rennais", "1.63", "4.20", "outcomes", "price"):
                assert forbidden not in text, f"{forbidden!r} was persisted in {receipt['command']}"

    def test_receipts_are_gitignored(self) -> None:
        from betmaxxing.providers.the_odds_api.activation import DEFAULT_RECEIPT_DIR

        ignore = Path(".gitignore").read_text(encoding="utf-8")
        assert DEFAULT_RECEIPT_DIR.split("/")[0] in ignore


class TestNoChaining:
    def test_no_command_invokes_another(self) -> None:
        """Each step is a separate human decision, so none may call the next."""
        import inspect

        from betmaxxing.providers.the_odds_api import activation

        source = inspect.getsource(activation)
        for caller, callee in [("def core", "run_additional"), ("def discover", "run_core")]:
            assert f"{callee}(" not in source.split(caller)[-1].split("\ndef ")[0]

    def test_the_help_advertises_no_run_all(self) -> None:
        result = runner.invoke(cli(), ["--help"])
        for forbidden in ("all", "full", "auto", "chain"):
            assert f" {forbidden} " not in result.output.lower()


class TestTheSuiteCannotReachAProvider:
    """The socket guard installed in `tests/conftest.py`, verified rather than assumed.

    Every provider test injects a fake transport, which is a convention. A
    convention is one forgotten fixture away from a real, billed request to
    `api.the-odds-api.com` from a machine that has a real key in its
    environment — during the very tranche preparing a controlled activation.
    """

    def test_an_outbound_connection_is_refused(self) -> None:
        import socket

        from conftest import OutboundNetworkBlocked

        with (
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
            pytest.raises(OutboundNetworkBlocked),
        ):
            sock.connect(("api.the-odds-api.com", 443))

    def test_the_loopback_stays_reachable(self) -> None:
        """PostgreSQL runs there; blocking it would disable the concurrency suite."""
        import socket

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.connect(listener.getsockname())
        finally:
            listener.close()

    def test_a_unix_socket_stays_reachable(self, tmp_path: Path) -> None:
        """The test cluster is reached through `/tmp`; a domain socket is a file."""
        import socket

        path = str(tmp_path / "s")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen(1)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(path)
        finally:
            listener.close()
