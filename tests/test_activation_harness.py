"""The activation harness: what each command may spend, and what it may touch.

The previous script had one boolean of consent and then called
``provider.collect([FOOTBALL, TENNIS], window)`` — a fan-out across every
configured sport key, followed by a per-event call for every football event it
found, bounded only by the *scan* budget. "I consent" is not a spending limit;
it is a mood. With a real key that script could quietly cost tens of credits,
and nobody could have said in advance how many.

The replacement is four commands with hard, separately-authorised ceilings:

===========  ========  =========  =====================================
command      network   credits    endpoints
===========  ========  =========  =====================================
plan         no        0          none — it does not even build a client
discover     yes       0          /v4/sports, /v4/sports/{sport}/events
core         yes       1          /v4/sports/{sport}/odds?eventIds=…
additional   yes       5          /v4/sports/{sport}/events/{id}/odds
===========  ========  =========  =====================================

Every test here runs against a fake transport or no transport at all. The suite
also installs a global socket guard (see ``tests/conftest.py``), so a command
that tried to reach a provider would raise rather than connect.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from typer.testing import CliRunner

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
#: Deliberately recognisable, and deliberately not a real key shape in use.
FAKE_KEY = "FAKEKEY0000deadbeef0000FAKEKEY00"
SPORT = "soccer_france_ligue_one"
BOOKMAKER = "winamax_fr"
EVENT_ID = "evt-fixture-0001"

runner = CliRunner()


def cli() -> Any:
    """Call-time import: the harness is introduced by this tranche."""
    from betmaxxing.providers.the_odds_api.activation import app

    return app


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_settings: Any) -> Path:
    """A throwaway receipt directory and a database, with no key configured."""
    monkeypatch.setenv("BETMAXXING_MODE", "paper")
    monkeypatch.setenv("BETMAXXING_DATABASE_URL", db_settings.database_url)
    monkeypatch.setenv("BETMAXXING_NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("BETMAXXING_ACTIVATION_RECEIPTS", str(tmp_path / "receipts"))
    monkeypatch.delenv("BETMAXXING_THE_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("BETMAXXING_ODDS_API_KEY", raising=False)
    from betmaxxing.config import reset_settings_cache

    reset_settings_cache()
    return tmp_path / "receipts"


@pytest.fixture
def keyed(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("BETMAXXING_THE_ODDS_API_KEY", FAKE_KEY)
    from betmaxxing.config import reset_settings_cache

    reset_settings_cache()
    return workspace


class Recorder:
    """Fake transport recording every request the harness attempts."""

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.routes = routes or {}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = urlparse(str(request.url)).path
        for suffix, reply in self.routes.items():
            if path.endswith(suffix) or suffix in path:
                if callable(reply):
                    return reply(request)
                return httpx.Response(200, json=reply, headers={"x-requests-last": "0"})
        return httpx.Response(200, json=[], headers={"x-requests-last": "0"})

    @property
    def paths(self) -> list[str]:
        return [urlparse(str(r.url)).path for r in self.requests]

    def query(self, index: int) -> dict[str, list[str]]:
        return parse_qs(urlparse(str(self.requests[index].url)).query)


def install(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    """Inject the fake transport into the harness's client factory."""
    from betmaxxing.providers.the_odds_api import activation

    monkeypatch.setattr(activation, "_TRANSPORT_FOR_TESTS", httpx.MockTransport(recorder.handler))


def run(*args: str) -> Any:
    return runner.invoke(cli(), list(args))


