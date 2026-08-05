# Dictionnaire de données

Tous les horodatages sont stockés en **UTC**. La conversion vers `Europe/Paris` a lieu
uniquement à l'affichage.

## `CanonicalEvent`

| Champ | Type | Description |
|---|---|---|
| `internal_id` | str | **Opaque et stable** (`evt_…`). Aucune sémantique temporelle : un report ne le change pas |
| `sport` | enum | `football`, `tennis` |
| `competition` | str | Libellé de la compétition tel que publié |
| `season` | str? | Saison, quand le fournisseur la donne. Signal de rapprochement : deux rencontres de la même paire dans deux saisons sont deux rencontres |
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
| `line` | Decimal? | Obligatoire sur over/under, interdit ailleurs. Lignes entières refusées |
| `line_canonical` | str? | Texte décimal normalisé : `2.5`, `2.50`, `2.500` → `2.5` |
| `key` | str | `market\|period\|line_canonical\|code` — **jamais** un rendu de float |

## `OddsSnapshot` (immuable, append-only)

| Champ | Type | Description |
|---|---|---|
| `provider` | str | Adaptateur ayant fourni la donnée |
| `bookmaker` | str | Book effectivement coté — jamais mélangé avec un autre |
| `event_internal_id` | str | Identité interne résolue |
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
| `model_id` | Identifiant du modèle |
| `model_version` | Version enregistrée |
| `validation_status` | Lu depuis `model_registry`, jamais codé en dur |
| `uncertainty` | Objet `UncertaintyEstimate` — voir ci-dessous |

## `UncertaintyEstimate` (D-019)

| Champ | Description |
|---|---|
| `method` | `none`, `synthetic_wilson_demo`, … |
| `status` | `SYNTHETIC` \| `UNAVAILABLE` \| `ESTIMATED` \| `VALIDATED` |
| `lower` / `upper` | **Nullables.** Absents quand le statut est `UNAVAILABLE` |
| `effective_sample_size` | **Nullable.** Uniquement pour une vraie proportion ou un substitut synthétique |
| `warning` | Texte visible, ex. `SYNTHETIC — NE PAS PARIER` |
| `half_width` | `None` sans bornes |

## `ValueAssessment`

| Champ | Formule / description |
|---|---|
| `implied_probability_raw` | `1 / o` |
| `implied_probability_novig` | Après retrait de marge, ou `None` si le marché n'est pas une partition complète |
| `devig_method` | Méthode appliquée, ou `None` |
| `win_probability` | Probabilité **inconditionnelle** de gagner |
| `push_probability` | Probabilité de remboursement (nul en DNB, ligne entière) |
| `conditional_win_probability` | `p_win / (p_win + p_loss)` — comparable au prix sans marge |
| `settlement_rule` | `WIN_LOSE`, `STAKE_REFUNDED_ON_PUSH`, … |
| `payoff_outcomes` | Distribution complète `(nom, probabilité, rendement net)` |
| `fair_odds` | `(p_win + p_loss) / p_win` — se réduit à `1/p` sans remboursement |
| `ev` | `Σ p(issue) × rendement_net(issue)` |
| `ev_conservative` | **Nullable.** `None` sans méthode d'incertitude utilisable |
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
| `status` | `CANDIDATES_FOUND`, `NO_BET` (= `NO_CANDIDATE`), `DATA_UNAVAILABLE` |
| `collection_status` | `OK`, `COLLECTED_NO_MODEL`, `NO_CANDIDATE`, `COVERAGE_MISSING`, `DATA_STALE`, `PROVIDER_ERROR` |
| `batch_id` | Lot de collecte dont proviennent les enregistrements |
| `warnings` | Avertissements fournisseur et erreurs partielles |
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
| `challenges` / `challenge_steps` | Challenge — Montante, avec `version` (concurrence optimiste) |
| `scheduler_jobs` | Occurrences du planificateur ; unique sur `(job_type, scheduled_for, scope_id)`. `claim_token` = jeton de possession exigé pour tout achèvement ; `next_attempt_at` = plancher de reprise (backoff d'échec **ou** frontière de reset budgétaire). États : `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `DEFERRED`, `SKIPPED_BUDGET` |
| `event_source_map` | `(provider, provider_event_id) → internal_id` — résolution autoritaire |
| `event_schedule_history` | Trace append-only des changements d'horaire et de statut |
| `participant_aliases` | Orthographes alternatives, unique sur `(sport, source, alias)` — un fournisseur ne peut plus évincer l'alias d'un autre. Consultée par le rapprochement ; **aucun import ne l'alimente aujourd'hui** |
| `event_mapping_reviews` | File de revue des identités ambiguës. Une ambiguïté n'écrit **que** ici : ni correspondance, ni événement, ni snapshot. `resolved_by` / `resolved_at` / `resolved_internal_id` conservent la décision humaine |
| `provider_budget_days` | **La** primitive de synchronisation du budget : une ligne par `(fournisseur, jour UTC)`, incrémentée par UPDATE conditionnel. Le détail ne sert plus de verrou |
| `provider_budget_ledger` | Journal d'audit : une ligne par tentative — coût réservé, coût constaté (`x-requests-last`), libération |
| `notification_outbox` | `(job_id, alert_key, channel)` unique. Réserver la ligne autorise **un** envoi ; une reprise du même job n'en autorise pas un second |
| `collection_batches` | Un lot de collecte, **même sans candidat** |
| `model_registry` | Statut de validation persistant par `(model_id, version)` |

## Contrat de stockage des dates

Tout est écrit en UTC. SQLite n'a pas de type conscient du fuseau, donc une valeur
relue est naïve : `from_storage()` la réattache à UTC. `ensure_utc()` continue de
**refuser** un datetime naïf venant d'un fournisseur ou d'un utilisateur — les deux
cas sont volontairement dans des fonctions distinctes pour que la lecture permissive
ne soit jamais atteignable depuis un chemin d'ingestion.
