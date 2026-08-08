# Politique de sécurité

Dépôt public, projet personnel, un seul mainteneur. Cette politique dit ce qui est
supporté, comment signaler, et surtout quoi faire dans les premières minutes d'une
clé exposée — parce que c'est déjà arrivé deux fois ici.

## Périmètre supporté

| | |
| --- | --- |
| Supporté | l'état courant de la branche par défaut `claude/prompt-markdown-file-wag9jw` |
| Non supporté | tout commit antérieur, tout clone, tout fork, toute copie locale |

Il n'y a **pas** de support implicite d'une version antérieure. L'historique de ce
dépôt a déjà été réécrit pour retirer des identifiants ; les anciens SHAs ne sont
donc pas des références de travail valides, et un clone ancien peut contenir des
objets qui ne sont plus atteignables ici.

Aucune version n'est distribuée sous forme de paquet ou de release : il n'y a rien
à mettre à jour ailleurs que par un clone neuf.

## Signaler un problème

Utilisez le **Private Vulnerability Reporting** de GitHub s'il est activé sur ce
dépôt (onglet *Security* → *Report a vulnerability*). À défaut, passez par un canal
privé déjà établi avec le propriétaire du dépôt.

**N'ouvrez jamais une issue publique, une pull request ou un commentaire contenant
un secret**, même partiellement masqué, même « expiré ». Un dépôt public est
indexable, et un commentaire supprimé reste souvent récupérable.

Aucune adresse de contact n'est publiée ici volontairement : ce dépôt n'expose pas
de coordonnées personnelles.

## Trois choses différentes, à ne pas confondre

1. **Vulnérabilité du produit** — un défaut du code : injection, contournement d'un
   garde, fuite par une sortie, dépendance vulnérable. Signalement privé.
2. **Incident de credential** — une clé, un jeton ou un secret exposé. La procédure
   ci-dessous s'applique **avant** toute discussion technique.
3. **Problème de données sportives** — une cote fausse, un événement mal
   rapproché, une statistique douteuse, un mapping erroné. Ce n'est pas une faille
   de sécurité : cela se traite comme un bug de données, publiquement, sans
   urgence particulière — mais ne collez pas de payload fournisseur brut, qui peut
   être soumis à des conditions d'utilisation.

## Procédure en cas de clé exposée

Dans cet ordre. Le premier point n'attend pas les autres.

1. **Révoquer ou faire tourner la clé chez le fournisseur.** Immédiatement, avant
   tout nettoyage, avant tout diagnostic, avant d'ouvrir un fichier. C'est la seule
   action qui rend la valeur exposée inoffensive.
2. **Ne pas afficher la valeur.** Ni en entier, ni un fragment, ni un préfixe ou un
   suffixe, ni sa longueur, ni son empreinte, ni une estimation d'entropie. Ces
   dérivés n'aident pas à corriger et aggravent la diffusion.
3. **Ne conserver que des preuves assainies** : un chemin, un numéro de ligne, un
   nom de variable, un compteur. Assez pour corriger, pas assez pour fuiter. Si un
   outil doit lire un journal, il doit d'abord le rédiger, valider la rédaction,
   puis détruire l'original avant lecture.
4. **Auditer les surfaces où la valeur a pu se propager**, pas seulement le fichier
   d'origine :
   - l'historique Git atteignable — une valeur vidée par un commit ultérieur
     survit dans le blob que pointe le premier commit ;
   - les exécutions GitHub Actions, leurs journaux et leurs artefacts — un garde
     qui imprime la ligne fautive recopie le secret dans un journal dont la
     rétention et les droits d'accès diffèrent de ceux du dépôt ;
   - les forks, les clones et les caches de la forge ;
   - les scrollbacks de terminal et les captures.
5. **Nettoyer les références** : vider la valeur dans les fichiers suivis, puis
   réécrire l'historique si nécessaire, avec `--force-with-lease` et jamais
   `--force` seul.

### Ce que le nettoyage ne fait pas

**Vider un fichier ou réécrire l'historique ne rend pas une clé valide sûre.**
Cela ne suffit pas, et ce n'est pas la remédiation :

- la valeur reste dans tout clone et tout fork existants ;
- elle peut rester accessible par SHA dans les caches de la forge, pour une durée
  que le mainteneur ne contrôle pas et ne peut pas vérifier ;
- elle peut subsister dans un journal d'exécution ou un artefact.

Ce que la réécriture accomplit : retirer l'objet des **références actives**. Ce qui
neutralise la valeur : la **révocation**. Les deux sont utiles ; une seule est
indispensable.

## Ce qui ne doit jamais être publié dans ce dépôt

- un secret réel, en clair ou encodé ;
- un exemple de clé « crédible » — un placeholder doit être manifestement
  impossible, pas juste inventé ;
- une URL authentifiée, une chaîne de requête portant une clé, un en-tête
  d'autorisation ;
- un extrait de payload fournisseur brut, ni un reçu d'activation ;
- une donnée personnelle.

Les fichiers de gouvernance eux-mêmes sont testés contre ces règles, dans
`tests/test_repository_governance.py`.

## Gardes en place

- `.env` est ignoré par Git et n'est jamais suivi ; `.env.example` ne contient que
  des noms de variables et des valeurs vides.
- `python -m betmaxxing.security.secret_hygiene` refuse toute variable secrète
  peuplée dans un fichier suivi, et ne reproduit jamais la valeur détectée.
- Un hook pre-commit applique le même garde **avant** que le commit existe.
- La CI le rejoue en filet de sécurité, sur l'arbre suivi et sur tous les blobs
  atteignables de l'historique.
- La branche par défaut est protégée par un ruleset : pas de push direct, deux
  checks requis, branche à jour, conversations résolues.
- La suite de tests bloque les connexions sortantes et efface les variables
  secrètes de l'environnement ambiant, pour qu'un échec de test ne puisse pas
  imprimer une clé réelle.

Aucun de ces gardes ne remplace la rotation. Ils réduisent la probabilité d'une
exposition ; ils ne réparent pas celle qui a eu lieu.
