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
