"""Shared machinery for the activation-harness suites.

Four test modules exercise the same CLI, so the fake transport, the fixture
payloads and the argument builders live here rather than in one of them. A test
module never imports a sibling test module — that is what made CI collect nothing
once before (see ``test_suite_reproducibility.py``). ``pyproject.toml`` declares
``pythonpath = ["tests"]``, so this is importable as ``helpers_activation`` under
both ``pytest`` and ``python -m pytest``.

The fixtures themselves (``workspace``, ``keyed``, ``frozen_clock``) live in
``tests/conftest.py``, which is the only place pytest looks for them.

Nothing here opens a socket. Every response comes from ``httpx.MockTransport``,
and ``conftest.py`` blocks outbound connections for the whole session anyway.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from typer.testing import CliRunner

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
#: Deliberately recognisable, and deliberately not a real key shape in use.
FAKE_KEY = "FAKEKEY0000deadbeef0000FAKEKEY00"
#: A deterministic signing secret, injected so no test depends on real randomness.
FAKE_RECEIPT_SECRET = "0011223344556677889900aabbccddeeff00112233445566778899aabbccddee"
SPORT = "soccer_france_ligue_one"
OTHER_SPORT = "soccer_epl"
BOOKMAKER = "winamax_fr"
OTHER_BOOKMAKER = "unibet"
EVENT_ID = "evt-fixture-0001"
OTHER_EVENT_ID = "evt-fixture-0002"

HOME = "Olympique Lyonnais"
AWAY = "Stade Rennais"

ADDITIONAL_MARKET_KEYS = (
    "draw_no_bet",
    "double_chance",
    "h2h_3_way_h1",
    "totals_h1",
    "double_chance_h1",
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------
def cli() -> Any:
    from betmaxxing.providers.the_odds_api.activation import app

    return app


def run(*args: str) -> Any:
    return runner.invoke(cli(), list(args))


def install(monkeypatch: Any, recorder: Recorder) -> None:
    """Inject the fake transport into the harness's client factory."""
    from betmaxxing.providers.the_odds_api import activation

    monkeypatch.setattr(activation, "_TRANSPORT_FOR_TESTS", httpx.MockTransport(recorder.handler))


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


# ---------------------------------------------------------------------------
# Argument builders
# ---------------------------------------------------------------------------
def plan_args(
    *,
    sport: str = SPORT,
    bookmaker: str = BOOKMAKER,
    max_credits: str | None = None,
    extra: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """``plan`` restates the total ceiling exactly, and opens no socket."""
    from betmaxxing.providers.the_odds_api.activation import TOTAL_MAX_CREDITS

    return (
        "plan",
        "--sport",
        sport,
        "--bookmaker",
        bookmaker,
        "--max-credits",
        max_credits or str(TOTAL_MAX_CREDITS),
        *extra,
    )


def discover_args(
    *,
    sport: str = SPORT,
    bookmaker: str = BOOKMAKER,
    extra: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return (
        "discover",
        "--sport",
        sport,
        "--bookmaker",
        bookmaker,
        "--allow-network",
        *extra,
    )


def core_args(
    *,
    discovery_receipt: str,
    sport: str = SPORT,
    bookmaker: str = BOOKMAKER,
    event_id: str = EVENT_ID,
    max_credits: str = "1",
    acknowledge: str | None = "1",
    allow_network: bool = True,
    extra: tuple[str, ...] = (),
) -> tuple[str, ...]:
    args = [
        "core",
        "--sport",
        sport,
        "--bookmaker",
        bookmaker,
        "--event-id",
        event_id,
        "--discovery-receipt",
        discovery_receipt,
        "--max-credits",
        max_credits,
    ]
    if acknowledge is not None:
        args += ["--acknowledge-credits", acknowledge]
    if allow_network:
        args.append("--allow-network")
    return (*args, *extra)


def additional_args(
    *,
    core_receipt: str,
    sport: str = SPORT,
    bookmaker: str = BOOKMAKER,
    event_id: str = EVENT_ID,
    max_credits: str = "5",
    acknowledge: str | None = "5",
    allow_network: bool = True,
    extra: tuple[str, ...] = (),
) -> tuple[str, ...]:
    args = [
        "additional",
        "--sport",
        sport,
        "--bookmaker",
        bookmaker,
        "--event-id",
        event_id,
        "--core-receipt",
        core_receipt,
        "--max-credits",
        max_credits,
    ]
    if acknowledge is not None:
        args += ["--acknowledge-credits", acknowledge]
    if allow_network:
        args.append("--allow-network")
    return (*args, *extra)


# ---------------------------------------------------------------------------
# Fixture payloads
# ---------------------------------------------------------------------------
def sports_payload(active: bool = True, key: str = SPORT) -> list[dict[str, Any]]:
    return [{"key": key, "group": "Soccer", "title": "Ligue 1", "active": active}]


def events_payload(
    hours_ahead: float = 6.0, event_id: str = EVENT_ID, sport: str = SPORT
) -> list[dict[str, Any]]:
    return [
        {
            "id": event_id,
            "sport_key": sport,
            "commence_time": iso_z(NOW + timedelta(hours=hours_ahead)),
            "home_team": HOME,
            "away_team": AWAY,
        }
    ]


def odds_payload(
    event_id: str = EVENT_ID, sport: str = SPORT, bookmaker: str = BOOKMAKER
) -> list[dict[str, Any]]:
    """Grouped `/odds` shape: `last_update` on the bookmaker."""
    return [
        {
            "id": event_id,
            "sport_key": sport,
            "sport_title": "Ligue 1",
            "commence_time": iso_z(NOW + timedelta(hours=6)),
            "home_team": HOME,
            "away_team": AWAY,
            "bookmakers": [
                {
                    "key": bookmaker,
                    "title": "Winamax (FR)",
                    "last_update": "2026-08-04T11:50:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": HOME, "price": 1.63},
                                {"name": AWAY, "price": 5.00},
                                {"name": "Draw", "price": 4.20},
                            ],
                        }
                    ],
                }
            ],
        }
    ]


