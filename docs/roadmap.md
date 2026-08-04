# État et feuille de route

**Dernière mise à jour :** 2026-08-04 · **Version :** 0.2.0

---

## Terminé

### Tranche 1 — Audit, spécification, architecture, matrice des sources
- Dépôt audité (vide au départ, une seule branche, un commit initial).
- Architecture cible et décisions structurantes : `docs/architecture.md`, `docs/decisions.md`.
- Matrice des sources avec les points non vérifiables marqués `À vérifier` :
  `docs/source-matrix.md`.
- Protocole de validation préenregistré : `docs/validation-protocol.md`.
- Dictionnaire de données : `docs/data-dictionary.md`.

### Tranche 2 — Squelette exécutable, mode démo, scan de bout en bout
- Configuration centralisée, versionnée, avec empreinte reproductible et masquage des
  secrets.
- Couche domaine : vocabulaires fermés, entités immuables, identifiants canoniques,
  règles de temps UTC/Paris.
- Interfaces fournisseurs + pack de démonstration déterministe et sans clé.
- Ingestion : déduplication, assemblage des books, quarantaine.
- Moteur : 4 méthodes de retrait de marge, EV, EV prudente, cote minimale, sensibilité,
  incertitude de Wilson, qualité des données, confiance explicable, mise fractionnelle
  plafonnée, grille d'éligibilité conjonctive, explication déterministe sourcée.
- Baselines football (Dixon-Coles) et tennis (Elo → modèle hiérarchique de points), avec
  marchés dérivés cohérents.
- Persistance : schéma, snapshots append-only, ingestion idempotente, archivage des scans.
- CLI (`scan`, `explain`, `providers`, `config`, `odds import`, `db …`).
- API FastAPI avec OpenAPI exploitable, export JSON et CSV.
- Import manuel horodaté (voie Winamax).
- Challenge — Montante complet, désactivé par défaut.
- Planificateur (planification pure + exécution, verrou, idempotence).
- Métriques d'évaluation du protocole.
- **474 tests**, ruff et mypy propres, CI configurée.

---

## Non fait — et pourquoi

| Élément | Raison |
|---|---|
| Adaptateur de fournisseur de cotes réel | Conditions d'utilisation non vérifiables hors ligne ; l'interface est prête |
| Pipeline d'entraînement | Nécessite des données historiques ; les modèles consomment des paramètres fournis |
| Exécution du protocole de validation | Nécessite l'historique ; le protocole est figé et prêt |
| Interface web React/Vite | Tranche 6 ; CLI et API couvrent les usages actuels |
| Persistance des challenges | Tables créées, dépôt non câblé (état en mémoire dans l'API) |
| SMS | Interface seulement — coût par message, activation délibérée requise |

---

## Blocages

1. **Aucun fournisseur de cotes réel n'est utilisable** sans lire et accepter des
   conditions d'utilisation, ce qui demande une décision de l'utilisateur (et
   potentiellement un compte payant — non créé, conformément aux consignes).
2. **Aucune donnée historique** : le protocole de validation ne peut pas être exécuté,
   donc aucun modèle ne peut sortir de `BACKTEST_ONLY`.

Ces deux blocages sont externes. Tout ce qui n'en dépend pas a été implémenté.

---

## Prochaine action recommandée

**Tranche 3 — ingestion réelle.** Dans l'ordre :

1. Choisir un fournisseur de cotes, lire ses CGU, compléter `docs/source-matrix.md` avec
   des faits vérifiés.
2. Implémenter l'adaptateur derrière `OddsProvider`, avec retries, backoff, limitation de
   débit, circuit breaker et suivi de quotas.
3. Écrire des tests contractuels sur fixtures enregistrées (aucun appel réseau en CI).
4. Mesurer la fraîcheur réelle et ajuster `max_odds_age_seconds` sur cette mesure.

En parallèle, sans dépendance externe : persister les challenges, et démarrer l'interface
web sur l'API existante.

---

## Suite des tranches

| # | Tranche | État |
|---|---|---|
| 1 | Audit, spécification, architecture, matrice | ✅ |
| 2 | Squelette, mode démo, scan de bout en bout | ✅ |
| 3 | Ingestion réelle, snapshots immuables | ⛔ bloquée (choix de fournisseur) |
| 4 | Baseline football, backtest, calibration | ⛔ bloquée (données historiques) |
| 5 | Baseline tennis, marchés dérivés | ✅ modèle fait ; validation bloquée |
| 6 | Éligibilité, explications, dashboard | ◐ moteur fait ; dashboard à faire |
| 7 | Scheduler et notifications | ✅ implémentés ; à éprouver en exploitation |
| 8 | Challenge — Montante | ✅ |
| 9 | Durcissement, CI, sauvegarde, déploiement | ◐ CI et guides faits |
| 10 | Forward test `paper` | ⛔ bloquée (tranches 3 et 4) |
