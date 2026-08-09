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

> **Superseded in part by D-028.** The Starlette exception was not a resolution;
> the filter is gone and the warning no longer occurs. The rest of D-027 stands.

---

## Instruction 02 bis — closing the audited P0/P1 anomalies

The record below is additive. Nothing above has been rewritten: a decision that
turned out to be wrong is marked superseded, not deleted.

### D-028 — The Starlette/httpx warning is removed, not filtered

**Decision.** Install `httpx2` as a dev dependency and delete the
`ignore:Using \`httpx\` with \`starlette.testclient\`` filter. `filterwarnings`
is now exactly `["error"]`, and CI runs `pytest -W error`.
**Raison.** Starlette ≥ 1.3 imports `httpx2` when it is present and only warns
when it has to fall back to `httpx` 0.x. The warning was therefore a missing
dependency, not an unavoidable upstream defect — and D-027 had described it as
the latter. A filter that hides a fixable warning trains everyone to ignore the
category.
**Coût.** Two extra packages in the test environment (`httpx2`, `httpcore2`) and
one more in `constraints.txt`. The application's own client still uses `httpx`;
the distributions have different import names and coexist.
**Vérification.** `grep starlette.testclient pyproject.toml` finds nothing, and
CI fails if it ever does again.

### D-029 — Test helpers live in an explicitly importable module

**Decision.** Shared factories move to `tests/helpers.py`, made importable by
`pythonpath = ["tests"]` in `pyproject.toml`. No test module may import another
test module; a test enforces it by parsing the AST of every test file.
**Raison.** `from tests.test_challenge import make_candidate` resolved under
`python -m pytest` (which puts the working directory on `sys.path`) and failed
under the `pytest` console script that CI runs. CI was therefore collecting
nothing while reporting success — the worst possible failure mode for a test
suite, because it is indistinguishable from passing.
**Coût.** One extra ini setting, and a rule to remember.
**Vérification.** A test runs both invocations in a subprocess and compares what
they collect, module by module.

### D-030 — Claim selection filters state in SQL; completion is fenced by a token

**Decision.** The claim query filters `PENDING` / eligible `FAILED_RETRYABLE` /
expired `RUNNING` **before** `ORDER BY` and `LIMIT`, backed by an index on
`(state, scheduled_for, next_attempt_at)`. Every claim mints a `claim_token`,
returned on `ClaimedJob`; `mark_succeeded`, `mark_failed` and `renew_lease` are
conditional updates on `(job_id, state=RUNNING, claim_token)` and raise
`StaleLeaseError` when they change zero rows.
**Raison.** Two distinct defects. Filtering claimable states in Python meant a
few dozen finished rows filled the selection window and a genuinely due job was
never reached — a scheduler that stops working the more it has worked. And
re-asserting `state = 'RUNNING'` cannot fence anything, because `RUNNING` is what
the row already says: both a stale lease holder and a second reclaimer matched
it.
**Coût.** Callers pass the `ClaimedJob` rather than a bare id, and must handle
`StaleLeaseError`. Both are improvements: losing a lease is a real event.
**Vérification.** 500 terminal rows do not starve a due job; a stale holder
changes nothing; two workers racing one expired lease yield exactly one winner.

### D-031 — `execute()` returns a typed outcome, and error scans are persisted

**Decision.** `ExecutionResult` carries `SUCCESS` / `RETRYABLE_FAILURE` /
`FINAL_FAILURE` / `BUDGET_EXHAUSTED`. A job is `SUCCEEDED` only on `SUCCESS`.
Failed collections persist their scan document, and `FAILED_RETRYABLE` carries a
`next_attempt_at` backoff.
**Raison.** `execute()` returned a scan id, and a provider outage still produces
a scan document — so an outage was acknowledged as a success and never retried.
Separately, the error scan was built and thrown away, leaving a log line as the
only trace of a failure. And with no backoff, a failing job was re-claimed on the
very next loop iteration.
**Coût.** One row per failed scan, which is the point.

### D-032 — Discovery resolves identity before milestones are planned

**Decision.** `discover_events()` returns events already mapped onto internal
ids; a milestone's `scope_id` is always an internal id.
**Raison.** The job carried the provider's id (`the_odds_api:evt-42`) while the
analysis filter compares internal ids (`evt_9f3…`). The two never matched, so
every milestone scan analysed zero events while reporting success. Resolving in
one place makes the mismatch unrepresentable rather than merely fixed.
**Coût.** Discovery now writes to the database, so it is no longer a pure read.

### D-033 — A milestone in the recent past is due, not lost

**Decision.** `milestones_for()` keeps instants at or before `now` as long as
they are inside `DEFAULT_CATCHUP_GRACE`.
**Raison.** With a 24 h scan window, the T−24 h milestone of an event inside that
window is *always* slightly in the past at discovery time. Dropping every past
instant therefore deleted one of the configured rescoring points entirely,
silently, on every run.
**Coût.** A restart inside the grace window may re-run one milestone. The ledger
makes that idempotent.

### D-034 — Ambiguous identity resolves to nothing at all

**Decision.** `ResolvedEvent` becomes `RESOLVED` / `CREATED` / `AMBIGUOUS` /
`REJECTED`, and only the first two carry an `internal_id`. An ambiguity creates
no mapping, mutates no event, attaches no snapshot, and is queued in
`event_mapping_reviews`. The scan rejects the fixture with
`EVENT_MAPPING_AMBIGUOUS`. Matching consults competition, season, stage and the
provider's declared aliases; a signal present on only one side is silence, not
disagreement.
**Raison.** The previous version returned `candidates[0]` *while* flagging the
result ambiguous, so a price was still attributed to whichever row happened to
sort first and a snapshot was persisted against it. Flagging a guess does not
make it not a guess.
**Coût.** Some prices are declined that a human could have attributed. That is
the intended trade.

### D-035 — Provider credits are reserved durably, before every attempt

