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

## Ce que la frontière des reçus garantit, et ce qu'elle ne garantit pas (D-078)

Cette section existe parce que sept tranches de suite, la formulation a dépassé le code.
Lisez-la avant de citer une garantie.

**La propriété garantie, littéralement :**

> Dans le pipeline applicatif supporté, seuls les reçus dont le HMAC a été vérifié par
> `audit_directory` sont transmis à l'évaluation. L'objet de provenance est un marqueur
> interne et un contrôle contre les erreurs d'utilisation ; il ne constitue pas une sandbox
> contre du code Python arbitraire exécuté dans le même processus.

**Dans le périmètre de sécurité.** Fichiers de reçus, intents et payloads fournisseur
hostiles ou malformés ; reçus sans signature ou signés avec une autre clé ; écritures
interrompues et erreurs de stockage ; liens symboliques, substitutions de chemins et courses
de système de fichiers ; appelant utilisant les API publiques et documentées ; erreurs
accidentelles du code applicatif ; processus extérieur ne possédant ni le secret HMAC ni la
capacité d'exécuter du code dans le processus Betmaxxing.

**Hors du périmètre de sécurité.** Exécution arbitraire de Python dans le processus
Betmaxxing ; accès réflexif aux attributs privés ; `object.__new__`, `object.__setattr__`,
monkeypatching, modification du bytecode ou des modules ; modification du code source
exécuté ; debugger ou processus compromis sous l'identité de l'application ; accès direct au
secret HMAC.

Un acteur capable d'exécuter arbitrairement du Python ici peut remplacer `evaluate`,
neutraliser le vérificateur ou lire le secret. Se protéger de lui demanderait une isolation
par processus ou service, hors périmètre de 03C-1. Donc : **l'authenticité vient du HMAC
vérifié à l'ingestion**, une fois. Le type de provenance et la somme de contrôle
`content_checksum` ne font que préserver cette décision jusqu'à l'évaluation — la somme de
contrôle attrape une mutation accidentelle, elle n'authentifie rien.

Ce que cela change pour vous, concrètement : si vous devez répondre « qu'est-ce qui prouve
que ce reçu est authentique ? », la réponse est « le HMAC du secret de cette installation,
vérifié par l'audit au moment de la lecture » — jamais « son type Python ».

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
  `--core-receipt`. Depuis D-077 la valeur est réduite **textuellement** à un nom de
  base du répertoire de reçus autorisé : le nom seul, ou le chemin que la commande
  précédente a imprimé, et rien d'autre. Aucune cible n'est résolue, donc aucun lien
  n'est suivi, et le fichier est lu par le même descripteur que l'audit.
  L'outil ne parcourt plus le répertoire de reçus pour se
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

## La campagne protocole 8, et la garde qui la fait respecter

Depuis le protocole 8, les bornes de la campagne ne sont plus seulement écrites : elles
sont comptées à partir des reçus vérifiés présents sur la frontière, et opposées à
chaque commande réseau **avant** qu'elle ne coûte quoi que ce soit.

### Le manifeste

| | |
|---|---|
| Bookmaker | `pinnacle` — et lui seul |
| Football | `soccer_epl`, `soccer_spain_la_liga` |
| Tennis | `tennis_atp_us_open`, `tennis_wta_us_open` |
| Instant d'effet | `2026-08-25T00:00:00+00:00` |
| Plafonds | `discover` 4 · `core` 6 (3 par famille) · `additional` 2 (football seulement) |

Sources publiques du choix, consultées le **2026-08-24**, dans `docs/source-matrix.md`.
`winamax_fr` et la piste B sont exclus de cette campagne.

### Ce que la garde refuse, et ce qu'elle laisse derrière elle

`campaign_preflight` s'exécute après la lecture du secret de signature local et **avant**
la lecture de la clé fournisseur, la publication d'un intent et toute socket. Elle refuse :