# ---------------------------------------------------------------------------
# plan — no key, no client, no network, no credit
# ---------------------------------------------------------------------------
class TestPlan:
    def test_it_runs_without_a_key(self, workspace: Path) -> None:
        result = run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")
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
        result = run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")
        assert result.exit_code == 0, result.stdout
        assert reads == [], "plan read the API key"

    def test_it_builds_no_http_client(self, keyed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        built: list[str] = []
        original = httpx.Client.__init__

        def spy(self: Any, *args: Any, **kwargs: Any) -> None:
            built.append("client")
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.Client, "__init__", spy)
        run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")
        assert built == [], "plan constructed an HTTP client"

    def test_it_makes_no_request(self, keyed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = Recorder()
        install(monkeypatch, recorder)
        run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")
        assert recorder.requests == []

    def test_it_reports_prepared_not_executed(self, workspace: Path) -> None:
        result = run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")
        assert "PREPARED_NOT_EXECUTED" in result.stdout

    def test_it_states_the_per_step_and_total_ceilings(self, workspace: Path) -> None:
        result = run(
            "plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6", "--json"
        )
        plan = json.loads(result.stdout)
        assert plan["status"] == "PREPARED_NOT_EXECUTED"
        assert plan["total_max_credits"] == 6
        by_step = {step["command"]: step for step in plan["steps"]}
        assert by_step["plan"]["max_credits"] == 0
        assert by_step["discover"]["max_credits"] == 0
        assert by_step["core"]["max_credits"] == 1
        assert by_step["additional"]["max_credits"] == 5

    def test_it_states_the_effective_regional_units(self, workspace: Path) -> None:
        result = run(
            "plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6", "--json"
        )
        plan = json.loads(result.stdout)
        assert plan["effective_region_units"] == 1

    def test_it_lists_the_exact_markets_of_each_paid_step(self, workspace: Path) -> None:
        result = run(
            "plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6", "--json"
        )
        by_step = {s["command"]: s for s in json.loads(result.stdout)["steps"]}
        assert by_step["core"]["markets"] == ["h2h"]
        assert by_step["additional"]["markets"] == [
            "draw_no_bet",
            "double_chance",
            "h2h_3_way_h1",
            "totals_h1",
            "double_chance_h1",
        ]

    def test_it_prints_no_key_in_the_planned_endpoints(self, keyed: Path) -> None:
        result = run(
            "plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6", "--json"
        )
        assert FAKE_KEY not in result.stdout
        assert "apiKey" not in result.stdout

    def test_it_is_deterministic(self, workspace: Path) -> None:
        args = ("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6", "--json")
        first = json.loads(run(*args).stdout)
        second = json.loads(run(*args).stdout)
        for plan in (first, second):
            plan.pop("generated_at", None)
        assert first == second

    def test_a_wrong_total_ceiling_is_refused(self, workspace: Path) -> None:
        result = run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "7")
        assert result.exit_code != 0

    def test_it_writes_no_receipt(self, workspace: Path) -> None:
        run("plan", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--max-credits", "6")
        assert not workspace.exists() or list(workspace.glob("*.json")) == []


# ---------------------------------------------------------------------------
# Network consent, keys and exact acknowledgement
# ---------------------------------------------------------------------------
class TestConsentGates:
    @pytest.mark.parametrize("command", ["discover", "core", "additional"])
    def test_every_networked_command_refuses_without_allow_network(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        recorder = Recorder()
        install(monkeypatch, recorder)
        args = ["--sport", SPORT, "--bookmaker", BOOKMAKER]
        if command != "discover":
            ceiling = "1" if command == "core" else "5"
            args += [
                "--event-id",
                EVENT_ID,
                "--max-credits",
                ceiling,
                "--acknowledge-credits",
                ceiling,
            ]
        result = run(command, *args)
        assert result.exit_code != 0
        assert recorder.requests == []

    @pytest.mark.parametrize("command", ["discover", "core", "additional"])
    def test_every_networked_command_refuses_without_a_key(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        recorder = Recorder()
        install(monkeypatch, recorder)
        args = ["--sport", SPORT, "--bookmaker", BOOKMAKER, "--allow-network"]
        if command != "discover":
            ceiling = "1" if command == "core" else "5"
            args += [
                "--event-id",
                EVENT_ID,
                "--max-credits",
                ceiling,
                "--acknowledge-credits",
                ceiling,
            ]
        result = run(command, *args)
        assert result.exit_code != 0
        assert recorder.requests == []

    @pytest.mark.parametrize(
        ("command", "max_credits", "ack"),
        [
            ("core", "1", "2"),
            ("core", "2", "1"),
            ("core", "2", "2"),
            ("core", "0", "0"),
            ("additional", "5", "4"),
            ("additional", "4", "5"),
            ("additional", "6", "6"),
            ("additional", "1", "1"),
        ],
    )
    def test_a_mismatched_or_wrong_ceiling_fails_before_the_network(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        command: str,
        max_credits: str,
        ack: str,
    ) -> None:
        recorder = Recorder()
        install(monkeypatch, recorder)
        result = run(
            command,
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            max_credits,
            "--acknowledge-credits",
            ack,
            "--allow-network",
        )
        assert result.exit_code != 0
        assert recorder.requests == [], "a request was made despite an invalid ceiling"

    @pytest.mark.parametrize("command", ["core", "additional"])
    def test_the_acknowledgement_is_mandatory(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        recorder = Recorder()
        install(monkeypatch, recorder)
        ceiling = "1" if command == "core" else "5"
        result = run(
            command,
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            ceiling,
            "--allow-network",
        )
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
    @pytest.mark.parametrize("command", ["discover", "core", "additional"])
    def test_two_sports_are_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        recorder = Recorder()
        install(monkeypatch, recorder)
        args = [
            "--sport",
            f"{SPORT},tennis_atp_aus_open_singles",
            "--bookmaker",
            BOOKMAKER,
            "--allow-network",
        ]
        if command != "discover":
            ceiling = "1" if command == "core" else "5"
            args += [
                "--event-id",
                EVENT_ID,
                "--max-credits",
                ceiling,
                "--acknowledge-credits",
                ceiling,
            ]
        result = run(command, *args)
        assert result.exit_code != 0
        assert recorder.requests == []

    @pytest.mark.parametrize("command", ["discover", "core", "additional"])
    def test_two_bookmakers_are_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        recorder = Recorder()
        install(monkeypatch, recorder)
        args = ["--sport", SPORT, "--bookmaker", "winamax_fr,unibet", "--allow-network"]
        if command != "discover":
            ceiling = "1" if command == "core" else "5"
            args += [
                "--event-id",
                EVENT_ID,
                "--max-credits",
                ceiling,
                "--acknowledge-credits",
                ceiling,
            ]
        result = run(command, *args)
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_window_over_24_hours_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = Recorder()
        install(monkeypatch, recorder)
        result = run(
            "discover",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--window-hours",
            "48",
            "--allow-network",
        )
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
def sports_payload(active: bool = True) -> list[dict[str, Any]]:
    return [{"key": SPORT, "group": "Soccer", "title": "Ligue 1", "active": active}]


def events_payload(hours_ahead: float = 6.0, event_id: str = EVENT_ID) -> list[dict[str, Any]]:
    return [
        {
            "id": event_id,
            "sport_key": SPORT,
            "commence_time": (NOW + timedelta(hours=hours_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "home_team": "Olympique Lyonnais",
            "away_team": "Stade Rennais",
        }
    ]


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from betmaxxing.providers.the_odds_api import activation

    monkeypatch.setattr(activation, "_clock", lambda: NOW)


class TestDiscover:
    def _run(self, monkeypatch: pytest.MonkeyPatch, recorder: Recorder, *extra: str) -> Any:
        install(monkeypatch, recorder)
        return run(
            "discover", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--allow-network", *extra
        )

    def test_it_calls_exactly_the_two_free_endpoints(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/sports/": events_payload(), "/sports": sports_payload()})
        result = self._run(monkeypatch, recorder)
        assert result.exit_code == 0, result.stdout
        assert len(recorder.paths) == 2
        assert recorder.paths[0].endswith("/v4/sports")
        assert recorder.paths[1].endswith(f"/v4/sports/{SPORT}/events")

    def test_it_never_touches_a_paid_endpoint(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/sports/": events_payload(), "/sports": sports_payload()})
        self._run(monkeypatch, recorder)
        assert not any("/odds" in path for path in recorder.paths)
        assert not any("historical" in path for path in recorder.paths)

    def test_it_spends_nothing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None, db_settings: Any
    ) -> None:
        from betmaxxing.providers.budget import ProviderBudgetLedger

        recorder = Recorder({"/sports/": events_payload(), "/sports": sports_payload()})
        self._run(monkeypatch, recorder)
        from betmaxxing.config import get_settings

        assert ProviderBudgetLedger(get_settings()).spent_today("the_odds_api", NOW) == 0

    def test_an_inactive_sport_stops_before_the_events_call(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/sports": sports_payload(active=False)})
        result = self._run(monkeypatch, recorder)
        assert len(recorder.paths) == 1
        assert result.exit_code != 0
        assert "COVERAGE_MISSING" in result.stdout

    def test_no_event_in_the_window_is_coverage_missing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(
            {"/sports/": events_payload(hours_ahead=48.0), "/sports": sports_payload()}
        )
        result = self._run(monkeypatch, recorder)
        assert "COVERAGE_MISSING" in result.stdout
        assert len(recorder.paths) == 2, "it widened the search after finding nothing"

    def test_an_event_already_started_is_excluded(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(
            {"/sports/": events_payload(hours_ahead=-1.0), "/sports": sports_payload()}
        )
        result = self._run(monkeypatch, recorder)
        assert "COVERAGE_MISSING" in result.stdout

    def test_it_selects_no_event_automatically(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        two = [
            *events_payload(),
            {
                "id": "evt-fixture-0002",
                "sport_key": SPORT,
                "commence_time": (NOW + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "home_team": "A",
                "away_team": "B",
            },
        ]
        recorder = Recorder({"/sports/": two, "/sports": sports_payload()})
        result = self._run(monkeypatch, recorder, "--json")
        payload = json.loads(result.stdout)
        assert payload["status"] == "DISCOVERY_VERIFIED"
        assert len(payload["events"]) == 2
        assert "selected_event_id" not in payload

    def test_a_nonzero_reported_cost_is_a_mismatch(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """These endpoints are documented free; a charge means the contract moved."""
        recorder = Recorder(
            {
                "/sports": lambda r: httpx.Response(
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
        recorder = Recorder({"/sports": lambda r: httpx.Response(503, json={})})
        result = self._run(monkeypatch, recorder)
        assert len(recorder.paths) == 1, f"{len(recorder.paths)} attempts — retries are on"
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# core — one event, one bookmaker, one market, one credit
# ---------------------------------------------------------------------------
def odds_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": EVENT_ID,
            "sport_key": SPORT,
            "sport_title": "Ligue 1",
            "commence_time": (NOW + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "home_team": "Olympique Lyonnais",
            "away_team": "Stade Rennais",
            "bookmakers": [
                {
                    "key": BOOKMAKER,
                    "title": "Winamax (FR)",
                    "last_update": "2026-08-04T11:50:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Olympique Lyonnais", "price": 1.63},
                                {"name": "Stade Rennais", "price": 5.00},
                                {"name": "Draw", "price": 4.20},
                            ],
                        }
                    ],
                }
            ],
        }
    ]


class TestCore:
    def _run(self, monkeypatch: pytest.MonkeyPatch, recorder: Recorder, *extra: str) -> Any:
        install(monkeypatch, recorder)
        return run(
            "core",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            "1",
            "--acknowledge-credits",
            "1",
            "--allow-network",
            *extra,
        )

    def test_it_makes_exactly_one_request(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        result = self._run(monkeypatch, recorder)
        assert result.exit_code == 0, result.stdout
        assert len(recorder.requests) == 1

    def test_it_uses_the_grouped_endpoint_filtered_by_event(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        self._run(monkeypatch, recorder)
        assert recorder.paths[0].endswith(f"/v4/sports/{SPORT}/odds")
        assert recorder.query(0)["eventIds"] == [EVENT_ID]

    def test_it_requests_exactly_one_market_and_one_bookmaker(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        self._run(monkeypatch, recorder)
        query = recorder.query(0)
        assert query["markets"] == ["h2h"]
        assert query["bookmakers"] == [BOOKMAKER]

    def test_it_never_calls_the_general_collector(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import TheOddsApiProvider

        calls: list[str] = []
        monkeypatch.setattr(
            TheOddsApiProvider,
            "collect",
            lambda *a, **k: calls.append("collect") or [],  # type: ignore[func-returns-value]
        )
        recorder = Recorder({"/odds": odds_payload()})
        self._run(monkeypatch, recorder)
        assert calls == [], "the smoke path fanned out through collect()"

    def test_it_does_not_retry(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": lambda r: httpx.Response(503, json={})})
        self._run(monkeypatch, recorder)
        assert len(recorder.requests) == 1

    def test_an_empty_response_is_coverage_missing_not_a_failure(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": []})
        result = self._run(monkeypatch, recorder)
        assert "COVERAGE_MISSING" in result.stdout
        assert len(recorder.requests) == 1, "it called again after an empty response"

    def test_a_missing_bookmaker_is_coverage_missing(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        payload = odds_payload()
        payload[0]["bookmakers"] = []
        recorder = Recorder({"/odds": payload})
        result = self._run(monkeypatch, recorder)
        assert "COVERAGE_MISSING" in result.stdout

    def test_a_reported_cost_above_the_ceiling_is_a_mismatch(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder(
            {
                "/odds": lambda r: httpx.Response(
                    200, json=odds_payload(), headers={"x-requests-last": "4"}
                )
            }
        )
        result = self._run(monkeypatch, recorder)
        assert "COST_MISMATCH" in result.stdout
        assert result.exit_code != 0

    def test_an_event_outside_the_window_is_refused_before_the_network(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        payload = odds_payload()
        payload[0]["commence_time"] = (NOW + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recorder = Recorder({"/odds": payload})
        result = self._run(monkeypatch, recorder)
        assert result.exit_code != 0

    def test_it_writes_a_receipt_marked_core_live_verified(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        self._run(monkeypatch, recorder)
        receipts = list(keyed.glob("*.json"))
        assert receipts
        payload = json.loads(receipts[-1].read_text())
        assert payload["status"] == "CORE_LIVE_VERIFIED"

    def test_a_malformed_payload_is_a_schema_mismatch(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": [{"unexpected": True}]})
        result = self._run(monkeypatch, recorder)
        assert "SCHEMA_MISMATCH" in result.stdout


# ---------------------------------------------------------------------------
# additional — same event, five markets, five credits, separate authorisation
# ---------------------------------------------------------------------------
class TestAdditional:
    def _core_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(
            "core",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            "1",
            "--acknowledge-credits",
            "1",
            "--allow-network",
        )
        assert result.exit_code == 0, result.stdout

    def _run(self, monkeypatch: pytest.MonkeyPatch, recorder: Recorder, *extra: str) -> Any:
        install(monkeypatch, recorder)
        return run(
            "additional",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            "5",
            "--acknowledge-credits",
            "5",
            "--allow-network",
            *extra,
        )

    def test_it_refuses_without_a_prior_core_receipt(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/events/": {}})
        result = self._run(monkeypatch, recorder)
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_it_refuses_when_core_covered_a_different_event(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._core_first(monkeypatch)
        recorder = Recorder({"/events/": {}})
        install(monkeypatch, recorder)
        result = run(
            "additional",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            "evt-a-different-one",
            "--max-credits",
            "5",
            "--acknowledge-credits",
            "5",
            "--allow-network",
        )
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_it_makes_exactly_one_request_to_the_event_endpoint(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._core_first(monkeypatch)
        recorder = Recorder({"/events/": _event_odds_payload()})
        result = self._run(monkeypatch, recorder)
        assert result.exit_code == 0, result.stdout
        assert len(recorder.requests) == 1
        assert recorder.paths[0].endswith(f"/v4/sports/{SPORT}/events/{EVENT_ID}/odds")

    def test_it_requests_exactly_the_five_markets(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._core_first(monkeypatch)
        recorder = Recorder({"/events/": _event_odds_payload()})
        self._run(monkeypatch, recorder)
        markets = recorder.query(0)["markets"][0].split(",")
        assert markets == [
            "draw_no_bet",
            "double_chance",
            "h2h_3_way_h1",
            "totals_h1",
            "double_chance_h1",
        ]

    def test_it_reads_market_level_timestamps(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._core_first(monkeypatch)
        recorder = Recorder({"/events/": _event_odds_payload()})
        result = self._run(monkeypatch, recorder, "--json")
        payload = json.loads(result.stdout)
        assert payload["status"] == "ADDITIONAL_LIVE_VERIFIED"
        assert len(set(payload["freshness"].values())) == 2

    def test_a_partially_missing_market_is_reported_not_compensated(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._core_first(monkeypatch)
        recorder = Recorder({"/events/": _event_odds_payload()})
        result = self._run(monkeypatch, recorder, "--json")
        payload = json.loads(result.stdout)
        assert set(payload["markets_requested"]) > set(payload["markets_observed"])
        assert payload["markets_observed"] == ["draw_no_bet", "double_chance"]

    def test_it_does_not_retry(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._core_first(monkeypatch)
        recorder = Recorder({"/events/": lambda r: httpx.Response(503, json={})})
        self._run(monkeypatch, recorder)
        assert len(recorder.requests) == 1

    def test_it_never_touches_another_sport(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        self._core_first(monkeypatch)
        recorder = Recorder({"/events/": _event_odds_payload()})
        self._run(monkeypatch, recorder)
        assert all("tennis" not in path for path in recorder.paths)


def _event_odds_payload() -> dict[str, Any]:
    """Event-odds shape: no bookmaker timestamp, one per market, two of five."""
    return {
        "id": EVENT_ID,
        "sport_key": SPORT,
        "sport_title": "Ligue 1",
        "commence_time": (NOW + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": "Olympique Lyonnais",
        "away_team": "Stade Rennais",
        "bookmakers": [
            {
                "key": BOOKMAKER,
                "title": "Winamax (FR)",
                "markets": [
                    {
                        "key": "draw_no_bet",
                        "last_update": "2026-08-04T11:40:00Z",
                        "outcomes": [
                            {"name": "Olympique Lyonnais", "price": 1.30},
                            {"name": "Stade Rennais", "price": 3.40},
                        ],
                    },
                    {
                        "key": "double_chance",
                        "last_update": "2026-08-04T11:12:00Z",
                        "outcomes": [
                            {"name": "Olympique Lyonnais or Draw", "price": 1.15},
                            {"name": "Draw or Stade Rennais", "price": 1.55},
                            {"name": "Olympique Lyonnais or Stade Rennais", "price": 1.28},
                        ],
                    },
                ],
            }
        ],
    }


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
        recorder = Recorder({"/sports": lambda r: httpx.Response(status, json={"m": "x"})})
        install(monkeypatch, recorder)
        result = run("discover", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--allow-network")
        assert FAKE_KEY not in result.stdout
        assert FAKE_KEY not in str(result.exception or "")

    def test_the_key_never_appears_on_a_transport_failure(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"failed connecting with {FAKE_KEY}", request=request)

        recorder = Recorder({"/sports": boom})
        install(monkeypatch, recorder)
        result = run("discover", "--sport", SPORT, "--bookmaker", BOOKMAKER, "--allow-network")
        assert FAKE_KEY not in result.stdout

    def test_the_receipt_carries_no_key(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        run(
            "core",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            "1",
            "--acknowledge-credits",
            "1",
            "--allow-network",
        )
        for receipt in keyed.glob("*.json"):
            text = receipt.read_text()
            assert FAKE_KEY not in text
            assert "apiKey" not in text

    def test_the_receipt_hashes_the_event_id(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        run(
            "core",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            "1",
            "--acknowledge-credits",
            "1",
            "--allow-network",
        )
        payload = json.loads(next(iter(keyed.glob("*.json"))).read_text())
        assert EVENT_ID not in json.dumps(payload)
        assert payload["event_id_hash"]

    def test_the_receipt_carries_no_odds_or_participants(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        run(
            "core",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            "1",
            "--acknowledge-credits",
            "1",
            "--allow-network",
        )
        text = json.dumps(json.loads(next(iter(keyed.glob("*.json"))).read_text()))
        for forbidden in ("Olympique", "Rennais", "1.63", "4.20", "outcomes", "price"):
            assert forbidden not in text, f"{forbidden!r} was persisted"

    def test_receipts_are_gitignored(self) -> None:
        from betmaxxing.providers.the_odds_api.activation import DEFAULT_RECEIPT_DIR

        ignore = Path(".gitignore").read_text()
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
            assert f" {forbidden} " not in result.stdout.lower()


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