**Decision.** `provider_budget_ledger` records one row per attempt: reserved
cost, observed cost, released flag, UTC day. Every attempt — including a retry —
reserves against both the per-scan and per-day ceilings before the request is
made. The reservation is reconciled against `x-requests-last`; an absent header
leaves the estimate in place; a transport error that produced no response
releases it.
**Raison.** The guard was an integer on the HTTP client. It could not bound a
retry (the counter moved only after a response), could not bound two workers
(each had its own), and did not survive a restart. The configured daily budget
was documentation, not a control.
**Coût.** A database round trip per request, and a hard dependency on the schema
existing before any paid call — which is the correct coupling.
**Limite.** Serialisation relies on the engine's write lock. Proven on SQLite;
the PostgreSQL path is written but not exercised in CI.

### D-036 — A total collection failure is `PROVIDER_ERROR`, never missing coverage

**Decision.** Six distinct outcomes: every league failing → `PROVIDER_ERROR`;
snapshots → `OK`; bookmaker quoted but nothing mapped → `NO_CANDIDATE`; events
present without our bookmaker → `COVERAGE_MISSING`; a valid empty response →
`NO_CANDIDATE`; budget/auth handled separately. An unrecognisable `/sports`
response is a *failed* discovery and falls back to the allowlist, not "nothing
is in season".
**Raison.** Collapsing the first four into `COVERAGE_MISSING` reported "every
league returned 500" as "Winamax was not in the response" — a fault dressed as a
normal absence, which is exactly the class of error this project exists to avoid.

### D-037 — Additional markets are requested, not merely mapped

**Decision.** `draw_no_bet`, `double_chance`, `h2h_3_way_h1`, `totals_h1` and
`double_chance_h1` are fetched from the per-event endpoint after the grouped
call, under the budget gate, and skipped with a reported reason when headroom is
short. Tests assert the requests actually issued and the snapshots persisted.
**Raison.** They were present in `MARKET_MAP` and never requested. A passing
`map_market()` test proved the mapping, and nothing about collection — so the
documentation claimed a coverage that no code path could produce.
**Coût.** One extra request per football event when the budget allows.

### D-038 — Historical odds get an interface and an offline estimator only

**Decision.** `estimate_historical_cost()` is pure arithmetic returning an
explicit upper bound; `fetch_historical()` raises. `HistoricalOddsRequest`
carries `acknowledged_cost`, defaulting to `False`.
**Raison.** Historical endpoints bill at a multiple of the live rate, and a
season-wide backfill is a large irreversible spend. Consent to a live scan is not
consent to a paid backfill, so the two must be separate decisions.

### D-039 — Widen, backfill, verify, tighten

**Decision.** A NOT NULL column added to a populated table is introduced
nullable, backfilled from the existing document, verified to have no residual
NULL, and only then tightened. A row that cannot be converted **refuses** the
migration by name; quarantine is available but opt-in via
`BETMAXXING_MIGRATION_UNUSABLE_CHALLENGE=quarantine`.
**Raison.** `ALTER TABLE challenges ADD COLUMN version INTEGER NOT NULL` is
rejected outright once the table has rows, so the previous migration could not be
applied to any deployment that had ever created a Challenge. The empty-database
test passed and proved nothing about that.
**Coût.** Migrations contain data logic and must be tested with data.
**Limite.** The `b7c1e9d24a10` downgrade does not rebuild `events.source_ids`
from `event_source_map`: that direction cannot be done without guessing which
rows the migration created. Documented rather than fabricated.


---

## Instruction 02 ter — closing the reliability reservations

Instruction 02 bis was **not** validated: its own report conceded that criterion 8
held only on SQLite, which by that instruction's rules means the tranche was not
finished. These records close that and the nine other findings.

### D-040 — The daily budget is one row, updated conditionally

**Decision.** ``provider_budget_days(provider, day_utc)`` holds the authoritative
counter. Reserving is a single conditional UPDATE:
``SET reserved_total = reserved_total + :cost WHERE ... AND reserved_total + :cost <= :ceiling``.
The detail table remains, as the audit trail, but nothing synchronises on it.
**Raison.** The previous design read ``SELECT SUM(...)`` and then inserted. Under
SQLite that looks atomic because SQLite serialises every writer behind one
database-level lock; under PostgreSQL in ``READ COMMITTED`` two transactions read
the same total and both insert, so two reservations that each fit under the
ceiling together exceed it. The earlier claim that "insertions alone give the same
serialisation as SQLite" was simply false. PostgreSQL locks the row for an UPDATE
and **re-evaluates the WHERE clause against the updated tuple**, which is what
makes one writer win.
**Coût.** One extra row per provider per day, and one more statement per
reservation.
**Vérification.** Barrier-synchronised threads on a real PostgreSQL: two
reservations of 3 against a ceiling of 5 yield exactly one grant; ten of 1 against
4 yield exactly four. ``verify_invariant()`` and ``betmaxxing budget audit`` check
the counter against the detail.

### D-041 — Only a request that never left is free

**Decision.** ``may_have_been_billed()`` names the transport failures that prove
the request never reached the provider — connect error, connect timeout, pool
timeout, local protocol error, unsupported protocol, invalid URL. Those release
the reservation. Everything else — read timeout, write timeout, read/write error,
remote protocol error — stays charged at its estimate.
**Raison.** The previous version released on *every* ``TimeoutException`` and
``TransportError`` and documented it as "no response arrived, so no credit was
consumed". A read timeout means the request was sent and the answer was late: the
provider may well have served and billed it. Under-counting spend is the one
direction a budget must never err in.
**Coût.** A flaky network can charge for requests that were never billed. That is
the safe direction, and the reservation ledger records the ambiguity.

### D-042 — The lease has a heartbeat, and effects have an outbox

**Decision.** ``LeaseGuard`` renews the lease at a third of its duration, starting
with one synchronous renewal before the work begins and stopping-and-joining in a
``finally``. A refused renewal marks the guard lost, the runner declines to
acknowledge, and ``ledger.assert_owns()`` gates anything external.
``notification_outbox(job_id, alert_key, channel)`` makes a delivery at-most-once.
**Raison.** ``renew_lease()`` existed and nothing called it, so a scan longer than
the lease was reclaimed and **executed twice**. Fencing stopped the first worker
from acknowledging; it could not undo the provider requests, the rows, or the
messages. Claiming that a fencing token makes a re-executed job safe was true only
of the bookkeeping.
**Coût.** One thread per running job, and one row per external effect.
**Limite.** An effect already delivered cannot be recalled. The outbox prevents a
*second* one; it does not undo the first.

