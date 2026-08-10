# Protocole de qualification du fournisseur — `PROVIDER_VALIDATION_PROTOCOL_VERSION = 4`

Ce document dit, **avant** les appels, combien de preuve live justifierait de
*demander* à un humain de promouvoir l'adaptateur The Odds API. Il ne promeut rien
lui-même.

Il existe parce que l'inverse s'est produit. Deux appels `core` réels ont abouti,
n'ont trouvé aucune couverture Winamax, et ont été résumés comme une activation qui
« fonctionnait ». Sans seuil écrit à l'avance, n'importe quel résultat se relit
comme encourageant. Des seuils argumentés après coup ne sont pas des critères : ce
sont des descriptions de ce qui est arrivé.

## 0. Ce que la v1, puis la v2, revendiquaient sans le tenir

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
sentinelle absente de sa propre fixture.

### 0.1 Puis la v2 a été auditée à son tour

Le même exercice, en lecture seule et avant tout appel, a trouvé cinq surfaces que
la v2 ne couvrait pas. La v3 les ferme :

| Revendication v2 | Ce que le code faisait | Ce que fait la v3 |
| --- | --- | --- |
| « échec fermé » sur une preuve signée | une **signature valide n'atteste que les octets** : `selections_mapped = "3"` valait trois sélections, `network_attempted = "false"` valait une tentative réseau, et un corpus mal typé atteignait la porte de revue | **contrat structurel positif** (§2.0) : types stricts, aucune vérité Python, aucune coercition ; un reçu courant malformé ne prouve rien **et** bloque l'éligibilité |
| « zéro appel non conforme » | un appel payant au coût **non établi** — `PROVIDER_UNAVAILABLE` après un timeout, par exemple — n'entrait dans aucune catégorie et disparaissait du dénominateur | **quatre catégories** exhaustives et disjointes (§2.1) ; un coût non établi est compté **et** bloquant |
| portée « bookmaker observé uniquement » | rien ne lisait `bookmaker_state` : absent ou inconnu, la preuve passait quand même | `bookmaker_state == OBSERVED` **exigé** pour tout critère de mapping |
| audit local robuste | un fichier JSON dont `schema_version` était un mapping ou une liste levait `TypeError` et faisait sortir `status` en erreur | une version est un entier réel ou n'est pas une version ; ces fichiers sont **comptés** invérifiables |
| commande opérateur documentée | `betmaxxing-the-odds-api activation status` n'existait pas — ni dans `[project.scripts]`, ni dans le wheel | forme canonique `python -m …`, et un test structurel interdit d'en documenter une autre |

Deux constats d'intégrité sont fermés avec : un reçu ne peut plus être écrasé
silencieusement (§9), et deux reçus portant le même identifiant avec des contenus
signés différents sont un **conflit de preuve**, pas un événement de plus.

### 0.2 Puis la v3 a été auditée à son tour

Troisième réaudit indépendant en lecture seule, cinq surfaces de plus. La v4 les
ferme — et la première est la v3 se trompant dans l'autre sens : sa rigueur avait
été écrite sans demander ce que le producteur écrit réellement.