- un bookmaker qui n'est pas `pinnacle` ;
- une compétition hors manifeste, ou un `additional` sur une compétition de tennis ;
- un plafond déjà atteint — 4 découvertes, 6 `core`, 2 `additional` ;
- une seconde découverte d'une compétition déjà découverte ;
- un quatrième `core` dans une famille, un second `additional` sur une compétition ;
- un événement déjà utilisé par la même commande ;
- **toute** commande si la campagne est `ABORTED` ou `CONFLICT` ;
- **toute** commande si les comptes ne sont pas établis ;
- **toute** commande si `BETMAXXING_BOOKMAKERS` ne nomme pas `pinnacle`.

Un refus laisse exactement : 0 socket, 0 lecture de clé fournisseur, 0 intent, 0 reçu,
0 crédit.

### Un échec consomme sa place

Une commande réseau v8 dont le reçu ne porte pas le statut de succès de sa commande
abandonne définitivement la campagne. `status` et `plan` restent lisibles ; `discover`,
`core` et `additional` sont refusés avant réseau. Recommencer exige un **nouveau
protocole** — pas une relance de la v8.

### Avant le premier appel

```bash
export BETMAXXING_BOOKMAKERS=pinnacle
```

Le harnais analyse une réponse payante avec le parser de l'adaptateur, et ce parser ne
retient que les bookmakers nommés par `BETMAXXING_BOOKMAKERS` — **pas** celui passé en
argument. Les deux coïncidaient tant que les deux valaient `winamax_fr`, qui reste le
défaut livré ; sous le manifeste v8 ils divergent.

Ce n'est plus une consigne à retenir : la garde le vérifie. `pinnacle` doit figurer dans
`BETMAXXING_BOOKMAKERS`, et toute autre configuration — variable absente, vide, ou
nommant d'autres bookmakers — est **refusée avant la lecture de la clé fournisseur,
avant tout intent et avant toute socket**, pour `discover`, `core` et `additional`. La
casse est exacte : `PINNACLE` n'est pas `pinnacle`.

Ce refus ne consomme aucune invocation, ne dépense aucun crédit et n'abandonne pas la
campagne. Sans lui, un `core` conforme au manifeste avec la variable simplement absente
atteignait l'endpoint payant, publiait `SCHEMA_MISMATCH`, dépensait un crédit et plaçait
la campagne en `ABORTED` sans retour possible.

### Ce que `status --json` publie

| Champ | Sens |
|---|---|
| `campaign_protocol_version` | `8` |
| `campaign_counts_state` | `ESTABLISHED` ou `UNESTABLISHED` |
| `campaign_invocation_counts` | `{"discover": …, "core": …, "additional": …}`, ou `null` si non établi |
| `campaign_invocation_limits` | `{"discover": 4, "core": 6, "additional": 2}` |
| `campaign_execution_state` | `NOT_STARTED` · `IN_PROGRESS` · `ABORTED` · `COMPLETE` · `CONFLICT` · `UNESTABLISHED` |
| `campaign_abort_reason` | vide, sinon la commande et le statut qui ont arrêté la campagne |
| `campaign_required_bookmaker` | `pinnacle` |
| `campaign_required_scopes` | les quatre compétitions, par famille |

**Aucun compteur numérique n'est publié avant d'avoir été établi.** « Je ne peux pas
compter » et « rien n'a été dépensé » sont des faits opposés, et le second autorise à
dépenser.

Le reçu réel du protocole 7 — la découverte vide de `soccer_france_ligue_one` chez
`winamax_fr` — reste sur la frontière, signé, **historique non qualifiant**. Il ne
compte dans aucun compteur v8 et ne doit être ni supprimé, ni mis en quarantaine, ni
réutilisé.

---

## Les reçus (schéma v2, signés)

Chaque **tentative réseau** écrit un reçu JSON local sous `.activation-receipts/`
(ou le chemin de `BETMAXXING_ACTIVATION_RECEIPTS`). Ce répertoire est dans
`.gitignore` : un reçu est une trace d'exploitation d'un appel réel et facturé, il
appartient à l'opérateur, pas au dépôt.

### Le secret local de signature

