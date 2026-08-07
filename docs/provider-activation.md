# Runbook — activation contrôlée de The Odds API

> **État à la date de rédaction : `PREPARED_NOT_EXECUTED`.**
> Aucun appel n'a été émis vers `api.the-odds-api.com`. Aucune clé réelle n'a été
> lue, validée ou affichée. Aucun crédit n'a été consommé. L'adaptateur reste
> `IMPLEMENTED_UNVERIFIED`, les modèles restent `BACKTEST_ONLY`.

Ce document décrit **comment** l'activation se fera, ce qu'elle coûtera au
maximum, et ce qu'elle prouvera. Il ne l'exécute pas.

---

## Pourquoi l'ancien script ne devait pas être lancé

`scripts/smoke_the_odds_api.py`, dans sa forme précédente, demandait un booléen
(`BETMAXXING_SMOKE_TEST=1`) puis appelait :

```python
provider.collect([Sport.FOOTBALL, Sport.TENNIS], window)
```

C'est un éventail : un appel groupé **par clé de compétition configurée** (quatre
par défaut), puis un appel **par événement football trouvé** pour les marchés
additionnels. Le seul plafond était le budget de scan (50 crédits). Personne ne
pouvait annoncer, avant de lancer, ce que ce script allait coûter.

Un booléen n'est pas une limite de dépense. Le remplacement l'est.

---

## Les quatre étapes

| Commande | Réseau | Plafond | Endpoints |
|---|---|---|---|
| `plan` | non | **0** | aucun — aucun client HTTP n'est même construit |
| `discover` | oui | **0** | `/v4/sports`, `/v4/sports/{sport}/events` |
| `core` | oui | **1** | `/v4/sports/{sport}/odds?eventIds=…` |
| `additional` | oui | **5** | `/v4/sports/{sport}/events/{id}/odds` |

Total de la séquence complète : **6 crédits**, plafond vérifié avant chaque appel.

Chaque étape s'autorise séparément. Aucune n'en déclenche une autre — un test
statique le vérifie sur le source du module.

### Faits officiels sur lesquels reposent ces plafonds

Relevés sur <https://the-odds-api.com/liveapi/guides/v4/> le **2026-08-05** :

| Fait | Citation |
|---|---|
| Coût d'un appel de cotes | *« cost = [number of markets specified] x [number of regions specified] »* |
| Priorité des bookmakers | *« When both `bookmakers` and `regions` are specified, `bookmakers` takes priority. Every group of 10 bookmakers is the equivalent of 1 region. »* |
| Gratuité de `/sports` et `/sports/{sport}/events` | *« This endpoint does not count against the usage quota. »* |
| Réponse vide | *« If no events are returned, the request will not count against the usage quota. »* |
| Horodatage par événement | *« The `last_update` field is only available on the market level in the response and not on the bookmaker level. »* |

`winamax_fr` est listé par la documentation dans les régions `eu` **et** `fr`.
Cela reste une **annonce**, pas une preuve : la présence dans un catalogue ne dit
rien de la cotation d'un événement donné. C'est exactement ce que `core` mesure.

### D'où viennent 1 et 5

Avec un seul bookmaker envoyé, `bookmakers` prime : **1 unité régionale**, quelles
que soient les régions configurées.

* `core` demande **un** marché (`h2h`) → 1 × 1 = **1 crédit**.
  `core_markets_for(FOOTBALL)` en demanderait deux (`h2h`, `totals`) et coûterait
  2 : l'activation demande le marché minimal qui prouve l'endpoint,
  l'authentification et le parseur, puis s'arrête.
* `additional` demande **cinq** marchés par événement → 5 × 1 = **5 crédits**.

---

## Ce que l'outil garantit par construction

* **La clé ne transite que par l'environnement.** Il n'existe pas d'option
  `--api-key` : un argument finit dans l'historique du shell, dans `ps` et dans
  les journaux de CI. Une tentative de la passer en argument échoue.
