# Matrice des sources de données

> **Statut : préliminaire.** Cette session a été conduite sans accès aux documentations
> et conditions d'utilisation en vigueur des fournisseurs. Chaque point non vérifiable
> est marqué **`À vérifier`** plutôt que renseigné de mémoire. Aucune caractéristique de
> fournisseur n'est inventée ici.

## Règle de sélection

Une source n'est retenue que si **toutes** ces conditions sont satisfaites :

1. l'accès est prévu et autorisé par ses conditions d'utilisation ;
2. le stockage des données récupérées est autorisé pour l'usage envisagé ;
3. l'accès ne nécessite ni contournement de protection, ni rétro-ingénierie d'API
   privée, ni scraping interdit ;
4. les identifiants d'événements et de participants permettent un rapprochement fiable ;
5. la fraîcheur réelle est mesurable et suffisante pour la fenêtre visée.

Une source qui échoue au point 3 est écartée définitivement, quelle que soit sa qualité.

## Priorité des cotes

1. **Winamax**, si et seulement si une voie autorisée et fiable existe.
2. Sinon, un fournisseur configuré, **avec le nom du bookmaker affiché explicitement**.
3. À défaut, **import manuel horodaté**, clairement étiqueté comme tel.

Une cote n'est jamais mélangée avec les règles de règlement d'un autre bookmaker. Chaque
snapshot conserve bookmaker, marché, période, ligne, devise et horodatages.

---

## Winamax

| Critère | État |
|---|---|
| API publique documentée | **Aucune identifiée.** Statut retenu : `Winamax indisponible`. |
| Conditions d'utilisation | `À vérifier` — à lire avant tout accès automatisé. |
| Voie retenue en V1 | **Import manuel horodaté** (`betmaxxing odds import`). |
| Scraping / API privée | **Exclu.** Non implémenté, non prévu. |

C'est une limite assumée, pas un contournement à trouver. Le moteur fonctionne
intégralement sur un import manuel, ce qui permet de tester la chaîne complète avec de
vraies cotes relevées à la main sans franchir la ligne.

**Conséquence pratique :** sans flux temps réel, la fraîcheur d'un import manuel se
dégrade vite. Le seuil `max_odds_age_seconds` (900 s par défaut) rejettera un import
vieux de plus de quinze minutes — c'est voulu.

---

## The Odds API (`the-odds-api.com`)

**Statut de l'adaptateur : `IMPLEMENTED_UNVERIFIED`.**

Ne pas confondre avec `odds-api.io`, qui est un service différent.

### Pages officielles à consulter

| Sujet | URL |
|---|---|
| Documentation V4 | https://the-odds-api.com/liveapi/guides/v4/ |
| Bookmakers | https://the-odds-api.com/sports-odds-data/bookmaker-apis.html |
| Marchés | https://the-odds-api.com/sports-odds-data/betting-markets.html |
| Historique | https://the-odds-api.com/historical-odds-data/ |
| Conditions | https://the-odds-api.com/terms-and-conditions.html |

### Ce qui est vérifié, et ce qui ne l'est pas

**Date de la dernière vérification par un appel réel : aucune.** Cette session
n'a effectué **aucun appel** vers le service et n'a consommé **aucun crédit**.

| Critère | État | Vérifié le |
|---|---|---|
| Sports et marchés couverts | `À vérifier` sur les pages officielles | — |
| Présence de `winamax_fr` (zones `fr`/`eu`) | **Annoncé** par l'instruction 02 ; **non confirmé** par un appel | — |
| Winamax présent sur un événement donné | `À vérifier` — la présence dans une liste ne prouve rien par événement | — |
| Accès aux marchés additionnels selon le plan | `À vérifier` | — |
| Historique (endpoints payants) | **Non utilisé.** Interfaces et estimateur de coût seulement | — |
| Quotas et coût par appel | En-têtes `x-requests-remaining` / `-used` / `-last` lus et reportés | — |
| **Droit de rétention des réponses brutes** | `À confirmer dans les CGU` — en attendant, **aucun payload brut n'est conservé** | — |
| Qualité des identifiants d'événements | `id` fournisseur utilisé comme clé de rapprochement autoritaire | — |
| Reports / annulations / abandons | `À vérifier` | — |

