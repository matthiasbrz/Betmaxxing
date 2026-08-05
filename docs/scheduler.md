# Guide d'exploitation du planificateur

## Avertissement matériel

Le planificateur ne s'exécute que **pendant que le processus tourne**. Un ordinateur
portable éteint, en veille ou hors ligne n'exécute aucune tâche et ne produit aucune
alerte. Des alertes continues exigent un **hébergement persistant** (VPS, conteneur
managé, machine allumée en permanence).

Ce n'est pas une limitation logicielle contournable : c'est une conséquence directe du
fait qu'un processus arrêté n'exécute rien.

## Démarrage

```bash
export BETMAXXING_SCHEDULER_ENABLED=true
python -m betmaxxing.scheduler.runner
```

Le planificateur est **désactivé par défaut**. Démarré sans ce réglage, il consigne un
avertissement et s'arrête immédiatement plutôt que de tourner silencieusement à vide.

## Ce qui est planifié

| Type | Déclencheur | Configuration |
|---|---|---|
| Scan quotidien | Heures locales configurées | `BETMAXXING_SCAN_TIMES` (défaut `08:00,12:00,18:00`) |
| Jalons pré-événement | T−24 h, T−12 h, T−6 h, T−2 h, T−1 h, T−15 min | `BETMAXXING_MILESTONES_HOURS_BEFORE` |
| Rescoring sur mouvement | Variation de cote ≥ 2 % | `should_rescore()` |

Les heures quotidiennes sont interprétées en **`Europe/Paris`**, pas en UTC : « 08:00 »
reste 08:00 à Paris après un changement d'heure, même si l'instant UTC correspondant
change. Testé aux deux transitions.

## Processus séparé, et pourquoi

Le planificateur **ne doit pas** tourner dans le serveur web :

- un serveur à N workers déclencherait chaque tâche N fois ;
- un scan qui occupe un worker dégrade le service des requêtes.

## Sémantique exacte

Une passe (`tick`) fait exactement ceci :

1. **découvrir** — lister les événements à venir **et résoudre leur identité
   interne** ; un jalon ne porte jamais un identifiant fournisseur ;
2. **matérialiser** — insérer dans `scheduler_jobs` les occurrences qui devraient
   exister dans les deux prochains jours ;
3. **réclamer** — prendre atomiquement les occurrences dues, avec un bail **et un
   jeton de possession** ;
4. **exécuter** — un jalon tourne **cadré sur son événement** (`scope_id`) ;
5. **acquitter** — marquer `SUCCEEDED` **après** la persistance du lot, et
   **uniquement** si le résultat appartient explicitement à la catégorie succès.

L'ordre du point 5 est ce qui compte : acquitter avant la persistance ferait croire
au ledger qu'un lot est collecté alors qu'un crash l'a perdu.

Le point 1 existe parce que la version précédente plaçait l'identifiant du
fournisseur dans `scope_id` alors que le filtre d'analyse compare des identifiants
internes : chaque scan de jalon analysait zéro événement en se déclarant réussi
(D-032).

## Taxonomie des résultats

`execute()` retourne un résultat typé. Le runner décide à partir de lui, jamais à
partir de l'absence d'exception.

| Résultat | Statuts de collecte | Effet sur le job |
|---|---|---|
| `SUCCESS` | `OK`, `NO_CANDIDATE`, `COLLECTED_NO_MODEL`, `COVERAGE_MISSING`, `DATA_STALE` | `SUCCEEDED` |
| `RETRYABLE_FAILURE` | timeout, transport, 5xx, panne partielle devenue totale | `FAILED_RETRYABLE` + `next_attempt_at` |
| `FINAL_FAILURE` | clé absente, 401/403, 422, configuration inutilisable | `FAILED_FINAL`, pas de retry |
| `BUDGET_EXHAUSTED` | plafond scan ou jour atteint | différé de 6 h, hors de la fenêtre budgétaire courante |

**Un scan d'erreur est persisté dans tous les cas**, y compris quand aucun lot de
données n'existe : le diagnostic est ce dont on a besoin après coup, et il coûte une
ligne. Une panne fournisseur ne peut donc jamais produire un job `SUCCEEDED` (D-031).

> **Historique.** L'implémentation précédente ne pouvait jamais déclencher : la
> planification écartait les occurrences `run_at <= now` et la sélection ne gardait
> que `run_at <= now`. L'intersection était vide par construction. Voir D-020.

## États

