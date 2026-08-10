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

## Reçus d'activation fournisseur — schéma v4

Ces fichiers **ne sont pas** en base : ce sont des JSON locaux signés sous
`.activation-receipts/` (répertoire gitignoré, jamais versionné, sans contrepartie
distante). Ils sont décrits ici parce qu'ils constituent le seul journal d'audit des
appels réels au fournisseur.

| Champ | Sens |
|---|---|
| `schema_version` | 4 pour tout reçu écrit désormais. Les v2 et v3 restent **lus** et honorés comme autorité de chaînage, jamais réécrits ni re-signés, et ne qualifient plus rien (D-072) ; v1 et inconnues sont refusées |
| `qualification_protocol_version` / `provider_adapter_evidence_version` | v4 seulement : sous quel protocole ce reçu serait jugé, et quel parser l'a produit. **Couverts par la signature** — altérer l'un invalide le reçu. Des entiers **réels** : un booléen ou une chaîne numérique rend le reçu malformé, jamais admissible (D-073) |
| `receipt_id` | identifiant local du reçu, **complet dans le nom de fichier** et créé de façon exclusive : un reçu n'est jamais remplacé silencieusement. Deux reçus courants de même identifiant et de contenus signés différents sont un conflit de preuve (D-073) |
| `parent_receipt_id` / `parent_schema_version` | le reçu qui a autorisé cette étape, et sous quel schéma il a été accepté |
| `command`, `status`, `recorded_at`, `expires_at` | étape, issue terminale, instant, péremption (6 h) |
| `sport_key`, `bookmaker` | portée demandée |
| `event_tag` / `event_tags` | identifiant(s) d'événement en **HMAC local**, jamais en clair. Volontairement visible dans `bookmaker_coverage_observations` et nulle part ailleurs : c'est ce qui borne une observation à un événement sans le nommer (D-062). Ce n'est pas l'identifiant fournisseur et ne doit jamais être présenté comme tel |
| `window_from`, `window_to` | fenêtre déclarée |
| `endpoints`, `endpoint`, `attempts` | endpoints **templatés** (jamais d'URL avec query string) et nombre exact de requêtes tentées. `attempts` est **obligatoire** et cohérent avec le drapeau réseau : `network_attempted = false` impose `0`, `true` impose `≥ 1` (D-074) |
| `network_attempted`, `may_have_reached_provider` | une socket a-t-elle été ouverte ; la requête a-t-elle pu être servie (un timeout de lecture vaut « oui »). Exactement `true` ou `false` : une valeur absente ou mal typée n'établit **rien**, et en particulier ne prouve pas qu'un appel n'est jamais parti (D-074) |
| `estimated_credits` | borne calculée avant l'appel |
| `observed_credits` | `x-requests-last`, ou **`null`** s'il est absent, illisible ou négatif — jamais remplacé par zéro |
| `accounted_credits` | ce qui est retenu : l'observation si elle existe, l'estimation sinon |
| `quota_remaining` | `x-requests-remaining` de la dernière réponse, ou `null` |
| **`bookmaker_state`** | `core` / `additional` seulement. `OBSERVED` ou `NOT_RETURNED` — dimension **indépendante** de l'état des marchés. **Absent** d'un reçu `discover` : `/events` ne renvoie aucune information de bookmaker, donc il n'y a rien à constater, et un défaut à `NOT_RETURNED` se lirait comme un constat |
| `markets_requested` | portée de marchés de l'appel |
| **`market_states`** | un état par marché demandé, **total** — pour un reçu dont les marchés ont réellement été classifiés : `NOT_EVALUATED_BOOKMAKER_ABSENT`, `NOT_RETURNED`, `OBSERVED_REJECTED` ou `OBSERVED_MAPPED`. **Vide** pour un reçu dont l'appel a échoué avant toute classification — phase `ATTEMPTED_UNCLASSIFIED` — et vide *parce que rien n'a été regardé*, ce qui interdit de le lire comme une observation (D-074) |
| `markets_mapped` / `markets_rejected` / `markets_absent` / **`markets_not_evaluated`** / `markets_observed` | projections strictes de `market_states`, partitionnant `markets_requested` exactement une fois — aucune ne peut le contredire |
| `freshness` | âge **en secondes** par marché, dérivé de l'horodatage que v4 envoie pour cette forme de réponse |
| `selections_mapped` | sélections retenues par le parseur réel |
| `mapping_rejections` | motifs généralisés (tronqués avant le premier `:`), sans nom ni valeur |
| **`events_returned`** / **`events_in_window`** / **`events_admissible`** | `discover` seulement. Entonnoir : reçus avant filtrage temporel, après la fenêtre stricte, après validation et déduplication. Invariants `0 ≤ admissible ≤ in_window ≤ returned` et `admissible == len(set(event_tags))`. Des entiers, jamais un détail par événement |
| `adapter_status`, `model_impact` | rappels constants : l'adaptateur n'est pas promu, aucun modèle n'est affecté |
| `signature` | HMAC-SHA256 sur le JSON canonique (clés triées, séparateurs serrés), vérifié par `hmac.compare_digest` avant tout usage comme précondition |

Ne s'y trouvent **jamais** : la clé API, le secret de signature, une URL non
expurgée, un corps de réponse brut, une cote, un nom de participant, un horaire
individuel, ni l'identifiant d'événement en clair.

## Les cinq dimensions de `activation status` (D-062, resserrées par D-074)

Cinq faits distincts qu'un seul libellé ne porte pas, plus le bloc de qualification
ci-dessous. Distinct ne veut pas dire indulgent : depuis D-074 chacune lit ses reçus
avec la même rigueur que le bloc strict, et aucune ne peut employer un libellé positif
sur une preuve que celui-ci rejette pour le même fait.

| Champ | Type | Sens |
|---|---|---|
| `adapter_state` | `str` | `IMPLEMENTED_UNVERIFIED`, quelle que soit l'issue de tout le reste |
| `execution_state` | `str` | jusqu'où la séquence est allée sur cette installation : `NO_NETWORK_ATTEMPTED`, `DISCOVERY_ATTEMPTED`, `CORE_ATTEMPTED`, `ADDITIONAL_ATTEMPTED` |
| `connectivity_and_cost_proof` | `str` | `NOT_EXERCISED`, `EXERCISED_CONFORMING`, `EXERCISED_UNESTABLISHED` ou `EXERCISED_NONCONFORMING`, par la précédence `NONCONFORMING > UNESTABLISHED > CONFORMING > NOT_EXERCISED`. `EXERCISED_UNESTABLISHED` existe parce qu'un coût non établi n'est ni conforme ni un écart (D-074) |
| `paid_call_cost_census` | `dict[str, int]` | le recensement dont le champ précédent est dérivé, sur **la même** population : toute tentative payante réelle du disque, protocoles antérieurs compris, sans déduplication. `COST_CONFORMITY` en compte une plus étroite, d'où des nombres qui peuvent légitimement différer |
| `paid_call_cost_census_population` | `str` | cette population, écrite en clair, pour que l'écart avec le critère ne se lise pas comme une contradiction |
| `mapping_freshness_proof` | `str` | `NOT_OBTAINED_LIVE`, `OFFLINE_CONTRACT_VERIFIED` ou `OBTAINED_LIVE`. `OBTAINED_LIVE` exige une observation de mapping **saine** — statut positif, bookmaker observé, marché cartographié, fraîcheur valide, contrat satisfait, aucune contradiction — jamais un simple `selections_mapped > 0` (D-074) |
| `paid_activation_state` | `str` | `PREPARED_NOT_EXECUTED`, `PAID_ATTEMPT_INCONCLUSIVE`, `CORE_EXECUTED_NO_COVERAGE`, `CORE_EXECUTED_COVERAGE_OBSERVED` ou `ADDITIONAL_EXECUTED`. `PAID_ATTEMPT_INCONCLUSIVE` nomme un appel payant réellement parti qui n'a établi ni couverture ni mapping ; le confondre avec « exécuté sans couverture » affirmait qu'on avait regardé (D-074) |
| `bookmaker_coverage_observations` | `list[dict]` | observations de portée stricte — un fournisseur, un bookmaker, une compétition, un événement tagué, un instant. N'y figurent que des reçus dont la phase a réellement répondu à la question du bookmaker, structurellement valides et non contradictoires : une observation est une **réponse**, pas la trace d'une tentative |
| `accounted_credits_total` | `int` | somme des `accounted_credits`, en n'additionnant que des entiers réels **non négatifs**. Ni booléen, ni chaîne numérique, ni négatif : c'est un chiffre de dépense lu avant de décider d'en dépenser plus |
| `verified_receipts` / `unverifiable_receipts` | `int` | population de l'audit local D-062. `unverifiable_receipts` compte aussi les liens symboliques, les cibles hors répertoire et les répertoires nommés `*.json`, jamais ouverts (D-074) |
| `receipt_directory` | `str` | chemin **local**, gitignoré et sans distant. Le supprimer remet la preuve à zéro, ce qui est voulu |

## Bloc de qualification fournisseur (D-071, corrigé par D-072, D-073 puis D-074)

Produit par `qualification.evaluate()` et recopié champ par champ dans la sortie
de `activation status` — jamais étalé, pour qu'une clé du protocole ne puisse pas
écraser un champ D-062 du même nom. Calcul pur : aucun réseau, aucune clé, aucune
configuration, aucun reçu modifié. Le protocole complet est dans
`docs/provider-validation-protocol.md`.

| Champ | Type | Sens |
|---|---|---|
| `qualification_protocol_version` | `int` | version des seuils et des règles d'admissibilité appliqués — `4` ; deux versions ne se comparent pas |
| `qualification_adapter_evidence_version` | `int` | version du parser sous laquelle une preuve compte — `1` |
| `qualification_evidence_not_before` | `str` | instant UTC littéral avant lequel un reçu est historique et jamais qualifiant |
| `qualification_state` | `str` | `INSUFFICIENT_EVIDENCE`, `EVIDENCE_CONFLICT` ou `CRITERIA_MET_AWAITING_HUMAN_REVIEW`. Il n'existe pas de `VERIFIED` |
| `criteria_results` | `list` | un élément par critère, ordre stable |
| `criteria_results[].criterion_id` | `str` | identifiant stable, ex. `CORE_MAPPING_FOOTBALL` |
| `criteria_results[].passed` | `bool` | seuils atteints pour ce critère seul |
| `criteria_results[].observed` | `dict` | compteurs après déduplication : `events`, `competitions`, `utc_days`. Pour `COST_CONFORMITY` : les quatre catégories de coût `conforming_paid_calls`, `nonconforming_paid_calls`, `paid_calls_with_unestablished_cost`, `paid_calls_that_never_left` — exhaustives et disjointes sur les **tentatives payantes réelles du protocole courant**, dédupliquées ; les trois premières doivent valoir `≥ 6`, `0` et `0` |
| `criteria_results[].required` | `dict` | seuils préenregistrés, mêmes clés |
| `criteria_results[].missing` | `list[str]` | ce qui manque, en clair, ou vide |
| `criteria_results[].scope` | `str` | sport, commande, marché, âge maximal |
| `criteria_results[].limit` | `str` | ce que le critère **n'**établit pas |
| `eligible_for_human_promotion_review` | `bool` | vrai seulement à `CRITERIA_MET_AWAITING_HUMAN_REVIEW`. N'autorise aucune promotion |
| `evidence_conflicts` | `list[str]` | contradictions internes nommées ; non vide ⇒ échec fermé |
| `qualification_admissible_receipts` | `int` | synonyme conservé de `qualification_usable_receipts`, publié sous son nom d'origine pour que deux rapports restent comparables d'une version de protocole à l'autre |
| `qualification_usable_receipts` | `int` | reçus qui sont une preuve **courante** et lisible : v4, versions `4/1`, postérieurs à la date d'effet, bien formés, non contradictoires |
| `qualification_current_malformed_receipts` | `int` | reçus **courants** hors contrat structurel. Comptés à part de l'histoire : les ranger sous « historique » se lisait comme « produits sous un protocole antérieur », l'inverse de la vérité (D-074) |
| `qualification_current_contradictory_receipts` | `int` | reçus **courants** qui se contredisent eux-mêmes |
| `qualification_unknown_pair_receipts` | `int` | reçus courants portant un couple commande/statut absent de la table de phases versionnée `RECEIPT_PHASES` (D-074) |
| `qualification_historical_nonqualifying_receipts` | `int` | reçus valides et lisibles qui ne qualifient rien parce qu'ils viennent d'ailleurs : v2/v3, autre version de protocole ou d'adaptateur, antérieurs à la date d'effet, `recorded_at` inutilisable |
| `qualification_duplicate_excluded_receipts` | `int` | population **exclusive et prioritaire** : un `receipt_id` nommant deux contenus signés différents rend tous les exemplaires concernés inutilisables, quelle que soit leur sous-population. Calculé sur **l'ensemble** des reçus vérifiés (D-074) |
| `qualification_unverifiable_receipts` | `int` | fichiers comptés et **jamais lus** : signature invalide, schéma inconnu, v1, lien symbolique, cible hors répertoire, répertoire nommé `*.json`. Distinct du champ D-062 `unverifiable_receipts`, qui compte la même idée sur la population de l'audit local |
| `qualification_exact_duplicate_copies` | `int` | **dimension croisée**, pas une population : combien de reçus répètent byte pour byte un reçu déjà vu. Chacun reste dans la population de son contenu, et seuls les compteurs de diversité les dédupliquent |
| `qualification_population_equation` | `str` | l'équation de réconciliation, publiée en clair : reçus vérifiés + fichiers invérifiables = la somme des sept populations exclusives ci-dessus |
| `qualification_reasons` | `dict[str, int]` | taxonomie agrégée : `stale_schema`, `malformed_current_schema`, `duplicate_receipt_identifier`, `other_protocol_version`, `other_adapter_evidence_version`, `before_effective_instant`, `unusable_recorded_at`, `self_contradictory`, `unverified_or_unknown_schema`, `unknown_command_status_pair`. **Des comptes seulement** — aucun chemin, reçu, tag ni identifiant |

Aucun de ces champs ne porte de cote, de nom d'équipe, d'identifiant d'événement en
clair, de clé ni de payload. `adapter_state` reste `IMPLEMENTED_UNVERIFIED` quelle
que soit la valeur de ce bloc.