#: Provider market blocks for the per-event endpoint, without their timestamps.
EVENT_MARKET_BLOCKS: dict[str, dict[str, Any]] = {
    "draw_no_bet": {
        "key": "draw_no_bet",
        "outcomes": [{"name": HOME, "price": 1.30}, {"name": AWAY, "price": 3.40}],
    },
    "double_chance": {
        "key": "double_chance",
        "outcomes": [
            {"name": f"{HOME} or Draw", "price": 1.15},
            {"name": f"Draw or {AWAY}", "price": 1.55},
            {"name": f"{HOME} or {AWAY}", "price": 1.28},
        ],
    },
    "h2h_3_way_h1": {
        "key": "h2h_3_way_h1",
        "outcomes": [
            {"name": HOME, "price": 2.30},
            {"name": AWAY, "price": 6.50},
            {"name": "Draw", "price": 2.05},
        ],
    },
    "totals_h1": {
        "key": "totals_h1",
        "outcomes": [
            {"name": "Over", "price": 2.40, "point": 1.5},
            {"name": "Under", "price": 1.55, "point": 1.5},
        ],
    },
    "double_chance_h1": {
        "key": "double_chance_h1",
        "outcomes": [
            {"name": f"{HOME} or Draw", "price": 1.32},
            {"name": f"Draw or {AWAY}", "price": 1.18},
            {"name": f"{HOME} or {AWAY}", "price": 1.95},
        ],
    },
}

#: A distinct instant per market, so a flattening bug cannot hide behind equality.
EVENT_MARKET_STAMPS: dict[str, str] = {
    "draw_no_bet": "2026-08-04T11:40:00Z",
    "double_chance": "2026-08-04T11:12:00Z",
    "h2h_3_way_h1": "2026-08-04T11:47:00Z",
    "totals_h1": "2026-08-04T11:22:00Z",
    "double_chance_h1": "2026-08-04T11:03:00Z",
}


def event_odds_payload(
    markets: tuple[str, ...] = ADDITIONAL_MARKET_KEYS,
    *,
    event_id: str = EVENT_ID,
    sport: str = SPORT,
    bookmaker: str = BOOKMAKER,
    stamped: bool = True,
    broken: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Event-odds shape: no bookmaker stamp, one per market.

    ``broken`` names markets whose outcomes are unusable, so the mapper rejects
    them while the provider did return them — the ``OBSERVED_REJECTED`` case.
    """
    blocks: list[dict[str, Any]] = []
    for key in markets:
        block = dict(EVENT_MARKET_BLOCKS[key])
        if key in broken:
            block = {**block, "outcomes": [{"name": "???", "price": 0.5}]}
        if stamped:
            block["last_update"] = EVENT_MARKET_STAMPS[key]
        blocks.append(block)
    return {
        "id": event_id,
        "sport_key": sport,
        "sport_title": "Ligue 1",
        "commence_time": iso_z(NOW + timedelta(hours=6)),
        "home_team": HOME,
        "away_team": AWAY,
        "bookmakers": [{"key": bookmaker, "title": "Winamax (FR)", "markets": blocks}],
    }


def iso_z(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Receipt inspection
# ---------------------------------------------------------------------------
def receipts_in(directory: Path) -> list[dict[str, Any]]:
    """Every receipt in the directory, oldest first, with its filename attached.

    ``_filename`` is added by this helper for the tests' convenience; it is not a
    receipt field.
    """
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        loaded["_filename"] = path.name
        out.append(loaded)
    return out


def only_receipt(directory: Path, command: str) -> dict[str, Any]:
    matching = [r for r in receipts_in(directory) if r.get("command") == command]
    assert len(matching) == 1, f"expected one {command} receipt, got {len(matching)}"
    return matching[0]


def receipt_path(directory: Path, command: str) -> Path:
    return directory / only_receipt(directory, command)["_filename"]


def tamper(path: Path, **changes: Any) -> None:
    """Rewrite a receipt's fields in place, leaving its signature untouched."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(changes)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
