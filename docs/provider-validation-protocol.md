# Protocole de qualification du fournisseur — `PROVIDER_VALIDATION_PROTOCOL_VERSION = 8`

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

### 0.3 Puis la v4 a été auditée à son tour

Quatrième réaudit indépendant en lecture seule. Il a trouvé **un P1** et cinq P2, et le
P1 est le plus grave de la série : la porte de revue humaine était atteignable alors que
**toutes** les observations de mapping du corpus portaient
`may_have_reached_provider = false`. La v5 les ferme.

| Revendication v4 | Ce que le code faisait | Ce que fait la v5 |
| --- | --- | --- |
| « toute preuve positive est fermée » | `may_have_reached_provider` n'était lu **que** par le recensement du coût. Un reçu `CORE_LIVE_VERIFIED` affirmant que la requête n'avait jamais atteint le fournisseur restait bien formé, admissible, « sain », et produisait `OBTAINED_LIVE` — la valeur la plus explicite était la seule à passer, un drapeau absent ou mal typé étant, lui, correctement refusé. Huit preuves de ce type plus six coûts honnêtes franchissaient la porte | **l'atteinte du fournisseur est une précondition** : `provider_was_reached` exige les deux booléens exacts, et il garde `admissible_for`, `mapping_observation_is_sound`, les observations de couverture et les dimensions historiques. Un statut impliquant une réponse avec une atteinte non établie est **contradictoire** (§2.2) |
| « les cinq dimensions lisent la même preuve » | la seule présence d'un reçu `additional` forçait `ADDITIONAL_EXECUTED`, y compris pour `AUTH_FAILED`, `COST_MISMATCH` ou une couverture jamais classifiée — alors que les mêmes issues en `core` rapportaient correctement `PAID_ATTEMPT_INCONCLUSIVE` | cascade **symétrique**, preuves d'abord et nom de commande en dernier (§2.3). `ADDITIONAL_EXECUTED` exige qu'une preuve `additional` classifiée et valide établisse effectivement couverture ou mapping |
| « une copie exacte est une dimension croisée » | vrai pour les seuils de mapping et les appels conformes, faux partout ailleurs : sept copies d'un `COST_MISMATCH` rapportaient **63 crédits** dépensés, sept appels non conformes contre un seuil qui doit valoir zéro, et sept observations de couverture d'un seul événement | **canon sémantique** : toute lecture sémantique passe par une collection dédupliquée par identifiant et empreinte scellée. Les comptes de fichiers restent disponibles sous des noms qui disent qu'ils sont physiques (§3.1) |
| « un statut positif incomplet reste refusé » | `set(market_states) == set(markets_requested)` est vrai à vide, donc un `CORE_LIVE_VERIFIED` sans marché demandé, sans carte, sans fraîcheur et à zéro sélection était bien formé, utilisable, et comptait comme appel payant conforme | **invariants positifs par statut** (§2.0), dérivés du producteur : une classification de rien n'est pas une classification |
| « réel », « tenté », « exécuté » | `network_attempted is not False` traitait un drapeau **absent** comme une tentative : `execution_state` rapportait `CORE_ATTEMPTED` et le recensement s'appelait « tentatives payantes réelles » | lecture **à trois états** (§2.4) : pas de tentative, tentative confirmée, état de tentative non établi. Le troisième est visible, bloquant, et jamais appelé tenté ni exécuté |
| écriture exclusive et idempotence | `O_CREAT | O_EXCL` crée le nom final **avant** d'écrire les octets : une interruption laissait un fichier vide, et le même reçu était ensuite refusé pour toujours sous le message « contenu signé différent », qui était faux | **publication atomique** (§9) : octets complets dans un temporaire, `fsync`, puis publication sous le nom final sans écrasement. Un fichier incomplet est nommé comme tel et récupérable |

Deux P3 de frontière sont fermés avec : l'ouverture porte désormais `O_NOFOLLOW`
relativement à un descripteur de répertoire, et les octets sont lus depuis le
descripteur ouvert — un `resolve()` antérieur ne prouvait rien contre un remplacement, et
un probe déterministe lisait une cible extérieure dans cette fenêtre. `receipt_secret`
utilise la même primitive. Trois P3 documentaires sont corrigés dans le corps de PR.

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

### 0.4 Puis la v5 a été auditée à son tour

Le cinquième réaudit indépendant en lecture seule a reproduit, sur `e43851e`, **un P1,
cinq P2 et douze P3**. Tous portaient sur la même frontière : ce qui est sur le disque
et ce que le programme accepte de croire.

**P1 — le secret n'était jamais validé.** `receipt_secret()` créait
`signing-key.secret` puis faisait confiance à ce qu'il relisait. Un fichier vide, un
retour à la ligne, un caractère, le mot `secret`, soixante-quatre caractères non
hexadécimaux et cent mille caractères étaient tous acceptés, tous utilisés pour signer
et tous vérifiés ; un corpus synthétique signé avec une telle clé atteignait
`CRITERIA_MET_AWAITING_HUMAN_REVIEW`. Une route ne demandait aucun adversaire : une
première exécution interrompue entre la création exclusive et l'écriture laissait un
fichier de zéro octet que chaque exécution suivante lisait comme une clé vide.

**P2 — cinq constats.** `evaluate` se disait pur alors que son graphe d'appels
atteignait le HMAC, l'environnement et un fichier qu'il créait. Le *répertoire* de
reçus était ouvert par chemin sans `O_NOFOLLOW`, et `link`, `unlink` et le `fsync` du
répertoire repassaient par un chemin : un répertoire-lien, un parent substitué et un
répertoire permuté entre le listing et l'ouverture faisaient lire, vérifier et
rapporter un fichier extérieur. Les cinq sites de `write_receipt` étaient hors de tout
gestionnaire : `ENOSPC` sur `discover` sortait sur un `OSError` nu, **sans aucune
sortie**, sans reçu, et au site `additional` la même forme perd la seule preuve d'un
appel à cinq crédits. `run_discovery` produit `COST_UNVERIFIED` et `COST_MISMATCH` par
`_settle_cost`, deux couples absents de la table — un reçu honnête écrit par le harnais
était classé « couple inconnu » et faisait basculer tout un corpus en
`EVIDENCE_CONFLICT` — tandis que `discover/SCHEMA_MISMATCH` y était déclaré sans
producteur. Enfin `execution_state` arrondissait toute tentative confirmée qui n'était
pas exactement `core` ou `additional` en `DISCOVERY_ATTEMPTED`, y compris `plan`, une
commande absente, `sync`, `7`, `Core` et `" core "`.

**Ce que la v6 avait changé**, point par point, avec la décision D-076 :

| Défaut v5 | Correction v6 |
| --- | --- |
| secret non validé, réparé silencieusement, créé non atomiquement | format strict — 64 caractères hexadécimaux minuscules, ni `strip()` ni casse tolérés ; `load_receipt_secret` lit sans créer, `ensure_receipt_secret` crée atomiquement ; un secret invalide échoue **fermé** et n'est jamais réécrit, car le réécrire invaliderait tous les reçus déjà signés |
| `evaluate` impur par son graphe d'appels | la vérification remonte à `audit_receipts`, qui est le seul endroit où une provenance est frappée ; `evaluate` n'accepte que des `VerifiedReceipt` et refuse une liste de mappings brute |
| frontière portant sur le nom, pas sur le répertoire | un seul descripteur de répertoire, ouvert composant par composant avec `O_NOFOLLOW`, conservé pour tout le cycle : listing, lecture, publication, link, unlink, quarantaine et `fsync` passent par lui |
| erreur de persistance en `OSError` nu, preuve perdue | un **intent** local est écrit et `fsync`-é *avant* la requête ; toute erreur de publication devient une erreur métier typée, non vide, à code de sortie non nul ; l'intent non résolu bloque la porte |
| commande lue par coercition | `CommandState` à cinq valeurs, domaine fermé, sans casse ni espace ; seul `discover` exact peut rapporter `DISCOVERY_ATTEMPTED` |
| un seul seau « non établi » suraffirmant l'atteinte | six populations de coût, dont `provider_reached_cost_unestablished` et `provider_reach_unestablished` séparés ; quatre bloquent |
| reçu rejeté alimentant des compteurs sémantiques | un reçu malformé, contradictoire, de couple inconnu ou d'identifiant divergent n'alimente que les raisons, les populations, `rejected_receipt_credits_not_counted` et un recensement **médico-légal** distinct |
| catalogue vérifié dans un seul sens | `PERSISTED_COUPLES` est comparé à ce que les vrais chemins de commande écrivent, dans les deux sens |
| quarantaine non bornée, remplaçante, inaccessible | elle opère sur un **nom de base** du répertoire déjà ouvert, réessaie au lieu de remplacer, et une commande `receipts quarantine --name` l'expose |

### 0.5 Puis la v6 a été auditée à son tour