* **Zéro réessai.** `max_retries=0` partout. Un réessai est une seconde requête
  facturée ; une étape plafonnée à un crédit ne fait qu'une tentative.
* **Portée singulière.** Une compétition, un bookmaker, un événement, une fenêtre
  d'au plus 24 h. Toute valeur plurielle est refusée **avant** le réseau.
* **Double confirmation chiffrée.** `--max-credits` doit valoir exactement le
  plafond publié de l'étape, et `--acknowledge-credits` doit le répéter. Deux
  nombres identiques tapés à la main restent une preuve d'intention faible, mais
  incomparablement plus forte qu'un booléen : on ne peut pas les fournir sans
  savoir ce que l'étape coûte.
* **Aucun endpoint historique ou payant** n'est joignable depuis cet outil.
* **`additional` exige un reçu `CORE_LIVE_VERIFIED`** portant sur le même
  événement. Cinq crédits ne sont engagés qu'après qu'un seul a démontré que
  l'endpoint, l'authentification et le parseur fonctionnent.
* **La suite de tests ne peut joindre aucun fournisseur.** `tests/conftest.py`
  installe un garde de socket global : seules la boucle locale et `AF_UNIX`
  (le PostgreSQL de test) sont autorisés. Trois tests le vérifient.

---

## Vocabulaire des statuts

| Statut | Signification |
|---|---|
| `PREPARED_NOT_EXECUTED` | rien n'a été exécuté ; c'est aussi le statut de tout refus en amont du réseau |
| `DISCOVERY_VERIFIED` | les deux endpoints gratuits ont répondu, des événements existent dans la fenêtre |
| `CORE_LIVE_VERIFIED` | un prix réel a été obtenu et cartographié pour le bookmaker demandé |
| `ADDITIONAL_LIVE_VERIFIED` | l'endpoint par événement a répondu et le parseur a lu les horodatages par marché |
| `COVERAGE_MISSING` | réponse valide, mais rien d'exploitable : compétition inactive, aucun événement, ou bookmaker absent. **Ce n'est pas une panne.** |
| `SCHEMA_MISMATCH` | la réponse n'a pas la forme documentée |
| `COST_MISMATCH` | le fournisseur annonce un coût supérieur au plafond autorisé — arrêt immédiat |
| `AUTH_FAILED` | 401/403 : clé absente, invalide, ou plan insuffisant |
| `PROVIDER_UNAVAILABLE` | erreur réseau ou HTTP non authentification |

Un `COVERAGE_MISSING` n'est jamais compensé, jamais élargi, jamais réessayé. La
fenêtre n'est pas étendue automatiquement pour trouver quelque chose à mesurer.

---

## Les reçus

Chaque étape réseau réussie écrit un reçu JSON local sous
`.activation-receipts/` (ou le chemin de `BETMAXXING_ACTIVATION_RECEIPTS`). Ce
répertoire est dans `.gitignore` : un reçu est une trace d'exploitation d'un
appel réel et facturé, il appartient à l'opérateur, pas au dépôt.

Un reçu contient : la commande, le statut, l'instant, l'endpoint **templaté**, la
forme de réponse, la compétition, le bookmaker, le **hachage** de l'identifiant
d'événement, le plafond, le coût annoncé, les marchés demandés / obtenus /
absents, la fraîcheur **en secondes** de chaque marché, le nombre de sélections
cartographiées et les motifs de rejet généralisés.

Un reçu ne contient **jamais** : la clé ni un fragment de clé, une URL non
expurgée, un corps de réponse brut, une cote, un nom de participant, ni
l'identifiant d'événement en clair. Sept tests le vérifient, dont un qui cherche
littéralement les noms et les cotes de la fixture dans le fichier écrit.

Rétention : ces fichiers sont locaux et sous le contrôle de l'opérateur.
Supprimez-les quand ils ne servent plus ; rien dans le produit n'en dépend.

---

## Séquence à exécuter — quand l'autorisation aura été donnée

### 0. Configurer la clé (aucun crédit)

