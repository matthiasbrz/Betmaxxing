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
from datetime import datetime
from pathlib import Path
from typing import Any

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual

#: The protocol 8 manifest, restated. A corpus meant to satisfy every threshold has
#: to be inside the pre-registered campaign: outside it, every receipt below would
#: be an evidence conflict and the corpus would prove the opposite of its purpose.
#: The register's own scopes live in :mod:`helpers_campaign_v8`, which builds the corpus
#: below; only the bookmaker is needed here, by :func:`receipt`.
BOOKMAKER = "pinnacle"


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
    """The twelve pre-registered invocations: enough for all eight criteria, and no more.

    * ``CORE_MAPPING_FOOTBALL`` — three soccer events, two competitions, two days;
    * ``CORE_MAPPING_TENNIS`` — the same for tennis;
    * the five ``ADDITIONAL_MAPPING_FOOTBALL_*`` — two soccer events, two
      competitions, all five markets mapped;
    * ``COST_CONFORMITY`` — eight conforming paid calls, above the six required. The
      four ``discover`` receipts are unpaid, so they enter no cost bucket.

    Six ``core`` and two ``additional`` were enough while the campaign was only counted.
    Since 03C-2F quater the position is *recognised* from the receipts, and eight paid
    steps with no discovery behind them is a corpus no command could have produced: the
    register would report it as a contradiction, and a corpus meant to satisfy every
    threshold would prove the opposite of its purpose. So the four discoveries they
    descend from are here, and every paid step names its parent and its event rank.

    Delegated to :mod:`helpers_campaign_v8` rather than restated: one builder for the
    register means the campaign suites and the qualification suites cannot disagree
    about what « conforming » is.
    """
    import helpers_campaign_v8 as v8

    return v8.register_corpus(secret=secret)


def write_threshold_corpus(directory: Path, secret: str) -> list[Path]:
    """Write the corpus as files the audit will list, and return their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for index, document in enumerate(threshold_corpus(secret)):
        path = directory / f"20260901T1200{index:02d}-{document['command']}-corpus{index:02d}.json"
        path.write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
