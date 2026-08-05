# État et feuille de route

**Dernière mise à jour :** 2026-08-05 · **Version :** 0.3.0

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
- **Qualité** : lint et format sur tout le dépôt, `constraints.txt`, avertissements
  non filtrés bloquants, migrations testées depuis le schéma de référence.
- **670 tests**, dont 22 tests de caractérisation écrits avant correction.

---

## Statuts honnêtes

| Composant | Statut | Ce que cela veut dire |
|---|---|---|
| Ordonnanceur | ✅ **fonctionnel** | Ledger durable ; sûr multi-workers contre **une seule** base |
| Collecte + persistance | ✅ **fonctionnel** | Les trois chemins persistent événements, snapshots et scan |
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

Ces deux blocages sont externes. Tout ce qui n'en dépend pas a été implémenté.

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
