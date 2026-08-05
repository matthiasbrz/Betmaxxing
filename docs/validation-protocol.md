# Protocole de validation préenregistré

**Version 1.0 — figée avant toute exécution sur le jeu de test final.**

Ce document est écrit *avant* d'ouvrir le jeu de test. Il fixe les découpages, les
métriques et les critères de promotion. Les modifier après avoir vu les résultats du test
final invaliderait la validation : dans ce cas, la version du protocole est incrémentée
et un nouveau jeu de test est nécessaire.

À ce jour, **aucune étape n'a été exécutée** : aucune donnée historique n'est intégrée.
Tous les modèles sont donc au statut `BACKTEST_ONLY`.

---

## 1. Découpage temporel

Découpage strictement chronologique. Aucun mélange aléatoire : les événements sportifs
sont ordonnés dans le temps et un tirage aléatoire ferait fuiter le futur dans le passé.

| Bloc | Usage | Règle |
|---|---|---|
| Entraînement | ajustement des paramètres | la plus ancienne portion |
| Validation | choix des seuils et de la calibration | suit l'entraînement |
| Test final | mesure unique, **scellé** | suit la validation, ouvert une seule fois |
| Forward test | mode `paper`, données réellement futures | après le test final |

Validation walk-forward sur le bloc de validation lorsque le volume le permet :
entraîner jusqu'à `T`, prédire `[T, T+Δ]`, avancer, ne jamais reculer.

---

## 2. Règles anti-fuite

Non négociables, et testables :

1. Une prédiction n'utilise que les informations disponibles à **son heure de calcul**.
2. Le backtest utilise la cote **réellement disponible à l'instant de décision**. Jamais
   la closing line comme prix d'entrée — c'est la fuite la plus fréquente et la plus
   flatteuse.
3. La closing line value est mesurée **a posteriori** comme diagnostic, jamais comme prix.
4. Aucune feature dérivée du résultat de l'événement prédit.
5. Aucune feature indisponible historiquement (voir `docs/source-matrix.md`).
6. Les paramètres de calibration sont ajustés sur le bloc de validation uniquement.

---

## 2 bis. Quatre évaluations distinctes, à ne pas confondre

Une erreur de conception du protocole initial : il mélangeait « le modèle est-il
bien calibré ? » et « la politique de sélection gagne-t-elle de l'argent ? ». Ce
sont des questions différentes, sur des populations différentes.

### (1) Modèle probabiliste — univers complet

Population : **tous** les événements et marchés de l'univers défini **avant** le
test, qu'ils soient devenus candidats ou non. Mesures : log loss, Brier,
calibration, pente et intercept de la régression de calibration, fréquences
observées par tranche préspécifiée.

### (2) Politique de sélection — candidats éligibles seulement

Population : les seuls paris que la grille aurait publiés. Mesures : volume,
rendement, drawdown, CLV. **Ne jamais** présenter une métrique de (2) comme une
évaluation du modèle : la sélection conditionne l'échantillon.

### (3) Simulation contrôlée — la seule où la probabilité vraie est connue

Des données générées depuis un processus connu permettent une **étude de
couverture** : un intervalle nominal à 90 % couvre-t-il ~90 % du temps ? C'est le
seul cadre où la question se pose proprement, parce que la probabilité latente
d'un événement réel unique n'est **jamais** observable.

C'est ici que se juge une méthode d'incertitude candidate (D-019), avant tout
usage sur données réelles.

### (4) Données réelles — pas d'observation de la probabilité latente

Sur données réelles on mesure des **fréquences agrégées** par tranche
préspécifiée, jamais la probabilité d'un événement individuel. Toute formulation
du type « le modèle avait raison sur ce match » est interdite dans les rapports.

### (5) Rendement — bootstrap clusterisé

Le bootstrap est **clusterisé par événement** au minimum, et par blocs temporels
si des événements corrélés se chevauchent. Un bootstrap IID par pari surestime la
précision dès que plusieurs marchés partagent un événement — ce qui est le cas
général ici, puisque tous les marchés d'un match viennent du même modèle.

## 2 ter. Éléments à préspécifier avant d'ouvrir le jeu de test

| Élément | À figer |
|---|---|
| Univers | sports, compétitions, marchés, période |
| Partitions temporelles | dates exactes de coupure |
| Bookmaker de référence | lequel, et pourquoi |
| Timestamp de décision | l'instant dont la cote est utilisée |
| Définition du CLV | quelle cote de clôture, chez qui, à quel instant |
| Suppression de marge | méthode, et son effet sur les métriques |
| Voids, demi-gains, demi-pertes | traitement exact dans le rendement |
| Données manquantes | exclusion ou imputation, décidé à l'avance |
| Seeds | pour tout tirage (bootstrap inclus) |
| Exclusions | critères, écrits avant |
| Multiplicité des tests | correction appliquée si plusieurs hypothèses |
| Puissance | analyse justifiant les seuils de volume minimal |

Un jeu n'est **« scellé »** qu'après fixation des sources, versions, dates, hashes
de fichiers et code de constitution. Sans cela, « scellé » est un mot, pas un fait.

## 3. Métriques

