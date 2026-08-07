# Déploiement et sauvegarde

## Local (développement)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" -c constraints.txt   # résolution reproductible
cp .env.example .env                          # renseignez ce dont vous avez besoin
alembic upgrade head
betmaxxing scan
```

`constraints.txt` fige la résolution utilisée par la CI. `pyproject.toml` garde des
bornes basses lâches pour rester installable ailleurs. Régénérez le fichier
**délibérément** lors d'une montée de version, jamais par effet de bord.

SQLite convient au développement et aux tests. Il ne convient pas à une exploitation
persistante avec un planificateur concurrent.

## Docker Compose

```bash
docker compose up --build
# API        : http://localhost:8000/docs
# PostgreSQL : localhost:5432
```

Trois services : `db` (PostgreSQL 16), `api` (uvicorn), `scheduler` (processus séparé,
profil `scheduler`).

```bash
docker compose --profile scheduler up -d    # démarre aussi le planificateur
```

## Production

### Base de données

```bash
export BETMAXXING_DATABASE_URL="postgresql+psycopg://user:PASSWORD@host:5432/betmaxxing"
pip install -e ".[postgres]"
alembic upgrade head
```

**Alembic est la source de vérité** du schéma en production. `betmaxxing db init`
(`create_all`) est une commodité locale : il ne gère pas les migrations et ne doit pas
être utilisé sur une base existante.

### API

```bash
uvicorn betmaxxing.api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Derrière un reverse proxy assurant TLS. L'API n'écoute que sur `127.0.0.1` par défaut.

**Si l'application devient accessible depuis Internet :**
- renseignez `BETMAXXING_API_TOKEN` et placez une authentification devant l'API ;
- restreignez `BETMAXXING_CORS_ORIGINS` aux origines réellement utilisées ;
- n'exposez jamais `/settings` publiquement (il masque les secrets, mais révèle la
  configuration).

### Planificateur

Processus **séparé** de l'API. Voir `docs/scheduler.md`.

```bash
BETMAXXING_SCHEDULER_ENABLED=true python -m betmaxxing.scheduler.runner
```

Son état vit dans `scheduler_jobs` : un redémarrage reprend là où il en était, et un
worker crashé libère son occurrence à l'expiration du bail. Plusieurs workers contre
**une même base SQLite** sont sûrs, et c'est testé (famine, jeton de possession,
reprise concurrente, insertion concurrente). Le chemin PostgreSQL `FOR UPDATE SKIP
LOCKED` est écrit mais n'est pas exercé en CI. Rien ne coordonne plusieurs bases.

## The Odds API — variables et budgets

```bash
export BETMAXXING_ODDS_PROVIDER=the_odds_api
export BETMAXXING_THE_ODDS_API_KEY=...          # jamais dans un fichier versionné
export BETMAXXING_BOOKMAKERS=winamax_fr
export BETMAXXING_THE_ODDS_API_REGIONS=eu,fr
export BETMAXXING_PROVIDER_BUDGET_PER_SCAN=50   # refus AVANT chaque tentative
export BETMAXXING_PROVIDER_BUDGET_PER_DAY=450   # idem, partagé entre workers
```

Les deux plafonds sont **appliqués**, pas seulement déclarés : chaque tentative — retry
compris — réserve son coût estimé avant d'être émise, et la réservation est rapprochée
du `x-requests-last` renvoyé. Un en-tête absent laisse l'estimation en place (coût
inconnu = pire cas).

**Attention à ce que « aucune réponse » ne veut pas dire.** Seul un échec qui prouve
que la requête n'est jamais partie libère la réservation (erreur ou timeout de
connexion, épuisement du pool). Un timeout de **lecture** signifie que la requête est
partie : le fournisseur a peut-être servi et facturé, donc l'estimation reste
comptabilisée. Table complète dans `docs/source-matrix.md`.

La primitive est une ligne par `(fournisseur, jour UTC)` dans `provider_budget_days`,
incrémentée par UPDATE conditionnel. C'est atomique sur SQLite **et** sur PostgreSQL, et
les deux sont testés — PostgreSQL avec des sessions distinctes et une barrière, parce
que SQLite sérialise tous les écrivains et ne peut donc pas distinguer un algorithme
atomique d'un algorithme chanceux.

Vérifier la cohérence à tout moment :

```bash
betmaxxing budget audit --provider the_odds_api
```

La clé n'apparaît jamais dans une URL journalisée, une exception, une trace ou une
réponse d'API : le client masque `apiKey=` avant toute sortie.

`BETMAXXING_ODDS_API_KEY` reste accepté par compatibilité mais est **déprécié** ; un
avertissement le signale, sans jamais afficher la valeur.

### Activation contrôlée (opt-in, consomme des crédits réels)

**L'état courant se lit, il ne se suppose pas :**

```bash
python -m betmaxxing.providers.the_odds_api.activation status
```

Cinq dimensions sont rapportées séparément — adaptateur, exécution, connectivité +
coût, couverture bookmaker, mapping + fraîcheur — parce qu'elles sont
indépendantes. Runbook complet : **`docs/provider-activation.md`**.