Un secret aléatoire est créé dans le répertoire de reçus, publié atomiquement en
mode `0600`. Il n'est jamais affiché, jamais journalisé, jamais versionné. Les
tests injectent un secret déterministe par `BETMAXXING_ACTIVATION_RECEIPT_SECRET`
et ne dépendent d'aucun aléa réel.

Il est créé de deux façons, et une seule est délibérée : par `receipts provision`
(voir plus bas), ou à défaut au premier besoin réseau. Jusqu'à l'ajout de la
commande, seule la seconde existait — la première commande qui ouvrait la
frontière était donc `discover`, c'est-à-dire un appel fournisseur, et
provisionner *avant* toute socket n'était pas exécutable.

Sa politique, depuis D-077, en toutes lettres :

* **un secret est exactement 64 caractères hexadécimaux minuscules.** Rien n'est
  « réparé » : ni `strip()`, ni casse tolérée, ni régénération d'un secret invalide —
  le régénérer rendrait invérifiable chaque reçu déjà signé ;
* **la variable d'environnement est une configuration, pas un argument.** Elle gagne
  quand elle est *positionnée*, et une variable **présente mais vide** est une valeur
  invalide, plus une absence. Seule l'absence réelle autorise la lecture du fichier ou
  la création ;
* **sur POSIX, un secret que quelqu'un d'autre peut lire est refusé** : non régulier,
  appartenant à un autre UID, ou accordant un droit au groupe ou à tous. Le mode
  attendu est `0600`. Sur une plateforme sans propriété ni bits de permission POSIX ce
  contrôle est **sauté**, et c'est une limite énoncée, pas une garantie implicite ;
* **des octets qui ne sont pas de l'UTF-8 valide sont un refus typé**, jamais un
  `UnicodeDecodeError` remonté à l'opérateur.

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

### 0 bis. `receipts provision` — ouvrir la frontière (hors ligne, 0 crédit)

```bash
export BETMAXXING_ACTIVATION_RECEIPTS="$HOME/.local/state/betmaxxing/activation-receipts"
python -m betmaxxing.providers.the_odds_api.activation receipts provision --json
```

Crée le répertoire en `0700` s'il manque, puis publie `signing-key.secret` en
`0600` par le même chemin atomique que toute autre publication. Aucun réseau,
aucun crédit, aucun reçu, aucun intent, aucune promotion.

Ce qu'elle exige, et pourquoi :

* **`BETMAXXING_ACTIVATION_RECEIPTS` doit être définie sur un chemin absolu.**
  C'est la seule commande qui refuse le défaut relatif. `.activation-receipts` se
  résout contre le répertoire courant — le bon comportement pour un opérateur qui
  lance une étape dans son projet, un piège pour une clé censée survivre à toute la
  campagne : la frontière atterrirait là où le shell se trouvait, et une exécution
  ultérieure depuis un cran plus haut rapporterait une ardoise vierge pendant que
  les reçus signés dormiraient ailleurs ;
* **un lien symbolique, un FIFO, un fichier régulier ou un composant ambigu sont
  refusés**, sans rien suivre et sans rien créer.

Ce qu'elle ne fait **jamais** : remplacer, faire tourner ou « réparer » un secret
existant, même invalide, même trop ouvert. Le réécrire rendrait invérifiable
chaque reçu déjà signé avec lui. Un second passage conserve donc strictement la
clé en place — la commande est idempotente, et son idempotence est une garantie
de conservation, pas une commodité.

Si `BETMAXXING_ACTIVATION_RECEIPT_SECRET` est **positionnée et valide**, elle est
la configuration : la commande ouvre le répertoire mais n'écrit aucun fichier de
clé, puisqu'un fichier doublant la variable serait une seconde source de vérité.
**Positionnée et invalide**, c'est un échec fermé — jamais un repli sur le
fichier. Le contenu d'une valeur valide n'est ni affiché ni journalisé.

Rien de ce que la commande écrit ne permet de reconstituer la clé : ni sa valeur,
ni sa longueur, ni un préfixe ou un suffixe, ni une empreinte.

Le succès n'est acquis qu'après relecture de la frontière :

```text
receipt_boundary_state     = "AVAILABLE"
receipt_boundary_reason    = ""
unresolved_attempt_intents = 0
```

