# Runbook — activation contrôlée de The Odds API

> **État réel : lisez-le, ne le supposez pas.**
>
> ```bash
> python -m betmaxxing.providers.the_odds_api.activation status
> ```
>
> Ce runbook ne peut pas énoncer l'état courant de votre installation, et il n'y a
> plus un seul label pour le faire. Cinq dimensions sont rapportées séparément
> (adaptateur, exécution, connectivité + coût, couverture bookmaker, mapping +
> fraîcheur), parce qu'elles sont indépendantes : des appels payants peuvent avoir
> prouvé l'authentification et la facturation sans rien prouver du parseur.
>
> Ce qui est vrai en toutes circonstances : l'adaptateur reste
> `IMPLEMENTED_UNVERIFIED` et les modèles restent `BACKTEST_ONLY` jusqu'à une
> décision de promotion écrite et satisfaite.

### Ce qui a réellement été exercé en réel (opérations 03B-1 à 03B-4)

| Dimension | État | Preuve |
|---|---|---|
| Découverte gratuite | **exercée, conforme** | 4 requêtes, `x-requests-last=0` à chaque fois |
| Authentification et endpoint payant | **exercés** | 2 requêtes `/v4/sports/{sport}/odds` |
| Comptabilité du coût | **exercée, conforme** | 2 × estimé 1 / observé 1 / comptabilisé 1 ; quota 494 → 492 |
| Chaînage et signature des reçus | **exercés** | reçus v2 signés, parent vérifié avant réseau |
| Couverture `winamax_fr` | **absente sur les 2 événements SPL testés**, à ces instants | `bookmaker_state = NOT_RETURNED` |
| Mapping et fraîcheur | **non obtenus en réel** | 0 sélection cartographiée ; aucun bloc bookmaker à lire |
| Mapping et fraîcheur, sur contrat documenté | `OFFLINE_CONTRACT_VERIFIED` | fixture **synthétique** de bout en bout |

Coût réel cumulé connu de ces opérations : **2 crédits**. Ce n'est pas une
constante de configuration, c'est un fait daté.

Les deux absences SPL valent pour **ces deux événements, à ces instants**. Elles
ne disent rien de la couverture Winamax en général chez le fournisseur, ni de
cette compétition à un autre moment.

Ce document décrit **comment** l'activation se fera, ce qu'elle coûtera, ce
qu'elle prouvera — et surtout ce qu'elle ne prouvera pas. Il ne l'exécute pas.

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

Un booléen n'est pas une limite de dépense.

---

## Quatre mots de coût, tenus séparés

Les confondre est la manière dont un relevé de dépense se met à mentir. Le
programme en distingue quatre, et n'en garantit que les deux premiers.

| Terme | Ce que c'est | Qui le garantit |
|---|---|---|
| **Borne technique locale** | nombre de requêtes, endpoints, événements, bookmakers et marchés | **ce programme**, avant toute socket |
| **Plafond contractuel estimé** | ce que ces requêtes *devraient* coûter selon la règle publiée (`marchés × unités régionales effectives`) | ce programme refuse d'aller au-delà, sur la base du tarif relu le 2026-08-05 |
| **Coût observé** | `x-requests-last` — ce que le fournisseur déclare avoir facturé | le fournisseur ; `null` s'il ne le déclare pas |
| **Coût comptabilisé** | ce qui est retenu : l'observation si elle existe, l'estimation sinon | ce programme, par prudence |

**Ce programme ne peut pas empêcher un fournisseur externe de modifier sa
tarification et de facturer autrement une requête qu'il a déjà servie.** Il peut
seulement le constater dans les en-têtes et s'arrêter (`COST_MISMATCH`). Le mot
« plafond » désigne ici les deux premières lignes, pas une garantie sur la
facture de quelqu'un d'autre.

Un coût absent ne devient **jamais** zéro. Un en-tête manquant, illisible ou
négatif donne `observed_credits = null`, `accounted_credits = estimation`, et le
statut `COST_UNVERIFIED` — qui n'autorise aucune étape suivante.

---

## Les quatre étapes

| Commande | Réseau | Borne locale | Plafond contractuel estimé | Endpoints |
|---|---|---|---|---|
| `plan` | non | aucun client HTTP n'est construit | **0** | aucun |
| `discover` | oui | 2 requêtes | **0** | `/v4/sports`, `/v4/sports/{sport}/events` |
| `core` | oui | 1 requête, 1 événement, 1 marché | **1** | `/v4/sports/{sport}/odds?eventIds=…` |
| `additional` | oui | 1 requête, 1 événement, 5 marchés | **5** | `/v4/sports/{sport}/events/{id}/odds` |

