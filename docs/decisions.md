# Journal des décisions

Chaque entrée : la décision, la raison, et ce qu'elle coûte.

---

### D-001 — Monolithe modulaire, pas de microservices

**Décision.** Un paquet Python unique, plus un processus de planification séparé.
**Raison.** Le périmètre (un utilisateur, deux sports, fenêtre 24 h) ne justifie ni Redis,
ni file distribuée, ni Kubernetes. Chaque composant ajouté est un composant à exploiter.
**Coût.** Montée en charge horizontale non immédiate. Acceptable ici.

### D-002 — Le planificateur est un processus distinct

**Décision.** `scheduler/runner.py` tourne seul, avec verrou et clés d'idempotence.
**Raison.** Un serveur web à N workers exécuterait chaque tâche N fois.
**Coût.** Un processus de plus à superviser.

### D-003 — Snapshots de cotes immuables et append-only

**Décision.** `frozen=True`, `fingerprint` UNIQUE, aucune méthode de mise à jour.
**Raison.** Un prix observé à un instant est un fait historique. C'est la condition d'un
backtest honnête et d'une ingestion idempotente.
**Coût.** Volume de stockage supérieur.

### D-004 — Winamax : import manuel, pas de scraping

**Décision.** Statut `Winamax indisponible` ; voie officielle = import CSV horodaté.
**Raison.** Aucune API publique autorisée identifiée. Contourner une protection ou
rétro-concevoir une API privée est exclu par les principes du projet.
**Coût.** Pas de cotes Winamax en temps réel. Assumé et affiché, jamais compensé par une
substitution silencieuse.

### D-005 — Shin par défaut pour le retrait de marge

**Décision.** `shin`, avec `multiplicative`, `additive` et `power` disponibles.
**Raison.** Shin se comporte mieux sur les books à 2 et 3 issues et traite le biais
favori-outsider, que la méthode proportionnelle ignore.
**Coût.** Résolution numérique (bissection) plutôt que formule fermée. Négligeable.
**Note.** Les quatre méthodes donnent des réponses différentes sur un book déséquilibré —
un test le vérifie. C'est pourquoi la méthode est enregistrée sur chaque candidat.

### D-006 — Refus des lignes entières en over/under

**Décision.** O/U 3.0 est mis en quarantaine ; seules les demi-lignes sont pricées.
**Raison.** Une ligne entière peut être remboursée : c'est un pari différent, et le
pricer comme un pari décisif serait une approximation entre deux marchés distincts.
**Coût.** Couverture de marché réduite.

### D-007 — Intervalle de Wilson plutôt qu'approximation normale

**Décision.** Wilson, sans dépendance SciPy.
**Raison.** L'approximation normale retourne des bornes négatives pour de petits `n` ou
des probabilités extrêmes. Wilson reste dans (0, 1), ce dont dépend l'arithmétique d'EV.
**Coût.** Aucun.

### D-008 — `INFORMATION_PER_MATCH` explicite et falsifiable

**Décision.** Constante nommée par modèle (football 2,5 ; tennis 3,0), documentée.
**Raison.** Traiter chaque match comme un tirage de Bernoulli surestime l'incertitude
d'un modèle paramétrique mutualisé : les intervalles deviennent si larges que le filtre
d'EV prudente ne laisse passer que des avantages irréalistes à deux chiffres.
**Coût.** C'est un paramètre qui **desserre** un filtre de sécurité — donc dangereux s'il
est réglé au doigt mouillé.
**Contrepartie.** Le protocole le teste par couverture d'intervalles : une valeur trop
haute produit une couverture inférieure au nominal et est détectée. C'est une affirmation
réfutable, pas un bouton de confort.

### D-009 — Grille d'éligibilité conjonctive

**Décision.** Tous les filtres doivent passer simultanément ; tous les échecs sont
retournés, pas seulement le premier.
**Raison.** Un score composite permettrait à une EV élevée de racheter une cote périmée.
C'est exactement ainsi qu'un faux avantage se publie.
**Coût.** Beaucoup de rejets. C'est le comportement voulu.

### D-010 — Marchés dérivés issus d'un objet unique

**Décision.** Football : une matrice de scores. Tennis : les probabilités de point au
service.
**Raison.** Des marchés pricés indépendamment se contredisent, et la contradiction est
précisément là où apparaît un avantage illusoire.
**Coût.** Moins de liberté de modélisation par marché.

### D-011 — Pas de martingale, structurellement

**Décision.** `Challenge.next_stake_cents()` ne lit que la banque courante ;
`compute_stake()` n'accepte aucun paramètre d'historique de résultats.
**Raison.** Une interdiction respectée par convention finit par être contournée. Une mise
de récupération doit être **inexprimable**.
**Coût.** Aucun. Un test verrouille la signature de `compute_stake`.

### D-012 — Argent en centimes entiers dans le Challenge

**Décision.** Arithmétique interne en centimes, arrondi au demi supérieur.
**Raison.** Les flottants perdent de la valeur au fil d'une progression multiplicative.
**Coût.** Conversions aux frontières.

### D-013 — Rendement toujours accompagné d'un intervalle bootstrap

**Décision.** `bootstrap_yield_interval` est graine et obligatoire à l'affichage.
**Raison.** Un rendement sans intervalle est le chiffre le plus trompeur de l'analyse de
paris. Dix paris ne distinguent pas une bonne stratégie d'une série chanceuse.
**Coût.** Calcul supplémentaire, négligeable.

### D-014 — Datetime naïf rejeté, jamais interprété

**Décision.** `ensure_utc()` lève sur un datetime sans fuseau.
**Raison.** Supposer un fuseau est une invention de donnée, au même titre qu'inventer une
cote.
**Coût.** Les entrées doivent porter un décalage explicite. C'est le but.

### D-015 — Fenêtre de scan en durée absolue

**Décision.** 24 heures absolues, pas un jour calendaire.
**Raison.** Un jour parisien fait 23 ou 25 heures aux changements d'heure. La fenêtre non.
**Coût.** Le nombre d'heures locales couvertes varie ces jours-là — testé explicitement.

### D-016 — Modèles livrés en `BACKTEST_ONLY`

**Décision.** Le registre bloque la publication en `live_analysis`.
**Raison.** Un modèle non validé ne doit pas pouvoir atteindre le tableau de bord, quelle
que soit la qualité apparente de ses chiffres.
**Coût.** Le mode `live_analysis` ne produit rien aujourd'hui. C'est correct.

### D-017 — Flush explicite avant l'écriture des enfants d'un scan

**Décision.** `ScanRepository.save()` appelle `flush()` après l'insertion du scan.
**Raison.** Les tables sont liées par de simples colonnes `ForeignKey`, sans `relationship`
ORM. SQLAlchemy n'a alors aucune dépendance à trier et ordonne les mappers par nom :
`candidates` et `rejections` passent avant `scan_runs`, ce qui viole la contrainte.
Découvert par un test, pas en production.
**Coût.** Un aller-retour supplémentaire.

### D-018 — Interface web reportée

**Décision.** CLI et API d'abord ; React/Vite en tranche 6.
**Raison.** La valeur du produit est dans la correction du moteur. Une interface sur un
moteur non testé aurait été une démonstration, pas un outil.
**Coût.** Pas de tableau de bord graphique aujourd'hui. La CLI rend des fiches denses et
l'API expose tout en JSON/CSV.
