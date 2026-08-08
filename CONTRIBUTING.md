# Contribuer à Betmaxxing

## Ce qu'est ce projet, et ce qu'il n'est pas

Betmaxxing est un moteur d'**aide à la décision** pour l'analyse de valeur sur des
paris sportifs prématch, à usage personnel. Il calcule, explique et trace.

Il ne place aucun pari, n'en placera pas, et n'expose aucune interface capable de
le faire. Il ne promet aucun gain : une espérance positive estimée est une
estimation, assortie d'une incertitude et d'un statut de modèle, pas une
prédiction. Toute contribution qui suggérerait le contraire — dans le code, un
message d'interface ou la documentation — sera refusée.

Le jeu d'argent expose à un risque de perte et d'addiction. Les avertissements et
les garde-fous du dépôt (mode démo par défaut, mises désactivées, `staking_enabled`
à `false`, plafonds de bankroll) ne sont pas décoratifs : ne les contournez pas,
ne les affaiblissez pas pour faire passer un test.

## Installation

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,postgres]" -c constraints.txt
pip install pre-commit && pre-commit install
```

`constraints.txt` fige la résolution : installez avec, sinon vous ne testez pas la
même chose que la CI. `pre-commit install` est à faire **une fois par clone** ; il
active le garde anti-secret avant que le commit existe.

## Commandes de qualité

Ce sont celles que la CI exécute, dans `.github/workflows/ci.yml`. Ce fichier est
l'autorité ; s'il change, cette section est périmée et doit être corrigée.

```bash
ruff check .                                     # lint, migrations incluses
ruff format --check .                            # format
mypy                                             # typage
pytest -W error --cov=betmaxxing --cov-report=term-missing
python -m pytest -W error -q                     # l'autre invocation, pas la même résolution d'imports
python -m betmaxxing.security.secret_hygiene     # garde anti-secret sur les fichiers suivis
betmaxxing scan --json                           # scan de démo, de bout en bout
```

Les avertissements sont fatals (`filterwarnings = ["error"]` dans `pyproject.toml`).
N'ajoutez ni filtre, ni `skip`, ni `xfail` pour contourner un avertissement : la
seule issue acceptable est de le résoudre.

### Tests PostgreSQL

La suite de concurrence a besoin d'un vrai cluster ; SQLite sérialise tous les
écrivains et ne peut pas distinguer un algorithme atomique d'un algorithme
seulement chanceux.

```bash
export BETMAXXING_TEST_POSTGRES_URL=postgresql+psycopg://user@localhost:5432/betmaxxing_test
pytest -W error -m postgres -rs
```

Sans cette variable, ces tests **skippent bruyamment**. Un test sauté ne prouve
rien : ne présentez jamais un skip comme un succès. La CI fait foi.

## Le flux obligatoire : branche de travail, puis pull request

La branche par défaut `claude/prompt-markdown-file-wag9jw` est **protégée** par un
ruleset. Le **push direct y est interdit**, y compris pour le propriétaire et pour
un administrateur. N'essayez pas — pas même pour vérifier que la protection
fonctionne.

```text
partir d'un clone à jour de la branche par défaut
→ créer une branche de travail dédiée
→ développer et tester dessus
→ commit(s) intentionnels
→ push sur la branche de travail uniquement
→ ouvrir une pull request vers claude/prompt-markdown-file-wag9jw
→ attendre les checks quality et secrets
→ mettre la branche source à jour si GitHub l'exige
→ résoudre toutes les conversations
→ fusionner, et seulement après autorisation explicite du propriétaire
```

Avant fusion, le ruleset de la branche par défaut est **configuré**, d'après
l'**attestation du propriétaire**, pour exiger :

- les deux checks requis en succès : **`quality`** et **`secrets`** ;
- la branche source **à jour** avec la branche cible (mode strict) ;
- toutes les **conversations résolues**.

Ce qui est **observé** et ce qui est **attesté** ne se recouvre pas, et la nuance
est utile le jour où une fusion est refusée sans explication. Voici la chronologie
probatoire exacte, sans l'arrondir :

1. **Observé, mais ailleurs et avant.** Un push vers une **branche de travail** a
   été refusé par le ruleset avec
   `GH013 — 2 of 2 required status checks are expected`. Cela établit qu'un
   ruleset attendait alors **deux** checks sur *cette* référence.
2. **Ce que ce message ne dit pas.** Il donne un **compte**, pas des noms : il
   **ne nomme** ni `quality` ni `secrets`. Et il précède le **reciblage** du
   ruleset sur la seule branche par défaut — la configuration a changé après
   l'observation, qui ne décrit donc pas l'état actuel.
3. **Observé, sur cette PR.** L'état de la pull request #1 est passé de `blocked`
   pendant l'exécution des deux jobs à `clean` après leur succès.
4. **Ce que valent ces deux observations.** Elles sont **comportementales** :
   elles disent ce que GitHub a *fait*, pas ce que sa configuration *déclare*.
   Elles sont **compatibles** avec l'application de checks requis, mais elles
   **ne prouvent pas** à elles seules la causalité ni la configuration exacte —
   d'autres conditions peuvent produire l'état `blocked`.
5. **Attesté, non relu.** Que le ruleset actuel de la branche par défaut exige
   précisément **`quality`** et **`secrets`**, en **mode strict**, avec les
   **conversations résolues**, repose sur l'**attestation du propriétaire** : les
   endpoints REST de protection de branche et de rulesets répondent `403` dans cet
   environnement, y compris sur un endpoint de contrôle, donc la configuration
   détaillée n'est pas lisible ici.

Cette distinction ne change **rien** à ce que vous devez faire. La politique du
dépôt exige la branche de travail, la pull request, `quality` et `secrets` verts,
la branche à jour, les conversations résolues et l'autorisation de fusion — que
GitHub les impose techniquement ou non. Ce qui précède dit seulement ce qui a été
vu et ce qui est déclaré.

Deux points qu'on confond souvent :

- **ouvrir** une PR, la passer en *ready for review*, la **fusionner**, la fermer et
  supprimer sa branche sont **cinq actions distinctes**. Une autorisation d'ouvrir
  n'autorise pas à fusionner.
- une PR verte n'est pas une autorisation de fusion. La fusion demande
  l'**autorisation explicite du propriétaire**, formulée séparément.

Une consigne de « correction et push » désigne un push vers une **branche de
travail**, jamais vers la branche par défaut.

## Secrets

**La règle, en une phrase :** `.env.example` ne contient que des **noms** de
variables et des valeurs **vides** ; les valeurs réelles vivent dans `.env`, qui
est ignoré par Git, ou dans un gestionnaire de secrets.

- ne jamais committer de clé, de jeton, de mot de passe ni de secret HMAC ;
- ne jamais committer un reçu d'activation local ni un payload fournisseur
  brut : ce sont des fichiers locaux, ils ne sont pas des fixtures ;
- ne jamais coller une valeur de secret dans une issue, une PR, un commit, un
  test, un log ou un message ;
- ne jamais publier la valeur, un fragment, un préfixe, une longueur ni une
  empreinte d'un secret : un garde dont la sortie doit elle-même être expurgée n'a
  fait que déplacer la fuite ;
- pour les tests, utilisez des valeurs **synthétiques** explicites.

Le garde `python -m betmaxxing.security.secret_hygiene` applique ces règles, et la
CI le rejoue sur l'arbre suivi **et sur tous les blobs atteignables de
l'historique**. Un sommet propre ne prouve rien sur ce qui reste atteignable.

Si une valeur a déjà été poussée : voir `SECURITY.md`. La remédiation est la
**rotation chez le fournisseur** ; vider le fichier ne suffit pas.

## Appels fournisseur réels

Aucun appel à un fournisseur de cotes n'est fait par la CI, par la suite de tests
ou par le mode démo. La suite bloque activement les connexions sortantes.

Un appel réel — qui consomme des crédits — exige une **autorisation séparée et
explicite** pour chaque activation, et un **compte rendu de coût** : endpoints
appelés, nombre de tentatives, crédits estimés, observés et comptabilisés. Le
script d'exercice `scripts/smoke_the_odds_api.py` consomme des crédits réels ; il
reste opt-in et manuel, et la CI vérifie qu'il n'est jamais invoqué.

Déclarez ces chiffres dans la PR **même quand ils valent zéro**. « Zéro » est une
réponse ; le silence n'en est pas une.

## Migrations

Quand une migration change :

- vérifiez qu'elle s'applique à une **base vide** ;
- vérifiez qu'elle s'applique à une base **déjà peuplée**, depuis les révisions de
  référence que la CI exerce déjà ;
- vérifiez le **downgrade puis re-upgrade** quand la migration en propose un ;
- terminez par `alembic check`, qui doit ne détecter aucune dérive entre les
  modèles et les migrations.

Les migrations historiques sont figées : corrigez en ajoutant une révision, pas en
réécrivant une révision déjà publiée.

## Statuts, modèles et promotions

Les statuts du projet sont délibérément prudents et **ne se promeuvent pas
d'eux-mêmes** :

- adaptateur The Odds API : `IMPLEMENTED_UNVERIFIED` ;
- modèles : `BACKTEST_ONLY` ;
- incertitude : `UNAVAILABLE` hors mode démo ;
- Challenge : `PARTIAL`, désactivé.

Aucune promotion d'un modèle ou d'un adaptateur sans **critères écrits à l'avance**
et **preuves documentées** qui les satisfont. Un test vert n'est pas un critère de
promotion. Une activation réussie prouve la connectivité et le coût, pas la
qualité du mapping ni la fraîcheur des cotes.

## Ce qui fera refuser une contribution

- un push direct sur la branche par défaut, ou une tentative ;
- un secret, un reçu ou un payload brut versionné ;
- un `skip`, un `xfail`, un filtre d'avertissement ou une exception de couverture
  ajoutés pour obtenir du vert ;
- une assertion correcte modifiée pour accepter un comportement fautif ;
- une promotion de statut sans critères ni preuves ;
- un appel fournisseur sans autorisation ni compte rendu de coût.
