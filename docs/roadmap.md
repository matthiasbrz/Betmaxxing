# État et feuille de route

**Dernière mise à jour :** 2026-08-05 · **Version :** 0.3.2

---

## Terminé

### Tranche 1 — Audit, spécification, architecture, matrice des sources
- Dépôt audité (vide au départ, une seule branche, un commit initial).
- Architecture cible et décisions structurantes : `docs/architecture.md`, `docs/decisions.md`.
- Matrice des sources avec les points non vérifiables marqués `À vérifier` :
  `docs/source-matrix.md`.
- Protocole de validation préenregistré : `docs/validation-protocol.md`.
- Dictionnaire de données : `docs/data-dictionary.md`.

### Tranche 2 — Squelette exécutable, mode démo, scan de bout en bout
- Configuration centralisée, versionnée, avec empreinte reproductible et masquage des
  secrets.
- Couche domaine : vocabulaires fermés, entités immuables, identifiants canoniques,
  règles de temps UTC/Paris.
- Interfaces fournisseurs + pack de démonstration déterministe et sans clé.
- Ingestion : déduplication, assemblage des books, quarantaine.
- Moteur : 4 méthodes de retrait de marge, EV, EV prudente, cote minimale, sensibilité,
  incertitude de Wilson, qualité des données, confiance explicable, mise fractionnelle
  plafonnée, grille d'éligibilité conjonctive, explication déterministe sourcée.
- Baselines football (Dixon-Coles) et tennis (Elo → modèle hiérarchique de points), avec
  marchés dérivés cohérents.
- Persistance : schéma, snapshots append-only, ingestion idempotente, archivage des scans.
- CLI (`scan`, `explain`, `providers`, `config`, `odds import`, `db …`).
- API FastAPI avec OpenAPI exploitable, export JSON et CSV.
- Import manuel horodaté (voie Winamax).
- Challenge — Montante complet, désactivé par défaut.
- Planificateur (planification pure + exécution, verrou, idempotence).
- Métriques d'évaluation du protocole.
- **474 tests**, ruff et mypy propres, CI configurée.

### Tranche 2 bis — Assainissement du socle (instruction 02)
- **Ordonnanceur** : ledger SQL, réclamation atomique, baux, reprise après crash,
  jalons cadrés sur leur événement, rattrapage borné. Le `tick` précédent ne pouvait
  jamais trouver de travail.
- **Collecte unifiée** : `AcquisitionService` utilisé par API, CLI et planificateur ;
  événements et snapshots persistés **avant** consultation d'un modèle.
- **Incertitude honnête** : D-019 supersède D-008. Statut explicite, bornes et EV
  prudente nullables, `UNCERTAINTY_UNAVAILABLE` hors démo.
- **Invariants du domaine** : identité d'événement opaque et stable, lignes en
  `Decimal`, EV issue d'une distribution de règlement, statut de modèle lu au registre.
