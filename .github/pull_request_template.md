# Résumé

<!-- Ce que fait cette PR, et pourquoi. Deux ou trois phrases suffisent. -->

## Périmètre

**Inclus :**

**Explicitement exclu :**

<!-- Dire ce que la PR ne fait pas évite qu'un relecteur le cherche. -->

## Preuves de tests

<!-- Commandes réellement exécutées et leur résultat exact. Un test sauté est un
skip, pas un succès : dites-le. -->

```text
ruff check .                 →
ruff format --check .        →
mypy                         →
pytest -W error              →
python -m pytest -W error    →
pytest -W error -m postgres  →   (ou : skippé, aucun cluster local — la CI fait foi)
```

## Risques et retour arrière

<!-- Ce qui peut casser, et comment revenir. `sans objet` est une réponse valable
pour une PR de documentation. -->

## Schéma et migrations

- Migration ajoutée ou modifiée : `oui` / `non`
- Si oui : appliquée sur base vide, sur base peuplée, `downgrade` puis `upgrade`
  rejoués, et `alembic check` sans dérive :

<!-- `non` suffit quand rien ne touche au schéma. -->

## Modèles, incertitude et statuts

- Modèle touché : `oui` / `non`
- Calcul d'incertitude touché : `oui` / `non`
- Promotion de statut demandée : `oui` / `non` — si oui, joindre les critères écrits
  à l'avance et les preuves qui les satisfont

<!-- Les statuts par défaut restent : adaptateur IMPLEMENTED_UNVERIFIED,
modèles BACKTEST_ONLY, incertitude UNAVAILABLE hors démo, Challenge PARTIAL
désactivé. Une PR qui n'y touche pas répond `non` partout. -->

## Appels fournisseur et coût

À remplir **même quand tout vaut zéro**. Écrivez `0` ou `sans objet` — ne cochez
rien qui serait faux.

| | |
| --- | --- |
| Appels fournisseur réels | |
| Endpoints appelés | |
| Nombre de tentatives | |
| Crédits estimés | |
| Crédits observés | |
| Crédits comptabilisés | |
| Autorisation d'activation reçue | `oui` / `non` / `sans objet` |

## Quatre décisions distinctes

Ouvrir cette PR, la voir verte, la passer en `ready for review` et la **fusionner**
sont **quatre décisions distinctes**, prises séparément :

| Décision | Qui, et sur quoi |
| --- | --- |
| **Ouvrir** la PR | l'auteur ; n'autorise rien d'autre |
| Les checks **verts** | la CI ; un constat, pas une permission |
| Passer en `ready for review` | le propriétaire, explicitement — une PR reste **brouillon** tant qu'il ne l'a pas demandé |
| **Fusionner** | le propriétaire, par une **autorisation explicite** et séparée |

Une PR verte n'est donc pas une PR relue, et une PR relue n'est pas une PR
autorisée à fusionner. Fermer la PR et supprimer sa branche sont encore deux
décisions de plus.

## Checklist

Cochez ce que vous avez réellement fait. Une case cochée est une **déclaration de
l'auteur**, pas une preuve : elle ne remplace ni les checks, ni la relecture du
diff.

- [ ] Aucun secret, clé, jeton ni mot de passe dans le diff
- [ ] `.env.example` ne contient que des noms de variables et des valeurs vides
- [ ] Aucun payload fournisseur brut ni reçu d'activation versionné
- [ ] Tests exécutés localement, résultats reportés tels quels, skips signalés
- [ ] Documentation mise à jour si le comportement change
- [ ] Compatibilité des migrations vérifiée, ou `sans objet`
- [ ] Aucune promotion de modèle ou d'adaptateur non autorisée
- [ ] Aucun `skip`, `xfail`, filtre d'avertissement ni exception de couverture
      ajouté pour obtenir du vert
- [ ] Je comprends que **l'ouverture de cette PR n'autorise pas sa fusion** :
      les checks `quality` et `secrets` doivent passer, les conversations être
      résolues, le passage en `ready for review` être demandé par le
      propriétaire, et la fusion exige son autorisation explicite

<!-- Si une case ne s'applique pas, laissez-la décochée et écrivez `sans objet` à
côté. Une case cochée à tort est pire qu'une case vide. -->
