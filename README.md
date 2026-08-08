# Betmaxxing

Aide à la décision pour paris sportifs **prématch** (football et tennis). L'application
scanne les événements des prochaines 24 heures, estime des probabilités avec un modèle
auditable, les compare aux cotes réellement observées et ne retourne que les candidats
dont l'espérance de valeur reste positive **une fois l'incertitude prise en compte**.

> **Betmaxxing ne place aucun pari.** Aucune connexion à un compte de bookmaker, aucune
> transaction, aucune promesse de gain. Usage réservé aux personnes majeures dans une
> juridiction où ce type de pari est autorisé.

Le résultat normal d'un scan peut être **`NO_BET`**. C'est une réponse, pas une panne.

---

## Démarrage rapide (aucune clé requise)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" -c constraints.txt   # résolution reproductible
pip install pre-commit && pre-commit install # garde anti-secret, une fois par clone

betmaxxing scan            # scan complet en mode démo
betmaxxing scan --json     # sortie JSON brute
betmaxxing explain 1       # explication détaillée du meilleur candidat
betmaxxing providers       # état des fournisseurs et statut des modèles
betmaxxing config          # configuration effective, secrets masqués
```

API :

```bash
uvicorn betmaxxing.api.main:app --reload
# http://127.0.0.1:8000/docs
```

Tests, lint, types :

```bash
pytest -W error        # `python -m pytest` exécute exactement la même suite
ruff check .           # tout le dépôt, migrations comprises
ruff format --check .
mypy
```

Aucun avertissement n'est filtré : `filterwarnings = ["error"]`, sans exception.

Vingt-quatre de ces tests exigent un **vrai PostgreSQL** et sont ignorés sans lui :

```bash
export BETMAXXING_TEST_POSTGRES_URL=postgresql+psycopg://user@localhost:5432/betmaxxing_test
pytest -m postgres
```

SQLite sérialise tous les écrivains derrière un verrou global, donc il ne peut pas
distinguer un algorithme concurrent correct d'un algorithme chanceux. Les garanties de
concurrence ne sont affirmées que là où un test PostgreSQL les soutient.

Le mode démo est **entièrement déterministe et synthétique**. Chaque cote qu'il produit
porte `provider="demo"` et `bookmaker="DEMO_BOOK"` pour qu'elle ne puisse jamais être
confondue avec une donnée réelle.

---

## Ce que fait un scan

```
collecte fournisseur (hors transaction)
  → résolution d'identité + PERSISTANCE des événements et snapshots
  → filtre fenêtre ]maintenant, +24 h]
  → normalisation en books immuables (déduplication, quarantaine)
  → retrait de la marge (shin par défaut)
  → probabilité du modèle + statut d'incertitude
  → distribution de règlement → EV, EV prudente, cote min., sensibilité
  → grille d'éligibilité (conjonctive)
  → explication déterministe sourcée