- **Challenge** : désactivé par défaut, persistant, versionné, fraction par défaut à 25 %.
- **The Odds API** : adaptateur `IMPLEMENTED_UNVERIFIED`, testé sur contrats locaux.
- **Qualité** : lint et format sur tout le dépôt, `constraints.txt`, migrations testées
  depuis le schéma de référence (base vide seulement — c'est l'une des lacunes que
  l'audit a relevées).
- **670 tests**, dont 22 tests de caractérisation écrits avant correction.

> **Cette tranche n'a pas été validée.** Un audit indépendant a montré que plusieurs
> garanties annoncées ci-dessus n'étaient pas tenues par le code : la commande `pytest`
> de la CI échouait à la collecte, l'avertissement Starlette/httpx était filtré et non
> résolu, la migration échouait sur toute base contenant un Challenge, l'ordonnanceur
> pouvait affamer un job dû et accepter l'acquittement d'un détenteur de bail périmé,
> un jalon analysait zéro événement, une panne fournisseur était acquittée en succès,
> le budget journalier n'était pas appliqué, cinq marchés étaient cartographiés sans
> être demandés, et une identité ambiguë rattachait les cotes au premier candidat.
> La tranche 2 ter ci-dessous ferme ces points.

### Tranche 2 ter — Fermeture des anomalies P0/P1 (instruction 02 bis)
- **Suite reproductible** : `pytest` et `python -m pytest` collectent et exécutent
  exactement la même suite (804 tests). Les fabriques partagées vivent dans
  `tests/helpers.py`, rendu importable par `pythonpath = ["tests"]`.
- **Avertissement Starlette/httpx supprimé à la source** : `httpx2` est installé, le
  filtre `ignore:Using \`httpx\` with \`starlette.testclient\`` a été retiré, et
  `pytest -W error` passe sans exception.
- **Migrations sûres avec des données** : `challenges.version` / `bank_cents` sont
  ajoutées nullables, backfillées depuis le dernier palier réglé (ou la banque
  initiale), vérifiées, puis rendues NOT NULL. Un document inexploitable **refuse** la
  migration en nommant la ligne, ou part en quarantaine sur consentement explicite.
  `participant_pair_key`, `event_source_map` et `line_canonical` sont backfillés,
  idempotents, et refusent les collisions.
- **Ordonnanceur** : états réclamables filtrés en SQL avant `ORDER BY`/`LIMIT`,
  jeton de possession (`claim_token`) exigé pour tout achèvement, reprise d'un bail
  expiré par compare-and-swap, `enqueue` idempotent face à une insertion concurrente,
  `next_attempt_at` contre les boucles de retry.
- **Résultat d'exécution typé** : succès / échec retryable / échec final / budget
  atteint. Un scan d'erreur est **persisté**, et un job n'est `SUCCEEDED` que sur un
  succès explicite.
- **Jalons** : la découverte résout l'identité avant de planifier, donc le `scope_id`
  d'un jalon et le filtre d'analyse vivent dans le même espace d'identifiants. T−24 h
  et le rattrapage sous deux heures sont couverts.
- **Identité** : `ResolvedEvent` porte `RESOLVED`/`CREATED`/`AMBIGUOUS`/`REJECTED`. Une
  ambiguïté ne retourne aucun identifiant, ne crée aucune correspondance, ne rattache
  aucun snapshot, et part en file de revue (`event_mapping_reviews`). Le rapprochement
  consulte compétition, saison, stage et alias fournisseur.
- **Fournisseur** : ledger de réservation persistant (réservation avant *chaque*
  tentative, rapprochement avec `x-requests-last`, libération sur erreur de transport),
  taxonomie complète des réponses, découverte `/sports`, marchés additionnels
  réellement demandés par événement, estimateur de coût historique **hors ligne**.
- **804 tests**, dont 114 écrits en rouge avant correction.

> **Cette tranche n'était pas validée non plus.** Son rapport affirmait les 25
> critères satisfaits puis reconnaissait que le critère 8 ne tenait que sur SQLite —
> ce qui, par la règle de l'instruction, interdit de déclarer la tranche terminée.
> Un audit a confirmé dix points : aucun test PostgreSQL réel, une réservation
> budgétaire non atomique hors SQLite, tout timeout compté à zéro, `renew_lease()`
> jamais appelé, un report budgétaire de six heures présenté comme « après
> minuit », `double_chance_h1` non prouvé, `totals` tennis demandé et facturé alors
> qu'il est déclaré désactivé, revues et alias inexploitables sans SQL, un arrondi
> monétaire binaire là où le domaine promet `ROUND_HALF_UP`, et un downgrade qui
> perd `events.source_ids`.

### Tranche 2 quater — Fermeture des réserves de fiabilité (instruction 02 ter)
- **PostgreSQL réel en CI** : service `postgres:16`, 24 tests de concurrence avec
  sessions distinctes et barrières. Une étape échoue si la suite est *skippée*.
- **Budget journalier réellement atomique** : bucket `(provider, day_utc)` mis à
  jour par UPDATE conditionnel (D-040). Deux réservations concurrentes qui tiennent
  isolément ne peuvent plus dépasser ensemble le plafond. Invariant vérifiable par
  `betmaxxing budget audit`.
- **Comptabilité prudente des erreurs réseau** : seul un envoi *démontrablement*
  impossible libère la réservation ; un timeout de lecture reste facturé (D-041).
- **Heartbeat de bail branché** : `LeaseGuard` renouvelle au tiers du bail, s'arrête
  et se joint dans un `finally`, et une perte de bail empêche tout acquittement. Un
  travail plus long que deux baux ne s'exécute **qu'une fois** (D-042).
- **Outbox de notification** : `(job_id, alert_key, channel)` unique, donc une
  reprise ne peut pas notifier deux fois. Un effet déjà envoyé n'est pas annulable —
  l'outbox empêche le second, pas le premier.
- **Sémantique budgétaire honnête** : report au prochain reset **UTC** avec gigue
  déterministe, aucun attempt consommé, jamais `FAILED_FINAL` ; `SKIPPED_BUDGET`
  quand l'occurrence perd sa valeur avant le reset (D-043).
- **Marchés par sport** : tennis groupé = `h2h` seul, `totals` tennis ni demandé ni
  budgété ; les cinq marchés football additionnels sont demandés, mappés et
  persistés sur fixture, `double_chance_h1` compris (D-044).
- **Arrondi monétaire décimal** : `to_cents` en `Decimal` + `ROUND_HALF_UP`, réutilisé
  par la migration (D-045). Cela corrige aussi un défaut du domaine : `1.005` donnait
  100 centimes.
- **Downgrade sans perte** : les correspondances repassent dans `events.source_ids`
  avant que la table soit supprimée, ou le downgrade refuse (D-046).
- **Revues et alias administrables** : `betmaxxing identity reviews list|show|resolve`
  et `identity aliases import|list`, sans résolution automatique (D-047).
- **972 tests** au total : 948 sur SQLite et **24 sur PostgreSQL 16 réel**. 94 ont été
  écrits en rouge sur `5d2109f` avant correction.

---

## Statuts honnêtes

| Composant | Statut | Ce que cela veut dire |
|---|---|---|
| Ordonnanceur | ✅ **fonctionnel** | Ledger durable, anti-starvation, fencing et heartbeat testés sur **SQLite et PostgreSQL 16 réel**. Sûr multi-workers contre une même base ; rien ne coordonne plusieurs bases |
| Collecte + persistance | ✅ **fonctionnel** | Les trois chemins persistent événements, snapshots et scan, y compris un scan d'erreur |
| Budget fournisseur | ✅ **appliqué, atomique** | Bucket journalier par UPDATE conditionnel, prouvé par courses PostgreSQL réelles. Un coût incertain reste facturé |
| Marchés additionnels | ◐ **collectés, non vérifiés** | Les **cinq** marchés football sont demandés, mappés et persistés **sur fixture**, `double_chance_h1` compris. `totals` tennis n'est pas demandé. Aucun appel réel ne l'a confirmé : `additional` n'a jamais été exécuté |
| Revues d'identité et alias | ✅ **administrables** | CLI `betmaxxing identity …`. Aucune résolution automatique ; l'opérateur et sa décision sont conservés |
| Historique | ◐ **estimateur seul** | Interface et estimateur de coût hors ligne. Aucun téléchargement implémenté |
| Modèles football / tennis | ⚠️ `BACKTEST_ONLY` | Produisent des probabilités ; aucune validation |
| Incertitude | ⛔ `UNAVAILABLE` | Aucune méthode défendable. `SYNTHETIC` en démo seulement |
| Mode `paper` / `live_analysis` | ⚠️ **ne publie rien** | Conséquence directe de la ligne précédente. C'est correct |
| Challenge — Montante | ⚠️ `PARTIAL`, désactivé | Persistant et testé, mais **désactivé par défaut** ; aucune validation d'usage réel |
| `TheOddsApiProvider` | ⚠️ `IMPLEMENTED_UNVERIFIED` | Contrats locaux verts. 6 appels réels le 2026-08-07 (4 gratuits, 2 payants, 2 crédits) ont validé auth, endpoint payant et comptabilité du coût ; le **mapping des cotes reste non vérifié en réel** (`winamax_fr` absent des 2 événements testés). Critères de qualification préenregistrés en D-071, aucun satisfait |
| Activation fournisseur | ◐ **partiellement exercée en réel** | Connectivité, authentification, endpoint payant, comptabilité du coût, chaînage et signature : **vérifiés en réel** (4 requêtes gratuites + 2 payantes, 2 crédits, quota 494 → 492). Mapping et fraîcheur : **non obtenus en réel**, seulement `OFFLINE_CONTRACT_VERIFIED` sur fixture. L'état courant se lit avec `activation status`, qui sépare les cinq dimensions |
| Couverture `winamax_fr` sur `soccer_spl` | ⛔ **absente** sur les 2 événements testés | Constat daté et borné : deux événements, deux instants. Aucune généralisation au fournisseur |
| Couverture Winamax | ❓ **non vérifiée** | Annoncée par la documentation officielle (lue le 2026-08-05) ; non confirmée par un appel |
| Migrations historiques | ✅ **figées** | `3ce123580afa` et `b7c1e9d24a10` n'importent plus le paquet applicatif ; rejouables à l'identique et équivalence testée |
| Interface web | ⛔ non commencée | Tranche 6 |

---

## Non fait — et pourquoi

| Élément | Raison |
|---|---|
| Vérification réelle du mapping The Odds API | Exige un événement où `winamax_fr` est effectivement coté. Les deux tentatives SPL du 2026-08-07 ne l'ont pas trouvé. Chaque nouvelle tentative demande une autorisation explicite et distincte. Runbook : `docs/provider-activation.md` |
| Promotion de l'adaptateur en `VERIFIED` | Une activation réussie est une preuve **limitée** (un endpoint, un bookmaker, une compétition, un événement, un marché, un instant). Les critères de promotion sont désormais **écrits et préenregistrés** — `PROVIDER_VALIDATION_PROTOCOL_VERSION = 1`, `docs/provider-validation-protocol.md`, D-071 — et **aucun n'est encore satisfait** : la campagne n'a pas été exécutée. `activation status` dit précisément ce qui manque. La promotion elle-même reste une décision humaine ; la machine plafonne à `CRITERIA_MET_AWAITING_HUMAN_REVIEW` |
| Exécution de la campagne de qualification | Préparée en deux pistes (parser générique, couverture Winamax), bornée à **12 requêtes et 16 crédits maximum**, avec arrêts anticipés écrits. Chaque appel exige une autorisation humaine distincte ; aucun n'a été lancé dans cette tranche |
| Méthode d'incertitude réelle | Nécessite des données historiques : bootstrap paramétrique/clusterisé + étude de couverture (D-019) |
| Endpoints historiques (payants) | Hors périmètre : aucun appel payant sans action de l'utilisateur |
| Pipeline d'entraînement | Nécessite des données historiques ; les modèles consomment des paramètres fournis |
| Exécution du protocole de validation | Nécessite l'historique ; le protocole est figé et prêt |
| Interface web React/Vite | Tranche 6 ; CLI et API couvrent les usages actuels |
| Promotion d'un modèle | Nécessite le protocole exécuté ; aucun jeu de test ouvert |
| SMS | Interface seulement — coût par message, activation délibérée requise |

---

## Blocages

1. **Couverture fournisseur non vérifiée.** L'adaptateur The Odds API est complet et
   testé sur contrats locaux ; deux appels réels du 2026-08-07 n'ont pas trouvé `winamax_fr`
   apparaît sur les événements visés. Seule une action de l'utilisateur (sa clé, son
   accord) peut lever ce point.