**Conserver cette clé jusqu'à la fin de la campagne.** Sa perte rendrait
invérifiables tous les reçus signés avec elle.

### 1. `plan` — hors ligne, 0 crédit

```bash
python -m betmaxxing.providers.the_odds_api.activation plan \
  --sport soccer_france_ligue_one \
  --bookmaker winamax_fr \
  --max-credits 6
```

Ne lit ni la clé ni le secret de signature, ne construit aucun client HTTP,
n'écrit aucun reçu. Affiche la séquence chiffrée et `PLAN_ONLY`.
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
  --discovery-receipt NOM_RECU_DISCOVER.json \
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
  --core-receipt NOM_RECU_CORE.json \
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

## Lire la qualification (D-071, corrigée par D-072 à D-077)

`activation status` porte, depuis 03C-1, un sixième bloc : l'évaluation des
critères **préenregistrés** de `docs/provider-validation-protocol.md`
(`PROVIDER_VALIDATION_PROTOCOL_VERSION = 7`,
`PROVIDER_ADAPTER_EVIDENCE_VERSION = 1`, schéma de reçu `v4`).

```bash
python -m betmaxxing.providers.the_odds_api.activation status         # lecture humaine
python -m betmaxxing.providers.the_odds_api.activation status --json  # les mêmes faits, parseable
```

Les deux sorties portent les **mêmes faits matériels** : recensement du coût et sa
population, crédits comptés, crédits rejetés non comptés, reçus payants rejetés, intents
de tentative non résolus, états d'exécution et de commande, preuve de connectivité, et
raisons bloquantes. La lecture humaine est plus compacte ; elle n'omet rien qui changerait
une décision. Jusqu'à la v5 le recensement et les crédits rejetés n'existaient qu'en JSON
alors que ce document annonçait « le même contenu ».

### Trois états de la frontière des reçus

`activation status` publie, en JSON et en lecture humaine, l'état de la frontière
elle-même — parce qu'un répertoire qu'on ne peut pas lire n'est pas un répertoire vide,
et que la v6 rapportait les deux à l'identique :

| État | Ce qu'il dit | Effet sur la porte |
| :-- | :-- | :-- |
| `ABSENT` | aucun répertoire de reçus : rien n'a encore été exécuté, et **rien n'est créé** par la lecture | aucune preuve, donc fermée |
| `AVAILABLE` | répertoire sûr et lu ; les comptes de reçus valent ce qu'ils disent | selon les critères |
| `UNAVAILABLE` | le répertoire existe et n'est pas lisible sans ambiguïté — lien symbolique, composant substitué, objet non régulier, permission refusée, garantie noyau absente | **conflit de preuve**, fermée |

`UNAVAILABLE` est accompagné d'une **catégorie** (`ambiguous_component`,
`not_a_directory`, `permission_denied`, `kernel_support_missing`, `unreadable`), jamais
d'un chemin. La lecture humaine ajoute une ligne `FRONTIÈRE INDISPONIBLE` qui dit que
plus aucun compte n'est établi.

### Le contrat d'un intent de tentative

Un intent est un **bloqueur prudent**, jamais une preuve positive. Depuis D-077 son
contrat est fermé dans les deux sens : neuf champs exactement — `intent_version`,
`attempt_id`, `command`, `sport_key`, `bookmaker`, `event_tag`, `max_credits`, `state`,
`prepared_at` —, types et bornes vérifiés, commande dans un domaine fermé, et
identifiant du corps égal au nom du fichier. Un champ absent, un champ en trop, une
valeur mal typée ou hors borne : l'intent est **invalide**, il reste **bloquant**, et il
est rapporté sous son seul nom local avec l'état `UNREADABLE_OR_INVALID`. Aucune valeur
de son contenu n'est réfléchie dans le JSON ni dans le terminal.

Publier deux fois le même intent est idempotent **sur octets identiques seulement**.
Le même `attempt_id` avec une commande, un sport, un bookmaker, un tag ou un plafond
différents est un refus typé **avant le réseau**, et une cible vide, tronquée, lien ou
répertoire n'est jamais comptée comme une publication réussie.