| Revendication v3 | Ce que le code faisait | Ce que fait la v4 |
| --- | --- | --- |
| « contrat structurel positif » | il exigeait une carte de marchés **totale** et un `event_tag` non vide de **tout** reçu non-`discover`. Six des quinze reçus que le harnais émet — tout échec `core` survenu *avant* la classification des marchés, et `plan` — devenaient `malformed_current_schema`, donc un seul `AUTH_FAILED` honnête sur le disque plaçait `status` en `EVIDENCE_CONFLICT` pour toujours | contrat **conscient de la phase** (§2.0) : la table versionnée `RECEIPT_PHASES` dit quelles formes honnêtes chaque couple commande/statut peut prendre, et un couple absent est **nommé** (`unknown_command_status_pair`) au lieu d'être jugé contre une forme que personne n'a choisie |
| cinq dimensions « descriptives » séparées | elles employaient des libellés positifs sur une preuve que le bloc strict rejetait : `EXERCISED_CONFORMING` coexistait avec un coût non établi, et `OBTAINED_LIVE` sortait d'un `AUTH_FAILED`, d'un bookmaker `NOT_RETURNED` ou d'un `selections_mapped = "3"` | une seule lecture partagée, `mapping_observation_is_sound`, plus l'état `EXERCISED_UNESTABLISHED` et l'état `PAID_ATTEMPT_INCONCLUSIVE` qui manquaient (§2.3) |
| `paid_calls_that_never_left` | il y rangeait un `may_have_reached_provider` absent ou mal typé — 250 des 875 combinaisons drapeaux/statut/coût affirmaient une certitude que rien n'établissait | la catégorie exige un `false` booléen **certain** ; absent ou mal typé va dans `paid_calls_with_unestablished_cost`, et bloque (§2.1) |
| audit local borné | `audit_receipts()` **suivait** un lien symbolique hors du répertoire, si bien qu'un reçu placé n'importe où sur le disque pouvait satisfaire un critère — alors que `load_parent()` refusait le même lien | la même frontière que `load_parent`, appliquée **avant** toute ouverture ; `write_receipt` valide chaque composant du nom et parse l'instant au lieu d'en découper le texte (§9) |
| « code et documents concordent » | le §3 de ce document publiait encore `qualification_protocol_version = 2` et la date d'effet de la v2, et le fait n°3 du §1 contredisait le §2.1 | une seule version et une seule date d'effet dans tout le texte courant, et un test documentaire distingue l'histoire de la norme |

Trois P3 sont fermés avec : les populations se réconcilient et portent des noms
exacts (§3.1), aucune valeur d'un reçu structurellement invalide n'est reflétée dans
une sortie, et un `receipt_id` divergent est détecté sur **l'ensemble** des reçus
vérifiés — pas seulement sur ceux déjà utilisables.

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
lit par `python -m betmaxxing.providers.the_odds_api.activation status [--json]`.
C'est la **seule** forme installée : `[project.scripts]` ne déclare que
`betmaxxing`, et un test structurel vérifie qu'aucun runbook n'invite à taper une
commande absente.

## 1. Neuf faits, jamais condensés

| # | Fait | Établi par |
| --- | --- | --- |
| 1 | l'adaptateur est **implémenté** | la revue de code et la suite hors ligne |
| 2 | **connectivité et authentification** | un appel réel qui revient sans `AUTH_FAILED` |
| 3 | **conformité du coût** | un coût **établi** au sens du §2.1 : `observed_credits` lisible, dans la borne, et égal à `accounted_credits`. Une comptabilisation prudente après un timeout n'établit rien et **fait échouer** le critère |
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
observation **et `bookmaker_state = OBSERVED`**, âge du marché ≤ **900 s**, reçu
**v4** portant `qualification_protocol_version = 4` et
`provider_adapter_evidence_version = 1`, `recorded_at`
**≥ `2026-08-10T09:11:48+00:00`**, et **contrat structurel du §2.0 satisfait**.

Le 900 est un littéral du protocole. Le produit a par ailleurs un réglage runtime
`max_odds_age_seconds` qui vaut aussi 900 par défaut — au-delà, le scan appelle
déjà un snapshot périmé — et les deux nombres sont **censés** coïncider. Mais ce
sont deux objets distincts : le réglage runtime reste configurable pour le scan,
le seuil du protocole ne l'est pas. S'ils divergent, le protocole garde son 900 et
aucun reçu ne devient plus admissible qu'avant.