2. **Aucune donnée historique.** Sans elle : pas d'entraînement, pas de protocole
   exécuté, pas de méthode d'incertitude ajustée. Donc aucun modèle ne sort de
   `BACKTEST_ONLY`, et `paper`/`live_analysis` ne publient rien.

Ces deux blocages nécessitent une action ou des données extérieures. Ils ne sont **pas**
la seule chose qui reste : voir « Limites internes connues » ci-dessous.

## Gouvernance du dépôt

| Fait | Niveau de preuve |
|---|---|
| Branche par défaut `claude/prompt-markdown-file-wag9jw` exposée comme protégée | **observé** — `protected: true` relu depuis GitHub |
| Mécanisme : ruleset actif, sans protection classique parallèle | **attesté par le propriétaire** — les endpoints REST de protection et de rulesets répondent `403` ici |
| Sous-règles : PR obligatoire, 0 approbation, checks requis `quality` et `secrets`, mode strict, conversations résolues, administrateurs inclus, sans bypass, force-push et suppression interdits | **attesté par le propriétaire**, non relu — ne pas présenter comme vérifié par l'API |
| Gouvernance versionnée : `CONTRIBUTING.md`, `SECURITY.md`, `.github/pull_request_template.md`, avec tests statiques | **fait** |
| Premier exercice du flux PR-only | **fait** — PR #1 fusionnée par merge commit `df846003`, cinq commits audités conservés, branche de travail non supprimée |
| CI post-fusion sur la branche par défaut | **observé** — run #24 `31308176620`, événement `push`, tentative 1, `quality = success`, `secrets = success`, aucune étape fonctionnelle skippée |

