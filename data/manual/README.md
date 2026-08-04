# Import manuel de cotes

Voie officielle pour les bookmakers sans flux programmatique autorisé — Winamax inclus.

```bash
betmaxxing odds import data/manual/example_odds.csv
betmaxxing scan --manual-odds data/manual/example_odds.csv
```

## Colonnes obligatoires

`bookmaker`, `sport`, `competition`, `home`, `away`, `start_time_utc`, `market`,
`period`, `selection_code`, `selection_label`, `decimal_odds`, `observed_at_utc`.

Optionnelles : `stage`, `surface`, `sets_to_win`, `line`, `currency`.

## Règles

- Les horodatages sont **ISO-8601 avec décalage explicite** (`+00:00`). Un horodatage
  naïf est mis en quarantaine, pas interprété : supposer un fuseau serait inventer une
  donnée.
- `observed_at_utc` est l'instant où **vous** avez lu le prix, pas l'instant de l'import.
  C'est ce qui détermine la fraîcheur, et une cote de plus de 15 minutes est rejetée par
  défaut (`ODDS_STALE`).
- `line` est obligatoire sur `total_goals` / `total_games` et interdite ailleurs. Les
  lignes entières (3.0) sont refusées : elles peuvent être remboursées.
- Cotez **toutes** les issues d'un marché. Un book incomplet ne peut pas être dé-viggé et
  sera rejeté (`MARKET_INCOMPLETE`).
- Une ligne invalide est mise en quarantaine avec son numéro et son motif ; les lignes
  valides du même fichier sont conservées.

Les prix du fichier d'exemple sont **fictifs** et servent uniquement à illustrer le format.
