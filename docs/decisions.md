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

> **SUPERSÉDÉE PAR D-019.** Conservée telle quelle : le raisonnement qui y a
> mené fait partie du dossier. Ne plus s'y référer comme à une décision active.

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

---

### D-019 — Uncertainty is a statement with a status, superseding D-008

**Supersedes D-008.** That decision is left in place above, unedited, because
the reasoning that led to it is part of the record.

**What D-008 got wrong.** It multiplied the number of observed matches by an
`INFORMATION_PER_MATCH` constant, fed the product into a Wilson interval around
the model's probability, and used the result to gate real candidates through the
conservative-EV filter.

A Wilson interval describes sampling error in an **observed binomial
proportion**. A model probability is not one. The interval propagates none of
what actually makes a prediction uncertain: estimation error in the fitted
parameters, calibration error, the uncertainty of the calibrator itself,
dependence between markets on the same event, distribution shift, or structural
error from unmodelled effects. Calling the constant "falsifiable by coverage
testing" did not repair that — coverage testing can reject a badly chosen
constant, but it cannot turn a quantity that measures the wrong thing into one
that measures the right thing. And the original justification pointed at the
demo producing plausible-looking EVs, which is not evidence of anything.

**Decision.** Uncertainty becomes a first-class object carrying a status:

| Status | Meaning |
|---|---|
| `SYNTHETIC` | Deterministic placeholder, **demo only**, labelled "NE PAS PARIER" |
| `UNAVAILABLE` | No defensible method exists. `ev_conservative` is `null` |
| `ESTIMATED` | A real method ran; its coverage has not been studied |
| `VALIDATED` | Coverage checked by the executed protocol |

`lower`, `upper`, `effective_sample_size` and `ev_conservative` are all nullable.
In `paper` and `live_analysis` the status is `UNAVAILABLE` today, so candidates
are rejected with `UNCERTAINTY_UNAVAILABLE` — no configuration value changes
that. `wilson_interval` survives as a utility for genuine observed proportions
(calibration bins, hit rates), which is what it is actually for.

**Cost.** `paper` and `live_analysis` currently publish nothing. That is the
honest state, and it is preferable to publishing on a number that means nothing.

**What would lift it.** A parametric or clustered bootstrap propagating fitted
parameters through to market probabilities, plus calibrator uncertainty, plus a
pre-registered one-sided quantile for the conservative EV. Then a coverage study.
Then, and only then, a registry row.

### D-020 — Scheduler occurrences live in a SQL ledger

**Decision.** Replace `plan(now)` + `due_jobs(now)` with a `scheduler_jobs`
table: materialise occurrences ahead of time, claim them atomically with a lease,
acknowledge only after the work is durably persisted.
**Raison.** The old pair could never fire. Planning dropped occurrences at or
before `now`; selection kept only occurrences at or before `now`. The
intersection was empty by construction, and no test covered the real path.
**Coût.** A table and a claim protocol. In exchange: restart safety, crashed-worker
recovery, and multi-worker safety against one database — none of which an
in-memory `set()` could provide.
**Limite.** Nothing coordinates across databases, and catch-up is bounded to two
hours so a restart after an outage does not fire a burst of stale scans.

### D-021 — One acquisition path, source data persisted first

**Decision.** `AcquisitionService` is used by API, CLI and scheduler alike. It
persists events and snapshots **before** consulting any model.
**Raison.** All three callers previously persisted only the scan document, so a
real provider's prices were dropped. Snapshots cannot be re-downloaded; an
analysis can always be re-run. A batch that yields no candidate is still worth
storing — a batch that vanishes because no model existed is data loss.
**Coût.** Source data is committed before the analysis, so a crash between the
two loses the analysis. That is the correct trade.

### D-022 — Event identity is opaque and assigned once

**Decision.** Replace the `(sport, UTC date, participants)` hash with an opaque
id, a `(provider, provider_event_id) → internal_id` mapping table, and a schedule
history.
**Raison.** The derived scheme broke twice: a kick-off pushed across midnight
minted a second event, and two fixtures between the same sides on one day
collided. Both are silent.
**Coût.** A resolution step and two tables.
**Note.** Cross-provider matching is narrow (±6 h) and never merges two ids from
the *same* provider — a provider is authoritative about its own catalogue, so two
ids mean two fixtures. Multiple plausible matches are refused as ambiguous rather
than guessed.

### D-023 — Market lines are decimal, never float

**Decision.** `Selection.line` is a `Decimal`; identity uses a canonical decimal
string (`2.5`, `2.50`, `2.500` → one line); SQL keeps both a canonical text
column and a numeric one.
**Raison.** Identity must not depend on binary floating-point rendering.
**Coût.** Conversion at the numeric-model boundary, done explicitly.

### D-024 — EV is computed from a settlement distribution

**Decision.** `EV = Σ p(outcome) × net_return(outcome)`, with the outcome
distribution and settlement rule recorded on every candidate.
**Raison.** `p·o − 1` is correct only for a Bernoulli with no refund. Draw-no-bet
refunds the stake on a draw, so the previous conditional formula overstated the
magnitude of the EV by exactly `1/(1 − p_push)` — flattering a positive edge and
exaggerating a negative one.
**Coût.** Models must expose push probabilities separately from win
probabilities.
**Vérification.** Markets that cannot push reproduce `p·o − 1`, `1/p` and
`(1+t)/p` exactly, so 1X2, match winner and half-line totals did not move.

### D-025 — Challenge is durable and off by default

**Decision.** `BETMAXXING_CHALLENGE_ENABLED=false` by default (routes 404);
state moves to `challenges`/`challenge_steps` with optimistic versioning; the
default stake fraction drops from 100% to 25%, and anything above 50% requires
an explicit risk acknowledgement.
**Raison.** It was announced complete while its state lived in a module-level
dict, its tables were unwired, and it staked the whole bank by default — which
makes total loss the likeliest outcome of the very first rung.
**Coût.** Two extra calls (enable, acknowledge) before a high-risk progression.

### D-026 — Pinned dependency resolution

**Decision.** `constraints.txt`, generated from a clean Python 3.11 install and
used by CI via `pip install -e ".[dev]" -c constraints.txt`.
**Raison.** An unpinned resolution made CI's warning surface drift with upstream
releases. `pyproject.toml` keeps loose lower bounds so the package stays
installable elsewhere.
**Coût.** Regeneration is a deliberate act when upgrading.

### D-027 — Unfiltered warnings fail the suite

**Decision.** `filterwarnings = ["error", ...]` in `pyproject.toml`, with the
one known Starlette TestClient warning silenced by message.
**Raison.** A warning nobody fails on is a warning nobody reads. CI runs plain
`pytest` — passing `-W` on the command line would override the ini filters and
defeat the point.