| `criterion_id` | Portée | Preuve admissible | Événements | Compétitions | Jours UTC | Schéma |
| --- | --- | --- | --- | --- | --- | --- |
| `CORE_MAPPING_FOOTBALL` | `soccer_*`, `core`, `h2h`, `GROUPED_ODDS` | statut `CORE_LIVE_VERIFIED`, `selections_mapped > 0`, aucun rejet de mapping | **3** | **2** | **2** | **v4/4/1 seul** |
| `CORE_MAPPING_TENNIS` | `tennis_*`, `core`, `h2h`, `GROUPED_ODDS` | idem | **3** | **2** | **2** | **v4/4/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DRAW_NO_BET` | `soccer_*`, `additional`, `draw_no_bet` | statut `ADDITIONAL_LIVE_VERIFIED` ou `ADDITIONAL_PARTIAL_COVERAGE`, `market_states[marché] = OBSERVED_MAPPED` | **2** | **2** | **1** | **v4/4/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DOUBLE_CHANCE` | idem, `double_chance` | idem | **2** | **2** | **1** | **v4/4/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_H2H_3_WAY_H1` | idem, `h2h_3_way_h1` | idem | **2** | **2** | **1** | **v4/4/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_TOTALS_H1` | idem, `totals_h1` | idem | **2** | **2** | **1** | **v4/4/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DOUBLE_CHANCE_H1` | idem, `double_chance_h1` | idem | **2** | **2** | **1** | **v4/4/1 seul** |
| `COST_CONFORMITY` | tous sports, appels payants | coût **établi** au sens du §2.1, 0 appel non conforme | **6** appels au coût établi | — | — | **v4/4/1 seul** |

### 2.0 Contrat structurel : une signature prouve des octets, pas des types

Une signature valide établit que ces octets sont les nôtres et n'ont pas été
altérés. Elle ne dit **rien** sur le fait que `network_attempted` soit un booléen
plutôt que la chaîne `"false"`. Avant qu'un champ soit lu comme preuve, le reçu
doit donc satisfaire un contrat positif.

**Types communs, exigés de tout reçu.** La distinction entre les deux règles
numériques est voulue : une version n'a pas de zéro, un compteur en a un.

- `schema_version`, `qualification_protocol_version` et
  `provider_adapter_evidence_version` sont des entiers **réels et strictement
  positifs** ;
- `attempts`, `selections_mapped`, `estimated_credits` et `accounted_credits` sont
  des entiers **réels et non négatifs** — zéro est une réponse : `discover` est
  documenté gratuit, et un appel prouvé jamais parti est facturé 0. Un booléen n'est
  jamais un entier admissible ;
- `attempts` est **obligatoire**, et cohérent avec le drapeau réseau :
  `network_attempted = false` impose `attempts == 0`, `true` impose `attempts ≥ 1` ;
- `observed_credits` et `quota_remaining` sont un entier réel **ou** `null` — et
  `null` rend le coût *non établi*, jamais conforme ;
- `network_attempted` et `may_have_reached_provider` valent exactement `true` ou
  `false` : ni chaîne, ni entier, ni conteneur ;
- `recorded_at` est un ISO 8601 textuel avec fuseau ;
- `receipt_id`, `sport_key`, `command` et `status` sont des chaînes non vides.

**Le reste dépend de la phase.** C'est l'apport de la v4. Ce qu'un reçu doit
contenir dépend de jusqu'où son couple commande/statut est réellement allé, et cette
correspondance est la table **versionnée** `RECEIPT_PHASES`, testée contre
`build_receipt` — pas déduite de la vérité d'un champ.

| Phase | Ce qu'elle signifie | Ce que le reçu doit porter |
| --- | --- | --- |
| `PLANNED` | aucune socket ouverte | `network_attempted = false`, `may_have_reached_provider = false`, `attempts = 0`, `bookmaker` et `bookmaker_state` présents, `event_tag` absent ou vide — aucun événement n'a été nommé —, carte de marchés **vide**, projections vides, `freshness` vide, `selections_mapped = 0` |
| `DISCOVERED` | `discover` a atteint les deux endpoints gratuits | `event_tags` liste de chaînes non vides sans doublon, `events_returned`, `events_in_window` et `events_admissible` entiers non négatifs. **Aucune** observation de bookmaker n'est exigée : `/events` n'en renvoie aucune |
| `ATTEMPTED_UNCLASSIFIED` | la requête payante est partie, aucun marché n'a été classifié | `network_attempted = true`, `attempts ≥ 1`, `event_tag` non vide, `bookmaker_state` connu, et carte de marchés **vide** — vide *parce que rien n'a été regardé*, ce qui est précisément ce qui interdit de la lire comme une observation |
| `CLASSIFIED` | l'état du bookmaker a été relevé et chaque marché demandé classifié | `network_attempted = true`, `attempts ≥ 1`, `event_tag` non vide, `market_states` **total** sur `markets_requested` avec des états connus, chaque projection présente image **exacte** de la carte, `freshness` mapping `marché → entier ≥ 0` dont les clés sont incluses dans `markets_requested` |

Deux couples portent **deux** phases admissibles, et c'est un fait sur le harnais,
pas une échappatoire : `COVERAGE_MISSING` et `SCHEMA_MISMATCH` sont atteignables
depuis `_event_of` — avant l'observation du bookmaker — et depuis la fin de
`run_core` / `run_additional`, après que chaque marché a un état. Les deux formes
sont honnêtes ; seule la forme classifiée peut porter une observation.

Un couple commande/statut **absent** de la table n'est pas jugé contre une forme que
personne n'a choisie : il est nommé `unknown_command_status_pair`. Inventer un
contrat pour un statut que nous n'avons jamais produit est la façon dont un statut
futur qualifierait quelque chose en silence.

Un reçu courant qui manque à ce contrat est signalé par la raison
`malformed_current_schema`, avec **les noms des champs fautifs et jamais leurs
valeurs**. Il ne prouve rien, il ne disparaît pas du corpus, et il fait passer
l'état global à `EVIDENCE_CONFLICT` : une preuve illisible n'est pas une archive
tranquille. Aucune valeur d'un tel reçu n'est reflétée dans le JSON complet de
`status`, dans la sortie humaine, dans les observations de couverture, dans les
raisons ou dans les conflits : une sortie peut nommer un champ, jamais recopier ce
qu'il contenait.

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

**Le dénominateur : une tentative payante réelle.** Les quatre catégories sont
exhaustives et disjointes sur une population **explicitement définie** — un reçu de
commande payante (`core` ou `additional`) dont `network_attempted` n'est pas
exactement `false`.

Seul un `false` exact prouve qu'aucun appel payant n'a eu lieu : c'est la forme d'une
étape refusée avant toute socket, et une telle étape n'est pas un appel payant, quel
que soit son libellé. Un drapeau **absent ou mal typé** ne prouve rien, donc le reçu
reste dans le recensement et tombe dans `paid_calls_with_unestablished_cost` au lieu
d'en sortir discrètement. Le dénominateur n'est **pas** étendu aux étapes payantes
refusées avant réseau : les compter gonflerait le dénominateur d'un critère sur la
facturation avec des appels jamais facturés.

**Quatre catégories, exhaustives et disjointes**, dans cet ordre :

| Catégorie | Ce qu'elle contient |
| --- | --- |
| — (hors recensement) | `network_attempted = false` exactement : aucun appel payant n'a été tenté |
| `paid_calls_with_unestablished_cost` | l'un des deux drapeaux est absent ou mal typé ; **ou** l'appel a pu atteindre le fournisseur mais son coût n'est pas établi : statut inconnu, observation absente ou hors borne, comptabilisation divergente, reçu malformé ou contradictoire |
| `nonconforming_paid_calls` | `COST_MISMATCH` ou `COST_UNVERIFIED` |
| `paid_calls_that_never_left` | les deux drapeaux sont des booléens **et** `may_have_reached_provider = false` : rien n'a pu être facturé, donc rien n'est prouvé ni reproché. Une certitude, jamais une valeur par défaut |
| `conforming_paid_calls` | le coût est établi au sens ci-dessus |

Le critère passe **si et seulement si** :

```text
conforming_paid_calls >= 6
nonconforming_paid_calls == 0
paid_calls_with_unestablished_cost == 0
```

Un `PROVIDER_UNAVAILABLE` qui a pu atteindre le fournisseur fait donc échouer le
critère, même après six appels conformes. La v2 l'ignorait en silence.

**Ce que ce critère ne prouve pas.** Il établit deux choses : aucun appel n'a
dépassé la borne annoncée, et ce que nous comptabilisons égale ce que le
fournisseur a annoncé. Il n'établit **pas** que le tarif contractuel a été appliqué
exactement — un appel annoncé à 0 crédit reste conforme, ce qui prouve l'absence de
dépassement et non le tarif.

### 2.2 Contradictions qui font échouer fermé

Un reçu qui se contredit n'est pas une preuve faible à escompter : l'un de ses
champs est faux et on ne sait pas lequel. Six invariants, réciproques :

1. un marché `OBSERVED_MAPPED` avec `selections_mapped ≤ 0` ;
2. `selections_mapped > 0` sans aucun marché `OBSERVED_MAPPED` ;
3. `bookmaker_state = NOT_RETURNED` avec un marché `OBSERVED_MAPPED` ;
4. `bookmaker_state = NOT_RETURNED` avec un `markets_mapped` non vide ;
5. `markets_mapped`, **quand le reçu le porte**, différent de l'ensemble des marchés
   `OBSERVED_MAPPED` — une projection absente est un silence, pas un désaccord, et le
   contrat structurel les traite déjà toutes comme facultatives ;
6. un marché `OBSERVED_MAPPED` sans âge de fraîcheur entier et **non négatif**.

S'y ajoutent, inchangés : un statut live sans tentative réseau enregistrée, et
`accounted_credits` inférieur à `observed_credits`. Un reçu contradictoire ne
contribue à aucun critère, produit `EVIDENCE_CONFLICT`, et la contradiction est
nommée **sans** nommer d'événement.

Le tennis n'a **pas** de marchés `additional` : `ADDITIONAL_MARKETS_BY_SPORT[TENNIS]`
est vide, donc aucun critère `additional` tennis n'existe. C'est une absence
voulue, pas un oubli.

### 2.3 Les cinq dimensions de `status` lisent la même preuve

`activation status` rapporte cinq dimensions distinctes plus le bloc de
qualification, parce que ce sont des faits distincts qu'un seul libellé ne porte pas.
Distinct ne veut pas dire indulgent, et c'est ce que la v4 corrige : aucune dimension
ne peut employer un libellé positif sur une preuve que le bloc strict rejette pour le
même fait.

**Une observation de mapping saine** — `mapping_observation_is_sound` — exige
cumulativement : commande payante ; statut positif de mapping pour cette commande ;
phase `CLASSIFIED` admissible ; contrat structurel satisfait ; aucune contradiction ;
`network_attempted = true` ; `bookmaker_state = OBSERVED` ; `selections_mapped ≥ 1` ;
au moins un marché `OBSERVED_MAPPED` ; et un âge ≤ 900 s pour ce marché.

Elle **n'inclut pas** la barrière de version et de date, délibérément. La
qualification demande « est-ce une preuve pour les critères que nous avons
préenregistrés », ce qu'un changement de protocole remet légitimement à zéro. Cette
lecture demande « le parser a-t-il déjà lu un marché live ici », ce qu'un changement
de protocole ne défait pas.

| Dimension | Libellé positif possible seulement si |
| --- | --- |
| `connectivity_and_cost_proof` | précédence `NONCONFORMING > UNESTABLISHED > CONFORMING > NOT_EXERCISED` appliquée au recensement du §2.1. `EXERCISED_CONFORMING` exige au moins un appel payant établi et conforme, **zéro** non conforme et **zéro** coût non établi. `EXERCISED_UNESTABLISHED` est un état à part entière : un coût non établi n'est ni conforme ni un écart. Une découverte gratuite seule laisse `NOT_EXERCISED` |
| `mapping_freshness_proof` | `OBTAINED_LIVE` exige au moins une observation de mapping **saine** au sens ci-dessus. Une erreur, une couverture absente, un reçu malformé ou contradictoire ne l'atteint jamais par la seule présence d'un `selections_mapped > 0` |
| `paid_activation_state` | `CORE_EXECUTED_COVERAGE_OBSERVED` exige une observation saine ; `CORE_EXECUTED_NO_COVERAGE` exige un reçu dont la phase a réellement répondu à la question du bookmaker ; sinon `PAID_ATTEMPT_INCONCLUSIVE` — un appel payant réellement parti qui n'a établi ni couverture ni mapping |
| `bookmaker_coverage_observations` | n'y figurent que des reçus de phase `CLASSIFIED`, structurellement valides et non contradictoires. Une observation est une **réponse**, pas la trace d'une tentative |
| `accounted_credits_total` | somme d'entiers réels **non négatifs** seulement. Ni booléen, ni chaîne numérique, ni nombre négatif : c'est un chiffre de dépense qu'un opérateur lit avant de décider d'en dépenser plus |

**Deux populations, nommées.** `paid_call_cost_census` recense **toute tentative
payante réelle vérifiée sur ce disque**, protocoles antérieurs compris et sans
déduplication : c'est la population dont `connectivity_and_cost_proof` parle.
`COST_CONFORMITY` compte une population plus étroite — protocole courant uniquement,
dédupliquée. Les deux nombres peuvent donc légitimement différer, et les nommer tous
les deux est ce qui empêche de lire cet écart comme une contradiction.

Le plafond machine reste inchangé : la meilleure conclusion atteignable est
`CRITERIA_MET_AWAITING_HUMAN_REVIEW`, et `adapter_state` reste
`IMPLEMENTED_UNVERIFIED` quelle que soit l'issue.

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
   `qualification_protocol_version = 4` et `provider_adapter_evidence_version = 1` ;
2. **postérieure ou égale** à `2026-08-10T09:11:48+00:00`, `recorded_at` étant un
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

### 3.1 Populations et équation de réconciliation

Chaque reçu vérifié appartient à **exactement une** population, et un fichier que
cette installation n'a pas pu vérifier est compté à part. L'équation est publiée par
`status` sous `qualification_population_equation` et testée :

```text
reçus vérifiés + fichiers invérifiables
  = qualification_usable_receipts
  + qualification_current_malformed_receipts
  + qualification_current_contradictory_receipts
  + qualification_unknown_pair_receipts
  + qualification_historical_nonqualifying_receipts
  + qualification_duplicate_excluded_receipts
  + qualification_unverifiable_receipts