Total de la séquence complète : **6 crédits** au tarif publié.

Chaque étape s'autorise séparément et exige le **reçu signé** de la précédente,
fourni en argument. Aucune n'en déclenche une autre — un test statique le vérifie
sur le source du module.

### Faits officiels sur lesquels reposent ces chiffres

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
  facturée ; une étape dont la borne locale est une requête n'en fait qu'une.
* **Portée singulière.** Une compétition, un bookmaker, un événement, une fenêtre
  d'au plus 24 h. Toute valeur plurielle est refusée **avant** le réseau.
* **Double confirmation chiffrée.** `--max-credits` doit valoir exactement le
  plafond contractuel de l'étape, et `--acknowledge-credits` doit le répéter. Deux
  nombres identiques tapés à la main restent une preuve d'intention faible, mais
  incomparablement plus forte qu'un booléen : on ne peut pas les fournir sans
  savoir ce que l'étape coûte.
* **Chaîne explicite.** `core` exige `--discovery-receipt`, `additional` exige
  `--core-receipt`. L'outil ne parcourt plus le répertoire de reçus pour se
  choisir une preuve à la place de l'opérateur.
* **Aucun endpoint historique ou payant** n'est joignable depuis cet outil.
* **Toute tentative réseau laisse un reçu**, quel que soit son statut terminal.
  Un refus **avant** le réseau n'en crée aucun.
* **La suite de tests ne peut joindre aucun fournisseur.** `tests/conftest.py`
  installe un garde de socket global : seules la boucle locale et `AF_UNIX`
  (le PostgreSQL de test) sont autorisés. Trois tests le vérifient.

---

## Vocabulaire des statuts

| Statut | Signification | Autorise la suite ? |
|---|---|---|
| `PLAN_ONLY` | `plan` a chiffré la séquence et n'affirme rien sur ce qui a été exécuté | sans objet |
| `PREPARED_NOT_EXECUTED` | refus **avant** toute socket ; également l'état de la dimension payante tant qu'aucun appel payant n'a été tenté | non |
| `DISCOVERY_VERIFIED` | les deux endpoints gratuits ont répondu, coût observé nul, des événements existent | oui |
| `CORE_LIVE_VERIFIED` | un prix réel a été obtenu et cartographié pour le bookmaker demandé | oui |
| `ADDITIONAL_LIVE_VERIFIED` | les cinq marchés sont revenus, horodatés et cartographiés | terminal |
| `ADDITIONAL_PARTIAL_COVERAGE` | au moins un marché correct, couverture incomplète | terminal |
| `COVERAGE_MISSING` | réponse valide, rien d'exploitable : compétition inactive, aucun événement, bookmaker absent, ou aucun marché demandé retourné. **Ce n'est pas une panne.** | non |
| `SCHEMA_MISMATCH` | la réponse n'a pas la forme documentée, ou rien n'a pu être cartographié | non |
| `COST_MISMATCH` | coût annoncé supérieur au plafond contractuel — arrêt immédiat | non |
| `COST_UNVERIFIED` | aucun `x-requests-last` exploitable : l'estimation reste comptabilisée, le coût réel est inconnu | non |
| `AUTH_FAILED` | 401/403 : clé absente, invalide, ou plan insuffisant | non |
| `PROVIDER_UNAVAILABLE` | erreur réseau ou HTTP hors authentification | non |

Un `COVERAGE_MISSING` n'est jamais compensé, jamais élargi, jamais réessayé, et
aucun autre bookmaker n'est substitué.

---

## Les reçus (schéma v2, signés)

Chaque **tentative réseau** écrit un reçu JSON local sous `.activation-receipts/`
(ou le chemin de `BETMAXXING_ACTIVATION_RECEIPTS`). Ce répertoire est dans
`.gitignore` : un reçu est une trace d'exploitation d'un appel réel et facturé, il
appartient à l'opérateur, pas au dépôt.

### Le secret local de signature

Un secret aléatoire est créé au premier besoin réseau, dans le répertoire de
reçus, en `O_CREAT | O_EXCL` et mode `0600`. Il n'est jamais affiché, jamais
journalisé, jamais versionné. Les tests injectent un secret déterministe par
`BETMAXXING_ACTIVATION_RECEIPT_SECRET` et ne dépendent d'aucun aléa réel.

### Contenu (schéma v3)

