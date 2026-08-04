# Dictionnaire de données

Tous les horodatages sont stockés en **UTC**. La conversion vers `Europe/Paris` a lieu
uniquement à l'affichage.

## `CanonicalEvent`

| Champ | Type | Description |
|---|---|---|
| `canonical_id` | str | Dérivé de (sport, date UTC, participants normalisés) |
| `sport` | enum | `football`, `tennis` |
| `competition` | str | Libellé de la compétition tel que publié |
| `stage` | str? | Tour ou journée (« R64 », « J3 ») |
| `surface` | str? | Tennis : `hard`, `clay`, `grass`, `carpet` |
| `sets_to_win` | int? | Tennis : 2 (bo3) ou 3 (bo5) |
| `home` / `away` | Participant | Équipe ou joueur |
| `start_time_utc` | datetime | Aware, UTC. Un datetime naïf est rejeté |
| `status` | enum | `scheduled`, `in_play`, `finished`, `postponed`, `cancelled`, `walkover`, `retired`, `unknown` |
| `mapping_ambiguous` | bool | Vrai si le rapprochement inter-sources n'a pas tranché |
| `source_ids` | dict | Identifiants d'origine, par fournisseur |

## `Selection`

Identité d'un pari. Deux sélections ne sont comparables que si **tous** ces champs
correspondent.

| Champ | Type | Description |
|---|---|---|
| `market` | enum | `1x2`, `draw_no_bet`, `double_chance`, `total_goals`, `match_winner`, `player_wins_a_set`, `total_games` |
| `period` | enum | `full_time`, `first_half` |
| `code` | str | Clé machine : `home`, `draw`, `away`, `over`, `under`, `home_or_draw`, … |
| `label` | str | Libellé **exact** du bookmaker, conservé verbatim |
| `line` | float? | Obligatoire sur over/under, interdit ailleurs. Lignes entières refusées |
| `key` | str | `market|period|line|code` — dérivé |

## `OddsSnapshot` (immuable, append-only)

| Champ | Type | Description |
|---|---|---|
| `provider` | str | Adaptateur ayant fourni la donnée |
| `bookmaker` | str | Book effectivement coté — jamais mélangé avec un autre |
| `event_canonical_id` | str | Rapprochement canonique |
| `event_source_id` | str | Identifiant chez la source |
| `selection` | Selection | Voir ci-dessus |
| `decimal_odds` | float | > 1.0, strictement |
| `currency` | str | Devise du book |
| `event_status` | enum | Statut au moment de l'observation |
| `provider_updated_at` | datetime? | Horodatage attribué par le fournisseur, si fourni |
| `observed_at` | datetime | Instant où le prix est réputé vrai |
| `received_at` | datetime | Instant de réception |
| `source_meta` | dict | Provenance (endpoint, fichier, ligne…) |
| `fingerprint` | str | SHA-256 de (provider, book, event, selection, cote, instant) |
| `implied_probability_raw` | float | `1 / o` — **marge incluse** |

## `MarketBook`

Prix d'un même (événement, marché, période, ligne) chez **un seul** bookmaker.

| Champ | Description |
|---|---|
| `overround` | Somme des probabilités implicites brutes ; 1,05 = book à 5 % |
| `margin` | `overround − 1` |

## `ProbabilityEstimate`

| Champ | Description |
|---|---|
| `probability` | Probabilité du modèle, dans (0, 1) |
| `lower` / `upper` | Bornes de l'intervalle (Wilson) |
| `effective_sample_size` | Information effective derrière l'estimation |
| `model_id` | Identifiant et version du modèle |
| `validation_status` | `BACKTEST_ONLY`, `PAPER_VALIDATED`, `LIVE_ANALYSIS` |
| `half_width` | `(upper − lower) / 2` — comparé à `max_prob_half_width` |

## `ValueAssessment`

| Champ | Formule / description |
|---|---|
| `implied_probability_raw` | `1 / o` |
| `implied_probability_novig` | Après retrait de marge, ou `None` si le marché n'est pas une partition complète |
| `devig_method` | Méthode appliquée, ou `None` |
| `fair_odds` | `1 / p` |
| `ev` | `p · o − 1` |
| `ev_conservative` | `p_borne_basse · o − 1` |
| `min_acceptable_odds` | `(1 + seuil) / p` |
| `ev_sensitivity_per_odds_tick` | `p × 0,01` |
| `overround` | Overround du book, ou `None` si incomplet |

## `DataQuality`

Score composite dans [0, 1] avec ses composantes.

| Composante | Poids | Signification |
|---|---|---|
| `freshness` | 0,30 | Décroît linéairement jusqu'à la limite de péremption |
| `market_completeness` | 0,25 | Sélections cotées / attendues |
| `event_mapping` | 0,20 | 0 si `mapping_ambiguous` |
| `feature_completeness` | 0,15 | Part des entrées du modèle réellement disponibles |
| `source_agreement` | 0,10 | Accord inter-sources |

## `Candidate`

| Champ | Description |
|---|---|
| `candidate_id` | Dérivé de (scan, événement, sélection, book) |
| `odds_age_seconds` | Ancienneté de l'observation au moment du scan |
| `confidence` | Score explicable + composantes + facteurs limitants |
| `evidence` | 2 à 5 éléments, chacun avec **source et date** |
| `risks` | Risques concrets et vérifiables |
| `missing_information` | Ce que le moteur sait ne pas savoir |
| `invalidation_conditions` | Ce qui ferait cesser d'être un candidat |
| `odds_movement` | Trail chronologique des prix |
| `stake` | Mise simulée, ou zéro avec sa raison |
| `config_fingerprint` | Empreinte de la configuration appliquée |

## `ScanResult`

| Champ | Description |
|---|---|
| `status` | `CANDIDATES_FOUND`, `NO_BET`, `DATA_UNAVAILABLE` |
| `window` | `{from, to}` en UTC |
| `data_health` | État des fournisseurs et compteurs |
| `candidates` | Triés par EV décroissante |
| `rejections` | Chaque sélection écartée, avec son code et son détail |
| `rejections_summary` | Comptage par code |
| `thresholds` | Seuils exacts appliqués |
| `config_fingerprint` | Empreinte reproductible |
| `disclaimer` | Avertissement, toujours présent |

## Tables

| Table | Particularité |
|---|---|
| `events` | Upsert |
| `odds_snapshots` | **Append-only**, `fingerprint` UNIQUE → ingestion idempotente |
| `scan_runs` | Document complet du scan pour reproduction |
| `candidates` | Vue aplatie + document |
| `rejections` | Codes et détails |
| `alerts` | Ledger de déduplication des notifications |
| `challenges` / `challenge_steps` | Challenge — Montante |