Le sixième réaudit indépendant, en lecture seule, sur `9adfb8f`, a reproduit **quatre
P1, huit P2 et onze P3**. Les quatre P1 disent la même chose sous quatre angles : la v6
avait *nommé* la provenance sans l'imposer.

`VerifiedReceipt` était un constructeur public qui ne vérifiait rien. Huit reçus dont la
clé `signature` avait été supprimée, emballés à la main, atteignaient
`CRITERIA_MET_AWAITING_HUMAN_REVIEW` — par un lot, par une liste nue et par un tuple ;
un corpus signé par une clé étrangère faisait de même. Le type n'était gelé qu'au premier
niveau, si bien qu'une seule écriture par l'API documentée,
`reçu["freshness"][marché] = 300`, faisait passer un corpus de `INSUFFICIENT_EVIDENCE` à
la porte de revue humaine après vérification, pendant que la signature du reçu ne
vérifiait plus. `reconcile_intents` comparait des identifiants contre un ensemble
construit **sans vérifier aucune signature** : un fichier de deux clés effaçait un intent
et rouvrait la porte, et treize formes forgées résolvaient toutes. Et
`receipts quarantine --name` n'avait aucun périmètre : `--name <id>.intent` supprimait un
conflit sans qu'aucun reçu existe, `--name signing-key.secret` rendait huit reçus
vérifiés invérifiables, l'un et l'autre sans `--force`.

Les P2 tenaient au même endroit. `audit_receipts` rendait « 0 reçu, 0 invérifiable » pour
un répertoire atteint par un lien symbolique — indiscernable d'une installation propre —
pendant que `load_parent`, entièrement par chemin avec un `resolve()` qui suit
précisément les liens que le store refuse, lisait ce même répertoire et autorisait un
appel payant. Un seul fichier dont la `signature` valait `"é" * 64` faisait mourir
`status` et `status --json` sur un `TypeError` nu, **zéro octet** sur la sortie, tant
qu'il restait sur le disque. Un secret d'UTF-8 invalide levait un `UnicodeDecodeError`
nu. `EACCES`, `EROFS` et `ENOSPC` à la création du temporaire du reçu s'échappaient en
`DirectoryUnsafe` sans rien afficher — la forme même que le P2-D3 du cinquième audit
prétendait avoir fermée. Un intent divergent sous un identifiant déjà pris était accepté
en silence, une cible vide comptait comme publication réussie, et le contenu hostile d'un
intent était réfléchi verbatim dans `unresolved_attempt_intent_details`.

## 0 quater. Ce que la v8 ferme, et ce qu'elle abandonne

La v7 a été exécutée une fois. Une seule commande réseau est partie — une découverte
sur `soccer_france_ligue_one` chez `winamax_fr` — et elle est revenue
`COVERAGE_MISSING`, `events_admissible = 0`, deux requêtes, zéro crédit. Le reçu de
cet appel est conservé, signé, **historique non qualifiant**. Il ne doit être ni
supprimé, ni mis en quarantaine, ni réutilisé.

La campagne v7 est **abandonnée**, et pas parce qu'elle a échoué : parce qu'une de ses
quatre invocations `discover` a été consommée sans événement, et que les trois places
restantes ne permettent plus d'établir les deux compétitions exigées dans chaque
famille. Aucun réessai, aucun élargissement de fenêtre, aucun changement opportuniste
de bookmaker n'ouvre de porte de sortie.

L'audit statique 03C-2D bis a mesuré pourquoi la v8 existe. Les bornes de la campagne
v7 — quatre `discover`, six `core`, deux `additional`, seize crédits — vivaient dans
une table de prose et dans `campaign_budget()`, une dérivation pure de constantes qui
**ne lisait aucun reçu**. Deux corpus ont été comparés champ par champ : neuf
découvertes, soit plus du double des quatre allouées, et un corpus conforme de neuf
reçus. Ils publiaient des valeurs **identiques** dans chaque champ susceptible de les
distinguer. Un opérateur pouvait relancer `discover` jusqu'à en trouver une non vide et
présenter le résultat comme la campagne prévue ; `activation status` ne l'aurait pas
contredit.

| Défaut v7 | Correction v8 |
| --- | --- |
| aucune compétition préenregistrée : les deux compétitions par famille étaient exigées par `min_competitions = 2` sans que lesquelles soit écrit nulle part | manifeste fermé : `pinnacle`, et exactement `soccer_epl`, `soccer_spain_la_liga`, `tennis_atp_us_open`, `tennis_wta_us_open`, choisis et datés **avant** tout appel |
| bookmaker de la piste A jamais choisi — « ce document ne nomme pas encore ce bookmaker » — et la seule découverte réelle partie sous le bookmaker de la piste B | `pinnacle`, nommé ici et dans `docs/source-matrix.md` avec ses sources publiques et leur date de consultation |
| plafonds documentaires : rien ne comptait les invocations, rien n'en publiait le compte | `campaign_ledger` compte les invocations à partir des reçus vérifiés du protocole courant, et `campaign_preflight` refuse **avant réseau** |
| un dépassement était indiscernable d'un corpus conforme | un dépassement est un `EVIDENCE_CONFLICT`, et `campaign_execution_state` le nomme |
| un compte impossible à prendre pouvait se lire comme un compte nul | `campaign_counts_state = UNESTABLISHED` et `campaign_invocation_counts = null` ; aucun chiffre n'est publié avant d'avoir été pris |

**Ce que la v7 change**, point par point, avec la décision D-077 :

| Défaut v6 | Correction v7 |
| --- | --- |
| `VerifiedReceipt(payload)` public et sans contrôle ; `trust(payload, secret=…)` prenant la clé de l'appelant | les trois types de provenance prennent un jeton privé en premier argument positionnel ; `trust` et `require_verified` sont supprimés ; le seul chemin est `audit_directory`, qui reçoit un répertoire déjà ouvert et fait lui-même lecture, schéma et HMAC contre le secret de l'installation |
| gel superficiel : imbrications partagées, `__getitem__` rendant l'objet vivant | gel **récursif** par `FrozenMapping`, qui implémente `Mapping` **sans hériter d'aucun conteneur mutable**, et par des `tuple` ; les quinze appels directs aux mutateurs de `dict` et de `list` lèvent, et l'audit scelle une empreinte par reçu que `require_audited` recalcule |
| `load_parent` décidant par `resolve`, `is_symlink`, `is_file` et `read_text` | l'argument est réduit **textuellement** à un nom de base du répertoire autorisé, puis lu par le même `SecureDirectory` que l'audit |
| frontière indisponible rapportée comme frontière vide | `BoundaryState` à trois valeurs — `ABSENT`, `AVAILABLE`, `UNAVAILABLE` — publiées en JSON et en humain ; `UNAVAILABLE` est un conflit de preuve et bloque |
| rapprochement d'intent sur un JSON non vérifié, sans portée | candidats issus de `audit_receipts`, même identifiant, même commande, même sport, même bookmaker, même tag, coût dans le plafond, couple persistable, aucune faute, aucune contradiction, même lignée de versions |
| publication d'intent idempotente par « le nom existe » | idempotence sur **octets identiques** ; portée divergente, cible vide, tronquée, lien ou répertoire : refus typé avant réseau |
| contenu d'intent hostile réfléchi | contrat positif fermé à neuf champs ; un intent hors contrat est réduit à son nom local et à `UNREADABLE_OR_INVALID`, et bloque toujours |
| quarantaine sans périmètre | uniquement un nom de base `*.json` ; secret, `*.intent`, temporaires et tout autre fichier refusés avec **et** sans `--force` |
| `hmac.compare_digest` sur une signature non ASCII ; UTF-8 invalide en exception nue ; `exists` traitant toute erreur comme « absent » ; `EACCES` au temporaire s'échappant | forme de signature vérifiée avant comparaison ; `ContentUndecodable` et `SecretInvalid` typés ; seul `ENOENT` vaut « absent » ; échec de temporaire = erreur de durabilité ; les cinq sites capturent le graphe réel |
| variable de secret vide lue comme absente ; permissions non vérifiées | présente mais vide = invalide ; sur POSIX, non régulier, autre UID ou droit groupe/autres = refus, attendu `0600`, limite de plateforme écrite |
| `unverifiable` et `unresolved_intents` non validés | entiers Python exacts, non booléens, positifs ou nuls ; `None` et `False` ne valent jamais zéro |

**Modèle de menace, énoncé exactement.** La revendication porte sur l'**API Python
publique du dépôt** : aucun point d'entrée exporté ne produit une provenance admise sans
vérification de signature contre le secret de l'installation, et aucun reçu admis ne se
modifie par cette API. Du code déjà en cours d'exécution dans le processus peut atteindre
un nom privé, appeler `dict.__setitem__` sur un conteneur gelé ou réécrire du bytecode ;
aucune conception ici ne l'empêche, et rien dans ce document ne prétend le contraire.