`schema_version`, `receipt_id`, `command`, `status`, `recorded_at`, `expires_at`,
`sport_key`, `bookmaker`, `event_tag` (ou `event_tags` pour `discover`),
`window_from` / `window_to`, `endpoints` templatés, `attempts`,
`network_attempted`, `may_have_reached_provider`, `estimated_credits`,
`observed_credits`, `accounted_credits`, `quota_remaining`, **`bookmaker_state`**,
`markets_requested`, `market_states` et ses projections (`markets_mapped`,
`markets_rejected`, `markets_absent`, **`markets_not_evaluated`**,
`markets_observed`), `freshness` en secondes, `selections_mapped`,
`mapping_rejections` généralisés, `parent_receipt_id`,
**`parent_schema_version`**, `adapter_status`, `model_impact`, `signature`.
Pour `discover` uniquement : **`events_returned`**, **`events_in_window`**,
**`events_admissible`**.

### Deux dimensions, jamais confondues

| `bookmaker_state` | Signification |
|---|---|
| `OBSERVED` | le bookmaker demandé est coté sur cet événement |
| `NOT_RETURNED` | il n'est pas dans la réponse — on n'a rien pu examiner |

Le champ est **absent** d'un reçu `discover` : `/v4/sports/{sport}/events` ne
renvoie aucune information de bookmaker, donc il n'y a rien à constater. Un défaut
à `NOT_RETURNED` s'y lirait comme un constat sur le bookmaker.

| État d'un marché demandé | Signification |
|---|---|
| `NOT_EVALUATED_BOOKMAKER_ABSENT` | aucun bloc bookmaker à examiner : **on ne sait rien** de ce marché |
| `NOT_RETURNED` | le bookmaker est coté et ne propose pas ce marché — fait sur son offre |
| `OBSERVED_REJECTED` | revenu, mais inexploitable par le parseur |
| `OBSERVED_MAPPED` | revenu, horodaté, cartographié |

Le tableau est **total** : `set(market_states) == set(markets_requested)` sur tout
reçu terminal dont la portée de marchés était connue. Les listes dérivées
partitionnent exactement une fois les marchés demandés, donc aucune ne peut
contredire `market_states`.

Les deux reçus `core` réels illustrent précisément le défaut corrigé : ils
portaient `markets_requested: ["h2h"]`, `market_states: {}` et
`markets_absent: []`, ce qui se lit comme « rien ne manquait » alors que rien
n'avait été regardé.

### Compteurs de découverte

| Compteur | Définition |
|---|---|
| `events_returned` | objets événement reçus **avant** filtrage temporel |
| `events_in_window` | après application stricte de la fenêtre déclarée |
| `events_admissible` | après validation minimale et déduplication |

Invariants : `0 <= events_admissible <= events_in_window <= events_returned`, et
`events_admissible == len(set(event_tags))`. Des entiers, jamais un détail par
événement : cela remettrait le calendrier dans un artefact conçu pour n'en porter
aucun.

### Versions lues, versions écrites

Les nouveaux reçus sont en **v3**. Les reçus **v2** déjà présents sur le disque
restent lus, vérifiés et honorés comme preuve d'autorisation — chacun des champs
dont la chaîne dépend a le même sens dans les deux versions — mais ils ne sont
**jamais** réécrits, promus ni re-signés, et l'enfant note
`parent_schema_version`. Le passage à v3 était nécessaire parce que
`market_states` a changé de **sens** : partiel en v2, total en v3 avec un état
supplémentaire. Les v1 et toute version inconnue sont refusées.

Un reçu ne contient **jamais** : la clé ni un fragment de clé, le secret de
signature, une URL non expurgée, un corps de réponse brut, une cote, un nom de
participant, ni l'identifiant d'événement en clair.

### L'identifiant d'événement

HMAC-SHA256 tronqué, clé = le secret local. Un simple `sha256(event_id)` était
calculable par quiconque dispose de la liste publique des rencontres du
fournisseur : il ne cachait rien. Le HMAC identifie l'événement **pour cette
installation** — assez pour que `core` reconnaisse l'approbation de `discover`
d'un processus à l'autre — sans être inversible par dictionnaire.

### Vérification avant usage

