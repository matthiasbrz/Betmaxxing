"""Synthetic corpora for the protocol 8 campaign boundary.

Everything here is synthetic and throwaway: the signing secret is a fixed test
value, the directory is a fresh ``tmp_path``, and no receipt, key or payload of a
real installation is ever read. The real protocol 7 receipt — the empty Ligue 1
discovery of 03C-2D — is *never* used as a fixture; where a suite needs a v7
receipt it builds one here, with these synthetic values.

The signature is computed with :mod:`hmac` over ``activation.canonical_bytes``
rather than through ``activation.sign_receipt``: a helper that records a red
baseline must not depend on the signing API it is about to guard.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual

#: Synthetic, bound to nothing, and never a real installation's key.
SECRET = "5e" * 32

#: The manifest the campaign is pre-registered against, restated here as literals
#: rather than imported. A helper that reads the constant it is meant to pin would
#: agree with any value the module happened to hold.
BOOKMAKER = "pinnacle"
FOOTBALL = ("soccer_epl", "soccer_spain_la_liga")
TENNIS = ("tennis_atp_us_open", "tennis_wta_us_open")
COMPETITIONS = (*FOOTBALL, *TENNIS)
NOT_BEFORE = "2026-08-25T00:00:00+00:00"

#: Outside the manifest in each of the two ways a receipt can be.
FOREIGN_BOOKMAKER = "winamax_fr"
FOREIGN_COMPETITION = "soccer_france_ligue_one"

FIVE = tuple(act.ADDITIONAL_MARKETS)

#: The pre-registered order of the twelve invocations:
#: ``(index, command, competition, event rank, parent step)``. Literals for the same
#: reason as the manifest above — a builder that read ``CAMPAIGN_SEQUENCE`` would call
#: « conforming » whatever order that object happened to hold. Since 03C-2F quater the
#: position is *recognised* from the receipts, so a corpus is only conforming when its
#: event ranks, its ``parent_receipt_id`` chain and its chronology all agree with this
#: table; ``tests/test_campaign_register_fidelity_v8.py`` restates it once more on
#: purpose, because a closure proof's oracle must not be this builder's twin.
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

#: Events per synthetic discovery. Three, so a rank the register never names exists and
#: a corpus can aim at it deliberately.
REGISTER_EVENTS = 3

#: A UTC day per step, so that each family's three ``core`` span two days — which
#: ``CORE_MAPPING_FOOTBALL`` and ``CORE_MAPPING_TENNIS`` require — while the register's
#: own order stays chronologically increasing. Football's cores are steps 2, 3 and 6,
#: tennis's are 9, 10 and 12, so the two boundaries fall between 5 and 6 and between 10
#: and 11: a single boundary anywhere would leave one of the two families inside one day.
REGISTER_DAYS: dict[int, int] = {
    **dict.fromkeys(range(1, 6), 0),
    **dict.fromkeys(range(6, 11), 1),
    **dict.fromkeys(range(11, 13), 2),
}


def instant(offset_hours: int = 0) -> datetime:
    """An instant inside the campaign's evidence window."""
    return datetime.fromisoformat(NOT_BEFORE) + timedelta(hours=1 + offset_hours)


def sign_with(payload: dict[str, Any], secret: str = SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"), act.canonical_bytes(payload), hashlib.sha256
    ).hexdigest()


def _sealed(payload: dict[str, Any], secret: str) -> dict[str, Any]:
    payload[act.SIGNATURE_FIELD] = sign_with(payload, secret)
    return payload


def sealed_again(payload: dict[str, Any], secret: str = SECRET) -> dict[str, Any]:
    """Re-sign a receipt a test has just edited, so it stays authentic but wrong.

    The point of several fixtures is a receipt whose *bytes* are ours and whose
    *fields* are not readable. Editing without re-signing would only produce an
    unverifiable file, which is a different fault.
    """
    payload.pop(act.SIGNATURE_FIELD, None)
    return _sealed(payload, secret)


def _spine(
    *,
    command: str,
    status: str,
    sport: str,
    bookmaker: str,
    moment: datetime,
    protocol: int,
    credits: int,
    attempts: int,
) -> dict[str, Any]:
    return {
        "schema_version": act.RECEIPT_SCHEMA_VERSION,
        "qualification_protocol_version": protocol,
        "provider_adapter_evidence_version": qual.PROVIDER_ADAPTER_EVIDENCE_VERSION,
        "command": command,
        "status": status,
        "recorded_at": moment.isoformat(),
        "expires_at": (moment + act.RECEIPT_TTL).isoformat(),
        "sport_key": sport,
        "bookmaker": bookmaker,
        "network_attempted": True,
        "may_have_reached_provider": True,
        "attempts": attempts,
        "estimated_credits": credits,
        "observed_credits": credits,
        "accounted_credits": credits,
        "quota_remaining": 400,
    }


