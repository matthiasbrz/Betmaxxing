# Model cards

Les deux modèles sont au statut **`BACKTEST_ONLY`**. Aucun n'a été validé hors
échantillon. Le mode `live_analysis` refuse structurellement leurs candidats.

> **Méthode d'incertitude : aucune (`UNAVAILABLE`).**
>
> Ni l'un ni l'autre ne sait produire une incertitude défendable sur sa
> probabilité. Conséquence, hors mode démo : `ev_conservative` vaut `null` et
> tout candidat est rejeté avec `UNCERTAINTY_UNAVAILABLE`.
>
> En mode démo, une incertitude **synthétique** étiquetée
> `SYNTHETIC — NE PAS PARIER` est produite pour exercer l'interface. Elle ne
> constitue pas une estimation de précision et ne peut pas atteindre `paper` ni
> `live_analysis`. Voir D-019.

---

## `football-dixon-coles-v1`

**Sport :** football · **Marchés :** 1X2, draw no bet, double chance, total de buts
(temps réglementaire et première mi-temps).

### Formulation

```
buts_domicile ~ Poisson(λ_dom)
buts_extérieur ~ Poisson(λ_ext)
P(x, y) = τ(x, y; ρ) · Poisson(x; λ_dom) · Poisson(y; λ_ext)
```

`τ` est la correction Dixon-Coles appliquée aux quatre cases 0-0, 1-0, 0-1 et 1-1. Elle
corrige la sous-estimation documentée des matchs nuls à faible score par un Poisson
indépendant.

Tous les marchés sont dérivés de la **même matrice de scores**, donc ils sont
mutuellement cohérents par construction : `P(1) + P(N) + P(2) = 1`, et le prix DNB
implicite du modèle est exactement le 1X2 conditionné.

### Entrées

Forces attaque/défense, moyenne de buts de la ligue, avantage domicile, `ρ`. Elles sont
**fournies** au modèle : l'ajustement appartient au pipeline d'entraînement (tranche 4),
pas à cette classe. La séparation garantit que backtest et production appliquent
exactement la même transformation paramètres → probabilités.

### Hypothèses et limites

| Point | Statut |
|---|---|
| Indépendance des buts hors bloc bas score | Hypothèse du modèle, non vérifiée |
| `FIRST_HALF_GOAL_SHARE = 0.45` | **Constante provisoire**, non ajustée |
| Mi-temps | Dérivée d'un partage fixe — approximation, signalée dans les diagnostics |
| Absences / compositions | **Non utilisées** (indisponibles historiquement) |
| xG | Non utilisé (licence non vérifiée) |
| Troncature à 15 buts | Masse négligeable, matrice renormalisée |

Les marchés mi-temps reçoivent une taille d'échantillon effective divisée par deux et une
complétude réduite : ils reposent sur une constante, pas sur un paramètre ajusté.

### `SYNTHETIC_INFORMATION_PER_MATCH = 2.5` — démo uniquement

Anciennement `INFORMATION_PER_MATCH`, présentée comme une incertitude de modèle.
Elle ne l'était pas : un intervalle de Wilson décrit une proportion binomiale
observée et ne propage ni l'erreur d'estimation des paramètres, ni la calibration,
ni les dépendances. Voir D-019.

Cette constante ne sert plus qu'à donner à la sortie de démonstration la bonne
*forme*. Elle n'a **aucun effet** hors mode démo.

### Marchés avec remboursement

Le draw-no-bet expose désormais la probabilité de nul comme **push** explicite, et
l'EV vient de la distribution de règlement. La forme conditionnelle précédente
surestimait la magnitude de l'EV de `1/(1 − p_nul)`.

---

## `tennis-elo-hierarchical-v1`

**Sport :** tennis · **Marchés :** vainqueur du match, joueur gagnant au moins un set,
total de jeux (temps réglementaire uniquement).

### Formulation

Un unique jeu de paramètres — les probabilités de gagner un point au service pour chaque
joueur — d'où tout est dérivé par énumération exacte :

```
point → jeu → tie-break → set (avec sa distribution de jeux) → match
```

La calibration remonte la chaîne : l'Elo par surface donne une probabilité de victoire
cible, et une bissection trouve l'écart de service `δ` autour d'une base de surface tel
que la chaîne reproduise cette cible. Tous les autres marchés en découlent, donc ils ne
peuvent pas contredire le vainqueur du match.

### Vérifications

| Propriété | Vérification |
|---|---|
| Formule du jeu | Comparée à une énumération DP indépendante, égalité à 1e-12 |
| Tie-break | DP validé par simulation Monte-Carlo |
| Joueurs égaux | `P(match) = 0,5` et `P(≥ 1 set) = 0,75` exactement (bo3) |
| Équité du tie-break | Le résultat ne dépend pas de qui sert en premier (1-2-2) |
| Calibration | Reproduit la cible à ±2e-3 |

### Hypothèses et limites

| Point | Statut |
|---|---|
| Points indépendants et identiquement distribués | Hypothèse forte : ignore momentum et fatigue intra-match |
| Bases de service par surface | **Constantes provisoires** (`SERVE_BASELINE_BY_SURFACE`) |
| Abandon, forfait, blessure | **Non modélisés** — règlement selon les règles du bookmaker, signalé dans les diagnostics et les risques |
| Fatigue, repos, voyages | Non modélisés |
| Format | Best-of-3 et best-of-5 ; super tie-break décisif non implémenté |
| Face-à-face | Non utilisé — échantillons trop faibles pour être informatifs |

Le point le plus important : le modèle **ne prédit pas les abandons**. Un abandon change
le règlement selon des règles propres à chaque bookmaker, et inventer une probabilité
serait exactement ce que ce projet interdit. C'est déclaré, pas dissimulé.

### `SYNTHETIC_INFORMATION_PER_MATCH = 3.0` — démo uniquement

Même statut que côté football : superseded par D-019, sans effet hors démo.

---

## Ce qui vaut pour les deux

- Aucune probabilité n'est retournée sans taille d'échantillon effective.
- Un modèle qui ne sait pas pricer retourne `None` → `NO_MODEL_AVAILABLE`. Il ne devine
  jamais pour éviter un résultat vide.
- Les diagnostics (λ, Elo utilisés, probabilités de service, jeux attendus) sont exposés
  et cités comme éléments sourcés dans l'explication.
- Chaque candidat porte `model_id`, `model_version` et le statut **lu depuis le
  registre** — plus aucune valeur codée en dur.
- La complétude des features réduit la taille d'échantillon effective de façon
  quadratique : une entrée partielle pèse plus lourd qu'une remise linéaire.
