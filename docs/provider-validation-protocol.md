# Protocole de qualification du fournisseur — `PROVIDER_VALIDATION_PROTOCOL_VERSION = 2`

Ce document dit, **avant** les appels, combien de preuve live justifierait de
*demander* à un humain de promouvoir l'adaptateur The Odds API. Il ne promeut rien
lui-même.

Il existe parce que l'inverse s'est produit. Deux appels `core` réels ont abouti,
n'ont trouvé aucune couverture Winamax, et ont été résumés comme une activation qui
« fonctionnait ». Sans seuil écrit à l'avance, n'importe quel résultat se relit
comme encourageant. Des seuils argumentés après coup ne sont pas des critères : ce
sont des descriptions de ce qui est arrivé.

## 0. Ce que la v1 revendiquait sans le tenir

La v1 de ce protocole a été auditée en lecture seule avant tout appel. L'audit a
reproduit cinq défauts qui rendaient trois de ses revendications fausses **au
runtime**, et la v2 les ferme. C'est écrit ici plutôt que réécrit en silence :

| Revendication v1 | Ce que le code faisait | Ce que fait la v2 |
| --- | --- | --- |
| « seuil préenregistré » | le seuil venait du réglage runtime `max_odds_age_seconds`, donc d'un `.env` — sous un numéro de version inchangé, et dans le sens qui desserre | `PROTOCOL_MAX_ODDS_AGE_SECONDS = 900`, un **littéral** ; le module de qualification ne lit **aucune** configuration |
| « écrit avant les observations qu'il juge » | aucune date d'effet : des reçus antérieurs de vingt jours satisfaisaient les huit critères | `QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC`, plus deux versions inscrites **dans** le reçu signé |
| « fermé » | liste noire seule : un statut inconnu, ou celui de l'autre commande, produisait une preuve positive | table **positive** `commande → statuts`, fermée par défaut |
| contradictions détectées | une seule direction : `NOT_RETURNED` + zéro sélection « prouvait » cinq marchés cartographiés | six invariants réciproques, échec fermé |
| « jours UTC » | date civile telle qu'écrite : `00:30+02:00` et `23:30+00:00` comptaient deux jours | normalisation en UTC avant de prendre la date |

Deux erreurs de documentation sont corrigées avec : le budget confondait
invocations CLI et requêtes HTTP (§8), et une assertion anti-fuite portait sur une
sentinelle absente de sa propre fixture (§9).

**Règles de version.** Toute modification d'un seuil, d'une portée, d'une règle
d'admissibilité ou de la date d'effet incrémente
`PROVIDER_VALIDATION_PROTOCOL_VERSION`. Toute modification du parser, du mapping,
de la lecture de fraîcheur ou de la logique de coût qui invalide une preuve
antérieure incrémente `PROVIDER_ADAPTER_EVIDENCE_VERSION`. Une preuve ne qualifie
que si **ses deux versions** correspondent exactement aux versions courantes ; une
preuve plus ancienne reste un fait historique et jamais une preuve courante par
défaut. Les résultats calculés sous deux versions ne se comparent pas. Un critère
assoupli après observation n'est plus un critère, et le numéro de version est ce
qui rend cette manœuvre visible.

Ce que la version de preuve d'adaptateur protège : qu'une preuve produite par un
parser que nous avons depuis modifié soit relue comme une preuve sur le parser que
nous livrons. Ce qu'elle ne protège pas : la validité du payload du fournisseur.
Aucun numéro de version ne valide un payload.

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
observation, âge du marché ≤ **900 s**, reçu **v4** portant
`qualification_protocol_version = 2` et `provider_adapter_evidence_version = 1`,
`recorded_at` **≥ `2026-08-09T19:38:29+00:00`**.

Le 900 est un littéral du protocole. Le produit a par ailleurs un réglage runtime
`max_odds_age_seconds` qui vaut aussi 900 par défaut — au-delà, le scan appelle
déjà un snapshot périmé — et les deux nombres sont **censés** coïncider. Mais ce
sont deux objets distincts : le réglage runtime reste configurable pour le scan,
le seuil du protocole ne l'est pas. S'ils divergent, le protocole garde son 900 et
aucun reçu ne devient plus admissible qu'avant.