**Une nuance assumée sur le rapprochement.** La « même lignée » exigée d'un reçu qui
résout un intent porte sur le schéma, le protocole et la preuve adaptateur, **non** sur
l'instant d'effet. Exiger aussi l'instant ferait qu'un changement de protocole orpheline
les intents en vol : un intent qu'aucun reçu ne peut plus résoudre bloque la porte pour
toujours, ce qui transformerait une correction en déni durable. Savoir si l'issue
*qualifie* reste la question de l'évaluateur.

## 1. Neuf faits, jamais condensés

| # | Fait | Établi par |
| --- | --- | --- |
| 1 | l'adaptateur est **implémenté** | la revue de code et la suite hors ligne |
| 2 | **connectivité et authentification** | un appel réel qui revient sans `AUTH_FAILED` |
| 3 | **conformité du coût** | un coût **établi** au sens du §2.1 : `observed_credits` lisible, dans la borne, et égal à `accounted_credits`. Une comptabilisation prudente après un timeout n'établit rien et **fait échouer** le critère |
| 4 | **présence ponctuelle d'un bookmaker** | `bookmaker_state = OBSERVED` sur *cet* événement, sur un reçu dont l'atteinte du fournisseur est établie |
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
**v4** portant `qualification_protocol_version = 5` et
`provider_adapter_evidence_version = 1`, `recorded_at`
**≥ `2026-08-25T00:00:00+00:00`**, **atteinte du fournisseur établie** au sens du §2.4,
et **contrat structurel du §2.0 satisfait**.

Le 900 est un littéral du protocole. Le produit a par ailleurs un réglage runtime
`max_odds_age_seconds` qui vaut aussi 900 par défaut — au-delà, le scan appelle
déjà un snapshot périmé — et les deux nombres sont **censés** coïncider. Mais ce
sont deux objets distincts : le réglage runtime reste configurable pour le scan,
le seuil du protocole ne l'est pas. S'ils divergent, le protocole garde son 900 et
aucun reçu ne devient plus admissible qu'avant.

| `criterion_id` | Portée | Preuve admissible | Événements | Compétitions | Jours UTC | Schéma |
| --- | --- | --- | --- | --- | --- | --- |
| `CORE_MAPPING_FOOTBALL` | `soccer_*`, `core`, `h2h`, `GROUPED_ODDS` | statut `CORE_LIVE_VERIFIED`, `selections_mapped > 0`, aucun rejet de mapping | **3** | **2** | **2** | **v4/5/1 seul** |
| `CORE_MAPPING_TENNIS` | `tennis_*`, `core`, `h2h`, `GROUPED_ODDS` | idem | **3** | **2** | **2** | **v4/5/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DRAW_NO_BET` | `soccer_*`, `additional`, `draw_no_bet` | statut `ADDITIONAL_LIVE_VERIFIED` ou `ADDITIONAL_PARTIAL_COVERAGE`, `market_states[marché] = OBSERVED_MAPPED` | **2** | **2** | **1** | **v4/5/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DOUBLE_CHANCE` | idem, `double_chance` | idem | **2** | **2** | **1** | **v4/5/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_H2H_3_WAY_H1` | idem, `h2h_3_way_h1` | idem | **2** | **2** | **1** | **v4/5/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_TOTALS_H1` | idem, `totals_h1` | idem | **2** | **2** | **1** | **v4/5/1 seul** |
| `ADDITIONAL_MAPPING_FOOTBALL_DOUBLE_CHANCE_H1` | idem, `double_chance_h1` | idem | **2** | **2** | **1** | **v4/5/1 seul** |
| `COST_CONFORMITY` | tous sports, appels payants | coût **établi** au sens du §2.1, 0 appel non conforme | **6** appels au coût établi | — | — | **v4/5/1 seul** |

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

**Invariants positifs par statut.** La forme de la phase ne suffit pas : `set(states) ==
set(requested)` est vrai à vide, si bien qu'un `CORE_LIVE_VERIFIED` sans marché demandé,
sans carte, sans fraîcheur et à zéro sélection était bien formé, utilisable, et comptait
comme appel payant conforme. Une classification de rien n'est pas une classification.
Dérivés du producteur :

