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

`PENDING` → `RUNNING` → `SUCCEEDED`, ou `FAILED_RETRYABLE` (réessayable jusqu'à
3 tentatives) → `FAILED_FINAL`.

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

**Garanti et testé sur SQLite.** Plusieurs workers contre **une même base** :
réclamation par compare-and-swap sur `(state, claim_token)`, insertion concurrente
idempotente, reprise d'un bail expiré par un seul gagnant.

**Écrit mais non exercé en CI.** Sur PostgreSQL, la sélection ajoute
`FOR UPDATE SKIP LOCKED`. Le code est là ; aucun test de la CI ne tourne contre
PostgreSQL, donc cette voie n'est pas *prouvée*.

**Non garanti.** Rien ne coordonne plusieurs bases. Le bail (15 min par défaut) borne
le temps pendant lequel un worker crashé bloque une occurrence ; il ne fait pas office
de verrou distribué. `renew_lease()` existe et est protégé par le jeton, mais le runner
ne l'appelle pas encore : un scan dépassant la durée du bail serait repris.

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