L'activation se fait en quatre commandes indépendantes, chaînées par reçu signé
et autorisées séparément :

| Commande | Réseau | Borne locale | Plafond contractuel estimé | Endpoints |
|---|---|---|---|---|
| `plan` | non | aucun client HTTP construit | 0 | aucun |
| `discover` | oui | 2 requêtes | 0 | `/v4/sports`, `/v4/sports/{sport}/events` |
| `core` | oui | 1 requête, 1 événement, 1 marché | 1 | `/v4/sports/{sport}/odds?eventIds=…` |
| `additional` | oui | 1 requête, 1 événement, 5 marchés | 5 | `/v4/sports/{sport}/events/{id}/odds` |

```bash
export BETMAXXING_THE_ODDS_API_KEY=...
python -m betmaxxing.providers.the_odds_api.activation plan \
    --sport soccer_france_ligue_one --bookmaker winamax_fr --max-credits 6
```

C'est le **seul** code du dépôt capable d'appeler réellement le service. Il n'est
ni collecté par pytest, ni exécuté par la CI. Chaque étape réseau exige
`--allow-network`, une clé présente dans l'environnement, une portée singulière
(une compétition, un bookmaker, un événement, 24 h au plus), le **reçu signé** de
l'étape précédente (`--discovery-receipt`, `--core-receipt`) et — pour les étapes
payantes — `--max-credits` **et** `--acknowledge-credits` égaux au plafond
contractuel. Aucune tentative n'est répétée (`max_retries=0`) : un réessai est une
seconde requête facturée. Aucun endpoint historique (payant) n'est joignable et
aucun statut de validation n'est modifié.

Ce que le programme borne, il le borne localement : nombre de requêtes,
endpoints, événements, bookmakers et marchés. Le chiffrage en crédits, lui, repose
sur le tarif publié. **Le programme ne peut pas empêcher le fournisseur de
facturer autrement une requête déjà servie** ; il le constate dans les en-têtes
et s'arrête (`COST_MISMATCH`). Un coût non annoncé donne `COST_UNVERIFIED` :
l'estimation reste comptabilisée et l'étape suivante est bloquée.

`scripts/smoke_the_odds_api.py` est conservé comme **redirection** et n'émet plus
aucun appel : sa version précédente demandait un booléen puis appelait
`collect([FOOTBALL, TENNIS], window)`, dont le coût n'était annonçable par
personne à l'avance.

### Reçus et secret local

Les reçus atterrissent sous `.activation-receipts/` (ou
`BETMAXXING_ACTIVATION_RECEIPTS`). Le répertoire est dans `.gitignore`. Un reçu
est écrit pour **toute tentative réseau**, y compris celles qui échouent après
avoir été facturées ; un refus antérieur au réseau n'en écrit aucun.

Un secret de signature aléatoire est créé au premier besoin réseau dans ce même
répertoire, en mode `0600`. Il n'est jamais affiché, journalisé ni versionné.
Sauvegardez-le si vous voulez pouvoir vérifier d'anciens reçus après une
réinstallation ; sans lui, les reçus antérieurs ne sont plus vérifiables et il
faut relancer `discover`.

Les reçus ne contiennent ni clé, ni secret, ni URL non expurgée, ni corps brut,
ni cote, ni nom de participant ; l'identifiant d'événement y figure en HMAC.

## Exploitation de l'identité des événements

Une ambiguïté de rapprochement n'écrit rien d'autre qu'une ligne de revue : ni
correspondance, ni événement, ni snapshot. Elle s'administre en ligne de commande —
l'interface web est une tranche ultérieure, et un opérateur ne devrait pas avoir à
écrire du SQL en attendant.

```bash
betmaxxing identity reviews list                    # file d'attente
betmaxxing identity reviews list --json             # même chose, exploitable
betmaxxing identity reviews show 12                 # détail + candidats
betmaxxing identity reviews resolve 12 \
    --event-id evt_9f3b… --operator matthias        # décision humaine
```

Il n'existe **aucune** résolution automatique, et c'est délibéré : la file existe
précisément parce que la machine n'a pas pu trancher. `--operator` est obligatoire ;
la décision, son auteur et sa date sont conservés.

Refusé sans rien écrire : un identifiant qui ne figurait pas parmi les candidats, une
revue déjà tranchée, une correspondance déjà existante pour cette source.

**Les snapshots déjà enregistrés ne sont pas réattribués.** La décision gouverne la
suite ; réécrire l'historique changerait ce qu'un scan passé est censé avoir observé.

### Alias de participants

Le rapprochement inter-fournisseurs consulte les alias déclarés. Ils s'importent :

```bash
betmaxxing identity aliases import aliases.csv      # idempotent
betmaxxing identity aliases list --sport football
```

Format : `sport,alias,canonical_participant_id,source`. L'import est idempotent, et une
ligne inutilisable ou **contradictoire** (le même alias pointant déjà sur un autre
participant pour la même source) part en quarantaine avec son numéro de ligne — jamais
écrasée, puisque les alias décident quelles rencontres fusionnent.

Aucun catalogue n'est fourni : le fichier est à constituer.