```

Chaque sélection cotée finit soit dans `candidates`, soit dans `rejections` avec un code
explicite. Rien n'est écarté silencieusement.

Statuts possibles : `CANDIDATES_FOUND`, `NO_BET`, `DATA_UNAVAILABLE`.

### Codes de rejet

`EV_TOO_LOW`, `CONSERVATIVE_EV_NEGATIVE`, `ODDS_STALE`, `MARKET_INCOMPLETE`,
`UNCERTAINTY_TOO_HIGH`, `LOW_DATA_QUALITY`, `OUT_OF_SCOPE`, `EVENT_MAPPING_AMBIGUOUS`,
`MODEL_NOT_VALIDATED`, `OUTSIDE_WINDOW`, `ODDS_OUT_OF_RANGE`, `NO_MODEL_AVAILABLE`,
`EVENT_NOT_SCHEDULED`, `MISSING_LINE`, `UNCERTAINTY_UNAVAILABLE`,
`BOOKMAKER_COVERAGE_MISSING`.

---

## Formules

Pour une cote décimale `o` et une probabilité estimée `p` :

| Grandeur | Formule |
|---|---|
| Probabilité implicite brute | `p_raw = 1 / o` |
| Probabilité sans marge | méthode de de-vig configurable |
| Fair odds du modèle | `(p_win + p_perte) / p_win`, soit `1/p` sans remboursement |
| Espérance de valeur | `EV = Σ p(issue) × rendement_net(issue)` |
| EV prudente | recalculée à la borne basse — **`null` sans méthode d'incertitude** |
| Cote minimale acceptable | `(1 + seuil) / p` |
| Sensibilité | `dEV/do = p` |

`p · o − 1` n'est correct que pour un pari sans remboursement. Le draw-no-bet rembourse
la mise sur un nul, donc son EV vient d'une **distribution de règlement** ; la forme
conditionnelle surestimait la magnitude de `1/(1 − p_nul)` (D-024). Les marchés sans
remboursement reproduisent exactement l'ancienne arithmétique.

### Incertitude — lisez ceci avant d'interpréter une EV prudente

L'incertitude porte un **statut** : `SYNTHETIC`, `UNAVAILABLE`, `ESTIMATED` ou
`VALIDATED`. Aujourd'hui, **aucun modèle ne dispose d'une méthode défendable**.

| Mode | Statut | `ev_conservative` | Candidats publiés |
|---|---|---|---|
| `demo` | `SYNTHETIC — NE PAS PARIER` | calculée, **fabriquée** | oui, illustratifs |
| `paper` / `live_analysis` | `UNAVAILABLE` | `null` | **aucun** (`UNCERTAINTY_UNAVAILABLE`) |

Un intervalle de Wilson décrit une proportion binomiale observée, pas la précision d'une
prédiction de modèle. La version précédente s'en servait pour filtrer de vrais candidats ;
D-019 supprime cette possibilité. Voir `docs/decisions.md`.

### Retrait de la marge

Quatre méthodes : `multiplicative`, `additive`, `power`, `shin` (défaut). Elles donnent
des réponses **différentes** sur un book déséquilibré — c'est une vraie décision de
modélisation, donc la méthode est configurable, enregistrée sur chaque candidat et incluse
dans l'empreinte de configuration.

Un marché qui n'est pas une partition complète (double chance, « gagne au moins 1 set »)
n'est **jamais** dé-viggé comme un book : `implied_probability_novig` vaut `None` et le
candidat porte un risque explicite le signalant.

---

## Modèles

| Sport | Modèle | Statut |
|---|---|---|
| Football | Poisson + correction Dixon-Coles | `BACKTEST_ONLY` |
| Tennis | Elo par surface → modèle hiérarchique de points | `BACKTEST_ONLY` |

Les deux dérivent **tous** leurs marchés d'un objet unique (matrice de scores pour le
football, probabilités de point au service pour le tennis), donc les marchés dérivés ne
peuvent pas se contredire. Voir `docs/model-cards.md`.

**Aucun modèle n'est validé.** Le statut `BACKTEST_ONLY` empêche structurellement la
publication d'un candidat en mode `live_analysis`. La promotion suit
`docs/validation-protocol.md`, écrit avant l'ouverture du jeu de test final.

---

## Modes d'exécution

| Mode | Données | Comportement |
|---|---|---|
| `demo` | synthétiques, déterministes | fonctionne sans aucune clé |
| `backtest` | historiques | protocole temporel, pas de fuite |
| `paper` | réelles, sans mise | refuse de démarrer sans fournisseur configuré |
| `live_analysis` | réelles | exige en plus un modèle validé |

`paper` et `live_analysis` **ne retombent jamais** sur les données de démonstration. Une
clé manquante produit `DATA_UNAVAILABLE` en nommant la variable absente.

Un scan rapporte aussi un `collection_status` : `OK`, `COLLECTED_NO_MODEL`,
`NO_CANDIDATE`, `COVERAGE_MISSING`, `DATA_STALE` ou `PROVIDER_ERROR`. « Aucun modèle » et
« fournisseur en panne » donnent tous deux zéro candidat ; un seul est une panne.

## The Odds API — `IMPLEMENTED_UNVERIFIED`

L'adaptateur est implémenté et testé sur contrats locaux (aucun appel réseau en CI).
Six appels réels ont eu lieu le **2026-08-07** — 4 gratuits, 2 payants, 2 crédits.
Ils ont prouvé l'authentification, l'endpoint payant, la comptabilité du coût, le
chaînage et la signature des reçus. Ils n'ont **rien** prouvé du mapping des cotes
ni de la fraîcheur : `winamax_fr` était absent des deux événements testés
(`soccer_spl`, 2026-08-08), donc aucun bloc bookmaker n'a pu être lu. La couverture
`winamax_fr` reste **non confirmée**, et l'adaptateur reste
`IMPLEMENTED_UNVERIFIED`.

Ce qu'il fait, et ce que « fait » veut dire ici :

| Élément | État |
|---|---|
| Découverte `/sports` | Implémentée ; les compétitions inactives ne sont pas interrogées |
| Marchés principaux (`h2h`, `totals`) | Appel groupé par compétition |
| `draw_no_bet`, `double_chance`, `h2h_3_way_h1`, `totals_h1`, `double_chance_h1` | **Réellement demandés** par événement, sous contrôle du budget — et non simplement présents dans `MARKET_MAP` |
| `h2h_s1`, « gagne au moins un set », tennis `totals` | Refusés : `UNSUPPORTED_BY_PROVIDER` ou sémantique non confirmée |
| Budget par scan et par jour | Réservation **persistante et atomique** avant chaque tentative, retries compris ; rapprochée avec `x-requests-last`. Un coût incertain reste facturé |
| Marchés tennis | `h2h` **seul**. `totals` tennis n'est ni demandé ni facturé tant que sa sémantique jeux/sets n'est pas confirmée |
| Historique (payant) | Interface et estimateur de coût **hors ligne** seulement. Aucun téléchargement |

« Demandé et persisté » est prouvé **sur fixture locale**, pas contre le service réel.
La distinction est le sujet de tout ce paragraphe.

Pour vérifier la couverture réelle vous-même. Six appels réels ont eu lieu le
2026-08-07 (4 gratuits, 2 payants, 2 crédits) : ils ont prouvé l'authentification,
l'endpoint payant et la comptabilité du coût, et **pas** le mapping des cotes —
`winamax_fr` était absent des deux événements testés. L'état courant se lit avec
`activation status`, qui sépare les cinq dimensions de preuve.

Quatre étapes indépendantes, chaînées par reçu signé et autorisées séparément
(`plan` 0, `discover` 0, `core` 1 crédit, `additional` 5 crédits au tarif
publié) :

```bash
export BETMAXXING_THE_ODDS_API_KEY=...   # votre clé, jamais versionnée, jamais en argument
python -m betmaxxing.providers.the_odds_api.activation plan \
    --sport soccer_france_ligue_one --bookmaker winamax_fr --max-credits 6
