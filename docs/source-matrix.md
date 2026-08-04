# Matrice des sources de données

> **Statut : préliminaire.** Cette session a été conduite sans accès aux documentations
> et conditions d'utilisation en vigueur des fournisseurs. Chaque point non vérifiable
> est marqué **`À vérifier`** plutôt que renseigné de mémoire. Aucune caractéristique de
> fournisseur n'est inventée ici.

## Règle de sélection

Une source n'est retenue que si **toutes** ces conditions sont satisfaites :

1. l'accès est prévu et autorisé par ses conditions d'utilisation ;
2. le stockage des données récupérées est autorisé pour l'usage envisagé ;
3. l'accès ne nécessite ni contournement de protection, ni rétro-ingénierie d'API
   privée, ni scraping interdit ;
4. les identifiants d'événements et de participants permettent un rapprochement fiable ;
5. la fraîcheur réelle est mesurable et suffisante pour la fenêtre visée.

Une source qui échoue au point 3 est écartée définitivement, quelle que soit sa qualité.

## Priorité des cotes

1. **Winamax**, si et seulement si une voie autorisée et fiable existe.
2. Sinon, un fournisseur configuré, **avec le nom du bookmaker affiché explicitement**.
3. À défaut, **import manuel horodaté**, clairement étiqueté comme tel.

Une cote n'est jamais mélangée avec les règles de règlement d'un autre bookmaker. Chaque
snapshot conserve bookmaker, marché, période, ligne, devise et horodatages.

---

## Winamax

| Critère | État |
|---|---|
| API publique documentée | **Aucune identifiée.** Statut retenu : `Winamax indisponible`. |
| Conditions d'utilisation | `À vérifier` — à lire avant tout accès automatisé. |
| Voie retenue en V1 | **Import manuel horodaté** (`betmaxxing odds import`). |
| Scraping / API privée | **Exclu.** Non implémenté, non prévu. |

C'est une limite assumée, pas un contournement à trouver. Le moteur fonctionne
intégralement sur un import manuel, ce qui permet de tester la chaîne complète avec de
vraies cotes relevées à la main sans franchir la ligne.

**Conséquence pratique :** sans flux temps réel, la fraîcheur d'un import manuel se
dégrade vite. Le seuil `max_odds_age_seconds` (900 s par défaut) rejettera un import
vieux de plus de quinze minutes — c'est voulu.

---

## Fournisseurs de cotes agrégés

Aucun adaptateur n'est implémenté. L'interface `OddsProvider` est prête à en recevoir un.

| Critère à documenter avant intégration | État |
|---|---|
| Sports, compétitions et marchés couverts | `À vérifier` |
| Présence de Winamax parmi les books | `À vérifier` |
| Historique disponible et profondeur | `À vérifier` |
| Fréquence de mise à jour / fraîcheur réelle | `À vérifier` |
| Quotas, coût, clé requise | `À vérifier` |
| Licence, CGU, droit de stockage | `À vérifier` |
| Qualité des identifiants d'événements | `À vérifier` |
| Gestion résultats / reports / annulations / abandons | `À vérifier` |
| Limites connues | `À vérifier` |

Aucun compte payant n'a été créé et aucun achat n'a été effectué.

---

## Données sportives et statistiques

| Critère | État |
|---|---|
| Calendriers et résultats football | `À vérifier` |
| xG (disponibilité **et** licence) | `À vérifier` — sans licence claire, non utilisé |
| Historique ATP/WTA, surfaces, formats | `À vérifier` |
| Statistiques service/retour tennis | `À vérifier` |
| Compositions et absences, structurées et horodatées | `À vérifier` |

**Règle sur les absences et compositions :** elles ne sont intégrées au modèle que si
elles sont structurées, horodatées **et disponibles historiquement**. Une donnée
disponible aujourd'hui mais absente de l'historique ne peut pas entrer dans un modèle
sans créer une fuite temporelle — elle ne serait pas backtestable.

---

## Contexte (blessures, forfaits)

`ContextProvider` ne retourne que des éléments portant **une source et une date**. Un
élément sans provenance n'est pas retourné du tout : il ne peut ni être cité dans une
explication, ni influencer une décision.

En V1 seul le fournisseur de démonstration est implémenté.

---

## Ce qui est implémenté aujourd'hui

| Adaptateur | Type | État |
|---|---|---|
| `demo` | odds, context, results | Opérationnel, **synthétique**, déterministe, sans clé |
| `manual_csv` | odds | Opérationnel, horodaté, quarantaine des lignes invalides |
| Telegram | notification | Implémenté, inactif sans configuration explicite |
| E-mail (SMTP) | notification | Implémenté, inactif sans configuration explicite |
| SMS | notification | Interface seulement — coût par message, jamais actif en V1 |

---

## Prochaine action

Avant d'intégrer un fournisseur réel :

1. lire ses conditions d'utilisation et vérifier le droit de stockage ;
2. remplir cette matrice avec des faits vérifiés, pas des suppositions ;
3. implémenter l'adaptateur derrière `OddsProvider` ;
4. écrire des tests contractuels sur fixtures enregistrées ;
5. mesurer la fraîcheur réelle avant de fixer `max_odds_age_seconds`.
