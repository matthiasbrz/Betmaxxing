# Spécification produit

## Ce que l'application est

Un outil d'analyse personnel qui répond à une question : *parmi les événements des
prochaines 24 heures, y a-t-il un pari dont l'espérance de valeur reste positive une fois
l'incertitude prise en compte ?*

La réponse est souvent **non**, et l'outil doit dire non clairement plutôt que de
descendre ses critères jusqu'à trouver quelque chose.

## Ce que l'application n'est pas

- Elle ne place aucun pari et ne se connecte à aucun compte de bookmaker.
- Elle ne promet aucun gain et n'affiche aucune projection de gains.
- Elle ne propose pas de stratégie de récupération après une perte.
- Elle ne produit pas de combinés automatiques.
- Elle ne remplace pas le jugement de l'utilisateur.

## Surfaces livrées

| Surface | État |
|---|---|
| CLI | ✅ fiches denses, JSON, explications |
| API REST + OpenAPI | ✅ |
| Export JSON / CSV | ✅ |
| Interface web | ⛔ tranche 6 |

## Les trois modes, et ce qu'ils promettent

| Mode | Données | Incertitude | Publie des candidats ? |
|---|---|---|---|
| `demo` | **synthétiques** | `SYNTHETIC — NE PAS PARIER` | Oui, à titre d'illustration seulement |
| `paper` | réelles | `UNAVAILABLE` | **Non** — `UNCERTAINTY_UNAVAILABLE` |
| `live_analysis` | réelles | `UNAVAILABLE` | **Non** — et exige en plus un modèle validé |

Autrement dit : **aujourd'hui, seul le mode démo produit des candidats, et ils sont
synthétiques.** C'est l'état honnête du produit, pas une panne. Aucun modèle n'est
validé et aucune méthode d'incertitude défendable n'existe.

Aucune promesse de gain n'est faite nulle part, et aucune projection de gains n'est
affichée.

## Écrans prévus (tranche 6)

Les captures de référence ont servi à calibrer la **densité et la hiérarchie de
l'information**, pas l'apparence. Ce qu'elles font bien : une fiche verticale compacte où
la sélection, la cote et l'EV se lisent d'un coup. Ce qu'elles font mal et qui n'est pas
repris : des étoiles de confiance subjectives, une EV sans incertitude, et aucune trace
des paris écartés.

### 1. Tableau de bord
En-tête : date/heure du scan, fenêtre, mode, état des fournisseurs, compteurs, statut
général. Puis les candidats triés par EV, en fiches.

Le mode et le statut de validation du modèle sont visibles en permanence, pas dans un
sous-menu.

### 2. Fiche candidat
Tout ce que la CLI affiche déjà : marché exact, période, ligne, cote et son âge,
probabilité implicite brute **et** sans marge, probabilité modèle avec son intervalle,
fair odds, EV et EV prudente, cote minimale acceptable, sensibilité, qualité des données,
confiance décomposée, 2 à 5 arguments sourcés et datés, risques, informations manquantes,
conditions d'invalidation, mouvement de cote, mise simulée, identifiants de modèle et de
configuration.

### 3. Vue « No bet »
Les rejets, groupés par code, avec leur détail. C'est un écran de premier plan : savoir
*pourquoi* rien n'est proposé vaut autant que la proposition.

### 4. Historique
Cotes, prédictions, décisions et résultats. Filtrable par empreinte de configuration pour
comparer des réglages.

### 5. Challenge — Montante
**Désactivé par défaut** (`BETMAXXING_CHALLENGE_ENABLED=false` ; les routes répondent
404). Une fraction supérieure à 50 % de la banque par palier exige une reconnaissance
explicite du risque de perte totale. Par palier : banque avant, mise, cote détectée, **cote acceptée**,
gain potentiel, banque projetée, probabilité, EV, risques, statut, preuve du résultat.
Le nombre de paliers est présenté comme une estimation recalculée, jamais comme une
promesse. Bouton d'arrêt toujours visible.

### 6. Configuration
Sports, marchés, seuils, bankroll, horaires, notifications. Tout seuil non validé porte
la mention `PROVISIONAL`.

### 7. Fournisseurs et modèles
Santé, quotas, fraîcheur, couverture. Statut de validation de chaque modèle et ce qu'il
autorise.

## Principes d'affichage

1. **Jamais un nombre sans son incertitude.** Une probabilité s'affiche avec son
   intervalle ; un rendement avec son intervalle bootstrap.
2. **Toujours distinguer brut et sans marge.** Et le dire quand la marge n'a pas pu être
   retirée.
3. **Les rejets sont du contenu**, pas des déchets.
4. **Le statut de validation est omniprésent.** `BACKTEST_ONLY` doit être impossible à
   manquer.
5. **Les données synthétiques sont signalées** à chaque endroit où elles apparaissent,
   et une incertitude synthétique porte la mention `SYNTHETIC — NE PAS PARIER`.
6. **Aucune étoile subjective.** Le score de confiance est une décomposition pondérée
   dont chaque composante est affichable.

## Parcours nominal

1. L'utilisateur lance un scan (manuellement ou par planification).
2. L'application retourne `CANDIDATES_FOUND`, `NO_BET` ou `DATA_UNAVAILABLE`.
3. Sur un candidat, il lit la fiche, les arguments sourcés, les risques et les conditions
   d'invalidation.
4. Il décide seul. S'il parie, il le fait lui-même chez son bookmaker.
5. S'il utilise le Challenge, il confirme manuellement la mise et saisit la **cote
   réellement obtenue**, qui est enregistrée séparément de la cote détectée.

À aucune étape l'application n'agit à sa place.