### D-043 — Budget exhaustion waits for the reset, or admits the job expired

**Decision.** ``BUDGET_EXHAUSTED`` no longer carries a delay. The runner computes
the next **UTC midnight** plus a deterministic per-job jitter under ten minutes.
The job goes to ``DEFERRED``, which consumes no attempt and can never become
``FAILED_FINAL``. A job whose value expires before that boundary — a milestone
whose event has kicked off, a daily scan past its catch-up grace — becomes
``SKIPPED_BUDGET`` with a reason and an audit scan.
**Raison.** A flat six hours was described as "past midnight" and is not: at 08:00
UTC it lands at 14:00, inside the same exhausted window. And each deferral consumed
one of the three provider-failure attempts, so three budget refusals parked a
healthy job as a permanent failure.
**Coût.** Two more states in the ledger. The jitter is derived from the job id so
it is stable across restarts; a random one would move the deadline every pass.

### D-044 — Requested markets are decided per sport

**Decision.** ``core_markets_for(sport)`` and ``additional_markets_for(sport)``.
Football groups ``h2h`` and ``totals`` and adds five per-event markets; tennis
groups ``h2h`` only and has no additional markets. Tennis ``totals``, ``h2h_s1``
read as "wins a set", and "wins at least one set" stay refused.
**Raison.** One global ``CORE_MARKETS`` asked every sport for ``totals``. Tennis
``totals`` is documented as disabled until the games-versus-sets semantics is
confirmed — so we were paying for a price the mapper then refused. Not requesting
it is the only way not to be billed for it.
**Vérification.** A fixture with both sports active asserts the tennis request
contains exactly ``h2h`` and reserves one credit, and that all five football
extras — ``double_chance_h1`` included — are requested, mapped and persisted.

### D-045 — Money conversion is decimal, in one place

**Decision.** ``to_cents`` parses with ``Decimal(str(value))``, rejects non-finite
input, and quantises with ``ROUND_HALF_UP``. The migration imports it rather than
reimplementing it.
**Raison.** ``math.floor(amount * 100 + 0.5)`` claimed half-up and did not deliver
it: 1.005 is stored as slightly *less* than one and five thousandths, so it floored
to 100 cents instead of 101. The migration's ``float(...)`` then ``round(...)`` was
a third rule again — banker's rounding on an already-drifted value. Values sitting
exactly on a half-cent are where a money rule must be unambiguous, and they were
the ones every version got wrong.
**Coût.** ``to_cents`` now raises on unusable input instead of returning nonsense,
so callers handle it.

### D-046 — The downgrade carries source ids back, or refuses

**Decision.** ``b7c1e9d24a10``'s downgrade folds every ``event_source_map`` row
into ``events.source_ids`` before the parent revision drops the table. A provider
id already present with a conflicting value stops the downgrade by name.
``EventIdentityService`` writes both places at once, so they cannot diverge.
**Raison.** Cross-provider links created after the upgrade lived only in the table.
The previous downgrade left them there and the parent revision dropped it, so the
round trip lost exactly the rows that connect a stored price to its fixture. The
earlier note calling that "documented rather than fabricated" described a loss, not
a policy.
**Vérification.** ``65c32b5e3f63`` populated → head → downgrade → head, with a
mapping added while at head, asserting the associations are identical at each step.

### D-047 — Reviews and aliases are operable from the CLI

**Decision.** ``betmaxxing identity reviews list|show|resolve`` and
``betmaxxing identity aliases import|list``, plus ``betmaxxing budget audit``.
Resolution is one transaction, requires ``--operator``, accepts only an event that
actually matched, refuses a colliding mapping, and records who decided what and
when. There is deliberately no automatic resolution. The alias import is
idempotent and quarantines bad or contradictory lines with their line numbers.
**Raison.** Both mechanisms shipped with no way to operate them: a queue nobody
could read, and a table the matcher consulted but nothing could fill. A control
that requires hand-written SQL is a place where a control could go.
**Coût.** CLI only — the web interface is a later tranche.
**Limite.** Resolving a review governs future attribution. Snapshots already
recorded are **not** re-attributed: a decision today must not rewrite what a past
scan is supposed to have seen.

---

## Instruction 03A — preparing a controlled activation

Nothing in this section calls The Odds API. It makes the future call safe,
bounded and auditable *before* a key exists. Statuses are unchanged: the
provider stays `IMPLEMENTED_UNVERIFIED`, the activation is
`PREPARED_NOT_EXECUTED`, models stay `BACKTEST_ONLY`, uncertainty outside the
demo stays `UNAVAILABLE`, and the Challenge stays `PARTIAL` and off by default.

### D-048 — The response shape is declared by the caller, never inferred

**Décision.** `_ingest_event()` takes a required `shape=` argument
(`ResponseShape.GROUPED_ODDS` or `EVENT_ODDS`). Grouped `/odds` reads
`last_update` on the bookmaker; `/events/{id}/odds` reads it on each market and
keeps the per-market instants distinct.
**Raison.** v4 says plainly: *"The `last_update` field is only available on the
market level in the response and not on the bookmaker level."* The adapter read
`book["last_update"]` for both, and the local fixtures were green because they
had been written from the code rather than from the contract. The first real
per-event response would have had every bookmaker rejected for a missing
timestamp, and the additional markets — five of the seven football markets —
would have collected nothing while still being billed.
Inference from the payload was rejected: it would silently accept a response of
the wrong shape, which is exactly the contract change we want to be told about.
**Coût.** Both call sites must state their endpoint. Two test fixtures were wrong
and had to be corrected to the real contract, not the code.
**Limite.** On the per-event endpoint a bookmaker-level stamp is ignored even if
present. A missing or unusable stamp rejects only the unit it belongs to, and no
date is ever substituted — not `received_at`, not `commence_time`, not the
neighbouring market's.

### D-049 — Cost is estimated in effective regional units

