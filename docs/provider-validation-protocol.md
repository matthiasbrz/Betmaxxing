# Protocole de qualification du fournisseur — `PROVIDER_VALIDATION_PROTOCOL_VERSION = 1`

Ce document dit, **avant** les appels, combien de preuve live justifierait de
*demander* à un humain de promouvoir l'adaptateur The Odds API. Il ne promeut rien
lui-même.

Il existe parce que l'inverse s'est produit. Deux appels `core` réels ont abouti,
n'ont trouvé aucune couverture Winamax, et ont été résumés comme une activation qui
« fonctionnait ». Sans seuil écrit à l'avance, n'importe quel résultat se relit
comme encourageant. Des seuils argumentés après coup ne sont pas des critères : ce
sont des descriptions de ce qui est arrivé.

**Règle de version.** Toute modification d'un seuil, d'une portée ou d'une règle
d'admissibilité incrémente `PROVIDER_VALIDATION_PROTOCOL_VERSION`. Les résultats
calculés sous deux versions ne se comparent pas. Un critère assoupli après
observation n'est plus un critère, et le numéro de version est ce qui rend cette
manœuvre visible.

L'évaluateur vit dans `src/betmaxxing/providers/the_odds_api/qualification.py` et se
lit par `betmaxxing-the-odds-api activation status [--json]`.

## 1. Neuf faits, jamais condensés

| # | Fait | Établi par |
| --- | --- | --- |
| 1 | l'adaptateur est **implémenté** | la revue de code et la suite hors ligne |
| 2 | **connectivité et authentification** | un appel réel qui revient sans `AUTH_FAILED` |
| 3 | **conformité du coût** | `observed_credits` conforme, ou comptabilisé prudemment |
| 4 | **présence ponctuelle d'un bookmaker** | `bookmaker_state = OBSERVED` sur *cet* événement |
| 5 | **mapping d'un marché** | `market_states[marché] = OBSERVED_MAPPED` |
| 6 | **fraîcheur et horodatage** | un âge exploitable pour ce marché |
| 7 | **diversité de l'échantillon** | événements, compétitions et jours UTC distincts |
| 8 | **qualification globale** | la matrice §2, entièrement satisfaite |
| 9 | **promotion** | **une décision humaine**, hors de ce document |

Deux conséquences qu'on confond vite :

- l'absence de `winamax_fr` sur un événement **n'est pas** un échec de mapping.
  C'est un fait sur l'offre de ce bookmaker, sur cet événement, à cet instant ;
- un mapping réussi **avec un autre bookmaker** ne prouve **aucune** couverture
  Winamax. Il prouve que notre parser lit la forme que l'endpoint envoie.

## 2. Matrice des critères

Portée commune à tous : provider `the_odds_api`, un seul bookmaker par
observation, âge du marché ≤ **900 s**. Ce nombre n'est pas choisi ici : c'est
`Settings.max_odds_age_seconds`, le seuil au-delà duquel le scan appelle déjà un
snapshot périmé. Si le produit le juge périmé, la qualification ne peut pas le
juger frais.

| `criterion_id` | Portée | Preuve admissible | Événements | Compétitions | Jours UTC | Schéma |
| --- | --- | --- | --- | --- | --- | --- |
| `CORE_MAPPING_FOOTBALL` | `soccer_*`, `core`, `h2h`, `GROUPED_ODDS` | `selections_mapped > 0`, aucun rejet de mapping | **3** | **2** | **2** | v2 ou v3 |
| `CORE_MAPPING_TENNIS` | `tennis_*`, `core`, `h2h`, `GROUPED_ODDS` | idem | **3** | **2** | **2** | v2 ou v3 |
| `ADDITIONAL_MAPPING_FOOTBALL_DRAW_NO_BET` | `soccer_*`, `additional`, `draw_no_bet` | `market_states[marché] = OBSERVED_MAPPED` | **2** | **2** | **1** | **v3 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DOUBLE_CHANCE` | idem, `double_chance` | idem | **2** | **2** | **1** | **v3 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_H2H_3_WAY_H1` | idem, `h2h_3_way_h1` | idem | **2** | **2** | **1** | **v3 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_TOTALS_H1` | idem, `totals_h1` | idem | **2** | **2** | **1** | **v3 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DOUBLE_CHANCE_H1` | idem, `double_chance_h1` | idem | **2** | **2** | **1** | **v3 seul** |
| `COST_CONFORMITY` | tous sports, appels payants | 0 appel non conforme | **6** appels conformes | — | — | v2 ou v3 |

Le tennis n'a **pas** de marchés `additional` : `ADDITIONAL_MARKETS_BY_SPORT[TENNIS]`
est vide, donc aucun critère `additional` tennis n'existe. C'est une absence
voulue, pas un oubli.

### Pourquoi ces nombres

**Trois événements pour `core`.** Un événement ne se distingue pas d'une réponse
chanceuse. Deux ne distinguent pas « la forme que cette compétition envoie » de
« la forme que l'endpoint envoie ». Trois, répartis sur deux compétitions et deux
jours UTC, exercent le parser sur des réponses générées indépendamment. Au-delà de
trois, l'information marginale sur **notre parser** s'effondre alors que le coût
reste linéaire à 1 crédit par événement.

