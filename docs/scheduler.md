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

## Idempotence

Chaque tâche porte un `job_key` déterministe, dérivé de (type, minute d'exécution, sujet).
Les clés déjà exécutées sont conservées et ne sont jamais rejouées, donc :

- un redémarrage en cours de passe ne réexécute pas ce qui est fait ;
- une passe partiellement terminée reprend exactement là où elle en était.

## Verrou

Un verrou par fichier (`O_CREAT | O_EXCL`, `/tmp/betmaxxing-scheduler.lock` par défaut,
surchargeable par `BETMAXXING_LOCK_PATH`) empêche deux planificateurs de coexister.

**Limite explicite :** il protège contre deux processus sur **un même hôte**, pas contre
deux machines. Un verrou consultatif PostgreSQL est le remplacement prévu si un
déploiement multi-hôtes devient nécessaire.

Si un processus s'est arrêté brutalement, le fichier peut subsister. Le message d'erreur
le dit et indique de le supprimer après avoir vérifié qu'aucun planificateur ne tourne.

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