Toutes implémentées et testées dans `src/betmaxxing/evaluation/metrics.py`.

### Qualité probabiliste
- log loss
- score de Brier
- courbe de calibration et erreur de calibration attendue (ECE)
- précision par tranche de probabilité et par marché

### Couverture des intervalles

Mesurée **en simulation contrôlée** (niveau 3), où la probabilité vraie est
connue. Sur données réelles, on ne mesure que des fréquences agrégées.

> **Correction.** Le protocole initial présentait la couverture d'intervalles
> comme rendant « falsifiable » la constante `INFORMATION_PER_MATCH`. C'était
> insuffisant : un test de couverture peut rejeter une constante mal réglée, mais
> il ne transforme pas une quantité qui mesure la mauvaise chose en une quantité
> qui mesure la bonne. Voir D-019. La couverture reste le bon test — d'une
> méthode d'incertitude réelle, pas d'un facteur multiplicatif sur un intervalle
> binomial.

### Performance de paris
- rendement (yield) et nombre de paris
- drawdown maximal et variance
- intervalle de confiance bootstrap sur le rendement (**obligatoire** : un rendement
  publié sans intervalle est trompeur et n'est jamais affiché seul)
- closing line value lorsqu'elle est disponible

### Stabilité
Résultats ventilés par saison, compétition, plage de cote et type de marché. Un
rendement global positif porté par une seule compétition n'est pas un résultat.

---

## 4. Critères de promotion

Écrits ici avant le test. **Non modifiables après ouverture du jeu de test final.**

### `BACKTEST_ONLY` → `PAPER_VALIDATED`

Toutes les conditions doivent être remplies simultanément :

| Critère | Seuil |
|---|---|
| Volume minimal de paris qualifiés sur le test final | ≥ 200 |
| Log loss vs référence marché (implicite sans marge) | strictement meilleure |
| Score de Brier vs référence marché | strictement meilleur |
| Erreur de calibration attendue | ≤ 0,03 |
| Couverture empirique des intervalles à 90 % (simulation contrôlée) | dans `[0,85 ; 0,95]` |
| Méthode d'incertitude | statut `ESTIMATED` au minimum, jamais `SYNTHETIC` ni `UNAVAILABLE` |
| Borne basse de l'IC bootstrap 95 % du rendement (**clusterisé par événement**) | > 0 % |
| Stabilité | rendement non négatif sur ≥ 3 des 4 découpages |
| Fuite temporelle | aucune détectée à la relecture |

### `PAPER_VALIDATED` → `LIVE_ANALYSIS`

| Critère | Seuil |
|---|---|
| Durée de forward test en mode `paper` | ≥ 90 jours |
| Volume de paris qualifiés en forward test | ≥ 100 |
| Borne basse de l'IC bootstrap 95 % du rendement | > 0 % |
| Closing line value moyenne | > 0 % |
| Erreur de calibration en forward test | ≤ 0,04 |
| Écart rendement backtest vs forward | ≤ 5 points |

### En cas d'échec

L'échec est **affiché**, le modèle **reste** au statut expérimental, et le mode
`live_analysis` continue de refuser ses candidats via `MODEL_NOT_VALIDATED`. Aucun seuil
n'est ajusté après coup pour faire passer le critère.

---

## 5. Reproductibilité

Chaque exécution archive :

- l'empreinte de configuration (`Settings.fingerprint()`) ;
- la version du schéma de configuration ;
- les seuils exacts appliqués ;
- l'identifiant et la version du modèle ;
- les graines aléatoires (le bootstrap est explicitement graine ;
  `bootstrap_yield_interval(..., seed=...)`) ;
- la liste complète des candidats **acceptés et rejetés**, avec leurs codes ;
- les métriques obtenues.

Le document complet d'un scan est stocké dans `scan_runs.document`, ce qui permet de
rejouer une décision passée exactement.

---

## 6. Statut actuel

| Étape | État |
|---|---|
| 1. Entraînement chronologique | Non démarrée — aucune donnée historique intégrée |
| 2. Validation et choix des seuils | Non démarrée — seuils actuels **provisoires** |
| 3. Calibration | Non démarrée |
| 4. Test final scellé | **Non ouvert** |
| 5. Forward test `paper` | Non démarré |

### Statut de l'incertitude (D-019)

| Modèle | Méthode | Statut |
|---|---|---|
| `football-dixon-coles-v1` | aucune | `UNAVAILABLE` (`SYNTHETIC` en démo) |
| `tennis-elo-hierarchical-v1` | aucune | `UNAVAILABLE` (`SYNTHETIC` en démo) |

Conséquence directe : en `paper` et `live_analysis`, `ev_conservative` vaut `null`
et tout candidat est rejeté avec `UNCERTAINTY_UNAVAILABLE`. **Aucune donnée n'a
été testée** ; ce document décrit un protocole préspécifié, pas des résultats.

Les seuils par défaut (`min_ev = 0,03`, `max_prob_half_width = 0,08`, …) sont des points
de départ raisonnables, **pas** des valeurs validées. `GET /settings/thresholds` les
renvoie explicitement marqués `PROVISIONAL`.