Un intent n'est résolu que par un reçu **durable, vérifié par l'audit contre le secret
local, de schéma accepté**, portant le même identifiant, la même commande, le même
sport, le même bookmaker, le même tag éventuel, un coût compatible avec son plafond, un
couple réellement persistable du catalogue, aucune faute structurelle, aucune
contradiction et la même lignée de versions. Un JSON seulement analysable, une signature
d'une autre clé, un schéma inconnu, une commande inconnue ou une portée différente ne le
résolvent **jamais** : la v6 les acceptait tous les treize.

### Reprendre après un reçu incomplet

Une interruption peut laisser un fichier de reçu vide ou tronqué. Il est nommé comme tel
et jamais confondu avec un reçu signé divergent, et la sortie de secours est une commande,
pas une fonction interne :

```bash
python -m betmaxxing.providers.the_odds_api.activation receipts quarantine --name NOM.json
```

Elle exige un **nom de base** du répertoire de reçus, jamais un chemin ; elle conserve
tous les octets sous un nom hors de l'audit, ne remplace jamais une quarantaine
existante, libère le nom d'origine, et refuse un reçu signé complet sans `--force`.
Rejouez ensuite l'étape : le même reçu est republié à l'identique.

**Son périmètre, depuis D-077 :** un nom de base finissant par `.json`, et rien d'autre.
Le secret de signature, tout fichier `*.intent`, tout temporaire de publication et tout
autre fichier régulier sont refusés **avec et sans `--force`**. La v6 ne l'imposait pas :
`--name <identifiant>.intent` rendait 0 et faisait passer la porte de
`EVIDENCE_CONFLICT` à `CRITERIA_MET_AWAITING_HUMAN_REVIEW` — un conflit supprimé sans
qu'aucun reçu existe — et `--name signing-key.secret` rendait huit reçus vérifiés
invérifiables. `--force` ne sert qu'à archiver un reçu signé complet.

### Une tentative dont la preuve n'a pas pu être écrite

Avant chaque requête, y compris `discover`, un **intent** local est écrit et synchronisé.
Si la publication du reçu échoue ensuite, la commande sort avec un code non nul, dit
lequel des faits est perdu, et l'intent reste : c'est la trace qu'une requête a pu partir.

```bash
python -m betmaxxing.providers.the_odds_api.activation status --json | \
  python -c "import json,sys; d=json.load(sys.stdin); print(d['unresolved_attempt_intents'])"
```

Tant qu'un intent n'est pas résolu, `qualification_state` reste `EVIDENCE_CONFLICT` :
le corpus est incomplet d'une manière que rien sur ce disque ne permet de chiffrer.
Rejouer l'étape publie le reçu et résout l'intent, sans compter le coût deux fois.

### Rapprocher un intent dont le reçu est déjà publié (D-079)

Il reste une fenêtre que rejouer l'étape ne referme pas : le reçu a été publié
durablement, **puis** le processus est mort avant que son intent soit retiré. Rejouer
republierait le même reçu à l'identique, mais l'intent, lui, resterait — et la porte avec
lui. C'est la seule situation où une commande de récupération est nécessaire :

```bash
python -m betmaxxing.providers.the_odds_api.activation receipts reconcile [--json]
```

Elle publie exactement ces dix champs — des comptes et des catégories, jamais un chemin, un
corps d'intent ni une valeur de secret :

<!-- champs-publiés-reconcile:début -->
```text
boundary_state
boundary_reason
verified_receipts_considered
unverifiable_receipts
resolved_intents
remaining_intents
intent_counts_state
intent_resolution_durability
qualification_state
eligible_for_human_promotion_review
```
<!-- champs-publiés-reconcile:fin -->

Un refus ajoute `status` et `detail`, et rien d'autre. Cette liste n'est pas décorative :
une garde **bidirectionnelle** la compare à la sortie réelle de la commande — tout champ
émis doit figurer ici, et tout champ listé ici doit être émis.