| Statut classifié | Ce qu'il doit positivement porter |
| --- | --- |
| `CORE_LIVE_VERIFIED` | marchés demandés **non vides**, `bookmaker_state = OBSERVED`, au moins un `OBSERVED_MAPPED`, au moins une sélection, un âge de fraîcheur pour chaque marché cartographié |
| `ADDITIONAL_LIVE_VERIFIED` | idem, et **tous** les marchés demandés `OBSERVED_MAPPED` — c'est la condition exacte à laquelle `_additional_status` retourne ce statut |
| `ADDITIONAL_PARTIAL_COVERAGE` | idem, et au moins un marché cartographié **et** au moins un qui ne l'est pas. « Partiel » a deux bords ; les deux extrémités sont un autre constat |
| `COVERAGE_MISSING` classifié | aucun marché cartographié, zéro sélection, et une forme compatible avec une absence **observée** : soit tous les marchés `NOT_EVALUATED_BOOKMAKER_ABSENT` (bookmaker jamais coté), soit tous `NOT_RETURNED` (bookmaker coté, n'offrant rien) |
| `SCHEMA_MISMATCH` classifié | aucun marché cartographié, zéro sélection, et au moins un `OBSERVED_REJECTED` — une réponse rejetée, qui ne se fait pas passer pour un mapping |

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

### 2.4 État de tentative et atteinte du fournisseur

Deux lectures distinctes, et aucune des deux n'est un booléen simple.

**L'état de tentative** est **à trois valeurs**, dérivé de `network_attempted` *et* de
`attempts` ensemble :

| État | Conditions | Sens |
| --- | --- | --- |
| `NOT_ATTEMPTED` | `network_attempted is false` **et** `attempts == 0` | l'étape s'est arrêtée avant toute socket. Ce n'est pas un défaut, et ce n'est pas un appel payant |
| `CONFIRMED_ATTEMPT` | `network_attempted is true` **et** `attempts ≥ 1` | une requête a réellement été émise |
| `ATTEMPT_STATE_UNESTABLISHED` | drapeau absent, mal typé, ou incohérent avec `attempts` | le reçu ne peut pas le dire. **Visible et bloquant**, jamais appelé tenté ni exécuté |

La v4 écrivait cette lecture comme `network_attempted is not False`, si bien qu'un drapeau
**absent** devenait une tentative : `execution_state` rapportait `CORE_ATTEMPTED` et la
population s'appelait « tentatives payantes réelles ». Une mesure manquante n'est ni une
mesure de zéro ni une mesure de un. Aucun état non établi ne produit désormais
`CORE_ATTEMPTED`, `ADDITIONAL_ATTEMPTED`, `*_EXECUTED` ni une phrase contenant
« tentative réelle » — il a ses propres valeurs,
`ExecutionState.NETWORK_ATTEMPT_STATE_UNESTABLISHED` et
`PaidActivationState.PAID_ATTEMPT_STATE_UNESTABLISHED`.

**L'atteinte du fournisseur** est établie quand, cumulativement, l'état de tentative est
`CONFIRMED_ATTEMPT` **et** `may_have_reached_provider is true`.

C'est une **précondition de toute preuve de réponse** : mapping, couverture, fraîcheur,
sélection cartographiée. Un payload qui n'est jamais arrivé n'a pas pu être analysé. La
v4 ne lisait ce drapeau que pour le recensement du coût, si bien qu'un reçu
`CORE_LIVE_VERIFIED` portant `may_have_reached_provider = false` restait admissible et
produisait `OBTAINED_LIVE` — et huit preuves de ce type, accompagnées de six coûts
honnêtes, franchissaient la porte de revue humaine.

Les statuts qui **impliquent** une réponse du fournisseur sont
`DISCOVERY_VERIFIED`, `CORE_LIVE_VERIFIED`, `ADDITIONAL_LIVE_VERIFIED`,
`ADDITIONAL_PARTIAL_COVERAGE`, `COVERAGE_MISSING`, `SCHEMA_MISMATCH`, `COST_MISMATCH`,
`COST_UNVERIFIED` et `AUTH_FAILED` : chacun est levé depuis un chemin qui a déjà lu une
réponse. L'un d'eux avec une atteinte non établie est **contradictoire** (§2.2), pas
seulement non qualifiant.

`PROVIDER_UNAVAILABLE` n'en fait pas partie : un timeout de lecture et un 5xx sont deux
issues différentes, et le harnais ne prétend pas savoir laquelle.

### 2.5 État de commande : un domaine fermé

`CommandState` lit `command` aussi strictement qu'`AttemptState` lit
`network_attempted` : `PLAN`, `DISCOVER`, `CORE`, `ADDITIONAL`, ou
`COMMAND_STATE_UNESTABLISHED`. Aucune casse, aucun espace, aucune coercition —
`Core`, `" core "`, `sync`, `7`, `["core"]`, `None` et un champ absent sont tous non
établis, et c'est une **faute structurelle**.

Trois conséquences :

* seul `discover` exact, avec une tentative confirmée cohérente, peut rapporter
  `DISCOVERY_ATTEMPTED`. La v5 y arrondissait tout le reste ;
* seuls `core` et `additional` entrent dans le dénominateur payant. `Core` et
  `" core "` échappaient à `PAID_COMMANDS` **et** au contrat structurel, donc un pas
  payant pouvait être rapporté comme non payant et disparaître du recensement ;
* un reçu `plan` portant une tentative est rejeté : la phase `PLANNED` exige déjà
  `network_attempted` faux et `attempts` nul, et `contradictions` le nomme aussi, pour
  que l'invariant survive à un changement de la table.

### 2.1 Ce qu'est un coût conforme

Un pas payant conforme est un pas dont le coût est **établi** et tenu : l'estimation
respecte le plafond contractuel, l'observation existe, et les deux concordent avec ce
que le reçu comptabilise. Tout le reste est nommé pour ce qui manque.

**Six populations, exhaustives et disjointes** sur tout pas payant distinct que le
contrat accepte de lire, dont l'état de tentative n'est pas « jamais tentée » :

```text
provider_reached_conforming_cost      >= 6   (contribue au seuil)
provider_reached_nonconforming_cost   == 0   (COST_MISMATCH — bloque)
provider_reached_cost_unestablished   == 0   (atteinte établie, coût illisible ou
                                              hors borne — bloque)
provider_reach_unestablished          == 0   (l'atteinte elle-même n'est pas établie
                                              — bloque)
paid_attempt_state_unestablished      == 0   (drapeau ou compteur de tentative non
                                              établi — bloque)
confirmed_attempts_not_sent            —     (recensé à part : ni aide, ni blocage)
```

La v5 n'en avait que cinq, et le nom du seau « non établi » affirmait que le
fournisseur avait été atteint alors que deux de ses trois alimentations étaient
exactement les reçus où l'atteinte n'était pas établie. Une population ne peut pas
affirmer dans son nom un fait que ses membres démentent.

**Conséquence assumée, énoncée plutôt que cachée.** `may_have_reached_provider` est un
booléen et `attempts` un compteur : un reçu qui laisse l'un des deux non établi est hors
du contrat structurel, donc rejeté, donc — par la règle ci-dessous — hors de tout
compteur sémantique. Les deux populations `provider_reach_unestablished` et
`paid_attempt_state_unestablished` restent donc à zéro dans le recensement sémantique et
sont comptées dans le recensement **médico-légal** `rejected_paid_cost_census`, qui est
la place d'un reçu que le contrat refuse de lire. Le contrat structurel n'est pas
affaibli pour rendre un seau atteignable.

**Un reçu rejeté n'alimente aucun compteur sémantique.** Un reçu courant malformé,
contradictoire, de couple inconnu ou dont l'identifiant désigne deux contenus signés
différents alimente : les raisons, les populations de réconciliation,
`rejected_receipt_credits_not_counted`, `rejected_paid_receipts` et
`rejected_paid_cost_census`. Il n'alimente pas : `execution_state`,
`paid_activation_state`, `connectivity_and_cost_proof`, `paid_call_cost_census`, les
observations de couverture, ni `accounted_credits_total`. Il bloque déjà la porte par
`EVIDENCE_CONFLICT`, et il reste visible dans les compteurs physiques.

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

**La cascade des états payants, preuves d'abord.** La v4 testait
`any(command == "additional")` avant tout le reste, si bien que la seule présence d'un
reçu `additional` rapportait `ADDITIONAL_EXECUTED` pour un `AUTH_FAILED`. L'ordre est
désormais :

1. aucune tentative confirmée et aucun état non établi → `PREPARED_NOT_EXECUTED` ;
2. aucune tentative confirmée mais un état non établi → `PAID_ATTEMPT_STATE_UNESTABLISHED` ;
3. tentative confirmée sans couverture ni mapping établis → `PAID_ATTEMPT_INCONCLUSIVE` ;
4. une preuve `additional` classifiée, valide et établissant couverture ou mapping →
   `ADDITIONAL_EXECUTED` ;
5. une observation de mapping saine en `core` → `CORE_EXECUTED_COVERAGE_OBSERVED` ;
6. une réponse `core` sur la question du bookmaker, sans mapping →
   `CORE_EXECUTED_NO_COVERAGE`.

`core` et `additional` appliquent la **même** règle d'inconclusivité ; seule l'étiquette
finale diffère, et elle diffère sur une preuve, jamais sur un nom de commande.

**Canon sémantique.** Après vérification des signatures et exclusion des identifiants
divergents, toute lecture sémantique passe par une collection **dédupliquée** par
identifiant et empreinte scellée : les huit critères, les cinq catégories de coût, les
crédits comptabilisés, le recensement, les deux libellés de coût et de progression, les
observations de couverture, les populations, les raisons et l'état global. La v4 ne
dédupliquait que les seuils de mapping et les appels conformes, si bien que sept copies
d'un seul `COST_MISMATCH` rapportaient soixante-trois crédits et sept appels non conformes
contre un seuil qui doit valoir zéro.

Les nombres de **fichiers** restent disponibles, et uniquement sous des noms qui disent
qu'ils sont physiques : `verified_receipts`, `unverifiable_receipts` et
`qualification_exact_duplicate_copies`. Aucun d'eux n'est une preuve métier.

**Crédits.** `accounted_credits_total` additionne des entiers réels non négatifs, de reçus
**distincts** et **structurellement lisibles**. Ce qu'un reçu rejeté par le contrat
revendique est publié à part, sous `rejected_receipt_credits_not_counted` : visible, jamais
sommé dans le premier.

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
   `qualification_protocol_version = 5` et `provider_adapter_evidence_version = 1` ;
2. **postérieure ou égale** à `2026-08-25T00:00:00+00:00`, `recorded_at` étant un
   ISO 8601 avec timezone, normalisé en UTC pour la comparaison ;
3. rattachée à une **tentative confirmée dont le fournisseur a réellement été
   atteint** : `network_attempted is true`, `attempts ≥ 1` **et**
   `may_have_reached_provider is true` (§2.4). Une preuve de réponse exige une
   réponse ;
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

Trois choses distinctes entrent dans cette équation, et les confondre est la façon dont
elle cesse de s'équilibrer :

1. les **populations sémantiques exclusives** — tout reçu vérifié *distinct* appartient à
   exactement une d'entre elles ;
2. les **fichiers invérifiables**, comptés et jamais lus, donc jamais rangés dans une
   population sémantique ;
3. l'**ajustement des copies physiques exactes** : les populations sont calculées sur un
   canon dédupliqué, alors que le membre de gauche compte des **fichiers**. Ce terme est
   l'écart entre les deux, **pas** une population supplémentaire.

L'équation est publiée par `status` sous `qualification_population_equation`, avec ses
**huit** termes, et testée sur un corpus où l'ajustement et le couple inconnu sont tous
deux non nuls :

```text
reçus vérifiés + fichiers invérifiables
  = qualification_usable_receipts
  + qualification_current_malformed_receipts
  + qualification_current_contradictory_receipts
  + qualification_unknown_pair_receipts
  + qualification_historical_nonqualifying_receipts
  + qualification_duplicate_excluded_receipts
  + qualification_unverifiable_receipts
  + qualification_exact_duplicate_copies
```

Le huitième terme a manqué à ce bloc jusqu'au réaudit sexdecies, alors que le calcul
l'utilisait depuis toujours : huit reçus honnêtes plus deux copies octet-pour-octet
donnaient `10 = 8` sous la forme documentée. Le code, lui, s'équilibrait ; c'était la
documentation normative qui était fausse, et un opérateur qui réconciliait ses comptes à
la main ne pouvait pas distinguer un reçu silencieusement perdu d'une erreur de rédaction.

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

### 3.2 Intents de tentative non résolus

Avant chaque requête — `discover` comprise — un **intent** local est écrit
atomiquement et `fsync`-é : identifiant, commande, portée, plafond contractuel, état
`PREPARED`. Aucune clé, aucune URL, aucun événement en clair, aucune cote, aucun
payload. Il n'est supprimé qu'après la publication durable du reçu final portant le
même identifiant.

Sa survie est la seule chose qui reste quand la publication échoue, et c'est le trou
que la v5 laissait ouvert : cinq crédits engagés, `write_receipt` en échec, et aucune
trace qu'une requête avait été tentée. Donc :

* `unresolved_attempt_intents` est publié, en JSON **et** en lecture humaine ;
* tout intent non résolu est un **conflit de preuve** et bloque la porte ;

**Contrat de l'intent, fermé dans les deux sens (v7).** Neuf champs exactement —
`intent_version`, `attempt_id`, `command`, `sport_key`, `bookmaker`, `event_tag`,
`max_credits`, `state`, `prepared_at` — types et bornes vérifiés, commande dans un
domaine fermé, instant analysable avec fuseau, identifiant du corps égal au nom du
fichier. Un identifiant est de 8 à 64 caractères hexadécimaux minuscules par
`fullmatch` : la v6 utilisait `re.match` avec `$`, donc `"aaaaaaaa\n"` était un nom
légal — le défaut même que le §9 documente avoir corrigé pour le format du secret.

Un champ absent, un champ en trop, une valeur mal typée ou hors borne rend l'intent
**invalide**. Un intent invalide ou illisible **bloque toujours**, et il est rapporté
sous son seul nom local avec l'état `UNREADABLE_OR_INVALID` : aucune valeur de son
contenu n'entre dans le JSON ni dans le terminal. La v6 publiait le fichier verbatim.

**Publication idempotente sur octets identiques seulement (v7).** Le même `attempt_id`
avec une commande, un sport, un bookmaker, un tag ou un plafond différents est un refus
typé **avant le réseau** ; une cible vide, tronquée, lien ou répertoire n'est jamais une
publication réussie. La v6 se fiait à « le nom existe », ce qui ne dit rien du contenu :
la portée du premier restait sur le disque sans qu'aucune requête soit bloquée, et un
fichier de zéro octet comptait comme la trace censée survivre à un arrêt brutal.

**Rapprochement (v7).** Un intent n'est résolu que par un reçu **durable**, **vérifié par
l'audit** contre le secret local, de **schéma accepté**, portant le même identifiant, la
même commande, le même sport, le même bookmaker, le même tag éventuel, un coût compatible
avec son plafond, un couple réellement **persistable** du catalogue, aucune faute
structurelle, aucune contradiction, et la **même lignée** de versions. La v6 comparait des
identifiants contre un ensemble construit sans vérifier aucune signature : un fichier de
deux clés effaçait un intent et rouvrait la porte, et treize formes forgées le faisaient
toutes.

**Deux questions distinctes, jamais déduites l'une de l'autre.**

| Question | Qui y répond | Ce qu'elle exige |
| :-- | :-- | :-- |
| **Résolution comptable** — « un reçu durable et vérifié consigne-t-il l'issue de cette tentative ? » | le rapprochement (§3.2) | même identifiant, même portée matérielle, coût dans le plafond, couple persistable, aucune faute, aucune contradiction, et la même **lignée** : schéma, protocole, preuve adaptateur |
| **Admissibilité à la qualification** — « ce reçu soutient-il un critère préenregistré ? » | `evaluate` (§3) | tout ce qui précède **plus** l'instant d'effet : un reçu antérieur reste **historique non qualifiant** |

La lignée du rapprochement porte donc sur le schéma, le protocole et la preuve
adaptateur, **non** sur l'instant d'effet. Exiger aussi l'instant ferait qu'un changement
de protocole orpheline les intents en vol, et un intent qu'aucun reçu ne peut plus
résoudre bloque la porte pour toujours — une correction transformée en déni durable.

Conséquence assumée, et c'est le comportement voulu : **un reçu de la bonne lignée peut
résoudre son intent sans contribuer à aucun critère** lorsqu'il est devenu historique. Le
compteur d'intents non résolus retombe à zéro, et le compteur d'historiques non
qualifiants monte d'un. Les deux faits sont publiés séparément.

### 3.3 Trois états de la frontière des reçus

Un répertoire qu'on ne peut pas lire n'est pas un répertoire vide. La v6 terminait son
audit par `except StoreRefused: → ((), 0)`, donc un répertoire de reçus atteint par un
lien symbolique, un parent substitué ou un répertoire impossible à ouvrir rapportaient
exactement ce que rapporte une installation propre.

| État | Ce qu'il établit | Effet |
| :-- | :-- | :-- |
| `ABSENT` | aucun répertoire de reçus ; rien n'est créé par la lecture | aucune preuve |
| `AVAILABLE` | répertoire sûr, lu par un descripteur ; les comptes valent ce qu'ils disent | selon les critères |
| `UNAVAILABLE` | le répertoire existe et n'est pas lisible sans ambiguïté | **conflit de preuve**, porte fermée |

`UNAVAILABLE` est accompagné d'une **catégorie** — `ambiguous_component`,
`not_a_directory`, `permission_denied`, `kernel_support_missing`, `unreadable` — et jamais
d'un chemin. Les deux rendus la publient.

**`load_parent` partage la même frontière (v7).** L'argument de la ligne de commande est
réduit **textuellement** à un nom de base du répertoire autorisé — jamais par `resolve`,
`is_symlink` ou `is_file` —, puis lu par le même `SecureDirectory` que l'audit. Jusqu'à
la v6 cette fonction, qui précède les deux commandes payantes, prenait quatre lectures de
chemin successives et un `resolve()` qui suit précisément les liens que le store refuse :
avec le répertoire de reçus devenu un lien, l'audit rapportait une installation vide et
`load_parent` autorisait un appel payant depuis la cible du lien.

Un lien **dur** vers un inode extérieur reste accepté si le fichier est régulier, signé
par le secret local et de portée exacte. La frontière garantit le nom et l'inode ouverts
dans ce répertoire, pas l'histoire de création de l'inode ; c'est écrit ici plutôt que
sous-entendu.
* le rapprochement est idempotent : si le reçu existe déjà, l'intent est résolu sans
  rien compter deux fois ;
* deux workers sur le même identifiant obtiennent un seul intent.

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

## 8. Campagne protocole 8 — préenregistrée, non exécutée

Aucune commande `discover`, `core` ou `additional` n'est lancée par cette tranche.
Chaque appel exigera une autorisation humaine distincte, et la machine refuse
désormais tout ce que ce manifeste n'autorise pas.

### Le manifeste, fermé avant le premier appel

**Bookmaker unique : `pinnacle`.** Choisi sur la liste publique des bookmakers du
fournisseur, consultée le **2026-08-24** et inscrite dans `docs/source-matrix.md` avec
son URL. C'est un préenregistrement, pas une affirmation de couverture live.

**Quatre compétitions, deux par famille :**

| Famille | Compétitions préenregistrées |
| --- | --- |
| football | `soccer_epl`, `soccer_spain_la_liga` |
| tennis | `tennis_atp_us_open`, `tennis_wta_us_open` |

Deux par famille n'est pas une préférence : `min_competitions = 2` rend une seule
compétition incapable de satisfaire un critère `CORE_MAPPING_*`. Lesquelles devait donc
être écrit à l'avance, et la v7 ne l'écrivait pas — c'est exactement ainsi que la
seconde aurait pu être choisie après avoir vu la première revenir vide.

`additional` est réservé au football : deux appels, un par compétition football.

Si une compétition est inactive, vide ou non couverte au moment autorisé, **la campagne
v8 échoue sans substitution**.

`winamax_fr` et la piste B sont exclus de la campagne v8. Les vérifier exigerait un
protocole ultérieur distinct.

### Les plafonds, comptés par la machine

| Commande | Plafond | Répartition |
| --- | --- | --- |
| `discover` : 4 invocations | une par compétition | 1 × 4 compétitions |
| `core` : 6 invocations | trois par famille | 3 × 2 familles |
| `additional` : 2 invocations | une par compétition football | 1 × 2 compétitions |

`campaign_preflight` vérifie tout cela **avant** la lecture de la clé fournisseur,
**avant** la publication d'un intent et **avant** toute socket. Un refus laisse zéro
socket, zéro lecture de clé, zéro intent, zéro reçu, zéro crédit. Le secret de signature
local est lu avant ce contrôle, parce qu'auditer nos propres reçus est ce qui rend le
compte possible — et cela ne coûte rien chez le fournisseur.

**Un échec consomme son invocation.** Il ne crée aucun droit de remplacement ni de
relance.

### L'abandon

Une commande réseau v8 dont le reçu vérifié ne porte pas le statut de succès de cette
commande abandonne définitivement la campagne :

| Commande | Statut de succès | Tout autre statut |
| --- | --- | --- |
| `discover` | `DISCOVERY_VERIFIED` | campagne `ABORTED` |
| `core` | `CORE_LIVE_VERIFIED` | campagne `ABORTED` |
| `additional` | `ADDITIONAL_LIVE_VERIFIED` ou `ADDITIONAL_PARTIAL_COVERAGE` | campagne `ABORTED` |

Après abandon, `status` et `plan` restent lisibles hors réseau ; `discover`, `core` et
`additional` sont refusés avant réseau. Recommencer exige un **nouveau protocole**, pas
une relance de la v8. Un reçu v8 postérieur à l'instant d'abandon est un
`EVIDENCE_CONFLICT` : le corpus contredirait son propre arrêt.

### Corpus hors manifeste ou forgé

Dans l'évaluation, un `EVIDENCE_CONFLICT` est produit par un reçu v8 signé mais hors
bookmaker, hors compétition ou hors plafond ; par une cinquième découverte, un septième
`core` ou un troisième `additional` ; par deux découvertes d'une même compétition ; par
deux appels d'une même commande sur un même événement. Les doublons et les lignées
contradictoires restent des conflits comme avant.

Un audit qui ne peut pas établir les comptes ne publie **aucun faux zéro** : il publie
`campaign_counts_state = UNESTABLISHED` et `campaign_invocation_counts = null`, et la
garde refuse tout appel réseau sur cette base.

Le reçu réel v7 demeure historique et ne compte dans aucun compteur v8.

### Ce que la campagne v8 ne peut toujours pas faire

Elle ne promeut rien. `QualificationState` conserve exactement ses trois valeurs —
`INSUFFICIENT_EVIDENCE`, `EVIDENCE_CONFLICT`, `CRITERIA_MET_AWAITING_HUMAN_REVIEW` — et
`adapter_state` reste `IMPLEMENTED_UNVERIFIED` dans tous les cas.

### La configuration du parser, garantie par la machine

Le harnais analyse une réponse payante avec le parser de l'adaptateur, et ce parser ne
retient que les bookmakers nommés par `BETMAXXING_BOOKMAKERS` — **pas** celui passé en
argument de la commande. Les deux coïncidaient tant que `--bookmaker` et le défaut livré
valaient tous deux `winamax_fr` ; sous le manifeste v8 ils divergent, et le défaut livré
reste `winamax_fr`.

Ce que cela coûtait tant que ce n'était qu'une consigne, mesuré par le réaudit final :
un `core` conforme au manifeste, **la variable simplement absente**, atteignait
l'endpoint payant, ne retenait aucune sélection, publiait `SCHEMA_MISMATCH`, dépensait
un crédit et plaçait la campagne en `ABORTED` — irréversiblement, puisque recommencer
exige un nouveau protocole. Une précondition écrite dans trois documents et gardée par
rien.

`campaign_preflight` vérifie donc que `pinnacle` figure dans `BETMAXXING_BOOKMAKERS`,
pour `discover`, `core` **et** `additional`, avant la lecture de la clé fournisseur,
avant tout intent et avant toute socket. La variable est lue **par son nom** : instancier
`Settings` peuplerait tous les champs depuis l'environnement, la clé fournisseur
comprise, et « avant » doit vouloir dire avant.

La casse est exacte : `PINNACLE` n'est pas `pinnacle`. Les clés du fournisseur sont des
identifiants minuscules, et accepter silencieusement une autre graphie ferait passer pour
correcte une configuration que le parser ne reconnaîtra pas.

Ce refus **ne consomme aucune invocation**, ne dépense aucun crédit, n'abandonne pas la
campagne et ne crée aucun conflit de preuve : la campagne reste exactement aussi
réutilisable qu'avant.

**La variable doit exister dans l'environnement du processus, et pas seulement dans `.env`.**
`Settings` accepte normalement `.env` — c'est le canal de configuration de tout le
reste, et `.env.example` y livre cette variable. La garde, elle, la lit directement par
son nom, sans instancier `Settings` : instancier le modèle peuplerait tous les champs
depuis l'environnement **et depuis `.env`**, la clé fournisseur comprise, alors que ce
contrôle doit précéder toute lecture de secret. Le prix de cette pureté est explicite :
une entrée présente seulement dans `.env` est refusée, fail-closed et sans coût. Ne
sourcez pas `.env` en bloc pour contourner cela — ce fichier contient des secrets.

```bash
export BETMAXXING_BOOKMAKERS=pinnacle
```

Le contrôle s'applique aussi à `discover`, qui n'analyse pourtant aucune cote :
s'arrêter à l'étape gratuite ne coûte rien, tandis que découvrir d'abord et échouer au
premier appel payant coûte la campagne.

### Budget maximal

Borne issue du tarif relu, **pas** une garantie de facture.

Une invocation CLI n'est **pas** une requête HTTP : `discover` en fait deux —
`/sports` puis les événements de la fenêtre. La v1 de ce document appelait
« requêtes » ce qui était un compte d'invocations, et sous-estimait donc le trafic
de quatre requêtes tout en chiffrant les crédits correctement. Les deux nombres du
total valent seize par coïncidence.

| Étape | Invocations CLI | Requêtes HTTP maximales | Crédits/appel | Crédits max |
| --- | --- | --- | --- | --- |
| `discover` football (`soccer_epl`, `soccer_spain_la_liga`) | 2 | 4 | 0 | 0 |
| `discover` tennis (`tennis_atp_us_open`, `tennis_wta_us_open`) | 2 | 4 | 0 | 0 |
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

Depuis la v8 ces bornes ne sont plus seulement documentaires : `campaign_ledger` les
confronte aux reçus vérifiés présents sur la frontière, `campaign_preflight` refuse
avant réseau ce qui les dépasserait, et `status --json` publie
`campaign_invocation_counts` à côté de `campaign_invocation_limits`. Le dépassement
qu'aucun champ ne distinguait d'un corpus conforme est maintenant un
`EVIDENCE_CONFLICT` nommé.

### Arrêts anticipés qui réduisent le coût

| Constat | Effet |
| --- | --- |
| `discover` sans événement admissible | 0 crédit dépensé, invocation consommée, campagne `ABORTED` — voir §8 |
| `COVERAGE_MISSING` au premier `core` | 1 crédit, pas de `additional` |
| `COST_MISMATCH` sur un appel | arrêt immédiat, `COST_CONFORMITY` échoue |
| mapping rejeté sur `core` | arrêt : `additional` n'est pas tenté |
| `CORE_MAPPING_*` non atteint | les 10 crédits `additional` ne sont jamais engagés |

Le pire cas coûte 16 crédits. Le cas d'échec précoce en coûte 1.

### Exécution en deux tranches (D-079)

Les 16 crédits sont le coût **contractuel de la campagne complète**, et le fractionner ne
le réduit pas. Il est en revanche exécuté en deux tranches autorisées séparément, parce que
les deux moitiés ne prouvent pas la même chose et n'ont pas le même prix.

| | Invocations | Crédits max | Critères atteignables au mieux |
| --- | --- | --- | --- |
| **Tranche 1** | six `core` d'un crédit | **6** | `CORE_MAPPING_FOOTBALL`, `CORE_MAPPING_TENNIS`, `COST_CONFORMITY` — soit **3 sur 8** |
| **Tranche 2** | deux `additional` de cinq crédits | **10** | les cinq `ADDITIONAL_MAPPING_FOOTBALL_*` — soit les **5** restants |
| **Total** | douze, plus quatre `discover` gratuites | **16** | 8 sur 8 |

La tranche 2 n'est engagée qu'après validation de la tranche 1, et jamais par déduction :
une autorisation ne se déduit pas de la précédente.

**Ce que `plan --max-credits 6` chiffre, et ce qu'il ne chiffre pas.** Ce plafond est
`TOTAL_MAX_CREDITS`, la somme de `STEP_CEILINGS` — le coût d'une séquence locale portant sur
**un seul événement** : un `core` à 1 crédit et un `additional` à 5. Ce n'est pas le budget
de la campagne, et le lire comme tel conduit à une conclusion fausse : six crédits dépensés
en un `core` et un `additional` donnent un événement dans chaque étape et ne satisfont
**aucun** critère, puisque les seuils demandent trois événements pour `core` et deux pour
chaque marché `additional`.

**Les seuils ne se satisfont pas par répétition.** `min_competitions` et `min_utc_days`
portent sur des compétitions et des jours UTC **distincts**, calculés sur un canon
dédupliqué par identifiant et somme de contrôle. Rejouer le même événement, ou re-déposer
le même reçu, ne rapproche d'aucun seuil : `qualification_exact_duplicate_copies` compte les
copies et aucun compteur sémantique ne bouge. `LOCAL_BOUNDS` borne d'ailleurs chaque
invocation payante à **un** événement, si bien que trois événements exigent trois
invocations et trois autorisations humaines.

**Aucun résultat intermédiaire n'est une qualification.** Trois critères sur huit, c'est
trois critères sur huit : `qualification_state` reste `INSUFFICIENT_EVIDENCE` tant que les
huit ne sont pas satisfaits, `adapter_state` reste `IMPLEMENTED_UNVERIFIED` dans tous les
cas, et le plafond machine demeure `CRITERIA_MET_AWAITING_HUMAN_REVIEW`.

### La seule récupération après la fenêtre de crash (D-079)

Un intent est écrit et `fsync`-é **avant** la requête, retiré une fois son reçu durablement
publié. Le processus peut mourir entre les deux : l'intent survit alors qu'un reçu existe, et
la porte reste fermée puisqu'un intent non résolu est un conflit de preuve.

```bash
python -m betmaxxing.providers.the_odds_api.activation receipts reconcile [--json]
```

C'est la **seule** récupération autorisée. Elle n'ouvre aucune socket, ne lit aucune clé
fournisseur, charge le secret de vérification **sans en créer un**, audite par
`audit_directory`, et ne retire un intent que sur un reçu durable, vérifié par le HMAC, de
portée matérielle identique et de même lignée de versions au sens de D-077. Elle est
idempotente, laisse intact tout intent sans preuve correspondante, et échoue de façon typée
si la frontière, le secret, la lecture, la suppression ou le `fsync` échoue.

`reconcile_intents` existait depuis la v7 et était documentée ici comme la résolution
comptable, mais aucune commande ne l'appelait : la récupération était décrite et non
exécutable — le défaut que D-077 avait fermé un cran plus bas pour la quarantaine.

**La suppression manuelle d'un intent reste interdite.** `receipts quarantine` refuse les
`*.intent` avec et sans `--force`, et il n'existe aucune commande de suppression. Retirer un
intent à la main rouvrirait la porte sans preuve, ce qui est l'inverse d'une récupération.

### Un compte n'est publié qu'une fois pris (D-080)

Le rapport de rapprochement publie des mesures, jamais des valeurs d'initialisation.
`resolved_intents`, `remaining_intents`, `verified_receipts_considered` et
`unverifiable_receipts` sont des **entiers ou `null`**, et le rendu humain écrit
`NON ÉTABLI` là où le JSON porte `null`. **Remplacer une absence de mesure par zéro est
interdit** : zéro est une mesure, et un refus survenu avant l'inventaire n'en a fait aucune.
C'est la règle de `BoundaryState.UNAVAILABLE` (D-077) appliquée aux comptes eux-mêmes.

Deux états accompagnent ces compteurs, et ils répondent à deux questions différentes :

| Champ | Valeurs | Ce qu'il dit |
| --- | --- | --- |
| `intent_counts_state` | `ESTABLISHED`, `PARTIAL`, `UNESTABLISHED` | combien des deux compteurs d'intents ont été pris ; **dérivé** d'eux, jamais assigné à la main |
| `intent_resolution_durability` | `NOT_ATTEMPTED`, `DURABLE`, `UNCERTAIN` | si les suppressions de cette exécution sont connues pour survivre à un crash |

Trois situations, et ce que chacune doit publier :

- **refus avant toute mesure** — secret absent ou invalide, frontière indisponible, faute de
  lecture avant inventaire complet : les deux compteurs à `null`, `UNESTABLISHED`,
  `NOT_ATTEMPTED`, `EVIDENCE_CONFLICT`, `eligible = false`. Aucune phrase n'affirme qu'il ne
  reste aucun intent ;
- **résultat partiel** — certaines opérations sont connues mais le comptage final échoue :
  seules les valeurs effectivement établies sont publiées, les autres restent à `null`,
  l'état est `PARTIAL`, et la porte reste fermée ;
- **succès complet** — inventaire et synchronisation aboutis : les deux compteurs sont des
  entiers mesurés, l'état est `ESTABLISHED` et la durabilité `DURABLE`.

**Un `fsync` qui échoue après un `unlink` réussi.** Dès que l'`unlink` retourne, la
suppression a eu lieu dans l'espace de noms courant : c'est un fait observé, et il est
compté. Le rapport publie alors la résolution observée, le nombre restant si sa mesure
aboutit, `UNCERTAIN`, une erreur typée et un code de sortie non nul, avec
`EVIDENCE_CONFLICT` et `eligible = false`. Il ne publie **jamais** `resolved_intents = 0` et
`remaining_intents = 0` sous une phrase affirmant qu'un intent restant bloque la porte.

Une exécution complète **synchronise le répertoire même lorsqu'elle ne retire rien**. C'est
ce qui permet à un second passage, après une faute de durabilité, d'établir durablement
l'état courant et de répondre `DURABLE` plutôt que « rien à faire » — et de produire un
rapport cohérent et idempotent.

**`UNCERTAIN` a donc deux formes, à lire avec `resolved_intents` (D-081).**

| Forme | `resolved_intents` | Ce qui s'est passé |
| --- | --- | --- |
| avec suppression | non nul | un `unlink` a réussi, le `fsync` qui le rend durable a échoué |
| sans aucune suppression | `0` | rien n'a été retiré ; c'est le `fsync` destiné à établir durablement l'état courant qui a échoué |

`resolved_intents` est le seul champ qui sépare les deux, et il suffit. Dans les **deux**
cas : erreur typée, code de sortie non nul, `EVIDENCE_CONFLICT`, `eligible = false`, porte
fermée, et **une nouvelle exécution est nécessaire** pour établir durablement l'état. Un
rapport qui répondrait `DURABLE` après un `fsync` d'établissement en échec affirmerait une
durabilité qu'il n'a pas établie — la faute même que cette section interdit. Un test le
tient : supprimer la synchronisation d'établissement le fait passer au rouge.

## 9. Écriture et audit des reçus : un descripteur, pas un chemin

**Frontière du répertoire.** Le répertoire de reçus est ouvert **une fois**, composant
par composant, chacun avec `O_DIRECTORY`, `O_NOFOLLOW` et `O_CLOEXEC` relativement au
descripteur du parent déjà sûr, `fstat` à l'appui. Le descripteur obtenu sert à tout :
`os.listdir(fd)`, `os.open(..., dir_fd=fd)`, `os.link(..., src_dir_fd=fd,
dst_dir_fd=fd, follow_symlinks=False)`, `os.unlink(..., dir_fd=fd)`, `os.stat(...,
dir_fd=fd, follow_symlinks=False)` et `os.fsync(fd)`. Aucune opération sensible ne
revient à `répertoire / nom` après l'ouverture.

La v5 protégeait le *nom* et pas le *répertoire* : elle l'ouvrait par chemin avec
`O_DIRECTORY` seul, puis reprenait des chemins pour `link`, `unlink` et le `fsync`.
Trois probes déterministes en ont fait la démonstration — répertoire-lien, parent
substitué, répertoire permuté entre le listing et l'ouverture — et dans les trois cas
le contenu d'un fichier extérieur a été lu, vérifié et rapporté. Sur une plateforme
sans `O_NOFOLLOW` ou sans opérations relatives à un descripteur, le répertoire n'est
**pas lu** : échec fermé, jamais un retour au contrôle vulnérable.

**Publication atomique, dans cet ordre exact :**

1. écrire tous les octets dans un temporaire neuf du même répertoire, sous un nom qui
   n'est pas `*.json` ;
2. `fsync` du temporaire ;
3. publier sous le nom final par un lien dur, qui **échoue** au lieu de remplacer si le
   nom est pris ;
4. `fsync` du répertoire, pour que la nouvelle entrée survive ;
5. supprimer le temporaire ;
6. `fsync` du répertoire, pour que sa suppression survive aussi.

La v5 documentait l'ordre 5-puis-6 à l'envers de ce qu'elle faisait, et **supprimait**
l'erreur de `fsync` du répertoire avec `contextlib.suppress(OSError)` tout en
revendiquant la durabilité. Ici aucune étape n'est supprimée : une erreur de durabilité
est levée et dit si la preuve avait été publiée avant l'échec (`published`) et s'il
reste quelque chose à nettoyer (`cleanup_pending`). La boucle d'écriture n'a pas de
`written += os.write(...)` sans garde : un retour à zéro est absorbé au plus trois fois,
puis c'est une erreur — un probe de la v5 tournait indéfiniment et a dû être tué.

Sur cible finale existante : un fichier régulier identique est idempotent ; un **reçu
signé valide** divergent est une collision explicite et reste intact ; un fichier vide,
tronqué ou qui n'est pas du JSON signé n'est **jamais** appelé « contenu signé
différent » — il est nommé incomplet, et le message renvoie vers la commande qui le met
de côté.

**Quarantaine.** `quarantine_incomplete_receipt` prend un **nom de base** du répertoire
déjà ouvert, jamais un chemin. La v5 dérivait son répertoire de son argument, donc elle
renommait n'importe quel fichier que le processus pouvait atteindre — y compris hors du
répertoire de reçus, et, sous parent substitué, un fichier étranger. Elle utilisait
aussi `os.rename`, qui **remplace** : une collision forcée détruisait les octets du
premier fichier mis de côté, contre la promesse du protocole de n'en perdre aucun. La
v6 déplace par lien dur puis suppression, réessaie un nombre borné de fois sur
collision, et refuse un reçu signé complet sans `--force`.

**Son périmètre (v7).** Un nom de base finissant par `.json`, et rien d'autre. Le secret
de signature, tout fichier `*.intent`, tout temporaire de publication et tout autre
fichier régulier sont refusés **avec et sans `--force`** ; `--force` ne sert qu'à
archiver un reçu signé complet. La v6 ne l'imposait pas, et deux conséquences ont été
reproduites : `--name <identifiant>.intent` rendait 0 sans `--force` et faisait passer la
porte de `EVIDENCE_CONFLICT` à `CRITERIA_MET_AWAITING_HUMAN_REVIEW` — un conflit supprimé
sans qu'aucun reçu existe — et `--name signing-key.secret` rendait huit reçus vérifiés
invérifiables. Ni la racine de confiance ni le journal des tentatives n'est un reçu.

Elle est enfin **exécutable** :

```bash
python -m betmaxxing.providers.the_odds_api.activation receipts quarantine --name NOM.json
```

La v5 renvoyait l'opérateur vers une fonction qu'aucune commande n'exposait : la seule
sortie de secours documentée n'était pas jouable.

**`write_receipt()`** — nom construit depuis des composants **validés**. `command` et
`receipt_id` doivent être des chaînes non vides sans séparateur de chemin ;
`recorded_at` est **parsé** puis reformaté, au lieu d'être découpé dans le texte. Un
`recorded_at` de `"../../2026-08-11T12:00:00+00:00"` survivait au découpage sous la
forme `"../../20260811T"` et plaçait le reçu deux répertoires au-dessus du sien.

**Provenance (v7).** Les trois types — `VerifiedReceipt`, `VerifiedReceiptBatch` et
`AuditResult` — prennent un **jeton privé** en premier argument positionnel :
l'orthographe naturelle lève `UnverifiedProvenance`. `trust(payload, secret=…)` et
`require_verified()` sont **supprimés** : une fabrique qui prend la clé de l'appelant est
exactement le trou que le sixième audit a franchi, et un `isinstance` n'est pas une
vérification. Le seul chemin est `audit_directory`, qui reçoit un répertoire déjà ouvert
composant par composant et fait lui-même la lecture, le contrôle de schéma et le HMAC
contre le secret de l'installation : pour obtenir une provenance admise il faut posséder
un répertoire sûr et y déposer des fichiers correctement signés, c'est-à-dire faire ce
que fait la production.

Un reçu admis est **gelé récursivement**. La v6 copiait un seul niveau, si bien que
`reçu["freshness"][marché] = 300` — l'API documentée, aucun attribut privé — faisait
passer un corpus de `INSUFFICIENT_EVIDENCE` à la porte de revue humaine après
vérification, pendant que la signature du reçu ne vérifiait plus.

La première rédaction de ce paragraphe scellait les conteneurs par une sous-classe de
`dict` et une sous-classe de `list` redéfinissant chaque mutateur, afin que rien en aval ne
change de vocabulaire, et présentait `dict.__setitem__(gelé, k, v)` comme une limite
acceptée. Ce n'était pas une limite mais le même défaut un niveau plus bas : redéfinir un
mutateur ne le supprime pas, la méthode de la classe de base restant joignable par l'objet
classe. Mesuré, les **quinze** appels `dict.__setitem__`, `dict.update`, `dict.pop`,
`dict.setdefault`, `dict.clear`, `dict.__ior__`, `list.__setitem__`, `list.append`,
`list.extend`, `list.insert`, `list.pop`, `list.clear`, `list.__iadd__`, `list.sort` et
`list.reverse` réussissaient sur un reçu réellement admis, et le premier rouvrait la porte.
`FrozenMapping` implémente donc `Mapping` **sans hériter d'aucun conteneur mutable**, les
séquences sont des `tuple`, et les quinze appels lèvent. Le prix est explicite : les
contrôles structurels qui demandaient `isinstance(value, list)` demandent une `Sequence`
non-`str`, et un reçu admis se re-sérialise par `to_builtin()` plutôt que par `dict()`.

L'audit enregistre une **somme de contrôle** sha256 non clée de chaque reçu admis sous
`AuditResult.checksums`, et `require_audited` les recalcule avant toute lecture du lot. Ce
contrôle attrape ce pour quoi il est fait : un contenu qui a changé entre l'audit et
l'évaluation — un conteneur partagé par erreur, un helper qui modifie ce qu'on lui a passé,
un refactor qui réutilise un objet qu'il aurait dû copier. Il **n'authentifie rien** :
aucun secret n'intervient et `content_checksum` est publique. Les noms le disent depuis
D-078 — c'était `fingerprint` enregistré sous `seals`, et les deux mots promettaient une
preuve d'origine qu'un condensé sans clé ne peut pas porter.

### Modèle de menace (D-078), normatif

La propriété garantie, littéralement :

> Dans le pipeline applicatif supporté, seuls les reçus dont le HMAC a été vérifié par
> `audit_directory` sont transmis à l'évaluation. L'objet de provenance est un marqueur
> interne et un contrôle contre les erreurs d'utilisation ; il ne constitue pas une sandbox
> contre du code Python arbitraire exécuté dans le même processus.

| Dans le périmètre | Hors du périmètre |
| --- | --- |
| fichiers de reçus, intents et payloads fournisseur hostiles ou malformés | exécution arbitraire de Python dans le processus Betmaxxing |
| reçus sans signature ou signés avec une autre clé | accès réflexif aux attributs privés |
| écritures interrompues et erreurs de stockage | `object.__new__`, `object.__setattr__`, monkeypatching |
| liens symboliques, substitutions de chemins, courses de système de fichiers | modification du bytecode, des modules ou du code source exécuté |
| appelant utilisant les API publiques et documentées | debugger ou processus compromis sous l'identité de l'application |
| erreurs accidentelles du code applicatif | accès direct au secret HMAC |
| processus extérieur sans le secret et sans exécution dans le processus | — |

**Justification.** Un acteur capable d'exécuter arbitrairement du Python dans le même
interpréteur peut remplacer `evaluate`, neutraliser le vérificateur ou lire le secret. Aucun
constructeur privé, jeton, type ou somme de contrôle exprimable en Python ne forme une
frontière cryptographique contre lui ; il faudrait une isolation par processus ou service,
hors périmètre de 03C-1.

Par conséquent « non-forgeable », « non constructible », « impossible à fabriquer », « aucun
objet mutable » et « preuve cryptographique portée par le type » ne sont **pas** employés
comme garanties. L'authenticité vient du HMAC vérifié à l'ingestion ; le type et la somme de
contrôle **préservent** cette décision, ils ne la rétablissent pas.

**Durcissement livré**, en défense en profondeur : plus aucun jeton au niveau module ;
constructeurs de provenance refusant inconditionnellement ; sous-classement refusé sur les
quatre types ; identité de type exacte (`type(x) is …`) aux frontières internes ;
`audit_directory` seule fabrique du graphe applicatif, vérifié par un test qui lit les
sources. `FrozenMapping` n'expose aucun mutateur **public** — son dictionnaire privé reste
joignable par les primitives réflexives, et c'est une limite écrite, pas une garantie.

**Scalaires (v7).** `unverifiable` et `unresolved_intents` sont des entiers Python
exacts, non booléens, positifs ou nuls. `None` et `False` ne valent jamais zéro
implicitement : « je ne sais pas combien » ne doit pas se lire « il n'y en a pas » pour un
bloqueur.

**Erreurs de stockage (v7).** Une signature de forme incorrecte rend le reçu
invérifiable au lieu de faire lever `hmac.compare_digest` — un seul fichier portant
`"é" * 64` faisait mourir `status` sur un `TypeError` nu, zéro octet en sortie, tant
qu'il restait sur le disque. De l'UTF-8 invalide devient `ContentUndecodable`, et
`SecretInvalid` pour le secret. `exists` ne traite plus que `ENOENT` comme « absent »,
parce que `ensure_secret` agit sur cette réponse en *créant*. L'échec de création du
temporaire de publication devient une erreur de durabilité, et les cinq sites de
publication capturent le graphe réel des exceptions, non seulement `PersistenceFailed`.

**`audit_receipts()`** — le seul endroit où une provenance est frappée. La signature est
vérifiée une fois, ici, contre un secret que cette fonction **charge** sans jamais le
créer : une installation qui a des reçus et pas de secret les rapporte tous comme
invérifiables au lieu d'inventer une clé qui les rendrait valides. Ce qui en sort est un
`VerifiedReceiptBatch`, et `evaluate` refuse tout le reste.

**Table des couples.** `RECEIPT_PHASES` contient **26 couples** et **30 formes** en
comptant les quatre couples bi-phase. Parmi eux, **21** sont réellement persistés par un
chemin de commande et **5** sont des réponses que le contrat doit avoir sans qu'aucun
producteur ne les écrive : les deux couples `plan`, qui n'écrit rien du tout, et les
trois `PREPARED_NOT_EXECUTED` de `discover`, `core` et `additional` — un refus *avant*
le réseau n'écrit aucun reçu, délibérément. Le test qui compare la table aux chemins
réels échoue dans les **deux** sens.