**Décision.** `effective_region_units(bookmakers=…, regions=…)` resolves the
billing rule; `estimate_cost(markets=…, region_units=…)` no longer accepts
regions at all.
**Raison.** Official rule, re-read 2026-08-05: *"When both `bookmakers` and
`regions` are specified, `bookmakers` takes priority. Every group of 10
bookmakers is the equivalent of 1 region."* The adapter counted the configured
regions while sending `bookmakers=winamax_fr`, so a one-bookmaker call under
`regions=eu,fr` reserved two units where the provider charges one. That never
overspends — the reservation is an upper bound — but it refuses calls the budget
could afford, and a guard that fires on correct requests gets widened until it
guards nothing.
**Coût.** A signature change and one existing test retargeted.
**Limite.** Still an upper bound. `x-requests-last` remains the authority after
the call, and a possibly-billed timeout still keeps its reservation (D-041).

### D-050 — Activation is four commands with separately authorised ceilings

**Décision.** `plan` (0 credits, no network, no client, no key read), `discover`
(0, two documented-free endpoints), `core` (1, one event/one market/one
bookmaker), `additional` (5, the five per-event markets). Each paid step requires
`--allow-network`, `--max-credits` equal to its published ceiling and
`--acknowledge-credits` repeating it. `max_retries=0`. No command calls another,
and `additional` refuses without a `CORE_LIVE_VERIFIED` receipt for the same
event. There is no `--api-key` option.
**Raison.** The previous script took one boolean and then called
`collect([FOOTBALL, TENNIS], window)` — a fan-out of one grouped request per
configured sport key plus one per-event request per football event, bounded only
by the 50-credit scan budget. A boolean is not a spending limit. Nobody could
state, before running it, what that script would cost.
**Coût.** Four invocations instead of one, and two numbers typed by hand per paid
step.
**Limite.** Two identical numbers are still a weak proof of intent — but they
cannot be supplied without knowing what the step costs, which a boolean could.

### D-051 — Receipts are local, sanitised and gitignored

**Décision.** Each successful network step writes one JSON receipt under
`.activation-receipts/` (or `BETMAXXING_ACTIVATION_RECEIPTS`): command, status,
instant, templated endpoint, response shape, competition, bookmaker, **hashed**
event id, ceiling, reported cost, markets requested/observed/absent, per-market
freshness **in seconds**, mapped selection count, generalised rejection reasons.
Never: the key or a fragment of it, an unredacted URL, a raw body, an odd, a
participant name, or the event id in clear.
**Raison.** An activation has to be auditable months later, and the auditable
part is what was called, what it cost and whether our parser coped — not the
prices. Anything else is a liability in a file nobody remembers writing.
**Coût.** The receipt cannot be used to reconstruct a market state.
**Limite.** The event-id hash is unsalted, because `additional` must recognise
the receipt `core` wrote across processes. It resists casual reading, not a
dictionary attack over a provider's public fixture list.

### D-052 — The suite cannot open an outbound socket

**Décision.** `tests/conftest.py` patches `socket.socket.connect`/`connect_ex`
for the whole session. `AF_UNIX` and the loopback (the test PostgreSQL) are
allowed; everything else raises.
**Raison.** "Every provider test injects a fake transport" was a convention, and
a convention is one forgotten fixture away from a real, billed request to
`api.the-odds-api.com` from a machine that has a real key in its environment —
during the very tranche preparing a controlled activation.
**Coût.** A test genuinely needing an external host would have to opt out
explicitly. None does.
**Limite.** Subprocesses do not inherit the patch. The Alembic harness only ever
touches SQLite files.

### D-053 — A historical migration depends on nothing that may change

**Décision.** `3ce123580afa` and `b7c1e9d24a10` no longer import `betmaxxing`.
They carry frozen copies of `to_cents`, `normalize_participant` and
`canonical_line`. An AST guard plus a loaded-symbol guard forbid the import in
any version script, an isolation test imports each revision with the package
blocked from `sys.meta_path`, and equivalence tests pin the frozen copies against
the live domain.
**Raison.** The coupling had already bitten: `to_cents` rounded `1.005` to 100
cents until the previous tranche fixed it to 101, so two databases migrated from
byte-identical documents carry different balances with nothing recording which
rule applied. A money value that depends on *when* you ran the upgrade is not an
audit trail. And renaming or moving any of those symbols would turn an old
revision into an `ImportError` — Alembic imports every script in the directory to
build its revision map, so one unreachable import disables every migration
command, including those unrelated to that revision.
**Coût.** Three small duplications, each pinned by an equivalence test.
**Limite.** If the domain deliberately changes a rule, the equivalence test fails
and the divergence must be decided explicitly: write a corrective revision, or
leave history as it was. That is the point, not a defect.

---

## Instruction 03A bis — closing the last gate before any provider call

Still nothing calls The Odds API. This tranche closes six gaps that would have
made the first real call unauditable. Statuses unchanged throughout.

### D-054 — An unknown cost is `null`, never zero

**Décision.** Three fields, never conflated: `estimated_credits` (the pre-call
bound), `observed_credits` (`x-requests-last`, or `null` when the header is
absent, non-integer or negative), `accounted_credits` (the observation when there
is one, the estimate otherwise). A step whose cost could not be read reports
`COST_UNVERIFIED` and authorises nothing.
**Raison.** `_check_observed_cost(None, …)` returned `0`. The client already did
the right thing — it charges the estimate when the header is missing, because
under-counting is the direction a budget must never err in (D-041) — so the
receipt contradicted the ledger by reporting nought. Worse, a documented-free
endpoint that answered without the header was accepted as *proof* of costing
nothing, which is precisely the evidence `core` was about to rely on.
**Coût.** One integer becomes three, in the receipt and in the output.
**Limite.** `accounted_credits` is a conservative guess whenever the provider
declines to say. It can over-count; it will not under-count.

### D-055 — Receipts are signed, tagged and chained by argument

