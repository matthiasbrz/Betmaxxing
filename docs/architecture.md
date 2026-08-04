# Architecture

## Forme générale

Monolithe modulaire Python, plus un processus de planification séparé. Pas de Redis, pas
de file distribuée, pas de microservices : rien dans le périmètre V1 (un utilisateur,
deux sports, une fenêtre de 24 heures) ne le justifie, et chaque composant ajouté est un
composant à exploiter et à surveiller.

```
┌──────────────┐      ┌──────────────────────────────┐
│  CLI         │      │  Scheduler (processus séparé)│
└──────┬───────┘      └───────────────┬──────────────┘
       │                              │
       └──────────┬───────────────────┘
                  ▼
        ┌──────────────────┐        ┌──────────────────┐
        │  engine.scan     │◄───────│  models_ml       │
        └────────┬─────────┘        │  + registre      │
                 │                  └──────────────────┘
   ┌─────────────┼─────────────┐
   ▼             ▼             ▼
┌────────┐ ┌───────────┐ ┌──────────┐
│providers│ │ ingestion │ │  engine  │
│(interf.)│ │normalize  │ │ margin   │
└────────┘ └───────────┘ │ ev       │
                          │ elig.    │
                          └──────────┘
                 │
                 ▼
          ┌─────────────┐        ┌──────────┐
          │  storage    │◄───────│   API    │
          └─────────────┘        └──────────┘
```

## Décisions structurantes

### Le planificateur est un processus distinct

Un serveur web avec N workers exécuterait chaque tâche N fois, et un scan qui monopolise
un worker dégrade le service des requêtes. Le planificateur tourne donc seul, avec un
verrou de processus et des clés d'idempotence par tâche.

### Les snapshots de cotes sont immuables

`OddsSnapshot` est `frozen=True`, la table est en append-only, et `fingerprint` est
UNIQUE. Un prix observé à un instant est un fait historique : une nouvelle observation
crée une nouvelle ligne, jamais une mise à jour. C'est ce qui rend un backtest honnête
possible.

### L'identité d'un marché est verbeuse

Une `Selection` porte marché, période, ligne et code. Deux sélections ne sont comparables
que si les quatre correspondent. La ligne est obligatoire sur les marchés over/under et
interdite ailleurs — validé par Pydantic, pas par convention.

Les lignes entières (O/U 3.0) sont refusées en V1 : elles peuvent être remboursées, ce
qui en fait un pari différent d'une ligne décisive.

### Le moteur probabiliste est indépendant du LLM

Aucun LLM n'intervient dans le calcul d'une probabilité, d'une EV ou d'une décision
d'éligibilité. Le module `engine/explain.py` est un rendu déterministe par gabarit,
toujours disponible. Un LLM pourra reformuler un *paquet de preuves déjà validé*, sans
jamais pouvoir modifier une valeur ni un statut.

### Toute décision est conjonctive

`engine/eligibility.py` renvoie **tous** les motifs d'échec, pas le premier. Il n'existe
aucun score composite où une EV élevée compenserait une cote périmée : ce compromis est
précisément la façon dont un faux avantage se publie.

### Les marchés dérivés viennent d'un objet unique

Le football dérive 1X2, DNB, double chance et totaux d'une même matrice de scores. Le
tennis dérive vainqueur, « gagne au moins 1 set » et total de jeux des mêmes probabilités
de point au service. Des marchés pricés séparément se contrediraient, et la contradiction
est exactement là où apparaît un avantage illusoire.

### Aucune substitution silencieuse

En mode `paper` ou `live_analysis`, une source manquante lève `ProviderUnavailable`, le
scan retourne `DATA_UNAVAILABLE` et le message nomme la variable d'environnement absente.
Le pack de démonstration n'est jamais utilisé en remplacement.

### Le temps

Stockage et calcul en UTC ; conversion en `Europe/Paris` uniquement à l'affichage. Un
datetime naïf est **rejeté**, pas interprété : supposer un fuseau est une invention de
donnée. La fenêtre de scan est une durée absolue de 24 h — un jour parisien peut faire 23
ou 25 heures, la fenêtre non.

## Modules

| Module | Rôle |
|---|---|
| `config` | seuils centralisés, versionnés, empreinte reproductible, masquage des secrets |
| `domain` | vocabulaires fermés, entités immuables, identifiants canoniques, temps |
| `providers` | interfaces + adaptateurs ; le moteur ne connaît aucun vendeur |
| `ingestion` | déduplication, assemblage des books, quarantaine |
| `engine` | marge, EV, incertitude, mise, qualité, éligibilité, explication, scan |
| `models_ml` | baselines + registre appliquant la garde de validation |
| `evaluation` | métriques du protocole |
| `challenge` | Challenge — Montante |
| `scheduler` | planification pure + exécution |
| `storage` | schéma, sessions, dépôts |
| `api` | FastAPI, OpenAPI exploitable |

## Rapprochement des événements

Un identifiant canonique est dérivé de (sport, date UTC, participants normalisés). Deux
fournisseurs nommant différemment la même rencontre convergent sans clé partagée. Quand
la normalisation ne tranche pas, l'événement est marqué `mapping_ambiguous` et **rejeté**
via `EVENT_MAPPING_AMBIGUOUS` — deviner serait pire que s'abstenir.

## Limites assumées

- Le verrou du planificateur protège un hôte, pas un cluster. Un verrou consultatif
  PostgreSQL est le remplacement prévu si le besoin apparaît.
- L'état des challenges vit en mémoire dans l'API ; les tables existent pour le persister.
- SQLite convient au développement et aux tests ; PostgreSQL est requis en exploitation
  persistante.