Ce qu'elle fait, exactement : aucun réseau, aucune clé fournisseur lue, le secret de
vérification **chargé sans être créé**, l'audit par `audit_directory`, et un intent retiré
**seulement** s'il existe un reçu durable, vérifié par le HMAC, de portée matérielle
identique et de même lignée de versions. Elle est idempotente : un second passage résout
zéro. Elle laisse intact tout intent que rien ne prouve. Et elle échoue de façon typée, avec
un rapport non vide et un code de sortie non nul, si la frontière, le secret, la lecture, la
suppression ou le `fsync` échoue — un intent n'est jamais retiré sur la base d'une lecture
incomplète.

#### Lire les compteurs sans se tromper (D-080)

Les quatre compteurs sont des **entiers ou `null`**, et `null` s'affiche `NON ÉTABLI` en
rendu humain. Un refus survenu avant l'inventaire ne compte pas zéro intent : il ne compte
rien, et le rapport le dit au lieu d'imprimer un zéro qu'il n'a pas mesuré.

- `intent_counts_state` — `ESTABLISHED` (les deux compteurs pris), `PARTIAL` (l'un des deux
  seulement, la porte reste fermée), `UNESTABLISHED` (aucun) ;
- `intent_resolution_durability` — `NOT_ATTEMPTED`, `DURABLE`, ou `UNCERTAIN`.

`UNCERTAIN` est la seule sortie qui demande une action, et elle prend **deux formes** (D-081) :

- **avec suppression** — l'`unlink` d'un intent a réussi, la suppression **a eu lieu** et
  elle est comptée dans `resolved_intents`, mais le `fsync` qui la rend durable a échoué ;
- **sans aucune suppression** — rien n'a été retiré, et c'est le `fsync` destiné à établir
  durablement l'état courant du répertoire qui a échoué. `resolved_intents` vaut alors `0`.

**C'est `resolved_intents` qui distingue les deux** : non nul, une suppression est en jeu ;
nul, aucune ne l'est et seule l'établissement de l'état a échoué. Le rendu humain le dit
aussi en toutes lettres, avec une phrase différente pour chaque forme.

Dans les deux cas le code de sortie est non nul, la qualification reste
`EVIDENCE_CONFLICT`, la porte reste fermée, et **une nouvelle exécution est nécessaire**.
**Relancez la commande** : une exécution complète synchronise le répertoire même sans rien
retirer, ce qui établit durablement l'état courant et rend le rapport `DURABLE`. Rien
d'autre n'est à faire, et surtout pas toucher au répertoire à la main.

**Ce qui reste interdit.** Supprimer un intent à la main, ou le passer en quarantaine :
`receipts quarantine` refuse les `*.intent` avec et sans `--force`, et aucune commande de
suppression n'existe. Un intent retiré sans reçu correspondant rouvrirait la porte sans
preuve, c'est-à-dire exactement le défaut que l'intent existe pour empêcher.

Ce que le bloc dit, et ce qu'il ne dit pas :

- `qualification_state` vaut au mieux `CRITERIA_MET_AWAITING_HUMAN_REVIEW`. Le
  vocabulaire de l'évaluateur ne contient aucun statut « vérifié » : la promotion
  est une décision humaine, prise ailleurs. Voir `QualificationState` ;
- chaque `criteria_results[]` porte son `observed`, son `required` et son `missing`.
  Lisez `missing` : c'est la réponse à « qu'est-ce qu'il manque encore » ;
- `limit` dit ce que le critère **n'**établit pas. Un `CORE_MAPPING_FOOTBALL` vert
  ne dit rien d'un bookmaker, d'une compétition non observée ou d'une autre date ;