**Décision.** Schema v2. A local HMAC secret is created on first network need
(`O_CREAT | O_EXCL`, `0600`, in the gitignored receipt directory, never printed).
Event ids travel as HMAC tags, not bare digests. Every receipt is signed over its
canonical JSON and verified with `hmac.compare_digest` before it is trusted.
`core` requires `--discovery-receipt`, `additional` requires `--core-receipt`.
**Raison.** Three failures compounded. `discover` wrote nothing, so the proof
`core` should have demanded did not exist and any well-formed `--event-id` was
accepted. `additional` scanned the directory for a file whose status and event
hash matched — choosing the operator's evidence for them, from an unauthenticated
file, in a directory anything can write to, without checking the command, the
schema, the sport, the bookmaker or the age. And the event hash was an unsalted
SHA of a public fixture id, computable by anyone with the provider's own event
list, so it hid nothing and a stray edit silently promoted a failed step.
**Coût.** Two more mandatory arguments, and a local secret worth backing up if
old receipts must stay verifiable across a reinstall.
**Limite.** The secret protects against a dictionary of public ids and against
accidental or casual edits on this machine. It is not a defence against someone
who already has read access to the receipt directory.

### D-056 — Every network attempt leaves a receipt; no local refusal does

**Décision.** Once a request has been attempted, a sanitised receipt is written
whatever the terminal status — including `COVERAGE_MISSING`, `SCHEMA_MISMATCH`,
`COST_MISMATCH`, `COST_UNVERIFIED`, `AUTH_FAILED`, `PROVIDER_UNAVAILABLE` and a
possibly-billed timeout. It records `network_attempted`, the exact number of
attempts, whether the request may have reached the provider, and the three costs.
A refusal *before* the network writes nothing and reserves nothing.
**Raison.** Receipts were written only after the run function returned. A response
that arrived, was charged, and then failed validation left no trace at all — the
credit was spent and the audit trail was silent, which is the inverse of what an
audit trail is for. Inventing a consumption record for a call that never happened
would be the same error pointing the other way.
**Coût.** `ProviderError` gained a `reached_provider` flag so the harness can
distinguish "never left" from "may have been served" without re-deriving it from
a message.
**Limite.** `may_have_reached_provider` is evidence, not certainty. A read timeout
records `true` and keeps its estimate charged; the provider may in fact have
served nothing.

### D-057 — A market has three states, and absence is not success

**Décision.** Each of the five requested markets gets `OBSERVED_MAPPED`,
`OBSERVED_REJECTED` or `NOT_RETURNED`. None returned → `COVERAGE_MISSING`;
returned but none mapped → `SCHEMA_MISMATCH`; some mapped → the explicit
`ADDITIONAL_PARTIAL_COVERAGE`; all five → `ADDITIONAL_LIVE_VERIFIED`.
**Raison.** `run_additional()` built an `ADDITIONAL_LIVE_VERIFIED` receipt as soon
as the bookmaker appeared, without requiring a single requested market, let alone
a mapped selection. A response containing the bookmaker and none of the markets
proves neither coverage nor market-level timestamp parsing.
**Coût.** Four terminal statuses where there was one.
**Limite.** `OBSERVED_REJECTED` conflates "the provider sent something we cannot
read" with "the market-level timestamp was missing". The receipt's
`mapping_rejections` distinguishes them; the state does not.

### D-058 — "Hard ceiling" was too strong a word

**Décision.** Four terms, kept apart in the code, the receipt and the docs: local
technical bound (requests, endpoints, events, bookmakers, markets — enforced
here), estimated contractual ceiling (0/0/1/5 under the published rule), observed
cost, accounted cost.
**Raison.** A local program cannot bind an external company's invoice. It bounds
what it does, and computes what that *should* cost under a tariff it re-read on a
given date. If the provider reprices a request it has already served, the harness
can notice it in the headers and stop — nothing more. An overstated guarantee is
the kind that gets relied on.
**Coût.** More words in every table.
**Limite.** This is the honest statement of the limit, not a fix for it.

### D-059 — A green activation is a limited proof, not a promotion

**Décision.** The runbook no longer tells the operator to set the adapter to
`VERIFIED`. A successful run attests six things — endpoint, bookmaker,
competition, event, market, instant — and the receipt records exactly those. The
adapter stays `IMPLEMENTED_UNVERIFIED` until a separate decision against written
criteria (events, competitions, days, observed coverage rate).
**Raison.** One event at one instant is not a property of an adapter. Promoting on
it would make the status mean "it worked once", which is not what a status is for.
**Coût.** The promotion criteria still have to be written; the roadmap says so.
**Limite.** Until they are, there is no path to `VERIFIED` at all — deliberately.

---

## Instruction 03B-4 bis — closing the gaps two real calls exposed

Strictly offline: no provider call, no credit. What changed is the *evidence
model*, because two billed `core` calls produced receipts that could not answer
the question they were bought to answer.

### D-060 — The bookmaker's presence is its own dimension

**Décision.** A receipt carries `bookmaker_state` (`OBSERVED` /`NOT_RETURNED`)
independently of `market_states`, and `market_states` gains
`NOT_EVALUATED_BOOKMAKER_ABSENT`. The map is **total** over `markets_requested`
on every terminal receipt whose market scope was known, and every derived list
(`markets_mapped`, `markets_rejected`, `markets_absent`,
`markets_not_evaluated`) is a strict projection of it, partitioning the requested
markets exactly once.
**Raison.** Both live `core` receipts read `markets_requested: ["h2h"]`,
`market_states: {}`, `markets_absent: []`. That is compatible with two entirely
different findings — the bookmaker was never quoted, or it was quoted and did not
offer h2h — and the second is a fact about its offer while the first is a fact
about nothing at all. Worse, `markets_absent: []` next to a requested market
invites the reading "nothing was missing". `_book_of` raised *before*
classification, so the map was empty by construction.
**Coût.** One more field, one more market state, one more projection; `_book_of`
returns instead of raising and the caller stops after recording.
**Limite.** `OBSERVED_REJECTED` still merges "the structure was unusable" with
"the market-level timestamp was missing". `mapping_rejections` distinguishes
them; the state does not.

### D-061 — A discovery says which of three things happened

**Décision.** A discovery receipt carries `events_returned`,
`events_in_window` and `events_admissible`, with
`0 <= admissible <= in_window <= returned` and
`admissible == len(set(event_tags))`. Integers only.
**Raison.** The Ligue 1 attempt could not distinguish an empty provider response
(a calendar fact) from a response whose fixtures all fell outside the declared
window (which would point at our own `commenceTimeFrom`/`To` filter) from
fixtures refused as unusable. Re-running a "free" endpoint to find out is not
consequence-free, so the counters must be right the first time.
**Coût.** Three integers per discovery receipt.
**Limite.** Integers by design: a per-event breakdown would put the schedule back
into an artefact whose whole point is to carry none of it. So the counters say
*how many*, never *which*.