| État | Sens | Terminal ? |
|---|---|---|
| `PENDING` | matérialisée, pas encore prise | non |
| `RUNNING` | détenue sous bail + jeton | non |
| `SUCCEEDED` | travail persisté et acquitté | **oui** |
| `FAILED_RETRYABLE` | panne fournisseur, backoff en cours (≤ 3 tentatives) | non |
| `FAILED_FINAL` | plafond de tentatives atteint, ou échec de configuration | **oui** |
| `DEFERRED` | attend l'ouverture d'une fenêtre externe — aujourd'hui le reset budgétaire UTC | non |
| `SKIPPED_BUDGET` | budget épuisé **et** l'occurrence perd sa valeur avant le reset | **oui** |

`DEFERRED` n'est **pas** un échec : il ne consomme aucune tentative et ne peut pas
devenir `FAILED_FINAL`. Confondre « nous n'avons plus de crédits » avec « le
fournisseur est en panne » parquait un job sain après trois refus budgétaires.

## Budget épuisé — report ou abandon explicite

Il n'y a plus de délai fixe. La politique est :

1. la prochaine tentative est le **prochain minuit UTC**, plus une gigue
   déterministe dérivée du `job_id` et bornée à dix minutes. Réessayer dans la
   même journée UTC ne peut pas réussir : le quota du fournisseur est journalier ;
2. le compteur de pannes fournisseur n'est pas touché ;
3. si l'occurrence n'aura plus de valeur au reset, elle finit en `SKIPPED_BUDGET`
   avec un motif et un scan d'audit, plutôt que d'être reportée dans le vide.

« Plus de valeur » veut dire précisément :

| Type | Échéance |
|---|---|
| `EVENT_MILESTONE` | le coup d'envoi de son événement |
| `DAILY_SCAN` | `scheduled_for` + 2 h (la même grâce de rattrapage que la matérialisation) |

Conséquence assumée : un scan quotidien dont le budget manque est **abandonné**,
pas reporté — le ressusciter à minuit contredirait la règle qui refuse déjà de
matérialiser une occurrence périmée. Les occurrences du lendemain sont créées
normalement : un budget épuisé coûte un scan, pas le calendrier.

La gigue vient du `job_id` et non d'un tirage aléatoire, pour que l'échéance ne
bouge pas à chaque passe et qu'un redémarrage ne la repousse pas indéfiniment.

## Heartbeat de bail

Un scan peut durer plus que son bail. Exposer `renew_lease()` ne suffisait pas :
personne ne l'appelait, donc l'occurrence était reprise et **exécutée une seconde
fois**. Le jeton empêchait l'ancien worker d'acquitter — il n'annulait ni les
requêtes fournisseur déjà payées, ni les lignes écrites, ni les messages envoyés.

`LeaseGuard` encadre désormais l'exécution :

- cadence de renouvellement = **bail / 3**, plancher 100 ms, dérivée du bail pour
  que les deux ne puissent pas diverger ;
- un renouvellement **synchrone** avant le travail : la réclamation a horodaté le
  bail avec l'instant de *planification*, le travail tourne sur l'horloge murale,
  et l'écart entre les deux est une fenêtre de reprise ;
- chaque renouvellement lit l'horloge **au moment du renouvellement** ;
- arrêt et `join` garantis dans un `finally`, en succès, en exception et en perte
  de bail ;
- un renouvellement refusé marque le garde comme perdu ; le runner **n'acquitte
  pas** et laisse le job à celui qui le détient désormais.

### Effets externes

Le fencing protège le ledger, pas le monde extérieur : quand un worker découvre
qu'il a perdu son bail, un message déjà envoyé est déjà arrivé. Deux garde-fous :

- `JobLedger.assert_owns(job)` — à appeler avant tout effet non annulable ;
- `notification_outbox(job_id, alert_key, channel)`, unique : réserver la ligne
  autorise **un** envoi. Une reprise de la même occurrence n'envoie rien de plus.

La clé inclut le `job_id` : une occurrence *nouvelle* doit pouvoir réalerter sur un
changement matériel ; ce qui est interdit, c'est que la même occurrence alerte deux
fois parce que son bail a changé de main.

**Limite honnête.** L'outbox empêche le second envoi, pas le premier. Aucun
mécanisme ici ne rappelle un message déjà délivré.

## Idempotence et reprise

Une contrainte unique sur `(job_type, scheduled_for, scope_id)` rend l'insertion
idempotente, y compris quand deux workers insèrent la même occurrence au même instant :
le perdant reçoit une `IntegrityError` et la traite comme « déjà planifiée », ce qui est
exactement ce qui s'est produit. L'état vit **en base**, pas en mémoire, donc :

