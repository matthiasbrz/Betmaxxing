"""One synthetic corpus that satisfies every pre-registered threshold.

Several suites need the same thing: a set of receipts that *would* qualify, so a
test can show what stops it. Building it in one place keeps the eight criteria and
the corpus in step, and keeps every suite's fixtures identical.

The signature is computed here with :mod:`hmac` over the module's own canonical
bytes rather than through ``activation.sign_receipt``, deliberately: a helper used
to record a red baseline must not depend on the signature of the API under
correction. Nothing here reads a real secret or a real receipt — the caller passes
a synthetic value and a throwaway directory.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual

BOOKMAKER = "corpusbook"
SOCCER = ("soccer_corpus_one", "soccer_corpus_two")
TENNIS = ("tennis_corpus_one", "tennis_corpus_two")
FIVE = list(act.ADDITIONAL_MARKETS)


def effective_instant() -> datetime:
    return datetime.fromisoformat(qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC)


def sign_with(payload: dict[str, Any], secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), act.canonical_bytes(payload), hashlib.sha256
    ).hexdigest()


def receipt(
    *,
    command: str,
    status: str,
    sport: str,
    moment: datetime,
    tag: str,
    markets: list[str],
    credits: int,
    secret: str,
    **over: Any,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": act.RECEIPT_SCHEMA_VERSION,
        "qualification_protocol_version": qual.PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "provider_adapter_evidence_version": qual.PROVIDER_ADAPTER_EVIDENCE_VERSION,
        "receipt_id": tag[:16],
        "command": command,
        "status": status,
        "recorded_at": moment.isoformat(),
        "expires_at": (moment + act.RECEIPT_TTL).isoformat(),
        "sport_key": sport,
        "bookmaker": BOOKMAKER,
        "network_attempted": True,
        "may_have_reached_provider": True,
        "attempts": 1,
        "estimated_credits": credits,
        "observed_credits": credits,
        "accounted_credits": credits,
        "quota_remaining": 400,
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
    document.update(over)
    document[act.SIGNATURE_FIELD] = sign_with(document, secret)
    return document


def threshold_corpus(secret: str) -> list[dict[str, Any]]:
    """Eight receipts: enough for all eight criteria, and no more.

    * ``CORE_MAPPING_FOOTBALL`` — three soccer events, two competitions, two days;
    * ``CORE_MAPPING_TENNIS`` — the same for tennis;
    * the five ``ADDITIONAL_MAPPING_FOOTBALL_*`` — two soccer events, two
      competitions, one day, all five markets mapped;
    * ``COST_CONFORMITY`` — eight conforming paid calls, above the six required.
    """
    day_one = effective_instant() + timedelta(days=1)
    day_two = day_one + timedelta(days=1)
    out: list[dict[str, Any]] = []
    core_plan = [
        (SOCCER[0], day_one, "a"),
        (SOCCER[1], day_one, "b"),
        (SOCCER[0], day_two, "c"),
        (TENNIS[0], day_one, "d"),
        (TENNIS[1], day_one, "e"),
        (TENNIS[0], day_two, "f"),
    ]
    for sport, moment, letter in core_plan:
        out.append(
            receipt(
                command="core",
                status="CORE_LIVE_VERIFIED",
                sport=sport,
                moment=moment,
                tag=letter * 32,
                markets=["h2h"],
                credits=1,
                secret=secret,
            )
        )
    for sport, letter in ((SOCCER[0], "g"), (SOCCER[1], "h")):
        out.append(
            receipt(
                command="additional",
                status="ADDITIONAL_LIVE_VERIFIED",
                sport=sport,
                moment=day_one,
                tag=letter * 32,
                markets=FIVE,
                credits=5,
                secret=secret,
            )
        )
    return out


def write_threshold_corpus(directory: Path, secret: str) -> list[Path]:
    """Write the corpus as files the audit will list, and return their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for index, document in enumerate(threshold_corpus(secret)):
        path = directory / f"20260901T12000{index}-{document['command']}-corpus{index:02d}.json"
        path.write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