- `evidence_conflicts` non vide est un **échec fermé**, pas une preuve à pondérer ;
- **sept populations exclusives**, dont les noms disent la différence, et une
  équation publiée sous `qualification_population_equation` qui les réconcilie avec
  le nombre de reçus vérifiés : `qualification_usable_receipts`,
  `qualification_current_malformed_receipts`,
  `qualification_current_contradictory_receipts`,
  `qualification_unknown_pair_receipts`,
  `qualification_historical_nonqualifying_receipts`,
  `qualification_duplicate_excluded_receipts` et
  `qualification_unverifiable_receipts` (comptés, jamais lus). Un reçu **courant**
  malformé ou contradictoire n'est plus rangé sous « historique » : ce classement se
  lisait comme « produit sous un protocole antérieur ».
  `qualification_exact_duplicate_copies` est à part — une **dimension croisée**, pas
  une population : la même observation deux fois reste dans la population de son
  contenu. `qualification_admissible_receipts` reste publié sous son nom d'origine,
  égal à `qualification_usable_receipts`, pour que deux rapports restent comparables.
  `qualification_reasons` agrège **pourquoi**, en comptes seulement ;
- un reçu v2 ou v3 reste lisible et peut encore autoriser l'étape suivante ; il ne
  qualifie plus aucun critère, `COST_CONFORMITY` inclus. C'est le prix assumé de
  la correction D-072 ;
- une preuve enregistrée avant `qualification_evidence_not_before`
  (`2026-08-10T14:00:37+00:00`) est de l'histoire. Aucune preuve réelle n'a encore été
  collectée sous protocole 5 : l'état courant est `INSUFFICIENT_EVIDENCE` avec zéro
  reçu utilisable ;
- **toute** preuve de réponse — mapping, couverture, fraîcheur — exige que l'atteinte du
  fournisseur soit établie : `network_attempted is true`, `attempts ≥ 1` **et**
  `may_have_reached_provider is true`. Un statut impliquant une réponse sur un reçu qui
  ne l'établit pas est **contradictoire**, pas seulement non qualifiant (D-075) ;
- l'état de tentative est **à trois valeurs** : pas de tentative, tentative confirmée, ou
  état non établi. Le troisième est visible sous
  `NETWORK_ATTEMPT_STATE_UNESTABLISHED` / `PAID_ATTEMPT_STATE_UNESTABLISHED`, il bloque, et
  il n'est jamais décrit comme tenté, réel ou exécuté ;
- une **tentative confirmée non envoyée** — les deux drapeaux exacts,
  `may_have_reached_provider is false` — est recensée sous `confirmed_attempts_not_sent` :
  elle ne bloque pas et ne qualifie rien, parce qu'une requête certainement non servie n'a
  mesuré aucun tarif ;
- une **copie byte-à-byte** ne change aucun nombre sémantique : crédits, recensement,
  observations, catégories et seuils passent par une collection dédupliquée. Seuls
  `verified_receipts`, `unverifiable_receipts` et
  `qualification_exact_duplicate_copies` comptent des fichiers, et aucun n'est une preuve ;
- `accounted_credits_total` ne somme que des reçus distincts et structurellement lisibles ;
  ce qu'un reçu rejeté revendique est publié à part sous
  `rejected_receipt_credits_not_counted` ;
- un reçu courant **mal typé** — booléen là où un entier est attendu, chaîne là où un
  booléen est attendu — ne prouve rien et fait passer l'état à `EVIDENCE_CONFLICT`,
  avec la raison `malformed_current_schema` et les **noms** des champs fautifs. Une
  signature valide atteste des octets, pas des types ;
- un critère de mapping exige `bookmaker_state = OBSERVED`. Absent, inconnu ou
  `NOT_RETURNED`, il ne qualifie rien : la portée « bookmaker observé » est désormais
  vérifiée et non seulement affichée ;
- `COST_CONFORMITY` expose **cinq** catégories exhaustives et disjointes sur une
  population écrite — tout pas payant distinct du protocole courant dont l'état de
  tentative n'est pas « jamais tenté » — et échoue si une seule d'entre elles est non
  conforme, non établie, ou d'état de tentative non établi, même après six appels
  conformes. `COST_UNVERIFIED` compte comme coût **non établi**, pas comme non conforme :
  un en-tête illisible n'est pas un tarif qui a désaccordé (D-075) ;