| `criterion_id` | Portée | Preuve admissible | Événements | Compétitions | Jours UTC | Schéma |
| --- | --- | --- | --- | --- | --- | --- |
| `CORE_MAPPING_FOOTBALL` | `soccer_*`, `core`, `h2h`, `GROUPED_ODDS` | statut `CORE_LIVE_VERIFIED`, `selections_mapped > 0`, aucun rejet de mapping | **3** | **2** | **2** | **v4/2/1 seul** |
| `CORE_MAPPING_TENNIS` | `tennis_*`, `core`, `h2h`, `GROUPED_ODDS` | idem | **3** | **2** | **2** | **v4/2/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DRAW_NO_BET` | `soccer_*`, `additional`, `draw_no_bet` | statut `ADDITIONAL_LIVE_VERIFIED` ou `ADDITIONAL_PARTIAL_COVERAGE`, `market_states[marché] = OBSERVED_MAPPED` | **2** | **2** | **1** | **v4/2/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DOUBLE_CHANCE` | idem, `double_chance` | idem | **2** | **2** | **1** | **v4/2/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_H2H_3_WAY_H1` | idem, `h2h_3_way_h1` | idem | **2** | **2** | **1** | **v4/2/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_TOTALS_H1` | idem, `totals_h1` | idem | **2** | **2** | **1** | **v4/2/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DOUBLE_CHANCE_H1` | idem, `double_chance_h1` | idem | **2** | **2** | **1** | **v4/2/1 seul** |
| `COST_CONFORMITY` | tous sports, appels payants | coût **établi** au sens du §2.1, 0 appel non conforme | **6** appels au coût établi | — | — | **v4/2/1 seul** |

### 2.1 Ce qu'est un coût conforme

Pas « tout reçu payant qui n'est pas un `COST_MISMATCH` ». Un coût est **établi**
quand, cumulativement : le reçu est admissible au sens ci-dessus ; la commande est
payante (`core` ou `additional`) ; une socket a été ouverte **et** la requête a pu
être servie ; `estimated_credits` est un entier dans `[0, plafond de la commande]` ;
`observed_credits` est un entier — jamais un booléen — dans le même intervalle ;
`accounted_credits == observed_credits` ; et le statut appartient à
`{CORE_LIVE_VERIFIED, ADDITIONAL_LIVE_VERIFIED, ADDITIONAL_PARTIAL_COVERAGE,
COVERAGE_MISSING}`.

Deux conséquences voulues. Un `COVERAGE_MISSING` **postérieur** à la date d'effet
compte pour le coût — il a été facturé et son en-tête était lisible — et ne compte
jamais pour un critère de mapping. Un coût seulement **supposé** après un timeout,
où `accounted_credits` retombe sur l'estimation, n'est pas une preuve de coût : c'est
une écriture de prudence.

### 2.2 Contradictions qui font échouer fermé

Un reçu qui se contredit n'est pas une preuve faible à escompter : l'un de ses
champs est faux et on ne sait pas lequel. Six invariants, réciproques :

1. un marché `OBSERVED_MAPPED` avec `selections_mapped ≤ 0` ;
2. `selections_mapped > 0` sans aucun marché `OBSERVED_MAPPED` ;
3. `bookmaker_state = NOT_RETURNED` avec un marché `OBSERVED_MAPPED` ;
4. `bookmaker_state = NOT_RETURNED` avec un `markets_mapped` non vide ;
5. `markets_mapped` différent de l'ensemble des marchés `OBSERVED_MAPPED` ;
6. un marché `OBSERVED_MAPPED` sans âge de fraîcheur entier et positif.

S'y ajoutent, inchangés : un statut live sans tentative réseau enregistrée, et
`accounted_credits` inférieur à `observed_credits`. Un reçu contradictoire ne
contribue à aucun critère, produit `EVIDENCE_CONFLICT`, et la contradiction est
nommée **sans** nommer d'événement.

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

1. portée par un reçu **v4** dont la **signature se vérifie localement**, portant
   `qualification_protocol_version = 2` et `provider_adapter_evidence_version = 1` ;
2. **postérieure ou égale** à `2026-08-09T19:38:29+00:00`, `recorded_at` étant un
   ISO 8601 avec timezone, normalisé en UTC pour la comparaison ;
3. rattachée à une **tentative réseau réellement envoyée** (`network_attempted`) ;
4. d'un statut **explicitement listé** pour cette commande — `core →
   CORE_LIVE_VERIFIED`, `additional → ADDITIONAL_LIVE_VERIFIED |
   ADDITIONAL_PARTIAL_COVERAGE`. Une liste positive, fermée par défaut : un statut
   inconnu, futur ou appartenant à l'autre commande est refusé ;
5. **non contradictoire** au sens du §2.2 ;
6. pour un critère de mapping : rattachée à des **sélections réellement
   cartographiées** (`core`) ou à `OBSERVED_MAPPED` pour ce marché (`additional`) ;
7. porteuse d'un **âge exploitable** pour le marché du critère, entier, ≤ 900 s ;
8. **sans rejet de mapping** pertinent pour la propriété revendiquée ;
9. **dédupliquée** selon la règle §4.

Le coût a sa propre définition, cumulative, au §2.1 : elle ne se réduit pas à
« pas un `COST_MISMATCH` ».

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
- **jours UTC** = dates distinctes de `recorded_at`, **normalisées en UTC** avant
  d'en prendre la date. Sans cette normalisation, `00:30+02:00` et `23:30+00:00` —
  le même jour UTC, à vingt-deux minutes d'écart — comptaient deux jours.

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
| signature invalide, schéma inconnu, v1 | invérifiable : compté dans `qualification_unverifiable_receipts`, jamais lu |
| un reçu **v2 ou v3**, même valide | il ne peut pas dire sous quel protocole il serait jugé ni quel parser l'a produit. Lisible, honoré pour le chaînage, compté dans `qualification_historical_nonqualifying_receipts` — et qualifiant **aucun** critère, `COST_CONFORMITY` inclus (D-072) |
| un reçu v4 d'une autre version de protocole ou d'adaptateur | historique non qualifiant, **pas** invérifiable : sa signature est valide |
| un reçu antérieur à la date d'effet | de l'histoire. Un seuil écrit après les observations qu'il juge n'est pas un seuil |
| un statut inconnu ou futur | la table d'admissibilité est positive et fermée |
| un rapport conversationnel sans reçu local | non vérifiable |

**Échec fermé.** Un reçu qui se contredit lui-même n'est pas une preuve faible à
pondérer : cela signifie qu'un de ses champs est faux sans qu'on sache lequel.
L'état devient `EVIDENCE_CONFLICT` et la contradiction est nommée, sans nommer
d'événement. Les six invariants réciproques sont listés au §2.2 ; s'y ajoutent un
statut live sans tentative réseau et `accounted_credits` inférieur à
`observed_credits`.

## 6. Expiration : deux questions différentes

| Question | Réponse |
| --- | --- |
| ce reçu **autorise-t-il l'étape suivante** ? | non passé 6 h — `load_parent()` refuse, sans exception |
| ce reçu **atteste-t-il qu'un appel a eu lieu** ? | oui, indéfiniment, s'il est signé et de schéma connu — `audit_receipts()` puis l'évaluateur le lisent |
| ce reçu **qualifie-t-il un critère** ? | seulement s'il est v4, aux versions courantes, et postérieur à la date d'effet. Troisième question, distincte des deux premières |

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

Une invocation CLI n'est **pas** une requête HTTP : `discover` en fait deux —
`/sports` puis les événements de la fenêtre. La v1 de ce document appelait
« requêtes » ce qui était un compte d'invocations, et sous-estimait donc le trafic
de quatre requêtes tout en chiffrant les crédits correctement. Les deux nombres du
total valent seize par coïncidence.

| Étape | Invocations CLI | Requêtes HTTP maximales | Crédits/appel | Crédits max |
| --- | --- | --- | --- | --- |
| `discover` football (2 jours) | 2 | 4 | 0 | 0 |
| `discover` tennis (2 jours) | 2 | 4 | 0 | 0 |
| `core` football | 3 | 3 | 1 | 3 |
| `core` tennis | 3 | 3 | 1 | 3 |
| `additional` football | 2 | 2 | 5 | 10 |
| **Total** | **12** | **16** | — | **16** |

- invocations CLI maximales : **12** ;
- autorisations humaines distinctes : **12**, une par invocation ;
- requêtes HTTP maximales : **16** ;
- requêtes HTTP payantes : **8** ;
- crédits contractuels maximaux : **16** ;
- `plan` et `status` restent à 0 crédit, 0 invocation payante et 0 requête.

Ces cinq totaux sont dérivés de `CAMPAIGN_INVOCATIONS`, `LOCAL_BOUNDS` et
`STEP_CEILINGS` par `qualification.campaign_budget()`, et un test compare la
dérivation à ce document ligne par ligne : une nouvelle confusion entre invocations
et requêtes fait échouer la suite au lieu de passer inaperçue.

### Arrêts anticipés qui réduisent le coût

| Constat | Effet |
| --- | --- |
| `discover` sans événement admissible | 0 crédit dépensé, campagne suspendue |
| `COVERAGE_MISSING` au premier `core` | 1 crédit, pas de `additional` |
| `COST_MISMATCH` sur un appel | arrêt immédiat, `COST_CONFORMITY` échoue |
| mapping rejeté sur `core` | arrêt : `additional` n'est pas tenté |
| `CORE_MAPPING_*` non atteint | les 10 crédits `additional` ne sont jamais engagés |

Le pire cas coûte 16 crédits. Le cas d'échec précoce en coûte 1.
