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

### Marchés cartographiés

| Clé fournisseur | Sport | Marché Betmaxxing |
|---|---|---|
| `h2h` | football | 1X2 temps réglementaire |
| `totals` | football | Total buts, ligne exacte |
| `draw_no_bet` | football | Draw no bet |
| `double_chance` | football | Double chance |
| `h2h_3_way_h1` | football | 1X2 première mi-temps |
| `totals_h1` | football | Total buts première mi-temps |
| `double_chance_h1` | football | Double chance première mi-temps |
| `h2h` | tennis | Vainqueur du match |
| `totals` | tennis | Total de jeux — **désactivé par défaut** (sémantique jeux/sets non confirmée) |

### Marchés explicitement refusés

| Clé | Raison |
|---|---|
| `h2h_s1` | Désigne le **vainqueur du 1er set**, pas « gagne au moins un set ». Marchés différents, probabilités très différentes. |
| « gagne au moins un set » | `UNSUPPORTED_BY_PROVIDER` — aucun identifiant source confirmé. |

**Aucune cote n'est fabriquée.** DNB, double chance et « gagne un set » ne sont
jamais synthétisés à partir d'autres cotes : un prix que le bookmaker n'a pas
proposé n'est pas un prix. Les fair odds internes du modèle restent disponibles
et sont clairement une sortie de modèle, pas une cotation.

### Couverture manquante ≠ panne

Une réponse valide qui ne contient pas `winamax_fr` produit
`COVERAGE_MISSING`, **pas** `PROVIDER_ERROR`, et ne déclenche jamais le mode démo.

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
