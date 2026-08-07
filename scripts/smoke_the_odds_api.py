#!/usr/bin/env python
"""Deprecated entry point. The activation is now four separate, bounded steps.

What this script used to do
---------------------------
Ask for one boolean (``BETMAXXING_SMOKE_TEST=1``) and then call
``provider.collect([FOOTBALL, TENNIS], window)``. That is a fan-out: one grouped
odds request per configured sport key, then one per-event request for every
football event returned, bounded only by the per-scan budget. A boolean is not a
spending limit. Nobody could state, before running it, what it would cost.

What replaces it
----------------
:mod:`betmaxxing.providers.the_odds_api.activation` — four commands, each with a
ceiling checked before any socket is opened, each authorised on its own:

    python -m betmaxxing.providers.the_odds_api.activation plan \\
        --sport soccer_france_ligue_one --bookmaker winamax_fr --max-credits 6

    # 0 credits, two endpoints documented as free
    ... discover --sport … --bookmaker … --allow-network

    # 1 credit, one event, one market
    ... core --sport … --bookmaker … --event-id … \\
        --max-credits 1 --acknowledge-credits 1 --allow-network

    # 5 credits, same event, five per-event markets
    ... additional --sport … --bookmaker … --event-id … \\
        --max-credits 5 --acknowledge-credits 5 --allow-network

The key comes from ``BETMAXXING_THE_ODDS_API_KEY`` in the environment. There is
no ``--api-key`` option, by construction.

This file is kept only so an operator following an older note is redirected
rather than left with a missing script. It performs no network call of its own.
See ``docs/provider-activation.md`` for the full runbook.
"""

from __future__ import annotations

import sys

from betmaxxing.providers.the_odds_api.activation import app

MESSAGE = """\
Ce script est remplacé. Il consommait un nombre de crédits que personne ne
pouvait annoncer à l'avance (un appel groupé par compétition configurée, puis
un appel par événement).

L'activation se fait désormais en quatre étapes plafonnées et autorisées
séparément :

  python -m betmaxxing.providers.the_odds_api.activation plan \\
      --sport <clé> --bookmaker <clé> --max-credits 6

  ... discover   --allow-network                                     0 crédit
  ... core       --event-id <id> --max-credits 1 --acknowledge-credits 1
  ... additional --event-id <id> --max-credits 5 --acknowledge-credits 5

La clé provient de BETMAXXING_THE_ODDS_API_KEY, jamais d'un argument.
Runbook complet : docs/provider-activation.md
"""


def main(argv: list[str] | None = None) -> int:
    """Print the redirection, or forward explicit arguments to the harness."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(MESSAGE)
        return 2
    # An operator who already knows the new interface can reach it from here;
    # every ceiling and consent check still applies, unchanged.
    app(args=args, standalone_mode=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