**Deux compétitions.** Une seule peut utiliser un gabarit de marchés uniforme : un
succès spécifique au gabarit ressemblerait à un succès général.

**Deux jours UTC.** La fraîcheur dépend de la cadence de mise à jour du
fournisseur et d'un `last_update` dont l'emplacement **change selon la forme de
réponse** — exactement l'endroit où cet adaptateur s'est déjà trompé. Un second
jour attrape un horodatage qui n'est correct que le jour où il a été produit.

**Deux événements pour `additional`, et pas trois.** La raison est le coût, dite
plutôt que cachée : un appel `additional` coûte 5 crédits et rend les cinq marchés
d'un coup. Deux événements coûtent donc 10 crédits pour deux observations
indépendantes par marché. C'est plus faible que les trois de `core`, et la limite
ci-dessous l'assume.

**Un seul jour UTC pour `additional`.** L'argument « deux jours » porte sur
l'horodatage, que les critères `core` exercent déjà sur deux jours pour la même
forme de réponse. Payer 10 crédits de plus pour le répéter n'achète presque rien.
Ce que ce choix coûte : un marché coté seulement à certaines heures pourrait
passer sur la preuve d'une seule journée.

**Six appels payants conformes.** C'est exactement le sous-produit de la campagne
`core` (3 événements × 2 sports). En exiger plus ferait payer une preuve de coût
que la campagne produit déjà ; en exiger moins laisserait un ou deux appels bien
élevés répondre du comportement de facturation de l'endpoint.

### Ce que chaque critère n'établit pas

- `CORE_MAPPING_*` : que le parser lit `h2h` réel de ce sport **sur les événements
  observés**. Rien sur un bookmaker, une compétition non observée, une autre date,
  un autre marché.
- `ADDITIONAL_MAPPING_*` : que le parser lit ce marché tel que l'endpoint per-event
  l'envoie, sur deux événements. Ni la disponibilité du marché chez un bookmaker,
  ni sa présence à d'autres heures.
- `COST_CONFORMITY` : que le coût observé a été conforme **sur les appels faits**.
  Aucune garantie de facturation future.
- L'ensemble satisfait : que la campagne préenregistrée a été exécutée sans
  contradiction. **Pas** que l'adaptateur est correct.

## 3. Preuve admissible

Une observation compte si, et seulement si, elle est :

1. portée par un reçu **v2 ou v3** dont la **signature se vérifie localement** ;
2. rattachée à une **tentative réseau réellement envoyée** (`network_attempted`) ;
3. de **coût conforme** ou prudemment comptabilisé ;
4. d'un **statut compatible** avec le critère ;
5. pour un critère de mapping : rattachée à des **sélections réellement
   cartographiées** (`core`) ou à `OBSERVED_MAPPED` pour ce marché (`additional`) ;
6. pour un critère de fraîcheur : porteuse d'un **âge exploitable** ≤ 900 s ;
7. **sans rejet de mapping** pertinent pour la propriété revendiquée ;
8. **dédupliquée** selon la règle §4.

## 4. Déduplication

Identité d'une observation, fixée à l'avance :

```text
(receipt_id, sport_key, event_tag, bookmaker, marché, recorded_at)
```

Deux entrées de même identité comptent **une** fois. Ensuite, la diversité se
mesure sur des ensembles distincts :

- **événements** = `event_tag` distincts — le même événement regardé deux fois
  reste **un** événement ;
- **compétitions** = `sport_key` distincts ;
- **jours UTC** = dates distinctes de `recorded_at`.

Répéter un appel est le moyen le moins cher de simuler une campagne. C'est
précisément ce que cette règle rend inopérant.

## 5. Preuve inadmissible

Ne comptent **jamais** comme preuve live de mapping :

| Cas | Pourquoi |
| --- | --- |
| `OFFLINE_CONTRACT_VERIFIED` | une fixture prouve que notre code lit la forme *documentée*, pas que le fournisseur l'envoie |
| une fixture, même complète | idem — aucun arrangement de fixtures ne devient live |
| `COVERAGE_MISSING` | un fait sur l'offre du bookmaker, pas sur le parser |
| `NOT_EVALUATED_BOOKMAKER_ABSENT` | on n'a jamais regardé ce marché |
| `COST_MISMATCH`, `COST_UNVERIFIED` | le coût n'est pas établi |
| `AUTH_FAILED`, `PROVIDER_UNAVAILABLE` | l'appel n'a rien observé |
| `PLAN_ONLY`, `PREPARED_NOT_EXECUTED` | aucun socket n'a été ouvert |
| une sélection non cartographiée | c'est l'échec que le critère cherche |
| signature invalide, schéma inconnu, v1 | invérifiable : compté dans `unverifiable_receipts`, jamais lu |
| un reçu v2 pour une propriété **par marché** | la carte v2 était partielle ; elle ne peut pas établir l'état d'**un** marché nommé |
| un rapport conversationnel sans reçu local | non vérifiable |

