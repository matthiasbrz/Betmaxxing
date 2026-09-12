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

**Dernière vérification par appel réel : 2026-08-07.** Six requêtes au total —
quatre gratuites (`/v4/sports`, `/v4/sports/{sport}/events`, coût observé nul) et
deux payantes (`/v4/sports/soccer_spl/odds`, 1 crédit chacune). Quota 494 → 492.
Ce qui a été prouvé et ce qui ne l'a pas été est détaillé ci-dessus.

| Critère | État | Vérifié le |
|---|---|---|
| Sports et marchés couverts | `À vérifier` sur les pages officielles | — |
| Présence de `winamax_fr` (zones `fr`/`eu`) | **Annoncé** par la documentation officielle (lue le 2026-08-05) ; **non confirmé** par un appel | — |
| Winamax présent sur un événement donné | **absent** sur les 2 événements `soccer_spl` testés (`bookmaker_state = NOT_RETURNED`). Constat borné à ces événements et ces instants ; aucune généralisation | 2026-08-07 |

### Le manifeste de la campagne protocole 8 — choisi et daté avant tout appel

Le protocole 7 exigeait que le bookmaker de la piste A soit « choisi sur la
documentation publique officielle du fournisseur, daté ici au moment du choix », et
ajoutait : « ce document ne nomme pas encore ce bookmaker ». Le premier appel réel est
pourtant parti sans que ce choix ait été fait, sous le bookmaker de la piste B. La
campagne v8 ferme cela : le manifeste est écrit **avant** le premier appel, et la
machine le fait respecter.

**Sources publiques, consultées le 2026-08-24 :**

| Source | URL |
|---|---|
| Sports et clés de compétition | <https://the-odds-api.com/sports-odds-data/sports-apis.html> |
| Bookmakers et zones | <https://the-odds-api.com/sports-odds-data/bookmaker-apis.html> |
| Contrat des endpoints v4 | <https://the-odds-api.com/liveapi/guides/v4/> |

**Ce que ces pages disaient ce jour-là :**

| Élément | Constat | Date |
|---|---|---|
| Bookmaker `pinnacle` | listé, zone **`eu`** uniquement, avec la note « odds are from public website which may incur a delay » | 2026-08-24 |
| `soccer_epl` | clé publiée pour l'English Premier League | 2026-08-24 |
| `soccer_spain_la_liga` | clé publiée pour La Liga | 2026-08-24 |
| `tennis_atp_us_open` | clé publiée pour l'US Open ATP | 2026-08-24 |
| `tennis_wta_us_open` | clé publiée pour l'US Open WTA | 2026-08-24 |

**Ce que ce tableau n'établit pas.** Qu'une clé soit publiée ne dit ni que la
compétition est active à une date donnée, ni que `pinnacle` cote un événement donné, ni
qu'un marché demandé sera retourné. C'est un **préenregistrement de portée**, pas une
preuve de couverture. Si une compétition est inactive, vide ou non couverte au moment
autorisé, la campagne v8 échoue sans substitution.