Le flux est désormais : branche de travail → PR vers la branche par défaut →
`quality` et `secrets` verts → branche à jour → conversations résolues → fusion sur
autorisation explicite du propriétaire. Aucun push direct sur la branche par défaut.

Cet exercice a coûté cinq commits et six audits successifs, dont quatre ont trouvé
une garantie surévaluée dans la documentation elle-même. Le résultat utile n'est pas
le flux — c'est que chaque revendication survivante a été mesurée.

Rappel de limite GitHub : un check requis est satisfait par `success`, `skipped`
**ou** `neutral`. La protection ne garantit donc pas à elle seule une conclusion
`success` ; les gardes du workflow restent nécessaires. Voir D-070.

## Limites internes connues

Rien ici ne dépend d'un tiers ; ce sont des choix de périmètre de cette tranche.

| Limite | Conséquence |
|---|---|
| Un effet externe déjà envoyé n'est pas annulable | L'outbox empêche un **second** envoi après reprise, pas le premier |
| Aucun notifieur n'est branché dans le runner | L'outbox et le contrôle de propriété existent et sont testés ; le canal reste à câbler |
| La revue d'ambiguïté n'a pas de route API | Elle s'administre en CLI ; l'interface web est la tranche 6 |
| Le fichier d'alias doit être constitué à la main | L'import est prêt et testé ; aucun catalogue n'est fourni |
| PostgreSQL n'est exercé que sur un seul nœud | Rien ne coordonne plusieurs bases, et ce n'est pas prévu |
| Aucune sortie web | Tranche 6 |