### D-062 — Five proof dimensions, and a `status` command to read them

**Décision.** `plan` reports `PLAN_ONLY` and defers; a new read-only `status`
command reports `adapter_state`, `execution_state`,
`connectivity_and_cost_proof`, `bookmaker_coverage_observations` and
`mapping_freshness_proof`, plus a separate `paid_activation_state`.
`PREPARED_NOT_EXECUTED` survives only where still true: a pre-network refusal, and
the paid dimension while no paid call has been attempted.
**Raison.** Two billed calls proved authentication, endpoint, billing, chaining
and signature, and proved *nothing* about the parser or freshness, and found no
coverage on the two events they looked at. One label cannot carry that, and
`PREPARED_NOT_EXECUTED` printed by `plan` had simply become false.
**Coût.** A fifth command, and a rename that broke two existing assertions —
correctly.
**Limite.** `status` reads what is on this installation's disk. Delete the receipt
directory and it reports `NO_NETWORK_ATTEMPTED` again; it is a local audit trail,
not an account-level one. `bookmaker_coverage_observations` stays a list of scoped
observations and is never reduced to a verdict about the provider.

### D-063 — Receipts move to schema v3, and v2 stays readable

**Décision.** `RECEIPT_SCHEMA_VERSION = 3`; `SUPPORTED_SCHEMA_VERSIONS = {2, 3}`.
A valid v2 receipt is still honoured as authority, is never rewritten and never
re-signed, and the child records `parent_schema_version` so provenance stays
traceable. v1 and unknown versions are refused.
**Raison.** This is a version bump, not v2 with extra fields, because
`market_states` changed *meaning*: partial in v2, total in v3 with a new state
value. A reader applying v3's invariants to a v2 file would conclude that nothing
was missing when in fact nothing was looked at — precisely what a version number
exists to prevent. v2 nevertheless remains usable because every field the chain
actually depends on (`event_tags`, `event_tag`, `observed_credits`,
`accounted_credits`, `selections_mapped`, `parent_receipt_id`, `expires_at`) has
identical meaning in both; only `market_states` and its projections changed, and
those are not preconditions.
**Coût.** Two supported versions to keep testing.
**Limite.** A v2 receipt's coverage evidence stays ambiguous — it cannot be
retro-fixed, only read for what it does say.

### D-064 — A synthetic fixture earns `OFFLINE_CONTRACT_VERIFIED`, never a live status

**Décision.** A wholly synthetic grouped-odds fixture exercises response →
shape check → ingestion → mapping → freshness → signed receipt, with the
bookmaker and `h2h` both present, order-independent across bookmakers and
outcomes. Its proof label is `OFFLINE_CONTRACT_VERIFIED`; `MappingProof` keeps
`OBTAINED_LIVE` for what only a real call can establish.
**Raison.** Neither real call reached a response containing our bookmaker, so the
success path had never been walked end to end *through the harness*. The unit
tests covered each link; nothing covered the chain.
**Coût.** A fixture that must be visibly synthetic and stay so.
**Limite.** It proves our code reads the documented shape — not that the provider
sends it. The instruction asked for a market-level timestamp in a `GROUPED_ODDS`
fixture; the v4 guide places that field on the *bookmaker* for this endpoint
(D-048). The fixture therefore carries the bookmaker stamp, and a second variant
adds a market-level one to prove the grouped parser ignores it. Freshness is
still reported per market, which is the operationally useful reading of the
request.

### D-065 — A local receipt path is a path

**Décision.** Receipt paths are rendered as local code paths, never as URLs into
the repository host. A guard test scans the versioned documents for any `http(s)`
URL whose path reaches the receipt directory, and the harness output for any URL
at all. (The pattern is described rather than written out here: spelling one would
make this very paragraph fail the guard — which it did on the first run, and which
is the guard working.)
**Raison.** `.activation-receipts/` is gitignored. Linking to it invents a remote
artefact that does not exist and must not: the whole point is that these files
stay on the operator's machine.
**Coût.** None.
**Limite.** The guard covers this repository's documents and the harness output.
It cannot reach conversational reports already written, and those are
deliberately left alone.

### D-066 — Detection was never the problem; enforcement was

A provider key was committed to `.env.example` twice. Both times CI refused it:
the `secrets` job failed on the step that asserts the template carries no
values, four seconds after the push. Both commits were published anyway.

Nothing was wrong with the check. What was missing was everything around it:

* no rule blocked the push, so a red check was advisory;
* CI had been red on every commit for other reasons, so one more red carried no
  signal at all;
* the only check ran *after* the commit object existed, which is after the point
  where the leak becomes permanent.

So the hardening is not another scanner. It is the same rule moved earlier (a
pre-commit hook), made single-sourced (one module, three callers), extended to
what the old check could not see (the whole history, not just the tip), and
paired with a branch-protection recommendation — because a guard that cannot
block is a logging statement.

Corollary recorded deliberately: emptying the value is not remediation. The
value stays reachable in the blob its first commit points at, in every existing
clone, and in the forge's caches. Rotation at the provider is the remediation;
rewriting history only removes the object from active references.

### D-067 — A guard must not reprint what it caught

The assertion that caught the committed key rendered its own failure as
`f"{line} must not carry a value"`. It therefore printed the key into the CI
log. A caught secret became a second copy of the secret, in a surface with
different retention and different access rules from the repository.

Every verdict in `secret_hygiene` now carries a path, a line number, a variable
name and a reason, and nothing derived from the value — not the value, not its
length, not a prefix, not a hash, not an entropy estimate. Tests assert the
absence of the value *and of every 8-, 12- and 16-character window of it* from
the rendered finding, the captured stdout, and the output of the module run as a
subprocess.

