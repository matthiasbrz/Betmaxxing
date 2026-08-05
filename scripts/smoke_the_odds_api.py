#!/usr/bin/env python
"""Opt-in smoke test against the real The Odds API.

**This is the only code in the repository that performs a real, credit-consuming
call, and it never runs by itself.** It is not collected by pytest, not run by
CI, and refuses to start without an explicit environment variable.

    export BETMAXXING_THE_ODDS_API_KEY=...        # your key, never committed
    export BETMAXXING_SMOKE_TEST=1                # explicit consent
    python scripts/smoke_the_odds_api.py

What it does
------------
* one grouped odds request per configured sport key (a handful of credits);
* reports the quota headers the service returned;
* reports whether the configured bookmaker actually appeared, and which markets
  were mapped or rejected.

What it does **not** do
-----------------------
* touch a historical (paid) endpoint;
* create a candidate, write a scan, or change any model's validation status;
* print the API key, in any form, anywhere.

Until this succeeds, the adapter's status stays ``IMPLEMENTED_UNVERIFIED``. A
green run tells you the coverage you actually have; it does not validate a model.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import timedelta

from betmaxxing.config import get_settings
from betmaxxing.domain.enums import Sport
from betmaxxing.domain.timeutil import format_display, utc_now
from betmaxxing.providers.base import ProviderError
from betmaxxing.providers.the_odds_api import TheOddsApiProvider

CONSENT_VARIABLE = "BETMAXXING_SMOKE_TEST"


def main() -> int:
    if os.environ.get(CONSENT_VARIABLE) != "1":
        print(
            f"Refus : {CONSENT_VARIABLE}=1 est requis.\n"
            "Ce script consomme des crédits réels chez The Odds API. "
            "Il ne s'exécute jamais sans consentement explicite."
        )
        return 2

    settings = get_settings()
    if not settings.resolved_the_odds_api_key:
        print(
            "Refus : aucune clé configurée. Définissez BETMAXXING_THE_ODDS_API_KEY "
            "dans votre environnement (jamais dans un fichier versionné)."
        )
        return 2

    for warning in settings.deprecation_warnings():
        print(f"! {warning}")

    now = utc_now()
    window = (now, now + timedelta(hours=settings.window_hours))
    provider = TheOddsApiProvider(settings, now=now)

    print("=" * 72)
    print("SMOKE TEST — The Odds API v4 (appels réels, crédits consommés)")
    print(f"Fenêtre        : {format_display(window[0])} → {format_display(window[1])}")
    print(f"Bookmakers     : {', '.join(settings.bookmaker_list) or '(aucun)'}")
    print(f"Régions        : {settings.the_odds_api_regions}")
    print(f"Sports         : {', '.join(settings.the_odds_api_sport_key_list)}")
    print(f"Budget/scan    : {settings.provider_budget_per_scan} crédits")
    print("=" * 72)

    try:
        batch = provider.collect([Sport.FOOTBALL, Sport.TENNIS], window)
    except ProviderError as exc:
        # Provider errors already carry redacted URLs.
        print(f"\nÉCHEC : {exc}")
        return 1

    print(f"\nÉvénements     : {len(batch.events)}")
    print(f"Snapshots      : {len(batch.snapshots)}")
    print(f"Couverture     : {batch.coverage}")
    print(
        "Quota          : "
        f"restants={batch.quota.remaining} utilisés={batch.quota.used} "
        f"coût du dernier appel={batch.quota.last_cost}"
    )

    if batch.snapshots:
        markets = Counter(f"{s.selection.market}/{s.selection.period}" for s in batch.snapshots)
        print("\nMarchés cartographiés :")
        for name, count in sorted(markets.items()):
            print(f"  · {name}: {count} sélection(s)")

        books = Counter(s.bookmaker for s in batch.snapshots)
        print("\nBookmakers observés :")
        for name, count in sorted(books.items()):
            print(f"  · {name}: {count}")
    else:
        print(
            "\nAucun snapshot. Couverture manquante n'est PAS une panne : la réponse "
            "peut être correcte sans contenir le bookmaker demandé."
        )

    if batch.partial_errors:
        print("\nRejets et erreurs partielles (aucune donnée valide perdue) :")
        for error in batch.partial_errors[:20]:
            print(f"  · {error}")

    print("\n" + "=" * 72)
    print(
        "Ce test confirme (ou non) la couverture observée à cet instant.\n"
        "Il ne valide aucun modèle : tous restent BACKTEST_ONLY.\n"
        "Mettez à jour docs/source-matrix.md avec la date et le constat."
    )
    return 0 if batch.snapshots else 1


if __name__ == "__main__":
    sys.exit(main())