def discovery(
    *,
    sport: str,
    moment: datetime,
    rid: str,
    status: str = "DISCOVERY_VERIFIED",
    bookmaker: str = BOOKMAKER,
    protocol: int = 8,
    secret: str = SECRET,
    events: int = 3,
) -> dict[str, Any]:
    """A ``discover`` receipt in the ``DISCOVERED`` phase."""
    found = events if status == "DISCOVERY_VERIFIED" else 0
    payload = _spine(
        command="discover",
        status=status,
        sport=sport,
        bookmaker=bookmaker,
        moment=moment,
        protocol=protocol,
        credits=0,
        attempts=2,
    )
    payload.update(
        {
            "receipt_id": rid,
            "event_tags": [f"{rid}{index:02d}" for index in range(found)],
            "events_returned": found,
            "events_in_window": found,
            "events_admissible": found,
        }
    )
    return _sealed(payload, secret)


def paid(
    *,
    command: str,
    status: str,
    sport: str,
    moment: datetime,
    rid: str,
    tag: str,
    markets: tuple[str, ...],
    credits: int,
    bookmaker: str = BOOKMAKER,
    protocol: int = 8,
    secret: str = SECRET,
    parent_rid: str | None = None,
) -> dict[str, Any]:
    """A ``core`` or ``additional`` receipt in the ``CLASSIFIED`` phase."""
    payload = _spine(
        command=command,
        status=status,
        sport=sport,
        bookmaker=bookmaker,
        moment=moment,
        protocol=protocol,
        credits=credits,
        attempts=1,
    )
    payload.update(
        {
            "receipt_id": rid,
            "markets_requested": list(markets),
            "market_states": dict.fromkeys(markets, "OBSERVED_MAPPED"),
            "markets_mapped": list(markets),
            "markets_observed": list(markets),
            "markets_rejected": [],
            "markets_absent": [],
            "markets_not_evaluated": [],
            "selections_mapped": 3 * len(markets),
            "freshness": dict.fromkeys(markets, 300),
            "mapping_rejections": [],
            "event_tag": tag,
            "bookmaker_state": "OBSERVED",
        }
    )
    # The lineage the real producer always writes. Protocol 8's schema 4 carries
    # `parent_receipt_id`, and since the register is read from the receipts the
    # identity of the parent is evidence, not decoration: a corpus that omitted it
    # would be a corpus no `core` or `additional` command could ever have produced.
    if parent_rid is not None:
        payload["parent_receipt_id"] = parent_rid
        payload["parent_schema_version"] = act.RECEIPT_SCHEMA_VERSION
    return _sealed(payload, secret)


def core(
    *, sport: str, moment: datetime, rid: str, tag: str, parent_rid: str | None = None, **over: Any
) -> dict[str, Any]:
    return paid(
        parent_rid=parent_rid,
        command="core",
        status=over.pop("status", "CORE_LIVE_VERIFIED"),
        sport=sport,
        moment=moment,
        rid=rid,
        tag=tag,
        markets=("h2h",),
        credits=1,
        **over,
    )


def additional(
    *, sport: str, moment: datetime, rid: str, tag: str, parent_rid: str | None = None, **over: Any
) -> dict[str, Any]:
    return paid(
        parent_rid=parent_rid,
        command="additional",
        status=over.pop("status", "ADDITIONAL_LIVE_VERIFIED"),
        sport=sport,
        moment=moment,
        rid=rid,
        tag=tag,
        markets=FIVE,
        credits=5,
        **over,
    )


def historical_v7_discovery(moment: datetime | None = None) -> dict[str, Any]:
    """A protocol 7 receipt shaped like the real one, built from synthetic values.

    Same command, status and emptiness as the 03C-2D receipt; none of its bytes.
    """
    when = moment or datetime(2026, 8, 23, 20, 57, 57, tzinfo=UTC)
    return discovery(
        sport=FOREIGN_COMPETITION,
        moment=when,
        rid="a" * 16,
        status="COVERAGE_MISSING",
        bookmaker=FOREIGN_BOOKMAKER,
        protocol=7,
        events=0,
    )