- les cinq dimensions plus anciennes lisent la **même** preuve que le bloc strict.
  `connectivity_and_cost_proof` suit la précédence
  `NONCONFORMING > UNESTABLISHED > CONFORMING > NOT_EXERCISED` et dispose désormais
  d'un état `EXERCISED_UNESTABLISHED` : un coût non établi n'est jamais présenté
  comme conforme. `mapping_freshness_proof = OBTAINED_LIVE` exige une observation de
  mapping **saine** — statut positif, bookmaker observé, marché cartographié,
  fraîcheur valide, contrat satisfait — et non un simple `selections_mapped > 0`.
  `paid_activation_state` gagne `PAID_ATTEMPT_INCONCLUSIVE` pour un appel payant
  réellement parti qui n'a établi ni couverture ni mapping, et applique la **même**
  cascade à `core` et à `additional` : `ADDITIONAL_EXECUTED` exige qu'une preuve
  `additional` classifiée et valide établisse effectivement couverture ou mapping, jamais
  la seule présence d'un reçu `additional` (D-075) ;
- `paid_call_cost_census` publie le recensement dont `connectivity_and_cost_proof`
  est dérivé, avec sa population en clair : **toute** tentative payante réelle du
  disque, protocoles antérieurs compris et sans déduplication. `COST_CONFORMITY`
  compte une population plus étroite — protocole courant, dédupliquée — donc les deux
  nombres peuvent légitimement différer ;
- `bookmaker_coverage_observations` ne contient que des reçus dont la phase a
  réellement répondu à la question du bookmaker, structurellement valides et non
  contradictoires. Une observation est une **réponse**, pas la trace d'une tentative,
  et aucune valeur d'un reçu invalide n'y est recopiée ;
- un reçu obtenu à travers un lien symbolique, ou dont la cible se résout hors du
  répertoire de reçus, n'est **pas lu** : il est compté invérifiable, sans que son
  chemin ni son contenu apparaisse dans une sortie ;
- le seuil de fraîcheur du protocole est le littéral **900 s**. Le réglage runtime
  `max_odds_age_seconds` du produit vaut aussi 900 par défaut et reste
  configurable pour le scan : les deux sont censés coïncider, mais reconfigurer le
  second ne déplace **pas** le premier ;
- les tags HMAC locaux apparaissent dans `bookmaker_coverage_observations`, et
  nulle part ailleurs — pas dans `criteria_results`, pas dans les raisons. Ce sont
  des substituts locaux, jamais l'identifiant fournisseur en clair ;
- supprimer le répertoire de reçus remet la preuve à zéro. C'est voulu.

Aucun appel réseau n'est fait par `status`, et aucune clé n'est lue.

## Campagne de qualification — préparée, non lancée

Le plan complet, ses seuils argumentés, son budget et ses arrêts anticipés sont
dans `docs/provider-validation-protocol.md` §8. Résumé opérationnel :

| | |
|---|---|
| Piste A | vérifier le parser avec un bookmaker documenté comme susceptible d'être couvert — choix, source officielle et date à écrire **avant** le premier appel |
| Piste B | couverture `winamax_fr`, indépendante ; le constat du 2026-08-07 reste borné aux deux événements SPL testés |
| Invocations CLI maximales | **12** |
| Requêtes HTTP maximales | **16**, dont **8** payantes — `discover` fait deux requêtes par invocation |
| Crédits contractuels maximaux | **16** — borne tarifaire relue, pas une garantie de facture |
| Autorisations humaines | **12**, une par invocation |
| Arrêt immédiat | `COVERAGE_MISSING`, `COST_MISMATCH`, mapping rejeté |
| Substitution | **aucune**, ni de bookmaker, ni d'événement, ni de compétition |
| Manifeste v8 | `pinnacle` · `soccer_epl`, `soccer_spain_la_liga`, `tennis_atp_us_open`, `tennis_wta_us_open` |
| Plafonds opposables | comptés depuis les reçus vérifiés, refusés **avant** réseau |
| Configuration du parser | `BETMAXXING_BOOKMAKERS` doit contenir `pinnacle` ; sinon refusé avant clé, intent et socket |

Aucune de ces commandes n'a été exécutée par les tranches 03C-1 ni 03C-1 ter :
elles n'écrivent que le protocole, l'évaluateur et leurs tests.
