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

1. **matérialiser** — insérer dans `scheduler_jobs` les occurrences qui devraient
   exister dans les deux prochains jours ;
2. **réclamer** — prendre atomiquement les occurrences dues, avec un bail ;
3. **exécuter** — un jalon tourne **cadré sur son événement** (`scope_id`) ;
4. **acquitter** — marquer `SUCCEEDED` **après** la persistance du lot.

L'ordre du point 4 est ce qui compte : acquitter avant la persistance ferait croire
au ledger qu'un lot est collecté alors qu'un crash l'a perdu.

> **Historique.** L'implémentation précédente ne pouvait jamais déclencher : la
> planification écartait les occurrences `run_at <= now` et la sélection ne gardait
> que `run_at <= now`. L'intersection était vide par construction. Voir D-020.

## États

`PENDING` → `RUNNING` → `SUCCEEDED`, ou `FAILED_RETRYABLE` (réessayable jusqu'à
3 tentatives) → `FAILED_FINAL`.

## Idempotence et reprise

Une contrainte unique sur `(job_type, scheduled_for, scope_id)` rend l'insertion
idempotente : deux passes identiques ne créent pas de doublon. L'état vit **en base**,
pas en mémoire, donc :

- un redémarrage ne rejoue pas une occurrence déjà réussie ;
- une occurrence `PENDING` en retard est reprise ;
- une occurrence `RUNNING` dont le bail a expiré (worker crashé) est récupérable.

## Rattrapage borné

Les occurrences antérieures à `DEFAULT_CATCHUP_GRACE` (2 h) ne sont pas matérialisées.
Rejouer une journée de scans manqués après une panne consommerait du quota fournisseur
pour produire des analyses périmées.

## Concurrence — ce qui est garanti, et ce qui ne l'est pas

**Garanti.** La réclamation est un `UPDATE` conditionnel (`WHERE job_id = … AND
state = …`) ; « 0 ligne modifiée » signifie « quelqu'un d'autre l'a prise ». PostgreSQL
sérialise par verrou de ligne, SQLite par verrou d'écriture global. Plusieurs workers
contre **une même base** sont donc sûrs, et c'est testé.

**Non garanti.** Rien ne coordonne plusieurs bases. Le bail (15 min par défaut) borne
le temps pendant lequel un worker crashé bloque une occurrence ; il ne fait pas office
de verrou distribué.

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