# ---------------------------------------------------------------------------
# Whole corpora
# ---------------------------------------------------------------------------
def register_rid(step: int) -> str:
    """The receipt identifier the synthetic corpus gives to a register step."""
    return f"{step:016x}"


def register_tags(step: int, count: int = REGISTER_EVENTS) -> list[str]:
    """The event tags the discovery of ``step`` publishes, in canonical rank order.

    The same construction :func:`discovery` uses, restated so a caller can name the rank
    it wants — including the third, which the register never names.
    """
    return [f"{register_rid(step)}{position:02d}" for position in range(count)]


def _numbering_discovery(step: int) -> int:
    """Which discovery numbers this paid step's event rank.

    A ``core`` counts ranks in the discovery it names as its parent. An ``additional``
    inherits the event its parent ``core`` proved, so its rank is numbered in *that*
    core's discovery — one hop further back.
    """
    _, command, _, _, parent = REGISTER[step - 1]
    assert parent is not None
    if command == "core":
        return parent
    grandparent = REGISTER[parent - 1][4]
    assert grandparent is not None
    return grandparent


def register_receipt(
    step: int,
    *,
    secret: str = SECRET,
    day: int = 0,
    events: int = REGISTER_EVENTS,
) -> dict[str, Any]:
    """The receipt a conforming invocation of register step ``step`` would publish."""
    index, command, sport, rank, parent = REGISTER[step - 1]
    moment = instant(index + 24 * day)
    if command == "discover":
        return discovery(
            sport=sport, moment=moment, rid=register_rid(index), events=events, secret=secret
        )
    assert rank is not None and parent is not None
    maker = core if command == "core" else additional
    return maker(
        sport=sport,
        moment=moment,
        rid=register_rid(index),
        tag=register_tags(_numbering_discovery(index))[rank - 1],
        parent_rid=register_rid(parent),
        secret=secret,
    )


def register_corpus(
    upto: int = len(REGISTER),
    *,
    secret: str = SECRET,
    days: dict[int, int] | None = None,
) -> list[dict[str, Any]]:
    """The first ``upto`` steps of the register, conforming in every respect.

    Conforming means all of it at once, since 03C-2F quater: the command and competition
    of each step, the event at the rank the register names in the applicable discovery's
    own signed order, the identity of the parent receipt, and a chronology that agrees
    with the order. Any corpus short of that is a contradiction, not weak evidence.
    """
    schedule = REGISTER_DAYS if days is None else days
    return [
        register_receipt(step[0], secret=secret, day=schedule.get(step[0], 0))
        for step in REGISTER[:upto]
    ]


def nominal_campaign() -> list[dict[str, Any]]:
    """The whole register: 4 + 6 + 2, every scope used once, every threshold reachable."""
    return register_corpus()


def discoveries(count: int, *, failed_last: bool = False) -> list[dict[str, Any]]:
    """``count`` discoveries over the manifest, cycling if it runs out of scopes.

    The failure is the **last** one in time, which is what a real campaign looks like:
    it runs until something comes back empty, and then it stops. A success filed
    *after* an abort is a different fault — the corpus contradicting its own stop —
    and has its own fixture rather than being smuggled in here.
    """
    out: list[dict[str, Any]] = []
    for index in range(count):
        failed = failed_last and index == count - 1
        out.append(
            discovery(
                sport=COMPETITIONS[index % len(COMPETITIONS)],
                moment=instant(index),
                rid=f"d{index:015x}",
                status="COVERAGE_MISSING" if failed else "DISCOVERY_VERIFIED",
                events=0 if failed else 3,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Writing them where the audit will find them
# ---------------------------------------------------------------------------
def install_secret(directory: Path, secret: str = SECRET) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / act.SECRET_FILENAME
    path.write_text(secret, encoding="utf-8")
    os.chmod(path, 0o600)
    os.chmod(directory, 0o700)
    return path


def write_corpus(
    directory: Path, receipts: list[dict[str, Any]], *, unreadable: int = 0, secret: str = SECRET
) -> Path:
    """Write ``receipts`` as files the audit will list, plus the local secret."""
    directory.mkdir(parents=True, exist_ok=True)
    for index, document in enumerate(receipts):
        stamp = f"20260901T{index // 60:02d}{index % 60:02d}00"
        name = f"{stamp}-{document.get('command', 'x')}-synth{index:03d}.json"
        (directory / name).write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    for index in range(unreadable):
        (directory / f"20260901T235900-core-unreadable{index:03d}.json").write_text(
            "{ this is not a receipt", encoding="utf-8"
        )
    install_secret(directory, secret)
    return directory
