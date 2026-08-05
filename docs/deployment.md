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
**une même base** sont sûrs ; rien ne coordonne plusieurs bases.

## The Odds API — variables et budgets

```bash
export BETMAXXING_ODDS_PROVIDER=the_odds_api
export BETMAXXING_THE_ODDS_API_KEY=...          # jamais dans un fichier versionné
export BETMAXXING_BOOKMAKERS=winamax_fr
export BETMAXXING_THE_ODDS_API_REGIONS=eu,fr
export BETMAXXING_PROVIDER_BUDGET_PER_SCAN=50   # refus AVANT l'appel si dépassé
export BETMAXXING_PROVIDER_BUDGET_PER_DAY=450
```

La clé n'apparaît jamais dans une URL journalisée, une exception, une trace ou une
réponse d'API : le client masque `apiKey=` avant toute sortie.

`BETMAXXING_ODDS_API_KEY` reste accepté par compatibilité mais est **déprécié** ; un
avertissement le signale, sans jamais afficher la valeur.

### Smoke test (opt-in, consomme des crédits réels)

```bash
export BETMAXXING_THE_ODDS_API_KEY=...
export BETMAXXING_SMOKE_TEST=1
python scripts/smoke_the_odds_api.py
```

C'est le **seul** code du dépôt qui appelle réellement le service. Il n'est ni
collecté par pytest, ni exécuté par la CI, et refuse de démarrer sans les deux
variables. Il ne touche aucun endpoint historique (payant) et ne modifie aucun statut
de validation.

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

Les migrations sont additives et testées dans les deux sens : sur base neuve et depuis
le schéma de référence `65c32b5e3f63`. `alembic check` échoue s'il manque une migration.

Redémarrez l'API **et** le planificateur.
