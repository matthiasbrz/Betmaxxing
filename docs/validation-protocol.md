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

## 3. Métriques

Toutes implémentées et testées dans `src/betmaxxing/evaluation/metrics.py`.

### Qualité probabiliste
- log loss
- score de Brier
- courbe de calibration et erreur de calibration attendue (ECE)
- précision par tranche de probabilité et par marché

### Couverture des intervalles
- **couverture empirique des intervalles** — un intervalle nominal à 90 % doit contenir
  la fréquence observée environ 90 % du temps.

  C'est le test qui rend falsifiable la constante `INFORMATION_PER_MATCH` de chaque
  modèle. Elle élargit ou resserre tous les intervalles, donc elle contrôle directement
  la sévérité du filtre d'EV prudente. Une valeur trop élevée resserre les intervalles,
  laisse passer des candidats mal déterminés, et se manifeste ici par une couverture
  nettement inférieure au nominal. Ce n'est pas un réglage de confort.

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
| Couverture empirique des intervalles à 90 % | dans `[0,85 ; 0,95]` |
| Borne basse de l'IC bootstrap 95 % du rendement | > 0 % |
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

Les seuils par défaut (`min_ev = 0,03`, `max_prob_half_width = 0,08`, …) sont des points
de départ raisonnables, **pas** des valeurs validées. `GET /settings/thresholds` les
renvoie explicitement marqués `PROVISIONAL`.