```bash
export BETMAXXING_THE_ODDS_API_KEY='…'     # jamais dans un fichier versionné
```

La variable dépréciée `BETMAXXING_ODDS_API_KEY` reste acceptée et signalée.

### 1. `plan` — hors ligne, 0 crédit

```bash
python -m betmaxxing.providers.the_odds_api.activation plan \
    --sport soccer_france_ligue_one \
    --bookmaker winamax_fr \
    --max-credits 6
```

Ne lit pas la clé, ne construit aucun client HTTP, n'écrit aucun reçu. Affiche la
séquence chiffrée et `PREPARED_NOT_EXECUTED`. Ajoutez `--json` pour la sortie
machine.

### 2. `discover` — 0 crédit

```bash
python -m betmaxxing.providers.the_odds_api.activation discover \
    --sport soccer_france_ligue_one \
    --bookmaker winamax_fr \
    --allow-network
```

Appelle `/v4/sports`, vérifie que la compétition est **active** — sinon il
s'arrête là, inutile de payer un crédit pour une réponse vide — puis
`/v4/sports/{sport}/events` borné par `commenceTimeFrom` / `commenceTimeTo`.

Si l'un de ces deux endpoints annonce un coût non nul, l'étape échoue en
`COST_MISMATCH` : le contrat de facturation aurait changé.

**Aucun événement n'est choisi pour vous.** Relevez un identifiant dans la liste.

### 3. `core` — 1 crédit

```bash
python -m betmaxxing.providers.the_odds_api.activation core \
    --sport soccer_france_ligue_one \
    --bookmaker winamax_fr \
    --event-id <identifiant relevé à l'étape 2> \
    --max-credits 1 --acknowledge-credits 1 \
    --allow-network
```

Un appel, `eventIds=` filtré sur cet événement, `markets=h2h`,
`bookmakers=winamax_fr`. La réponse passe par le **vrai** `_ingest_event` en
forme `GROUPED_ODDS` : l'objectif n'est pas de voir du JSON arriver, c'est de
savoir si le code qui le lira en production le lit effectivement.

Ce que cette étape prouve ou infirme :

* l'authentification et le plan donnent accès à l'endpoint ;
* `winamax_fr` cote **cet** événement (ou non → `COVERAGE_MISSING`) ;
* le coût réel annoncé vaut bien 1 ;
* le parseur produit des sélections exploitables.

### 4. `additional` — 5 crédits, autorisation distincte

```bash
python -m betmaxxing.providers.the_odds_api.activation additional \
    --sport soccer_france_ligue_one \
    --bookmaker winamax_fr \
    --event-id <le même identifiant> \
    --max-credits 5 --acknowledge-credits 5 \
    --allow-network
```

Refusé sans reçu `CORE_LIVE_VERIFIED` pour ce même événement. Demande les cinq
marchés par événement et lit les horodatages **au niveau marché**, conformément
au contrat v4. Un marché absent de la réponse est **constaté**, ni compensé, ni
réessayé.

---

## Après l'exécution

1. Reporter la date et le constat dans `docs/source-matrix.md` (tableau « Ce qui
   est vérifié »).
2. Ne changer le statut de l'adaptateur en `VERIFIED` que si `core` **et**
   `additional` ont réussi ; sinon consigner précisément ce qui a échoué.
3. **Aucun statut de modèle ne change.** Une couverture confirmée n'est pas une
   validation : les modèles restent `BACKTEST_ONLY` jusqu'au protocole de
   `docs/validation-protocol.md`.
4. Supprimer ou archiver les reçus locaux selon vos besoins.

---

## Ce qui reste hors périmètre

Endpoints historiques et payants, scraping ou rétro-ingénierie de Winamax,
entraînement ou backtest sur données nouvelles, promotion de modèle, publication
de candidat en `paper` ou `live_analysis`, démarrage d'un ordonnanceur réel,
envoi de notification, pari ou automatisme de mise, interface web, et
versionnement d'un payload fournisseur brut.