```

Runbook complet : **`docs/provider-activation.md`**. L'ancien script `smoke` est une
redirection : il demandait un booléen puis appelait `collect([FOOTBALL, TENNIS],
window)`, un éventail dont personne ne pouvait annoncer le coût.

Une exécution verte sera une **preuve limitée** — cet endpoint, ce bookmaker, cette
compétition, cet événement, ce marché, cet instant — et non une promotion :
l'adaptateur reste `IMPLEMENTED_UNVERIFIED` jusqu'à une décision séparée.

Une réponse valide sans Winamax est `COVERAGE_MISSING`, pas une panne — et ne déclenche
jamais le mode démo. Détails et marchés refusés : `docs/source-matrix.md`.

---

## Cotes Winamax

Aucune voie programmatique autorisée n'a été identifiée pour Winamax. Le projet ne
contourne aucune protection et ne fait pas de rétro-ingénierie d'API privée.

La voie prévue est l'**import manuel horodaté** :

```bash
betmaxxing odds import data/manual/example_odds.csv
betmaxxing scan --manual-odds data/manual/example_odds.csv
```

Le fichier déclare le bookmaker, l'instant d'observation et chaque sélection. Un horodatage
sans décalage UTC est mis en quarantaine plutôt que deviné. Voir `docs/source-matrix.md`.

---

## Structure

```
src/betmaxxing/
  config.py          seuils centralisés, versionnés, empreinte reproductible
  domain/            vocabulaires, entités, identifiants canoniques, temps
  providers/         demo, the_odds_api, import manuel, notifications + interfaces
  ingestion/         identité des événements, déduplication, books, quarantaine
  engine/            acquisition, marge, payoff, EV, incertitude, éligibilité, scan
  models_ml/         baselines football et tennis, registre + garde de validation
  evaluation/        métriques du protocole de validation
  challenge/         Challenge — Montante (désactivé par défaut, persistant)
  scheduler/         ledger d'occurrences + runner (processus séparé)
  storage/           schéma, sessions, dépôts
  api/               FastAPI (aucune route ne place de pari)
  cli.py