## Challenge — Montante

```bash
export BETMAXXING_CHALLENGE_ENABLED=true   # désactivé par défaut
```

Quand c'est faux, toutes les routes `/challenges` répondent 404.

## Secrets

- Aucun secret dans Git. `.gitignore` exclut `.env` et les bases locales.
- `.env.example` liste les variables **sans valeur**, et un test le vérifie.
- `Settings.redacted()` masque tout champ finissant par `_key`, `_token`, `_password` ou
  `_secret`. C'est ce que renvoient `/settings` et `betmaxxing config`.
- Un test parcourt `src/` à la recherche de secrets codés en dur.

## Sauvegarde

### PostgreSQL

```bash
pg_dump --format=custom --file=betmaxxing-$(date +%F).dump "$BETMAXXING_DATABASE_URL"
```

Restauration :

```bash
pg_restore --clean --if-exists --dbname="$BETMAXXING_DATABASE_URL" betmaxxing-2026-08-04.dump
```

**Une sauvegarde non restaurée n'est pas une sauvegarde.** Testez la restauration sur une
base jetable avant d'en dépendre.

### Ce qui compte

| Table | Enjeu |
|---|---|
| `odds_snapshots` | **Irremplaçable** — un prix passé ne se re-télécharge pas |
| `event_source_map` | Sans elle, l'identité des événements doit être reconstruite |
| `collection_batches` | Provenance et coût de chaque collecte |
| `scan_runs` | Reproduction et audit des décisions |
| `challenges` / `challenge_steps` | État des progressions |
| `model_registry` | Statuts de validation — une perte rétrograderait tout en `BACKTEST_ONLY` |

Les événements et candidats se reconstruisent ; les snapshots, non. Priorisez-les.

### Rétention

Proposition à arbitrer selon l'usage :

| Donnée | Rétention |
|---|---|
| Snapshots de cotes | Illimitée (matière première des backtests) |
| Lots de collecte | 24 mois |
| Occurrences du planificateur | 3 mois |
| Documents de scan | 24 mois |
| Rejets | 12 mois |
| Ledger d'alertes | 3 mois |

## Observabilité

- Logs structurés JSON corrélés par `scan_id`.
- `GET /health` — vivacité et empreinte de configuration.
- `GET /providers` — santé, fraîcheur, quotas.
- `GET /models` — statut de validation.

À surveiller en priorité : `data_health.stale_snapshots`, `data_health.quarantined_records`,
et tout passage à `DATA_UNAVAILABLE`.

## Mise à jour

```bash
git pull
pip install -e ".[dev]" -c constraints.txt
alembic upgrade head
pytest
```

Les migrations sont testées sur **cinq** chemins, dont ceux qui peuvent perdre des
données :

| Chemin | Couvert |
|---|---|
| Base vide → `head` | ✅ |
| Schéma initial vide → `head` | ✅ |
| **Schéma initial peuplé → `head`** | ✅ challenge + palier, événement avec `source_ids`, snapshot avec ligne, scan, candidat |
| `3ce123580afa` (commit `f901d6e`) déjà appliqué → `head` | ✅ |
| `b7c1e9d24a10` (commit `5d2109f`) déjà appliqué → `head` | ✅ |
| **Aller-retour `head` → `65c32b5e3f63` → `head`** | ✅ associations fournisseur/événement identiques à chaque étape |
| PostgreSQL 16 neuf → `head` | ✅ en CI |
| `alembic check` sans dérive, sur base peuplée et sur PostgreSQL | ✅ |

Une base contenant un Challenge **ne pouvait pas** être migrée avant cette tranche :
`ADD COLUMN ... NOT NULL` est refusé sur une table non vide. Les colonnes sont désormais
ajoutées nullables, backfillées depuis le dernier palier réglé, vérifiées, puis
resserrées.

Si un document de Challenge est inexploitable, la migration **refuse** en nommant la
ligne. Aucune banque n'est inventée. Pour parquer explicitement ces lignes :

```bash
BETMAXXING_MIGRATION_UNUSABLE_CHALLENGE=quarantine alembic upgrade head
```

Elles passent alors à l'état `quarantined` avec une banque à zéro et un motif lisible.

**Downgrade sans perte.** `b7c1e9d24a10` repasse chaque ligne d'`event_source_map` dans
`events.source_ids` **avant** que la révision parente ne supprime la table. Ces lignes
sont le seul lien entre un prix enregistré et la rencontre pour laquelle il a été coté :
les perdre en redescendant est une perte de données, pas un nettoyage. Un identifiant
déjà présent dans la colonne avec une valeur contradictoire **arrête** le downgrade en
nommant la ligne, plutôt que d'être écrasé.

Le service d'identité écrit désormais les deux emplacements en même temps, donc ils ne
peuvent plus diverger.

**Arrondi monétaire.** Le backfill de banque importe `betmaxxing.challenge.to_cents` au
lieu de réimplémenter l'arrondi. Une valeur non finie ou illisible **fait échouer** la
migration en nommant la ligne ; aucune banque n'est inventée.

Redémarrez l'API **et** le planificateur.