The same reasoning applied to the test suite itself. `Settings` is a pydantic
settings model, so any field a test does not pass is filled from the
environment. An operator with a real key exported — exactly the state during a
controlled activation — ran a different suite from CI, and the mismatch printed
the real key as pytest's "actual" value. An autouse fixture now clears the
secret variables for every test, so the suite depends only on what a test
passes. `BETMAXXING_TEST_POSTGRES_URL` is left alone on purpose: it is a local
database address, and the PostgreSQL suites must keep skipping loudly when it is
absent rather than being quietly neutered.

### D-068 — The purge is keyed on the variable name and the value's shape

Rewriting history to remove the keys could not simply blank every assignment of
`BETMAXXING_THE_ODDS_API_KEY` in every blob. Twenty-eight of the thirty
assignments reachable in this repository are documentation placeholders — in
`README.md`, `docs/deployment.md`, `docs/provider-activation.md`,
`docs/source-matrix.md` and `scripts/smoke_the_odds_api.py`. Blanking those
would have changed the current tree, which is the one thing the operation was
required not to do.

The transformation therefore matched the variable **name** and the credential
**shape** (a bare hexadecimal run), and never a list of the compromised values —
which it was never given. Two occurrences matched, both in `.env.example`, and
both were emptied; the twenty-eight placeholders were preserved byte for byte,
so the tree at the tip is identical before and after.

Shape, not path, on purpose: a path rule would have missed a key pasted into a
document, whereas the shape rule catches a credential wherever it sits. That the
two agreed here — every credential-shaped occurrence was inside `.env.example` —
is a verified fact about this history, not an assumption the rule depends on.

### D-069 — `--json` is an interface, not a display

CI's `quality` job had been red for days on a suite that passed locally. The
difference was colour: Rich decides styling from the environment, so the same
commit rendered plainly through a local pipe and with ANSI escapes on the
runner. Two different defects hid behind that one symptom, and only the second
one is a test problem.

**The product defect.** Five commands emitted machine-readable output through
`console.print_json`, which syntax-highlights JSON and wraps it to the console
width. Whenever colour is active — an interactive terminal, `FORCE_COLOR` set, a
CI runner — the bytes a caller pipes into `jq` are not JSON, they are JSON with
escape sequences in them. A test in `test_identity_cli.py` is literally named
`test_the_listing_is_machine_readable`, and under colour the listing was not.
Soft wrapping is the same class of hazard without colour: a long string value can
be broken by a line break the caller never asked for.

So JSON now goes through `emit_json`, which writes it verbatim with
`typer.echo`. The console keeps doing what it is good at, which is output for a
human. `config` is the one deliberate mixture — a JSON object followed by a
styled human trailer — and its guard asserts the object leads and is unstyled,
not that the whole stream parses.

**The test defect.** `test_there_is_no_automatic_resolution_command` asserted
`"--event-id" in result.stdout` against Typer's help. Rich styles an option name
as its own span, so with colour on an escape sequence lands *inside* the token
and the substring is absent even though the help plainly advertises the option.
That assertion now strips styling first: it reads what the help says, not how a
terminal painted it.

**What was tried and rejected.** An autouse fixture pinning `TERM=dumb` and
clearing `FORCE_COLOR` looked like a tidy one-line fix and was removed again: it
cannot work. `cli.py` builds its `Console` at import time, so the colour decision
is already baked in before any fixture runs — the fixture measurably left ANSI in
`--json` output. Keeping it would have given false assurance while the real bug
survived. The suite is instead colour-independent because the product and the
assertions are, which is checked by running the whole suite with `FORCE_COLOR=1`.

Nothing was relaxed to get green: no `skip`, no `xfail`, no warning filter, no
coverage, PostgreSQL or migration change. Four guards force colour back on, one
of which asserts that colour really is enabled — otherwise the others could pass
by quietly staying plain — and one of which pins the splitting mechanism, so if a
future Rich stops splitting the token that fails loudly instead of silently
making the stripping look unnecessary.

The rule this leaves: assert on behaviour and on declared interfaces; where a
test must read rendered output, strip the styling first; and never send a data
contract through a renderer.

### D-070 — Detection was the easy half; the barrier is what was missing

A provider key was published from this repository twice, on 7 and 8 August. Both
times CI refused it: the `secrets` job failed on the step that asserts the
template carries no values, four seconds after the push. Both commits were
published anyway, and both keys had to be rotated and the history rewritten.

Nothing was wrong with the detection. What was missing was everything that turns
a finding into a refusal:

* nothing blocked the push, so a red check was advisory;
* CI had been red on every commit for unrelated reasons, so one more red carried
  no signal — the key's red was indistinguishable from the ambient red;
* the only check ran *after* the commit object existed, which is after the point
  where the leak becomes permanent;
* the assertion that caught it interpolated the offending line into its own
  failure message, copying the key into a CI log.

So the barrier is not one more scanner. It is five things that only work
together, and each of which is useless alone:

1. **the ruleset** on the default branch — a check that cannot block is a logging
   statement;
2. **the pre-commit hook** — the same rule moved before the commit exists, which
   is the only moment at which the leak is still preventable;
3. **`secret_hygiene` as one implementation** called by the hook, by CI and by the
   test suite — two entry points with two opinions produce an argument, not a
   verdict — and whose verdict never reprints what it caught;
4. **the history scan**, because a clean tip proves nothing: a value emptied by a
   later commit still lives in the blob its first commit points at;
5. **versioned policy** — `CONTRIBUTING.md`, `SECURITY.md` and the pull-request
   template, with static tests over them, so the absence of a required governance
   artefact or section, the disappearance of a selected marker from the scope
   actually inspected, or a stale name cross-checked with the repository becomes
   visible.

The pull-request template belongs on that list for a reason that is easy to
dismiss: it forces a *declaration*. Provider calls, endpoints, attempts and
credits have to be written down even when they are all zero. Zero is an answer;
silence is not, and silence is what preceded both incidents.