---

## Prochaine action recommandée

1. **Exécuter l'activation, étape par étape, après validation de cette tranche.**
   L'outillage est prêt et plafonné (`docs/provider-activation.md`) ; l'ouverture
   d'un accès réel reste une décision séparée. Trois autorisations distinctes sont
   nécessaires, dans cet ordre : `discover` (0 crédit), puis `core` (1 crédit),
   puis `additional` (5 crédits). Rien ne s'enchaîne tout seul.
2. **Lire les CGU de The Odds API** et trancher le droit de rétention des réponses
   brutes. En attendant, seul le normalisé est conservé.
3. **Constituer un jeu historique** — sans lui, ni entraînement, ni incertitude, ni
   promotion.

Sans dépendance externe : démarrer l'interface web sur l'API existante (tranche 6).

---

## Suite des tranches

| # | Tranche | État |
|---|---|---|
| 1 | Audit, spécification, architecture, matrice | ✅ |
| 2 | Squelette, mode démo, scan de bout en bout | ✅ |
| 3 | Ingestion réelle, snapshots immuables | ◐ adaptateur fait, **non vérifié** |
| 4 | Baseline football, backtest, calibration | ⛔ bloquée (données historiques) |
| 5 | Baseline tennis, marchés dérivés | ✅ modèle fait ; validation bloquée |
| 6 | Éligibilité, explications, dashboard | ◐ moteur fait ; dashboard à faire |
| 7 | Scheduler et notifications | ✅ scheduler refait et testé ; notifications à éprouver |
| 8 | Challenge — Montante | ◐ `PARTIAL` — persistant, désactivé par défaut |
| 9 | Durcissement, CI, sauvegarde, déploiement | ◐ CI et guides faits |
| 10 | Forward test `paper` | ⛔ bloquée (tranches 3 et 4) |