docs/                spécification, matrice des sources, protocole, journal, roadmap
```

---

## Jeu responsable

- Aucune martingale, aucune poursuite des pertes, aucune mise de récupération.
- `Challenge.next_stake_cents()` ne lit **que** la banque courante : une mise de
  récupération est structurellement inexprimable, et un test le vérifie.
- Une défaite termine une montante par défaut.
- Les suggestions de mise sont **désactivées** tant qu'aucune bankroll n'est configurée.
- Une probabilité trop incertaine produit une mise de **zéro**, pas une petite mise.
- Arrêt volontaire immédiat : `POST /challenges/{id}/stop`.
- `GET /responsible-gambling` expose les contrôles en vigueur.

Les coordonnées d'aide françaises ne sont pas codées en dur : leur formulation officielle
doit être vérifiée auprès de l'ANJ avant diffusion plutôt qu'affichée périmée.

---

## Documentation

| Fichier | Contenu |
|---|---|
| `docs/architecture.md` | architecture cible et décisions structurantes |
| `docs/source-matrix.md` | matrice des sources, licences, `À vérifier` |
| `docs/data-dictionary.md` | dictionnaire de données |
| `docs/validation-protocol.md` | protocole préenregistré et critères de promotion |
| `docs/model-cards.md` | model cards, hypothèses, limites |
| `docs/scheduler.md` | exploitation du planificateur |
| `docs/deployment.md` | déploiement et sauvegarde |
| `docs/decisions.md` | journal des décisions (D-019 supersède D-008, D-028 supersède en partie D-027) |
| `docs/roadmap.md` | état, en cours, blocages, prochaine action |

---

## Limites connues

- Aucun modèle n'est validé hors échantillon ; **aucune décision réelle ne doit reposer
  sur cette version**.
- Aucun adaptateur de fournisseur de cotes réel n'est implémenté (tranche 3).
- Aucun entraînement : les forces d'équipe et Elo sont fournis en entrée (tranche 4).
- Interface web React non commencée (tranche 6) ; CLI et API couvrent les usages actuels.
- **Aucune méthode d'incertitude défendable** : `paper` et `live_analysis` ne publient
  rien aujourd'hui.
- `TheOddsApiProvider` est `IMPLEMENTED_UNVERIFIED` — auth, endpoint payant et comptabilité du coût vérifiés en réel le 2026-08-07 ; **mapping des cotes non vérifié en réel**.
- Le Challenge est `PARTIAL` : persistant et testé, mais désactivé par défaut.
- Le planificateur est sûr multi-workers contre **une même base**, testé sur SQLite
  **et PostgreSQL 16 réel** (réclamation, fencing, heartbeat, insertion concurrente).
  Rien ne coordonne plusieurs bases, et ce n'est pas prévu.
- Un effet externe déjà envoyé n'est pas annulable. L'outbox empêche un **second**
  envoi après reprise du job ; il ne rappelle pas le premier.
- Aucun notifieur n'est branché dans le runner : l'outbox et le contrôle de propriété
  existent et sont testés, le canal reste à câbler.
- La file de revue d'ambiguïté et les alias s'administrent en CLI
  (`betmaxxing identity …`) ; aucune route API, et aucun catalogue d'alias fourni.