- un redémarrage ne rejoue pas une occurrence déjà réussie ;
- une occurrence `PENDING` en retard est reprise ;
- une occurrence `RUNNING` dont le bail a expiré (worker crashé) est récupérable.

## Rattrapage borné

Les occurrences antérieures à `DEFAULT_CATCHUP_GRACE` (2 h) ne sont pas matérialisées.
Rejouer une journée de scans manqués après une panne consommerait du quota fournisseur
pour produire des analyses périmées.

À l'inverse, un jalon **légèrement** dans le passé est conservé. Avec une fenêtre de
24 h, le jalon T−24 h d'un événement situé dans cette fenêtre est toujours un peu
derrière nous au moment de la découverte : écarter tout instant passé supprimait donc
purement et simplement ce point de rescoring, silencieusement, à chaque passe (D-033).
Un instant **égal** à `now` est dû, pas passé.

## Sélection sans famine

La requête de réclamation filtre les états réclamables **en SQL, avant `ORDER BY` et
`LIMIT`** :

```sql
WHERE scheduled_for <= :now
  AND ( state = 'PENDING'
     OR (state = 'FAILED_RETRYABLE' AND attempts < 3
         AND (next_attempt_at IS NULL OR next_attempt_at <= :now))
     OR (state = 'RUNNING' AND attempts < 3
         AND lease_expires_at IS NOT NULL AND lease_expires_at <= :now) )
ORDER BY scheduled_for LIMIT :limit
```

Index dédié : `ix_scheduler_claimable (state, scheduled_for, next_attempt_at)`.

La version précédente sélectionnait les lignes les plus anciennes **tous états
confondus** puis filtrait en Python : quelques dizaines de lignes terminées
remplissaient la fenêtre et un job réellement dû n'était jamais atteint. Autrement dit,
l'ordonnanceur cessait de fonctionner à mesure qu'il travaillait. Un test le vérifie
avec 500 occurrences terminées.

## Concurrence — ce qui est garanti, et ce qui ne l'est pas

**Jeton de possession.** Chaque réclamation génère un `claim_token`. `mark_succeeded`,
`mark_failed` et le renouvellement de bail sont des `UPDATE` conditionnés par
`(job_id, state = 'RUNNING', claim_token)` et lèvent `StaleLeaseError` quand ils
modifient zéro ligne. Un worker qui a perdu son bail pendant une pause ne peut donc ni
réussir ni échouer la tentative qui l'a remplacé.

Réaffirmer `state = 'RUNNING'` ne suffisait pas : c'est ce que la ligne disait déjà,
donc l'ancien détenteur **et** un second repreneur correspondaient tous les deux
(D-030).

**Garanti et testé sur SQLite *et* PostgreSQL 16 réel.** Plusieurs workers contre
**une même base** : réclamation par compare-and-swap sur `(state, claim_token)`,
`FOR UPDATE SKIP LOCKED` sur PostgreSQL, insertion concurrente idempotente, reprise
d'un bail expiré par un seul gagnant, refus des acquittements, échecs et
renouvellements périmés.

Les tests PostgreSQL utilisent des sessions distinctes et une `threading.Barrier` :
deux appels séquentiels ne prouvent rien sur la concurrence. Une étape de CI échoue
si cette suite est *skippée*, parce qu'une suite skippée et une suite verte se
ressemblent trop dans un résumé.

Pourquoi SQLite ne suffisait pas : il sérialise **tous** les écrivains derrière un
verrou global. Un algorithme incorrect y paraît atomique. C'est exactement ce qui
avait laissé passer un `SELECT SUM(...)` puis `INSERT` pour la comptabilité
budgétaire.

**Non garanti.** Rien ne coordonne plusieurs bases, et ce n'est pas prévu. Le bail
(15 min par défaut) borne le temps pendant lequel un worker crashé bloque une
occurrence ; il ne fait pas office de verrou distribué.

## Quotas

Les jalons multiplient les appels fournisseur. Avant d'activer la liste complète sur un
fournisseur à quota, réduisez `BETMAXXING_MILESTONES_HOURS_BEFORE` et vérifiez la
consommation via `GET /providers`.

## Journalisation

Logs structurés JSON, corrélés par `scan_id`. Une exception dans une passe est consignée
avec sa trace et la boucle continue : une erreur transitoire ne doit pas tuer le
planificateur.

## Arrêt

`SIGINT` / `SIGTERM`. Le verrou est libéré à la sortie.