**Échec fermé.** Un reçu qui se contredit lui-même n'est pas une preuve faible à
pondérer : cela signifie qu'un de ses champs est faux sans qu'on sache lequel.
L'état devient `EVIDENCE_CONFLICT` et la contradiction est nommée. Sont détectées :
`selections_mapped > 0` sans aucun marché `OBSERVED_MAPPED` en v3 ;
`bookmaker_state = NOT_RETURNED` avec des sélections cartographiées ; un statut
live sans tentative réseau ; `accounted_credits` inférieur à `observed_credits`.

## 6. Expiration : deux questions différentes

| Question | Réponse |
| --- | --- |
| ce reçu **autorise-t-il l'étape suivante** ? | non passé 6 h — `load_parent()` refuse, sans exception |
| ce reçu **atteste-t-il qu'un appel a eu lieu** ? | oui, indéfiniment, s'il est signé et de schéma connu — `audit_receipts()` puis l'évaluateur le lisent |

La TTL de six heures protège contre la réutilisation d'une preuve périmée pour
autoriser une dépense. Elle ne fait pas dis-arriver l'appel qui a eu lieu. Les deux
comportements sont testés, et la TTL n'est pas affaiblie.

## 7. Ce que la machine peut conclure

```text
INSUFFICIENT_EVIDENCE                 — au moins un critère non satisfait
EVIDENCE_CONFLICT                     — au moins un reçu se contredit
CRITERIA_MET_AWAITING_HUMAN_REVIEW    — plafond absolu
```

Il n'existe **pas** de `VERIFIED`. Même tous critères satisfaits :

```text
adapter_state = IMPLEMENTED_UNVERIFIED
models        = BACKTEST_ONLY
```

L'évaluateur n'écrit aucun registre, ne promeut aucun modèle et ne rend `paper` ni
`live_analysis` publiables. `eligible_for_human_promotion_review` ouvre une
conversation, pas une porte.

Supprimer le répertoire de reçus remet la preuve à zéro (D-062). C'est voulu : la
preuve est locale, et une machine réinstallée n'a rien observé.

## 8. Campagne préparée — non exécutée

Aucune commande `discover`, `core` ou `additional` n'est lancée par cette tranche.
Chaque appel exigera une autorisation humaine distincte.

### Piste A — vérifier le parser

Objet : établir `CORE_MAPPING_*` et `ADDITIONAL_MAPPING_*` avec un bookmaker
**raisonnablement susceptible d'être couvert**, choisi sur la documentation
publique officielle du fournisseur, **datée dans `docs/source-matrix.md` au moment
du choix**. Ce document ne nomme pas encore ce bookmaker : le faire maintenant
serait transformer une disponibilité théorique en preuve de couverture. Le choix,
sa source et sa date seront écrits avant le premier appel.

Règles :

- football puis tennis, **séparément** ;
- un sport, une compétition, un événement, un bookmaker **par autorisation** ;
- `discover` (0 crédit) puis `core` (1 crédit) ;
- `additional` (5 crédits) **uniquement après** un `CORE_LIVE_VERIFIED` pertinent ;
- **arrêt immédiat** sur `COVERAGE_MISSING`, `COST_MISMATCH` ou mapping rejeté ;
- **aucune substitution automatique** de bookmaker ou d'événement.

Cette piste valide le parser pour le bookmaker réellement observé. Elle **ne
remplace pas Winamax** dans le produit.

### Piste B — couverture Winamax

Indépendante de la piste A. Le constat acquis reste **borné** : `winamax_fr` était
absent des deux événements SPL testés le **2026-08-07**. Cela ne se généralise ni
au fournisseur, ni à la SPL, ni à une autre date. Toute nouvelle vérification
exige une autorisation par appel, et ne déclenche **aucun** repli vers la démo.

### Budget maximal

Borne issue du tarif relu, **pas** une garantie de facture.

| Étape | Appels | Crédits/appel | Crédits max |
| --- | --- | --- | --- |
| `discover` football (2 jours) | 2 | 0 | 0 |
| `discover` tennis (2 jours) | 2 | 0 | 0 |
| `core` football | 3 | 1 | 3 |
| `core` tennis | 3 | 1 | 3 |
| `additional` football | 2 | 5 | 10 |
| **Total** | **12** | — | **16** |

- requêtes maximales : **12** ;
- autorisations humaines distinctes : **12**, une par appel ;
- crédits maximaux de la campagne complète : **16** ;
- `plan` et `status` restent à 0 crédit et 0 requête.

### Arrêts anticipés qui réduisent le coût

| Constat | Effet |
| --- | --- |
| `discover` sans événement admissible | 0 crédit dépensé, campagne suspendue |
| `COVERAGE_MISSING` au premier `core` | 1 crédit, pas de `additional` |
| `COST_MISMATCH` sur un appel | arrêt immédiat, `COST_CONFORMITY` échoue |
| mapping rejeté sur `core` | arrêt : `additional` n'est pas tenté |
| `CORE_MAPPING_*` non atteint | les 10 crédits `additional` ne sont jamais engagés |

Le pire cas coûte 16 crédits. Le cas d'échec précoce en coûte 1.