Signature HMAC-SHA256 sur le JSON canonique (clés triées, séparateurs serrés),
comparée avec `hmac.compare_digest`. Est refusé **avant le réseau** un reçu :
non signé ou de signature invalide ; de schéma inconnu ; **v1** (non signé, non
chaîné — il ne prouve rien et n'est pas promu silencieusement) ; expiré ; de
commande ou de statut inattendus ; portant un autre sport, bookmaker ou
événement ; dont le coût n'est pas vérifié ; sans parent quand la chaîne l'exige ;
hors du répertoire autorisé, lien symbolique ou chemin ambigu.

Durée de validité : **6 heures**. Une découverte périmée ne dit rien des
rencontres d'aujourd'hui, et une preuve qui n'expire jamais finit réutilisée pour
autre chose.

### Rétention

Ces fichiers sont locaux et sous le contrôle de l'opérateur. Supprimez-les quand
ils ne servent plus ; rien dans le produit n'en dépend.

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

Ne lit ni la clé ni le secret de signature, ne construit aucun client HTTP,
n'écrit aucun reçu. Affiche la séquence chiffrée et `PREPARED_NOT_EXECUTED`.
`--json` pour la sortie machine.

### 2. `discover` — 0 crédit

```bash
python -m betmaxxing.providers.the_odds_api.activation discover \
  --sport soccer_france_ligue_one \
  --bookmaker winamax_fr \
  --window-hours 24 \
  --allow-network
```

Appelle `/v4/sports`, vérifie que la compétition est **active** — sinon il
s'arrête là, inutile de payer un crédit pour une réponse vide — puis
`/v4/sports/{sport}/events` borné par `commenceTimeFrom` / `commenceTimeTo`.

Si l'un de ces deux endpoints annonce un coût non nul → `COST_MISMATCH`. S'il
n'annonce aucun coût → `COST_UNVERIFIED`, et `core` refusera de partir.

**Aucun événement n'est choisi pour vous.** La commande affiche la liste et le
**chemin du reçu** ; relevez les deux.

### 3. `core` — 1 crédit

```bash
python -m betmaxxing.providers.the_odds_api.activation core \
  --sport soccer_france_ligue_one \
  --bookmaker winamax_fr \
  --event-id EVENT_ID_CHOISI \
  --discovery-receipt CHEMIN_RECU_DISCOVER \
  --max-credits 1 \
  --acknowledge-credits 1 \
  --allow-network
```

Le reçu de découverte est vérifié avant le réseau : v2, signé, non expiré,
`DISCOVERY_VERIFIED`, même sport et même bookmaker, contenant le HMAC de
l'événement demandé, attestant un coût observé nul et un quota restant suffisant.

Un appel, `eventIds=` filtré sur cet événement, `markets=h2h`,
`bookmakers=winamax_fr`. La réponse passe par le **vrai** `_ingest_event` en forme
`GROUPED_ODDS` : l'objectif n'est pas de voir du JSON arriver, c'est de savoir si
le code qui le lira en production le lit effectivement.

### 4. `additional` — 5 crédits, autorisation distincte

```bash
python -m betmaxxing.providers.the_odds_api.activation additional \
  --sport soccer_france_ligue_one \
  --bookmaker winamax_fr \
  --event-id LE_MEME_EVENT_ID \
  --core-receipt CHEMIN_RECU_CORE \
  --max-credits 5 \
  --acknowledge-credits 5 \
  --allow-network
```

Le reçu de `core` est vérifié avant le réseau : v2, signé, non expiré,
`command=core`, `status=CORE_LIVE_VERIFIED`, même sport, bookmaker et HMAC
d'événement, référençant une découverte, attestant au moins une sélection
cartographiée et un coût compatible avec le plafond de 1 crédit.

Chacun des cinq marchés reçoit ensuite un état explicite :

| État | Signification |
|---|---|
| `OBSERVED_MAPPED` | retourné, horodaté au niveau marché, cartographié |
| `OBSERVED_REJECTED` | retourné, mais inexploitable par le parseur |
| `NOT_RETURNED` | le bookmaker ne l'a pas coté |

Et le statut de l'étape en découle : aucun retourné → `COVERAGE_MISSING` ;
retournés mais aucun cartographié → `SCHEMA_MISMATCH` ; au moins un cartographié
sans couverture complète → `ADDITIONAL_PARTIAL_COVERAGE` ; les cinq →
`ADDITIONAL_LIVE_VERIFIED`.

---

## Après l'exécution

0. Lire l'état réel : `… activation status`. Il rapporte les cinq dimensions
   séparément et ne condense rien.
1. Reporter la date, l'état du bookmaker et l'état **marché par marché** dans
   `docs/source-matrix.md`.
2. **Ne promouvoir aucun statut global.** Un événement, à un instant, sur une
   compétition, avec un bookmaker, est une **preuve limitée** — pas une
   validation de l'adaptateur. Ce que le reçu atteste tient en six termes :
   endpoint, bookmaker, compétition, événement, marché, instant. Le statut global
   reste `IMPLEMENTED_UNVERIFIED` jusqu'à une décision de promotion séparée,
   fondée sur des critères documentés (nombre d'événements, de compétitions, de
   jours, taux de couverture constaté).
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
