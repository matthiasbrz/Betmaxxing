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
        ┌──────────────────────────┐     ┌──────────────────┐
        │  engine.acquisition      │◄────│  models_ml       │
        │  collecte → persiste →   │     │  + registre      │
        │  analyse → persiste      │     └──────────────────┘
        └──────┬──────────┬────────┘
               │          │
   ┌───────────┘          └──────────────┐
   ▼                                     ▼
┌──────────┐ ┌───────────┐ ┌───────────────────────┐
│providers │ │ ingestion │ │  engine.scan          │
│(interf.) │ │normalize  │ │  margin · payoff · ev │
│the_odds_ │ │identity   │ │  uncertainty · elig.  │
│api·demo  │ └───────────┘ └───────────────────────┘
└──────────┘
               │
               ▼
        ┌─────────────┐        ┌──────────┐
        │  storage    │◄───────│   API    │
        │ + ledger    │        └──────────┘
        └─────────────┘
```

## Décisions structurantes

### Le planificateur est un processus distinct, adossé à un ledger SQL

Un serveur web avec N workers exécuterait chaque tâche N fois, et un scan qui monopolise
un worker dégrade le service des requêtes. Le planificateur tourne donc seul.

Son état vit dans `scheduler_jobs` : occurrences matérialisées à l'avance, réclamées
atomiquement avec un bail **et un jeton de possession**, acquittées **après** persistance
et **uniquement** sur un résultat explicitement classé succès. Un `set()` en mémoire ne
pouvait offrir ni reprise après redémarrage, ni récupération d'un worker crashé, ni
sûreté multi-workers (D-020).

Deux corrections structurantes s'y ajoutent (D-030, D-031) : les états réclamables sont
filtrés **en SQL avant `ORDER BY`/`LIMIT`**, sinon les lignes terminées finissent par
occuper toute la fenêtre de sélection ; et tout achèvement est conditionné par le jeton
de la réclamation courante, car réaffirmer `state = 'RUNNING'` ne distingue pas un
ancien détenteur d'un nouveau. Détail et limites : `docs/scheduler.md`.

### Un seul chemin de collecte

`AcquisitionService` est utilisé identiquement par l'API, la CLI et le planificateur.
Il **persiste événements et snapshots avant** de consulter le moindre modèle, puis
analyse, puis persiste le scan. Les snapshots ne se retéléchargent pas ; une analyse se
rejoue toujours (D-021).

Frontières transactionnelles : l'appel HTTP se fait **hors transaction** ; la
persistance du lot est une transaction ; la persistance du scan en est une autre. Un
crash entre les deux perd l'analyse et garde les prix — le bon compromis. La reprise est
idempotente par empreinte de snapshot, pas par cache mémoire.

### L'identité d'un événement est opaque

Un identifiant sans sémantique, une table `(provider, provider_event_id) → internal_id`,
et un historique des horaires. Un report met à jour le même événement ; deux affiches
distinctes le même jour restent distinctes (D-022).

**Et une identité indéterminée n'est pas une identité.** La résolution retourne
`RESOLVED`, `CREATED`, `AMBIGUOUS` ou `REJECTED`, et seuls les deux premiers portent un
identifiant. Une ambiguïté n'écrit rien d'autre qu'une ligne de revue : marquer un
résultat « ambigu » tout en retournant `candidates[0]` revenait à deviner en le
signalant, ce qui reste deviner (D-034).

### Un budget n'est un budget que s'il est persistant

Un compteur en mémoire ne borne ni un retry, ni deux workers, ni un redémarrage. Chaque
tentative fournisseur réserve son coût dans `provider_budget_ledger` avant d'être émise,
puis rapproche la réservation du coût réellement facturé (D-035).

### Le registre de modèles est la seule autorité sur la publication

`RegisteredModel` porte `model_id`, `version` et un statut lu depuis `model_registry`.
Un modèle absent de la table est `BACKTEST_ONLY`. La lecture échoue **fermée** : une
panne de base ne peut jamais élever les privilèges d'un modèle.

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

### L'incertitude est une affirmation, pas un nombre par défaut

Une probabilité de modèle porte un statut (`SYNTHETIC`, `UNAVAILABLE`, `ESTIMATED`,
`VALIDATED`). Les bornes et l'EV prudente sont **nullables**. Hors mode démo aucune
méthode défendable n'existe aujourd'hui, donc le statut est `UNAVAILABLE` et les
candidats sont rejetés avec `UNCERTAINTY_UNAVAILABLE` (D-019).

### L'EV vient d'une distribution de règlement

`EV = Σ p(issue) × rendement_net(issue)`. `p·o − 1` n'est correct que sans
remboursement ; le draw-no-bet rembourse la mise sur un nul (D-024).

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
| `engine.acquisition` | **le** chemin unique collecte → persistance → analyse → persistance |
| `engine.payoff` | distribution de règlement et EV générale |
| `ingestion.identity` | résolution d'identité stable des événements |
| `scheduler.ledger` | occurrences durables, réclamation atomique, baux |
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

Deux étapes, dans cet ordre :

1. **Autoritaire** — `(provider, provider_event_id)` dans `event_source_map`. Un
   fournisseur qui garde son identifiant stable à travers un report nous donne une
   identité stable sans effort.
2. **Inter-fournisseurs** — seulement si la paire est inconnue. Tout signal présent des
   **deux** côtés doit concorder : sport, participants canoniques (via les alias déclarés
   par le fournisseur), compétition, saison, tour/stage, et coup d'envoi à ±6 h. Un
   signal absent d'un côté est un silence, pas un désaccord : les fournisseurs
   renseignent ces champs de façon inégale, et traiter une compétition absente comme
   « compétition différente » scinderait chaque rencontre en deux.

Deux identifiants du **même** fournisseur ne fusionnent jamais : un fournisseur connaît
son catalogue, donc deux identifiants signifient deux affiches.

Une seule correspondance lie. Plusieurs sont **refusées** : la résolution retourne
`AMBIGUOUS` sans identifiant, n'écrit aucune correspondance, ne modifie aucun événement
candidat, ne rattache aucun snapshot, et dépose le cas dans `event_mapping_reviews`.
Le scan rejette explicitement l'événement via `EVENT_MAPPING_AMBIGUOUS` — deviner serait
pire que s'abstenir.

## Limites assumées

- Le ledger sécurise plusieurs workers contre **une même base**, et c'est testé sur
  SQLite. Le chemin PostgreSQL (`FOR UPDATE SKIP LOCKED`) est écrit mais n'est exercé
  par aucun test de la CI. Rien ne coordonne plusieurs bases.
- `renew_lease()` est protégé par le jeton mais le runner ne l'appelle pas : un travail
  plus long que le bail serait repris par un autre worker.
- La file `event_mapping_reviews` n'a ni CLI ni route : elle se lit en SQL.
- La table d'alias participants est consultée par le rapprochement, mais aucun import ne
  l'alimente.
- Le rattrapage est borné à 2 h : une panne plus longue ne rejoue pas les occurrences
  manquées.
- SQLite convient au développement et aux tests ; PostgreSQL est requis en exploitation
  persistante.
- Aucune méthode d'incertitude réelle n'existe, donc `paper` et `live_analysis` ne
  publient rien aujourd'hui.
- L'adaptateur The Odds API est `IMPLEMENTED_UNVERIFIED` : aucun appel réel n'a validé
  sa couverture.