### Politique de rétention appliquée en attendant

Tant que le droit de conserver une réponse brute n'est pas confirmé, seuls sont
stockés : le **normalisé** (événements, snapshots), les **identifiants source**,
les **horodatages** et les **métadonnées d'audit**. Aucun payload brut durable.

### Marchés : cartographié ≠ collecté

Ces deux mots ne veulent pas dire la même chose, et la version précédente de ce
document les confondait. **Cartographié** signifie que `map_market()` sait traduire la
réponse. **Collecté** signifie qu'une requête la demande réellement. Cinq marchés
étaient cartographiés sans jamais être demandés : leurs tests de mapping passaient et
ne prouvaient rien sur la collecte.

| Clé fournisseur | Sport | Marché Betmaxxing | Cartographié | Demandé | Persisté sur fixture |
|---|---|---|---|---|---|
| `h2h` | football | 1X2 temps réglementaire | ✅ | ✅ appel groupé | ✅ |
| `totals` | football | Total buts, ligne exacte | ✅ | ✅ appel groupé | ✅ |
| `draw_no_bet` | football | Draw no bet | ✅ | ✅ par événement | ✅ |
| `double_chance` | football | Double chance | ✅ | ✅ par événement | ✅ |
| `h2h_3_way_h1` | football | 1X2 première mi-temps | ✅ | ✅ par événement | ✅ |
| `totals_h1` | football | Total buts première mi-temps | ✅ | ✅ par événement | ✅ |
| `double_chance_h1` | football | Double chance première mi-temps | ✅ | ✅ par événement | ✅ |
| `h2h` | tennis | Vainqueur du match | ✅ | ✅ appel groupé (**seul marché tennis**) | ✅ |
| `totals` | tennis | Total de jeux | ✅ | ⛔ **ni demandé ni facturé** | — (sémantique jeux/sets non confirmée) |

« Persisté sur fixture » veut dire : un test sans réseau vérifie la requête émise,
**puis** le mapping des sélections, **puis** le snapshot enregistré en base. Aucune de
ces lignes n'a été confirmée contre le service réel — l'adaptateur reste
`IMPLEMENTED_UNVERIFIED`.

**La politique est par sport, pas globale.** `core_markets_for(sport)` et
`additional_markets_for(sport)` décident quoi demander. Une constante unique
demandait `totals` pour le tennis alors que ce document le déclare désactivé : nous
payions un prix que le mapper refusait ensuite. Ce qui n'est pas demandé n'est pas
facturé, et la requête est le seul endroit qui puisse le garantir — un test vérifie
que la requête tennis contient exactement `h2h` et ne réserve qu'un crédit.

Les marchés par événement coûtent une requête chacun. Ils passent par le même contrôle
budgétaire que le reste et sont **ignorés avec un motif rapporté** quand la marge
journalière est insuffisante : un jeu de marchés incomplet est un résultat normal.

### Découverte des compétitions actives