**How much the static tests over that policy actually guarantee.** Less than the
first version of this entry claimed, and the correction matters because an
overstated guarantee is itself a governance defect. A pre-merge review of the
first pull request took `CONTRIBUTING.md`, rewrote it to assert the *opposite* of
every rule — direct pushes fine, checks optional, secrets acceptable — and ran the
suite: 46 of 47 tests passed, and the single failure was an accident of line
wrapping rather than a detection. `tests/test_repository_governance.py` matches
markers, so it cannot distinguish a rule from its inversion, and it does not see a
contradiction between two paragraphs or a qualifier quietly deleted from a
sentence. What it does catch is the **removal** of a topic or of a name the
repository still uses — a deleted section, a job renamed in `ci.yml` while the
policy keeps the old name. That is a real property and it is the whole of it.
Meaning stays with the human review of the diff, and no count of passing tests
replaces it. The suite's own docstring now says so, and its phrase searches go
through one normalisation function, because the near-miss above was decided by a
newline.

**What is observed and what is merely attested.** `protected: true` is read back
from GitHub for the default branch. Everything underneath it — pull request
required, zero approvals, required checks `quality` and `secrets`, strict
up-to-date mode, conversation resolution, admins included, no bypass, force-push
and deletion refused — is **attested by the owner** and was **not** read back:
the REST endpoints for branch protection and rulesets answer `403` in this
environment, including on a control endpoint, so the sub-rules are unverifiable
here. That distinction is kept deliberately. `protected: true` on its own proves
that *some* policy applies, not which one.

**A limit of the mechanism itself.** GitHub currently accepts `success`,
`skipped` **or** `neutral` as satisfying a required check. A required check that
is skipped therefore satisfies the ruleset. This is not hypothetical here: ten
steps of `quality` sat `skipped` for days behind an upstream failure, and a
skipped step reports nothing at all. The workflow's own guards remain necessary
for that reason — neither `quality` nor `secrets` is conditioned by an `if:`,
neither uses `continue-on-error`, and `tests/test_ci_workflow.py` pins that the
expensive checks are still invoked.

**Five distinct mutations.** Opening a pull request, marking it ready for review,
merging it, closing it and deleting its branch are five separate acts requiring
five separate authorisations. An instruction that permits "fix and push" permits
a push to a *work branch*; it never permits a push to the default branch, and a
green pull request is not permission to merge.

### D-071 — Écrire les seuils avant les appels, et n'en tirer qu'une invitation

Le manque restant après 03B-4 n'était pas une observation. C'était qu'aucun texte
ne disait, à l'avance, **combien** de preuve live justifierait de demander une
promotion de l'adaptateur. Deux appels `core` réels ont abouti, n'ont trouvé aucune
couverture Winamax, et ont malgré tout été résumés comme une activation qui
« fonctionnait ». Sans seuil préenregistré, tout résultat se relit comme
encourageant — et le seuil qu'on écrit après avoir vu les chiffres n'est pas un
critère, c'est une description.

`docs/provider-validation-protocol.md` porte donc
`PROVIDER_VALIDATION_PROTOCOL_VERSION = 1`, et toute modification d'un seuil, d'une
portée ou d'une règle d'admissibilité incrémente ce nombre. Deux rapports calculés
sous des versions différentes ne se comparent pas : c'est ce qui rend visible un
critère assoupli après coup.

**Neuf faits tenus séparés**, parce qu'un mot ne les porte pas : implémentation,
connectivité, coût, présence ponctuelle d'un bookmaker, mapping d'un marché,
fraîcheur, diversité de l'échantillon, qualification globale, promotion humaine.
L'absence de `winamax_fr` sur un événement est un fait sur l'offre de ce bookmaker,
pas un échec de notre parser ; et un mapping réussi avec un autre bookmaker ne
prouve aucune couverture Winamax.

**Huit critères, seuils argumentés avant observation.** Trois événements, deux
compétitions et deux jours UTC pour `core` — un événement ne se distingue pas d'une
réponse chanceuse, et le `last_update` change d'emplacement selon la forme de
réponse, ce qui est exactement là où cet adaptateur s'était trompé. Deux événements
et un seul jour pour chacun des cinq marchés `additional`, parce que l'endpoint
coûte cinq fois plus ; le protocole écrit ce que ce compromis coûte en confiance
plutôt que de le taire. Le seuil de fraîcheur est `Settings.max_odds_age_seconds`,
non un nombre inventé ici : si le scan appelle un snapshot périmé, la qualification
ne peut pas l'appeler frais.

**v2 contribue à ce que son schéma peut établir, et à rien de plus.** Sa carte
`market_states` était partielle, donc il ne peut pas établir l'état d'**un** marché
nommé — aucun critère `additional` ne l'accepte. Mais `selections_mapped` a le même
sens en v2 et v3, donc un `core` v2 compte. C'est plus étroit qu'un refus global de
v2, et la raison est écrite.

**Expiration : deux questions.** Un reçu de plus de six heures n'autorise plus
l'étape suivante — `load_parent()` refuse, sans exception. Il atteste toujours
qu'un appel a eu lieu, et l'évaluateur le lit à ce titre. La TTL empêche de
réutiliser une preuve périmée pour engager une dépense ; elle ne fait pas
dis-arriver l'appel.

**Échec fermé.** Un reçu qui se contredit — sélections cartographiées sans marché
`OBSERVED_MAPPED`, bookmaker absent avec des sélections, statut live sans tentative
réseau, `accounted_credits` sous `observed_credits` — donne `EVIDENCE_CONFLICT` et
la contradiction est nommée. Ce n'est pas une preuve faible à pondérer : un de ses
champs est faux et on ne sait pas lequel.

**Plafond.** La machine peut conclure `INSUFFICIENT_EVIDENCE`,
`EVIDENCE_CONFLICT` ou `CRITERIA_MET_AWAITING_HUMAN_REVIEW`. Il n'y a pas de
`VERIFIED` dans le vocabulaire, et `adapter_state` reste
`IMPLEMENTED_UNVERIFIED` même tous critères satisfaits. `eligible_for_human_promotion_review`
ouvre une conversation, pas une porte — un programme capable d'écrire « vérifié »
a déjà pris la décision qu'un humain devait prendre.

Ce que cette décision **ne** fait pas : elle n'implémente rien de D-060 à D-064,
qui étaient déjà en place et sont désormais épinglées par
`tests/test_activation_characterisation.py`. Aucun schéma v4 : l'évaluation se fait
avec les champs v2/v3 existants, et un v4 exigerait une nécessité démontrée, un
test rouge et une décision séparée.