```

| Population | Ce qu'elle contient |
| --- | --- |
| `qualification_usable_receipts` | courant, bien formé, non contradictoire : utilisable par l'évaluation |
| `qualification_current_malformed_receipts` | courant et hors contrat structurel. **Courant**, pas « historique » : le ranger sous l'histoire se lisait comme « produit sous un protocole antérieur », l'inverse de la vérité |
| `qualification_current_contradictory_receipts` | courant et se contredisant lui-même |
| `qualification_unknown_pair_receipts` | courant, portant un couple commande/statut absent de la table de phases |
| `qualification_historical_nonqualifying_receipts` | schéma antérieur, autre version de protocole ou d'adaptateur, antérieur à la date d'effet, `recorded_at` inutilisable |
| `qualification_duplicate_excluded_receipts` | population **exclusive** et prioritaire : un `receipt_id` nommant deux contenus signés différents rend tous les exemplaires concernés inutilisables, quelle que soit leur sous-population |
| `qualification_unverifiable_receipts` | signature invalide, schéma inconnu, fichier illisible, lien symbolique, répertoire nommé `*.json` |

Un identifiant nomme **un** reçu. La divergence est calculée sur **l'ensemble** des
reçus vérifiés avant tout classement : sous la v3 elle ne voyait que la
sous-population déjà utilisable, si bien qu'un reçu utilisable et un reçu malformé,
contradictoire ou historique partageant un identifiant passaient pour un fait unique.

Les **copies byte-à-byte identiques** sont une **dimension croisée**, pas une
population : la même observation deux fois reste dans la population de son contenu, et
seuls les compteurs de diversité la dédupliquent. Le nombre est publié séparément sous
`qualification_exact_duplicate_copies`. Mélanger les deux modèles est la façon dont
une équation de réconciliation cesse de s'équilibrer.

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
| un statut inconnu ou futur | la table d'admissibilité est positive et fermée, et la table de phases nomme le couple `unknown_command_status_pair` au lieu de lui inventer une forme |
| un reçu de phase `ATTEMPTED_UNCLASSIFIED` | sa carte de marchés est vide **parce que rien n'a été regardé**. Le reçu est courant et honnête ; il n'observe rien |
| un reçu atteint par un lien symbolique, ou dont la cible se résout hors du répertoire de reçus | il n'est même pas ouvert : compté invérifiable, sans que son chemin ni son contenu apparaissent nulle part |
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

## 9. Écriture et audit des reçus : une frontière, appliquée avant toute lecture

Le répertoire de reçus est local, gitignoré, sans distant, et **tout ce qui peut y
écrire n'est pas nous**. Les deux fonctions qui le touchent appliquent donc la même
frontière, et l'appliquent **avant** d'ouvrir quoi que ce soit.

`audit_receipts()` — lecture, jamais autorité. Aucun reçu trouvé ici n'autorise une
étape : une étape est autorisée par un reçu que l'opérateur nomme en ligne de
commande. Jusqu'à la v3 cette fonction **suivait** les liens symboliques, si bien
qu'un reçu placé n'importe où sur le disque pouvait satisfaire un critère — alors que
`load_parent()` refusait exactement le même lien.

| Cas | Résultat |
| --- | --- |
| fichier régulier interne valide | vérifié et lu |
| copie régulière byte-à-byte identique | **une** observation (dimension croisée du §3.1) |
| lien symbolique interne | jamais suivi, compté invérifiable |
| lien symbolique externe | jamais suivi, compté invérifiable, **zéro** contribution |
| lien brisé | compté invérifiable, jamais ouvert |
| répertoire nommé `x.json` | compté invérifiable |
| cible se résolvant hors du répertoire | jamais lue |

Aucun de ces cas ne fait apparaître un chemin ni un contenu étranger dans une sortie.

`write_receipt()` — écriture exclusive, nom construit depuis des composants
**validés**. `command` et `receipt_id` doivent être des chaînes non vides sans
séparateur de chemin ; `recorded_at` est **parsé** puis reformaté, au lieu d'être
découpé dans le texte. Cette dernière règle est ce qui manquait : un `recorded_at` de
`"../../2026-08-11T12:00:00+00:00"` survivait au découpage sous la forme
`"../../20260811T"` et plaçait le reçu deux répertoires au-dessus du sien.

Le parent résolu est revérifié juste avant l'ouverture exclusive, et un lien
symbolique déjà présent à la cible est refusé **sans** lire ce qu'il désigne. Réécrire
un reçu byte-à-byte identique est idempotent ; un contenu divergent sous le même nom
est refusé plutôt que substitué — un reçu n'est jamais remplacé.