`/sports` est interrogé avant toute collecte et intersecté avec l'allowlist configurée.
Une compétition inactive n'est pas interrogée du tout — inutile de payer un crédit pour
une réponse vide. Une réponse `/sports` illisible est traitée comme un **échec de
découverte** (repli sur l'allowlist, avec avertissement), pas comme « rien n'est en
saison » : la confusion inverse annulerait silencieusement toute la collecte.

### Marchés explicitement refusés

| Clé | Raison |
|---|---|
| `h2h_s1` | Désigne le **vainqueur du 1er set**, pas « gagne au moins un set ». Marchés différents, probabilités très différentes. |
| « gagne au moins un set » | `UNSUPPORTED_BY_PROVIDER` — aucun identifiant source confirmé. |

**Aucune cote n'est fabriquée.** DNB, double chance et « gagne un set » ne sont
jamais synthétisés à partir d'autres cotes : un prix que le bookmaker n'a pas
proposé n'est pas un prix. Les fair odds internes du modèle restent disponibles
et sont clairement une sortie de modèle, pas une cotation.

### Taxonomie des réponses — six situations, pas une

Une réponse valide qui ne contient pas `winamax_fr` produit `COVERAGE_MISSING`, **pas**
`PROVIDER_ERROR`, et ne déclenche jamais le mode démo. L'inverse est tout aussi
important, et c'est ce que la version précédente ne faisait pas : **un échec total ne
doit jamais être présenté comme une couverture manquante.**

| Situation | Statut |
|---|---|
| Toutes les compétitions en erreur | `PROVIDER_ERROR` |
| Snapshots obtenus | `OK` |
| Bookmaker présent, aucun marché exploitable | `NO_CANDIDATE` |
| Événements présents, bookmaker configuré absent | `COVERAGE_MISSING` |
| Réponse valide et vide (rien dans la fenêtre) | `NO_CANDIDATE` |
| Échec partiel | données valides conservées + `partial_errors` |

Authentification invalide et plafond budgétaire sont traités séparément, comme des
échecs typés que l'ordonnanceur distingue (voir `docs/scheduler.md`).

### Budget — appliqué, pas déclaré

Chaque tentative, retry compris, réserve son coût estimé dans `provider_budget_ledger`
**avant** d'être émise, contre le plafond par scan et le plafond journalier UTC. La
réservation est ensuite rapprochée de `x-requests-last`. En-tête absent : l'estimation
est conservée (coût inconnu = pire cas). Erreur de transport sans réponse : la
réservation est libérée.

Deux workers d'une même base ne peuvent pas dépasser ensemble le plafond journalier.
La primitive de synchronisation est **une ligne par `(fournisseur, jour UTC)`** mise à
jour par un UPDATE conditionnel :

```sql
UPDATE provider_budget_days
   SET reserved_total = reserved_total + :cost
 WHERE provider = :p AND day_utc = :d
   AND reserved_total + :cost <= :plafond
```

PostgreSQL verrouille la ligne et **réévalue la clause WHERE sur le tuple mis à
jour**, donc le perdant modifie zéro ligne. SQLite sérialise. Les deux sont testés,
PostgreSQL avec des sessions distinctes et une barrière.

L'ancienne version faisait `SELECT SUM(...)` puis `INSERT`. C'est correct sur SQLite
pour une mauvaise raison — SQLite sérialise tous les écrivains — et **faux sur
PostgreSQL** en `READ COMMITTED` : deux transactions lisent le même total et insèrent
toutes les deux. Deux réservations qui tiennent isolément dépassaient ensemble le
plafond.

### Erreurs réseau — ce qu'on peut prouver, et ce qu'on facture

Un timeout ne coûte pas forcément zéro. Le partage se fait sur les **preuves** :

| Échec | Requête reçue ? | Réservation |
|---|---|---|
| `ConnectError`, `ConnectTimeout`, `PoolTimeout` | impossible | **libérée** |
| `LocalProtocolError`, `UnsupportedProtocol`, `InvalidURL` | impossible | **libérée** |
| `ReadTimeout` | envoyée, réponse en retard | **conservée à l'estimation** |
| `WriteTimeout`, `WriteError` | envoi interrompu | **conservée** |
| `ReadError`, `RemoteProtocolError` | réponse tronquée | **conservée** |
| Réponse HTTP, `x-requests-last` présent | oui | rapprochée au coût réel |
| Réponse HTTP, en-tête absent | oui, coût inconnu | **conservée à l'estimation** |
| Réponse 4xx/5xx | oui, servie | facturée |

La version précédente libérait sur **tout** `TransportError` et le documentait comme
« aucune réponse, donc aucun crédit ». Un timeout de lecture signifie que la requête
est partie et que la réponse a tardé : le fournisseur a peut-être servi et facturé.
Sous-compter la dépense est la seule direction dans laquelle un budget ne doit jamais
se tromper.

Conséquence utile : une série de timeouts de lecture épuise le budget du scan au lieu
de boucler gratuitement, donc les retries ne peuvent dépasser aucun plafond.

### Audit

```bash
betmaxxing budget audit --provider the_odds_api
```

Compare le compteur journalier au détail qu'il résume et sort en erreur s'ils
divergent.

### Historique (payant) — estimation seule

`betmaxxing.providers.the_odds_api.historical` fournit une interface et un **estimateur
de coût hors ligne** prenant sports, compétitions, période, marchés, intervalle de
snapshots et bookmaker. Il retourne une **borne supérieure** accompagnée de ses
hypothèses. `fetch_historical()` lève : aucun téléchargement n'est implémenté, aucun
endpoint payant n'est contacté, et une exécution future exigera un consentement
explicite distinct de celui d'un scan.

### Comment vérifier vous-même

```bash
export BETMAXXING_THE_ODDS_API_KEY=...   # votre clé, jamais versionnée
export BETMAXXING_SMOKE_TEST=1
python scripts/smoke_the_odds_api.py
```

Le script effectue le minimum d'appels, masque la clé, rapporte les crédits et la
couverture constatée, et **ne modifie aucun statut de validation**. Reportez la
date et le constat dans le tableau ci-dessus.

Aucun compte payant n'a été créé et aucun achat n'a été effectué.

---

## Données sportives et statistiques

| Critère | État |
|---|---|
| Calendriers et résultats football | `À vérifier` |
| xG (disponibilité **et** licence) | `À vérifier` — sans licence claire, non utilisé |
| Historique ATP/WTA, surfaces, formats | `À vérifier` |
| Statistiques service/retour tennis | `À vérifier` |
| Compositions et absences, structurées et horodatées | `À vérifier` |

**Règle sur les absences et compositions :** elles ne sont intégrées au modèle que si
elles sont structurées, horodatées **et disponibles historiquement**. Une donnée
disponible aujourd'hui mais absente de l'historique ne peut pas entrer dans un modèle
sans créer une fuite temporelle — elle ne serait pas backtestable.

---

## Contexte (blessures, forfaits)

`ContextProvider` ne retourne que des éléments portant **une source et une date**. Un
élément sans provenance n'est pas retourné du tout : il ne peut ni être cité dans une
explication, ni influencer une décision.

En V1 seul le fournisseur de démonstration est implémenté.

---

## Ce qui est implémenté aujourd'hui

| Adaptateur | Type | État |
|---|---|---|
| `demo` | odds, context, results | Opérationnel, **synthétique**, déterministe, sans clé |
| `manual_csv` | odds | Opérationnel, horodaté, quarantaine des lignes invalides |
| `the_odds_api` | odds | **`IMPLEMENTED_UNVERIFIED`** — testé sur contrats locaux, aucun appel réel |
| Telegram | notification | Implémenté, inactif sans configuration explicite |
| E-mail (SMTP) | notification | Implémenté, inactif sans configuration explicite |
| SMS | notification | Interface seulement — coût par message, jamais actif en V1 |

---

## Prochaine action

Avant d'intégrer un fournisseur réel :

1. lire ses conditions d'utilisation et vérifier le droit de stockage ;
2. remplir cette matrice avec des faits vérifiés, pas des suppositions ;
3. implémenter l'adaptateur derrière `OddsProvider` ;
4. écrire des tests contractuels sur fixtures enregistrées ;
5. mesurer la fraîcheur réelle avant de fixer `max_odds_age_seconds`.