Depuis **D-083** (2026-09-05) le manifeste ne se limite plus à *quelles* compétitions :
l'ordre des douze appels et le rang de l'événement de chacun sont fixés eux aussi, et le
rang se lit dans l'ordre canonique `(instant du coup d'envoi, identifiant en octets
UTF-8)` de la découverte — pas dans l'ordre où le fournisseur a répondu, qu'aucun
contrat ne promet.

`pinnacle` étant en zone `eu` seule, `effective_region_units(bookmakers=["pinnacle"])`
vaut 1 : le chiffrage des crédits est inchangé.

`winamax_fr` et la piste B sont **exclus** de la campagne v8. Le constat du 2026-08-07
ci-dessus reste borné à ses deux événements SPL et ne se généralise pas.
| Accès aux marchés additionnels selon le plan | `À vérifier` | — |
| Historique (endpoints payants) | **Non utilisé.** Interfaces et estimateur de coût seulement | — |
| Quotas et coût par appel | En-têtes lus, reportés et **conformes** : gratuit = 0, `core` = 1, sur 6 appels réels | 2026-08-07 |
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

### Deux formes de réponse, deux contrats

Vérifié sur <https://the-odds-api.com/liveapi/guides/v4/> le **2026-08-05** :

| Endpoint | Où vit `last_update` |
|---|---|
| `GET /v4/sports/{sport}/odds` | sur **chaque bookmaker** |
| `GET /v4/sports/{sport}/events/{eventId}/odds` | sur **chaque marché** |

Le guide est explicite : *« The `last_update` field is only available on the
market level in the response and not on the bookmaker level. »*

L'adaptateur lisait `book["last_update"]` pour les deux. Les fixtures locales
étaient vertes parce qu'elles avaient été écrites d'après le code, pas d'après le
contrat : la **première** réponse réelle de l'endpoint par événement aurait vu
tous ses bookmakers rejetés pour horodatage manquant, et les marchés additionnels
n'auraient rien collecté.

La forme est désormais **déclarée par l'appelant** (`ResponseShape.GROUPED_ODDS`
ou `EVENT_ODDS`), jamais devinée depuis la charge utile : une déduction
accepterait silencieusement une réponse de la mauvaise forme, c'est-à-dire
exactement le changement de contrat dont nous voulons être avertis.

Conséquence gardée volontairement : sur l'endpoint par événement, deux marchés du
même bookmaker conservent **leurs** horodatages distincts. Les aplatir sur un seul
instant rendrait indiscernables un prix vieux de cinq minutes et un prix vieux de
cinq heures — ce qui est précisément l'entrée du contrôle de fraîcheur. Un
horodatage absent ou illisible rejette **la seule unité concernée** (le bookmaker
en forme groupée, le marché en forme par événement) et n'invente jamais de date :
ni `received_at`, ni `commence_time`, ni celle du marché voisin.

### Coût d'un appel : unités régionales effectives

Règle officielle, relue le **2026-08-05** :

> `cost = [number of markets specified] x [number of regions specified]`
>
> *« When both `bookmakers` and `regions` are specified, `bookmakers` takes
> priority. Every group of 10 bookmakers is the equivalent of 1 region. »*

L'estimateur comptait les **régions configurées** alors même que la requête
envoyait `bookmakers=winamax_fr`. Avec `regions=eu,fr`, un appel à un seul
bookmaker réservait deux unités là où le fournisseur en facture une. Cela ne fait
jamais dépenser trop — la réservation est une borne supérieure — mais cela refuse
des appels que le budget pouvait payer, et un garde qui se déclenche sur des
requêtes correctes finit élargi jusqu'à ne plus rien garder.

`effective_region_units(bookmakers=…, regions=…)` applique la règle : des
bookmakers présents priment, par groupes de dix arrondis vers le haut ; sinon les
régions distinctes ; jamais zéro. `estimate_cost(markets=…, region_units=…)` ne
prend plus de régions du tout, pour que l'erreur ne puisse pas revenir par la
signature. Espaces, doublons et casse sont normalisés : `["eu", "EU"]` désigne une
seule région facturée.

La borne reste conservatrice avant l'appel ; `x-requests-last` reste l'autorité
après.

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

**L'activation a été partiellement exercée en réel.** L'état courant se lit,
il ne se suppose pas :

```bash
python -m betmaxxing.providers.the_odds_api.activation status
```

### Ce qui a été vérifié, et comment

| Dimension | État | Vérifié |
|---|---|---|
| Découverte (endpoints gratuits) | **conforme** | en réel — 4 requêtes, `x-requests-last=0` |
| Authentification, endpoint payant, comptabilité du coût | **conforme** | en réel — 2 requêtes, 2 crédits, quota 494 → 492 |
| Chaînage et signature des reçus | **conforme** | en réel |
| Couverture `winamax_fr` | **absente** sur les 2 événements `soccer_spl` testés, à ces instants | en réel |
| Mapping des cotes, horodatage, fraîcheur | **non vérifiés en réel** | uniquement sur **fixture synthétique** (`OFFLINE_CONTRACT_VERIFIED`) |
| Adaptateur dans son ensemble | `IMPLEMENTED_UNVERIFIED` | — |

Coût réel cumulé connu : **2 crédits** (fait daté, pas une constante).

Les deux absences SPL portent sur **deux événements, à ces instants**. Elles ne
disent rien de la couverture Winamax en général chez le fournisseur, ni de cette
compétition à un autre moment.

La procédure complète est dans **`docs/provider-activation.md`**. En résumé,
quatre étapes indépendantes, chaînées par reçu signé et autorisées séparément,
plus une commande `status` de lecture seule :

| Commande | Réseau | Borne locale | Plafond contractuel estimé | Endpoints |
|---|---|---|---|---|
| `plan` | non | aucun client HTTP construit | 0 | aucun |
| `discover` | oui | 2 requêtes | 0 | `/v4/sports`, `/v4/sports/{sport}/events` |
| `core` | oui | 1 requête, 1 événement, 1 marché | 1 | `/v4/sports/{sport}/odds?eventIds=…` |
| `additional` | oui | 1 requête, 1 événement, 5 marchés | 5 | `/v4/sports/{sport}/events/{id}/odds` |

```bash
export BETMAXXING_THE_ODDS_API_KEY=...   # votre clé, jamais versionnée, jamais en argument
python -m betmaxxing.providers.the_odds_api.activation plan \
    --sport soccer_france_ligue_one --bookmaker winamax_fr --max-credits 6
```

L'ancien `scripts/smoke_the_odds_api.py` demandait **un booléen** puis appelait
`collect([FOOTBALL, TENNIS], window)` : un éventail d'un appel groupé par
compétition configurée plus un appel par événement football, borné par le seul
budget de scan. Personne ne pouvait annoncer son coût à l'avance. Le script
subsiste comme redirection et n'émet plus aucun appel.

`core` exige `--discovery-receipt`, `additional` exige `--core-receipt`. Les reçus
sont signés en HMAC-SHA256 avec un secret local (`0600`, non versionné), portent
l'identifiant d'événement en HMAC et non en clair, expirent au bout de six heures,
et référencent leur parent. Un reçu altéré, périmé, d'un autre sport, d'un autre
bookmaker, d'un autre événement, ou de schéma v1 est refusé **avant** le réseau.

Chaque étape masque la clé, distingue coût estimé / observé / comptabilisé, écrit
un reçu local expurgé **quelle que soit l'issue** — y compris un appel facturé qui
échoue ensuite — et **ne modifie aucun statut de validation**.

### Ce qu'une exécution réussie prouvera, et ce qu'elle ne prouvera pas

Une exécution verte est une **preuve limitée** : cet endpoint, ce bookmaker, cette
compétition, cet événement, ce marché, cet instant. Elle ne promeut pas
l'adaptateur. Le statut global reste `IMPLEMENTED_UNVERIFIED` jusqu'à une décision
séparée fondée sur des critères documentés — nombre d'événements, de compétitions
et de jours observés, et taux de couverture constaté.

Reportez la date, l'événement et l'état **marché par marché** dans le tableau
ci-dessus.

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
| `the_odds_api` | odds | **`IMPLEMENTED_UNVERIFIED`** — contrats locaux verts ; auth, endpoint payant et coût **vérifiés en réel** le 2026-08-07 ; mapping des cotes **non vérifié en réel** |
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
