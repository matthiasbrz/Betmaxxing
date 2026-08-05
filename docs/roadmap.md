# État et feuille de route

**Dernière mise à jour :** 2026-08-05 · **Version :** 0.3.1

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

---

## Statuts honnêtes

| Composant | Statut | Ce que cela veut dire |
|---|---|---|
| Ordonnanceur | ✅ **fonctionnel** | Ledger durable, anti-starvation et fencing testés. Sûr multi-workers contre **une seule base SQLite** ; le chemin PostgreSQL (`SKIP LOCKED`) est écrit mais **non exercé en CI** |
| Collecte + persistance | ✅ **fonctionnel** | Les trois chemins persistent événements, snapshots et scan, y compris un scan d'erreur |
| Budget fournisseur | ✅ **appliqué** | Réservation persistante avant chaque tentative ; plafonds scan et jour opposables entre workers d'une même base |
| Marchés additionnels | ◐ **collectés, non vérifiés** | DNB, double chance et mi-temps sont réellement demandés et persistés **sur fixture** ; aucun appel réel ne l'a confirmé |
| Historique | ◐ **estimateur seul** | Interface et estimateur de coût hors ligne. Aucun téléchargement implémenté |
| Modèles football / tennis | ⚠️ `BACKTEST_ONLY` | Produisent des probabilités ; aucune validation |
| Incertitude | ⛔ `UNAVAILABLE` | Aucune méthode défendable. `SYNTHETIC` en démo seulement |
| Mode `paper` / `live_analysis` | ⚠️ **ne publie rien** | Conséquence directe de la ligne précédente. C'est correct |
| Challenge — Montante | ⚠️ `PARTIAL`, désactivé | Persistant et testé, mais **désactivé par défaut** ; aucune validation d'usage réel |
| `TheOddsApiProvider` | ⚠️ `IMPLEMENTED_UNVERIFIED` | Contrats locaux verts ; **aucun appel réel** |
| Couverture Winamax | ❓ **non vérifiée** | Annoncée par la documentation ; non confirmée |
| Interface web | ⛔ non commencée | Tranche 6 |

---

## Non fait — et pourquoi

| Élément | Raison |
|---|---|
| Vérification réelle de The Odds API | Nécessite la clé de l'utilisateur et son accord explicite. `scripts/smoke_the_odds_api.py` est prêt |
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
   testé sur contrats locaux, mais aucun appel réel n'a confirmé que `winamax_fr`
   apparaît sur les événements visés. Seule une action de l'utilisateur (sa clé, son
   accord) peut lever ce point.
2. **Aucune donnée historique.** Sans elle : pas d'entraînement, pas de protocole
   exécuté, pas de méthode d'incertitude ajustée. Donc aucun modèle ne sort de
   `BACKTEST_ONLY`, et `paper`/`live_analysis` ne publient rien.

Ces deux blocages nécessitent une action ou des données extérieures. Ils ne sont **pas**
la seule chose qui reste : voir « Limites internes connues » ci-dessous.

## Limites internes connues

Rien ici ne dépend d'un tiers ; ce sont des choix de périmètre de cette tranche.

| Limite | Conséquence |
|---|---|
| Le chemin `SKIP LOCKED` PostgreSQL n'est pas exercé en CI | La sûreté multi-workers n'est **prouvée** que sur SQLite |
| Le renouvellement de bail existe mais le runner ne l'appelle pas | Un scan plus long que 15 min serait repris par un autre worker |
| La file `event_mapping_reviews` n'a ni CLI ni route | Une ambiguïté est enregistrée mais doit être lue en SQL |
| Les alias participants ne sont alimentés par aucun import | La table est consultée par le rapprochement, mais reste vide en pratique |
| `double_chance_h1` est demandé mais aucune fixture ne l'exerce | Son mapping reste non prouvé côté collecte |
| Le downgrade de `b7c1e9d24a10` ne reconstruit pas `events.source_ids` | Documenté plutôt que fabriqué ; un aller-retour perd l'attribution d'origine |
| Aucune sortie web | Tranche 6 |

---

## Prochaine action recommandée

1. **Lancer le smoke test** avec votre clé (voir `docs/source-matrix.md`), puis reporter
   la date et la couverture constatée dans ce même document. C'est ce qui fait passer
   l'adaptateur de `IMPLEMENTED_UNVERIFIED` à `LIVE_VERIFIED`.
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
