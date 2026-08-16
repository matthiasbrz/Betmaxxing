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

> **Supersédée pour la qualification par D-072.** L'intention et les huit critères
> restent ; cinq propriétés que ce texte revendiquait n'étaient pas tenues **au
> runtime**, ce qu'un audit indépendant en lecture seule a reproduit avant tout
> appel : (1) le seuil de fraîcheur venait du réglage `max_odds_age_seconds`, donc
> d'un `.env`, sous un numéro de version inchangé ; (2) aucune date d'effet ni
> liaison à une version d'implémentation, si bien que des reçus antérieurs de vingt
> jours satisfaisaient les huit critères ; (3) l'admissibilité était une liste
> noire, donc un statut inconnu ou celui de l'autre commande produisait une preuve
> positive ; (4) les contradictions n'étaient détectées que dans un sens ; (5) les
> « jours UTC » étaient des dates civiles non normalisées. Les paragraphes
> ci-dessous sont conservés tels qu'écrits, y compris ce qui est maintenant faux :
> le seuil n'est plus `max_odds_age_seconds`, v2 ne contribue plus à rien, et le
> schéma v4 dont ce texte disait qu'il exigerait « une nécessité démontrée, un test
> rouge et une décision séparée » a reçu exactement cela.

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

### D-072 — Une preuve de qualification est fermée, datée et versionnée

> **Supersédée pour la qualification par D-073.** Tout ce qui suit reste vrai et
> reste en vigueur ; un second audit indépendant en lecture seule, mené avant tout
> appel, a montré que « fermée » était encore une revendication trop large. Une
> signature valide n'atteste que des **octets** : un reçu correctement signé mais
> mal typé — `selections_mapped = "3"`, `network_attempted = "false"` — produisait
> encore une preuve positive et ouvrait la porte de revue. Quatre autres surfaces
> manquaient : un appel payant au coût non établi sortait du dénominateur, la portée
> « bookmaker observé » n'était vérifiée par personne, un `schema_version` non
> hachable faisait planter `status`, et une commande opérateur documentée n'existait
> pas. Le numéro de protocole passe donc à **3** ; le schéma de reçu reste **v4** et
> la version de preuve d'adaptateur reste **1**, parce que ni le parser ni le mapping
> du payload ne changent.

D-071 avait raison sur l'intention et faux sur l'exécution. Un audit indépendant en
lecture seule, mené **avant** tout nouvel appel, a reproduit cinq défauts qui
rendaient trois de ses revendications fausses au runtime. Cette décision les ferme
et n'efface pas la première : D-071 reste lisible, annotée, avec ses erreurs.

**Le seuil est un littéral.** `PROTOCOL_MAX_ODDS_AGE_SECONDS = 900` vit dans le
protocole. v1 lisait le réglage runtime `max_odds_age_seconds`, si bien qu'un `.env`
portant `BETMAXXING_MAX_ODDS_AGE_SECONDS=123` produisait un protocole *différent*
sous le même numéro de version — et dans le sens qui desserre, puisque relever le
seuil laisse une cote périmée soutenir une prétention de fraîcheur. Le module de
qualification ne lit désormais **aucune** configuration : ni réglage, ni `.env`, ni
variable d'environnement, ce qu'un test structurel et un sous-processus vérifient.
Le réglage du produit reste configurable pour le scan ; ce sont deux objets aux rôles
distincts, qui valent tous deux 900 par défaut et sont censés coïncider. S'ils
divergent, le protocole garde son 900 et aucun reçu ne devient plus admissible.

**Deux versions, dans le reçu signé.** `PROVIDER_VALIDATION_PROTOCOL_VERSION = 2` et
`PROVIDER_ADAPTER_EVIDENCE_VERSION = 1` sont écrits dans chaque reçu par le chemin
commun de création, donc sur `discover`, `core` et `additional`, et **couverts par la
signature HMAC** : altérer l'un des deux champs invalide le reçu. Une preuve ne
qualifie que si ses deux versions correspondent exactement aux versions courantes.
La première règle empêche de comparer des résultats calculés sous des seuils
différents ; la seconde empêche qu'une preuve produite par un parser que nous avons
depuis modifié soit relue comme une preuve sur le parser que nous livrons. Ce que la
version de preuve d'adaptateur **ne** fait pas : valider le payload du fournisseur.
Aucun numéro de version ne valide un payload.

**Le schéma de reçu passe à v4**, parce que l'absence de ces deux champs est
signifiante : un reçu v3 ne peut pas dire sous quel protocole il serait jugé ni quel
parser l'a produit, donc il ne peut pas être une preuve *courante*. v2 et v3 restent
lus, vérifiés, honorés comme autorité de chaînage, jamais réécrits ni re-signés, et
comptés dans le bloc historique. Ils ne qualifient plus **aucun** critère, y compris
`COST_CONFORMITY`. C'est le prix assumé de la correction : la preuve déjà sur disque
devient de l'histoire. Aucun reçu réel n'a été migré, ouvert ni supprimé.

**Une date d'effet.** `QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC =
"2026-08-09T19:38:29+00:00"` — l'instant du début de cette tranche, choisi une fois,
écrit à l'identique dans le code, ici et dans le protocole, jamais recalculé au
runtime. Un `recorded_at` doit être un ISO 8601 avec timezone, normalisé en UTC, et
supérieur ou égal à cet instant. Aucun appel fournisseur n'étant autorisé par cette
tranche, toute preuve réelle future lui sera postérieure — et les deux appels réels
du 7 août, qui alimentaient auparavant 2/6 du compteur de coût sans rien prouver sur
le parser, n'y contribuent plus.

**L'admissibilité est une table positive.** `core → CORE_LIVE_VERIFIED` ;
`additional → ADDITIONAL_LIVE_VERIFIED | ADDITIONAL_PARTIAL_COVERAGE`. Tout statut
inconnu, futur, ou associé à la mauvaise commande est refusé par défaut. La liste
noire de v1 reste, comme défense supplémentaire et jamais comme seule barrière —
c'est précisément ce qu'elle était, et un statut inventé produisait alors une preuve
positive. Le coût a sa propre définition, cumulative : reçu admissible, commande
payante, socket ouverte et requête servie, `estimated_credits` entier sous le plafond
de la commande, `observed_credits` entier — jamais booléen — dans le même intervalle,
`accounted_credits == observed_credits`, statut établissant un coût. Un
`COVERAGE_MISSING` postérieur compte donc pour le coût et jamais pour le mapping ; un
coût seulement supposé après un timeout ne compte pas du tout.

**Les contradictions sont réciproques.** Six invariants, sur les cartes totales v3 et
v4 : un marché `OBSERVED_MAPPED` sans sélection cartographiée ; des sélections sans
aucun marché `OBSERVED_MAPPED` ; `NOT_RETURNED` avec un marché `OBSERVED_MAPPED` ;
`NOT_RETURNED` avec un `markets_mapped` non vide ; `markets_mapped` en désaccord avec
la carte ; un marché `OBSERVED_MAPPED` sans âge de fraîcheur entier positif. v1 ne
tenait que la deuxième, et un reçu déclarant *le bookmaker jamais retourné* et *zéro
sélection* « prouvait » cinq marchés cartographiés sans lever le moindre conflit.

**Les jours UTC sont des jours UTC.** `astimezone(UTC)` avant de prendre la date.
`00:30+02:00` et `23:30+00:00` sont le même jour ; v1 en comptait deux, et trois
observations d'une seule journée UTC satisfaisaient « deux jours UTC ».

**Compteurs séparés.** Le bloc de qualification expose
`qualification_admissible_receipts`, `qualification_historical_nonqualifying_receipts`,
`qualification_unverifiable_receipts` et une table de raisons agrégées — schéma
ancien, protocole différent, version d'adaptateur différente, antérieur à la date
d'effet, horodatage inexploitable, reçu contradictoire, non vérifié ou schéma
inconnu. Des comptes seulement : aucun chemin, aucun reçu, aucun tag, aucun
identifiant. Le champ D-062 `unverifiable_receipts` garde son propre sens : il était
écrasé par étalement de dictionnaire, chaque clé est désormais listée explicitement.

**Tags HMAC : politique tranchée.** Le tag local reste visible dans
`bookmaker_coverage_observations` et nulle part ailleurs — c'est ce qui borne une
observation à un événement sans jamais le nommer, conformément à D-062. Il n'est pas
l'identifiant fournisseur en clair et ne doit jamais être présenté comme tel.
L'assertion qui prétendait l'inverse cherchait une sentinelle absente de sa propre
fixture, donc ne pouvait pas échouer ; elle est remplacée par des tests portant sur
les valeurs réellement injectées.

**Budget corrigé.** Une invocation CLI n'est pas une requête HTTP : `discover` en
fait deux. La campagne préparée vaut 12 invocations, 12 autorisations humaines, 16
requêtes HTTP dont 8 payantes, et 16 crédits contractuels. v1 annonçait « 12
requêtes » et sous-estimait donc le trafic de quatre, en chiffrant les crédits
correctement. Les cinq totaux sont dérivés de `CAMPAIGN_INVOCATIONS`, `LOCAL_BOUNDS`
et `STEP_CEILINGS`, et un test compare la dérivation au document.

**Ce que cette décision ne fait pas.** Aucun appel fournisseur, aucun crédit, aucune
promotion, aucun changement de statut métier : l'adaptateur reste
`IMPLEMENTED_UNVERIFIED`, les modèles `BACKTEST_ONLY`. Aucune preuve réelle n'a
encore été collectée sous protocole v2 et schéma v4 — l'état courant est
`INSUFFICIENT_EVIDENCE` avec zéro reçu admissible, ce qui est exactement ce qu'un
protocole préenregistré doit afficher avant sa première campagne.

### D-073 — Une signature prouve des octets ; le contrat prouve les types

> **Supersédée pour la qualification par D-074**, et seulement sur les points que
> D-074 remplace réellement : la forme du contrat structurel, qui devient consciente
> de la phase au lieu d'exiger une carte totale de tout reçu non-`discover` ; le sens
> exact de `paid_calls_that_never_left` ; la frontière du répertoire de reçus ; le
> numéro de protocole et la date d'effet. Tout le reste de D-073 reste en vigueur tel
> quel : la lecture stricte des types, le bookmaker observé obligatoire, le coût non
> établi visible et bloquant, ce que `COST_CONFORMITY` ne prouve pas, l'écriture
> exclusive, un identifiant pour un reçu, et la commande canonique.

D-072 avait raison sur ses cinq fermetures et trop large sur une revendication : elle
disait l'évaluateur « fermé ». Un second audit indépendant, en lecture seule et avant
tout appel, a montré qu'un reçu **correctement signé** pouvait encore fabriquer une
preuve positive en étant simplement mal typé, et a trouvé quatre autres surfaces
ouvertes. Cette décision les ferme. D-072 reste lisible, annotée, avec ce qu'elle
promettait de trop.

**Protocole 3, adaptateur 1, schéma 4.** Les règles d'admissibilité changent, donc
`PROVIDER_VALIDATION_PROTOCOL_VERSION = 3`. Ni le parser fournisseur ni le mapping du
payload ne changent, donc `PROVIDER_ADAPTER_EVIDENCE_VERSION` reste `1` et le schéma de
reçu reste `4` : aucun champ nouveau n'est nécessaire pour porter cette correction.
Nouvelle date d'effet, choisie avant toute correction et avant toute campagne :
`QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC = "2026-08-10T07:19:48+00:00"`, écrite au
caractère près dans le code, ici, dans le protocole et dans la feuille de route.

**Contrat structurel positif.** Une signature valide établit que ces octets sont les
nôtres et qu'ils n'ont pas été altérés. Elle ne dit rien de leur type. Sous protocole 3,
un reçu qui prétend qualifier doit satisfaire un contrat explicite avant que le moindre
champ soit lu comme preuve : entiers **réels** et positifs pour les versions, les
tentatives, les sélections et les crédits — un booléen n'est jamais un entier ;
`observed_credits` et `quota_remaining` entiers réels ou `null`, `null` rendant le coût
non établi ; `network_attempted` et `may_have_reached_provider` exactement `true` ou
`false`, aucune chaîne ni conteneur ; `market_states` mapping d'états connus **total**
sur `markets_requested` ; `markets_requested` et chaque projection présente listes de
chaînes non vides sans doublon, chaque projection image **exacte** de la carte ;
`freshness` mapping `marché → entier ≥ 0` dont les clés sont incluses dans les marchés
demandés ; `recorded_at` ISO 8601 textuel avec fuseau ; `receipt_id`, `sport_key`,
`bookmaker` et `event_tag` chaînes non vides. Le contrat est **conscient de la
commande** : `discover` porte `event_tags` et aucune observation de bookmaker, parce que
`/events` n'en renvoie aucune — exiger l'inverse aurait invalidé un reçu de découverte
parfaitement bon.

Un reçu courant qui manque à ce contrat reçoit la raison `malformed_current_schema`,
avec **les noms des champs fautifs et jamais leurs valeurs**. Il ne prouve rien, il ne
disparaît pas du corpus, et il fait passer l'état global à `EVIDENCE_CONFLICT` : une
preuve illisible n'est pas une archive tranquille. Le lecteur tolérant `_int`, qui
acceptait booléens et chaînes numériques, est supprimé de tout chemin de décision ; un
lecteur distinct et explicitement nommé `_reported_int` reste dans le bloc d'audit
D-062, parce qu'un rapport qui décrit ce qui est sur le disque vaut mieux qu'un rapport
qui refuse de s'imprimer — et il ne décide de rien.

**Bookmaker observé, obligatoire.** Un critère de mapping n'est satisfait que si
`bookmaker_state == OBSERVED`. La portée « bookmaker observé uniquement » était affichée
par la v2 sans que rien ne la vérifie : absent ou inconnu, la preuve passait. Elle n'est
donc pas retirée, elle est devenue vraie.

**Coût non établi : visible et bloquant.** Quatre catégories exhaustives et disjointes
pour tout reçu payant courant : `conforming_paid_calls`, `nonconforming_paid_calls`,
`paid_calls_with_unestablished_cost` et `paid_calls_that_never_left`. Le critère passe
si et seulement si les conformes atteignent six, les non conformes valent zéro **et** les
coûts non établis valent zéro. Un `PROVIDER_UNAVAILABLE` qui a pu atteindre le
fournisseur fait donc échouer le critère, même après six appels conformes ; la v2
l'ignorait en silence et affichait « 0 non conforme ». Le recensement porte sur tous les
reçus payants **courants**, malformés compris : un reçu payant malformé est précisément
un reçu dont le coût ne peut pas être établi.

**Ce que `COST_CONFORMITY` ne prouve pas.** Décision conservée et désormais écrite dans
le `limit` du critère : il établit l'absence de dépassement de la borne annoncée et
l'égalité entre observation et comptabilisation. Il n'établit **pas** l'exactitude d'un
tarif fixe. Un appel annoncé à 0 crédit reste conforme — ce qui prouve qu'aucune borne
n'a été franchie, pas que le tarif contractuel vaut zéro.

**Aucun JSON ne fait planter l'audit.** Un fichier dont `schema_version` était un
mapping ou une liste levait `TypeError` — `in` sur un `frozenset` hache son opérande — et
faisait sortir `status` en erreur. Une version est désormais un entier réel ou n'est pas
une version : ces fichiers sont comptés invérifiables, sans exposer leur contenu, dans
`audit_receipts` comme dans `load_parent`. Le code fautif était **antérieur** à cette
série de tranches ; il est vivant sur cette tête et sur le chemin de la preuve, donc il
est corrigé ici.

**Écriture exclusive des reçus.** Le nom de fichier porte le `receipt_id` **complet** et
la création est exclusive, à `0600`. L'ancien nom tronquait l'identifiant à huit
caractères et utilisait `write_text` : deux reçus partageant la même seconde, la même
commande **et** le même préfixe de huit caractères s'écrasaient sans un mot. Les trois
conditions étaient nécessaires — un rapport précédent disait « deux reçus au même instant
s'écrasent », ce qui était trop large et est corrigé ici. Réécrire un reçu byte pour byte
identique est idempotent ; un contenu divergent sous le même nom est **refusé**. Compromis
assumé : un refus d'écriture pourrait faire perdre la trace d'un appel réel, mais avec un
identifiant complet de seize caractères hexadécimaux tiré de `secrets.token_hex(8)`, ce
cas est hors d'atteinte pratique, alors que l'écrasement, lui, était atteignable dès
qu'un schéma d'identifiants non aléatoire serait choisi.

**Un identifiant, un reçu.** Deux copies byte pour byte du même reçu comptent une fois.
Deux reçus valides portant le même `receipt_id` avec des contenus signés **différents**
constituent un conflit de preuve : tous les reçus de cet identifiant sont écartés des
critères, l'état devient `EVIDENCE_CONFLICT`, et le message ne divulgue ni contenu, ni
chemin, ni tag. La v2 les comptait comme deux événements distincts.

**Marché demandé, carte totale, projections.** Un critère ne peut porter que sur un
marché appartenant à `markets_requested` ; les clés de `market_states` correspondent
exactement aux marchés demandés ; chaque projection présente est l'image exacte de la
carte ; une fraîcheur ne peut pas prouver un marché jamais demandé. La décision sur
`expires_at` est inchangée : la TTL concerne l'autorité de chaînage, pas la persistance
de l'attestation historique.

**Commande canonique.** Le runbook dit désormais
`python -m betmaxxing.providers.the_odds_api.activation status [--json]`.
`betmaxxing-the-odds-api` n'existait ni dans `[project.scripts]` ni dans le wheel
construit : une commande documentée qu'un opérateur ne peut pas taper est un défaut, pas
une coquille. Aucun point d'entrée n'est ajouté dans cette tranche, et un test structurel
analyse les blocs de commandes des runbooks : leur premier mot doit être `python`, un
outil courant, ou un script réellement déclaré.

**Compatibilité.** Schémas v2 et v3 : toujours lus, vérifiés, honorés comme autorité de
chaînage, jamais réécrits ni re-signés, et ne qualifiant rien. v4 portant le protocole 2 :
devient **historique** pour la qualification — c'est le prix assumé d'un changement
d'admissibilité, et aucun reçu réel v4 n'existait. Aucun reçu n'est migré, ouvert,
re-signé ni supprimé.

**Ce que cette décision ne fait pas.** Aucun appel fournisseur, aucun crédit, aucune
promotion, aucun changement de statut métier : l'adaptateur reste
`IMPLEMENTED_UNVERIFIED`, les modèles `BACKTEST_ONLY`. Aucune preuve réelle n'existe sous
protocole 3 — l'état courant est `INSUFFICIENT_EVIDENCE` avec zéro reçu admissible.

### D-074 — La rigueur doit accepter ce que le producteur écrit vraiment

> **Supersédée pour la qualification par D-075**, et seulement sur les points que D-075
> remplace réellement : l'absence de précondition d'atteinte fournisseur sur les preuves de
> réponse ; la lecture binaire de l'état de tentative ; le court-circuit
> `command == "additional"` de l'état payant ; la déduplication partielle des lectures
> sémantiques ; l'admission d'un statut positif à portée de marchés vide ; la création du
> nom final avant les octets ; le classement de `COST_UNVERIFIED` en « non conforme » ; et
> le numéro de protocole avec sa date d'effet. Tout le reste de D-074 reste en vigueur tel
> quel : le contrat conscient de la phase et sa table versionnée, la lecture partagée du
> mapping, l'équation des populations, la détection des identifiants divergents sur
> l'ensemble des reçus vérifiés, et l'absence de réflexion des valeurs rejetées.

D-073 avait raison sur ses cinq fermetures et s'est trompée dans l'autre sens sur la
première : elle a écrit un contrat structurel strict sans demander ce que le harnais
émet réellement. Un troisième audit indépendant, en lecture seule et avant tout appel,
a montré que **six des quinze reçus** que le producteur écrit — tout échec `core`
survenu *avant* la classification des marchés, et `plan` — étaient déclarés
`malformed_current_schema`. Conséquence : un seul `AUTH_FAILED` honnête sur le disque
plaçait `status` en `EVIDENCE_CONFLICT` définitivement, et un opérateur n'avait aucun
moyen de revenir à un état lisible sans supprimer une preuve réelle. Le même audit a
trouvé quatre autres surfaces ouvertes. Cette décision les ferme. D-073 reste lisible,
annotée, avec ce qu'elle a durci de trop.

**Protocole 4, adaptateur 1, schéma 4.** Les règles d'admissibilité changent, donc
`PROVIDER_VALIDATION_PROTOCOL_VERSION = 4`. Ni le parser fournisseur ni le mapping du
payload ne changent, donc `PROVIDER_ADAPTER_EVIDENCE_VERSION` reste `1`, et les champs
signés existants suffisent : `RECEIPT_SCHEMA_VERSION` reste `4`, seule leur
interprétation est distinguée par le numéro de protocole. Nouvelle date d'effet,
choisie une seule fois après le préflight et avant la première correction :
`QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC = "2026-08-10T09:11:48+00:00"`, écrite au
caractère près dans le code, ici, dans le protocole et dans la feuille de route, et
jamais recalculée au runtime.

**Le contrat devient conscient de la phase.** `RECEIPT_PHASES` est une table
**versionnée** qui dit, pour chaque couple commande/statut réellement productible,
quelles formes honnêtes il peut prendre : `PLANNED` — aucune socket ouverte ;
`DISCOVERED` — `discover` a atteint les deux endpoints gratuits ;
`ATTEMPTED_UNCLASSIFIED` — la requête payante est partie et aucun marché n'a été
classifié ; `CLASSIFIED` — l'état du bookmaker a été relevé et chaque marché demandé
classifié. Le contrat commun aux quatre reste celui de D-073, avec une distinction que
D-073 formulait mal : une **version** est un entier réel strictement positif, un
**compteur** est un entier réel non négatif — zéro est une réponse, `discover` étant
documenté gratuit.

La table est testée contre `build_receipt`, pas déduite de la vérité d'un champ, et
c'est ce qui empêche le contrat de dériver à nouveau loin de son producteur. Deux
couples portent deux phases admissibles, et c'est un fait sur le harnais :
`COVERAGE_MISSING` et `SCHEMA_MISMATCH` sont atteignables depuis `_event_of` — avant
l'observation du bookmaker — et depuis la fin de `run_core` / `run_additional`. Les
deux formes sont honnêtes. Ce qui reste interdit, et c'est la propriété qui compte :
une forme non classifiée ne peut **jamais** être lue comme une observation, parce que
la phase `ATTEMPTED_UNCLASSIFIED` exige positivement une carte de marchés vide, des
projections vides, une fraîcheur vide et `selections_mapped == 0`. La rigueur n'est pas
levée, elle est adressée à la bonne question.

Un couple **absent** de la table reçoit sa propre raison,
`unknown_command_status_pair`, plutôt que d'être jugé contre une forme que personne n'a
choisie. Inventer un contrat pour un statut jamais produit est exactement la façon dont
un statut futur qualifierait quelque chose en silence.

`attempts` devient **obligatoire** et cohérent avec le drapeau réseau :
`network_attempted = false` impose `attempts == 0`, `true` impose `attempts ≥ 1`. Le
producteur l'écrit sur chaque reçu ; trois fixtures de test l'omettaient et décrivaient
donc des documents que `build_receipt` n'émet pas. Elles sont corrigées, pas les
assertions.

**Les cinq dimensions de `status` lisent la même preuve.** Elles restent distinctes —
ce sont des faits distincts — mais aucune ne peut plus employer un libellé positif sur
une preuve que le bloc strict rejette pour le même fait.
`mapping_observation_is_sound` est la lecture unique et partagée : commande payante,
statut positif de mapping, phase `CLASSIFIED`, contrat satisfait, aucune contradiction,
`network_attempted is True`, `bookmaker_state == OBSERVED`, au moins un marché
`OBSERVED_MAPPED`, `selections_mapped ≥ 1`, et un âge ≤ 900 s pour ce marché.

Elle **omet délibérément** la barrière de version et de date. La qualification demande
« est-ce une preuve pour les critères préenregistrés », ce qu'un changement de
protocole remet légitimement à zéro ; cette lecture demande « le parser a-t-il déjà lu
un marché live ici », ce qu'un changement de protocole ne défait pas. Les garder
séparées est ce qui laisse la dimension historique rester un fait historique.

Deux états manquaient et sont ajoutés. `CostProof.EXERCISED_UNESTABLISHED` : un coût
non établi n'est ni conforme ni un écart, et le présenter comme conforme était la
contradiction la plus directe entre les deux blocs. `PaidActivationState.
PAID_ATTEMPT_INCONCLUSIVE` : un appel payant réellement parti qui n'a établi ni
couverture ni mapping n'est pas « exécuté sans couverture » — cette formule affirme
qu'on a regardé et que le bookmaker était absent. La précédence du coût est
`NONCONFORMING > UNESTABLISHED > CONFORMING > NOT_EXERCISED`, appliquée appel par
appel ; une découverte gratuite seule laisse `NOT_EXERCISED`.

Les observations de couverture ne contiennent plus que des reçus de phase `CLASSIFIED`,
structurellement valides et non contradictoires : une observation est une **réponse**,
pas la trace d'une tentative. `accounted_credits_total` n'additionne que des entiers
réels non négatifs — ni booléen, ni chaîne numérique, ni nombre négatif : c'est un
chiffre de dépense qu'un opérateur lit avant de décider d'en dépenser plus.

**Deux populations de coût, nommées.** `connectivity_and_cost_proof` parle de toute
tentative payante réelle vérifiée sur le disque, protocoles antérieurs compris ;
`COST_CONFORMITY` compte une population plus étroite, protocole courant et
dédupliquée. Les deux nombres peuvent légitimement différer, ce qui rendait leur
voisinage illisible. Le recensement dont le libellé est dérivé est donc publié à côté
de lui, sous `paid_call_cost_census`, avec sa population écrite en clair. Nommer les
deux populations est ce qui empêche de lire cet écart comme une contradiction — et ce
qui aurait évité de résoudre le problème en rétrécissant le libellé, ce qui aurait
détruit un fait historique pour faire coïncider deux chiffres.

**`never_left` exige une certitude.** La catégorie n'est admise que si les deux
drapeaux sont des booléens **et** `may_have_reached_provider is False`. Sous D-073, un
drapeau absent ou mal typé y était rangé : 250 des 875 combinaisons drapeaux/statut/
coût affirmaient qu'un appel était prouvé n'être jamais parti, ce que rien
n'établissait. Le dénominateur est écrit : une **tentative payante réelle** est un reçu
de commande payante dont `network_attempted` n'est pas exactement `false`. Seul un
`false` exact prouve qu'aucun appel payant n'a eu lieu ; un drapeau absent ou mal typé
ne prouve rien et reste dans le recensement, en coût non établi. Le dénominateur n'est
pas étendu aux étapes refusées avant réseau.

**Le répertoire de reçus a une frontière, et elle est appliquée avant toute lecture.**
`audit_receipts()` applique désormais celle de `load_parent()` : un lien symbolique
n'est jamais suivi, interne ou externe ; une cible se résolvant hors du répertoire
n'est jamais lue ; un lien brisé, un répertoire nommé `*.json` et tout candidat qui
n'est pas un fichier régulier du répertoire sont comptés invérifiables sans que leur
chemin ni leur contenu apparaisse nulle part. Jusqu'ici la fonction lisait à travers un
lien, si bien qu'un reçu placé n'importe où pouvait satisfaire un critère depuis un
répertoire où il n'était pas — alors que le chemin d'autorisation refusait le même
lien. Ce code était **antérieur** à cette série de tranches ; il est vivant sur le
chemin de la preuve, donc il est corrigé ici.

`write_receipt()` construit son nom depuis des composants validés — `command` et
`receipt_id` chaînes non vides sans séparateur de chemin — et **parse** `recorded_at`
au lieu d'en découper le texte. C'est cette dernière règle qui manquait : un
`recorded_at` de `"../../2026-08-11T12:00:00+00:00"` survivait au découpage sous la
forme `"../../20260811T"` et écrivait deux répertoires au-dessus du bon. Le parent
résolu est revérifié juste avant l'ouverture exclusive, et un lien symbolique déjà
présent à la cible est refusé **sans** lire ce qu'il désigne. La validation précède la
création du répertoire, si bien qu'un composant hostile ne laisse aucune trace.

**Les populations se réconcilient.** Chaque reçu vérifié appartient à exactement une
population : utilisable, courant malformé, courant contradictoire, couple inconnu,
historique non qualifiant, exclu pour identifiant divergent, invérifiable. L'équation
est publiée par `status` et testée. Un reçu courant malformé ou contradictoire n'est
plus compté « historique » : ce classement se lisait comme « produit sous un protocole
antérieur », l'inverse de la vérité. Les copies byte-à-byte identiques sont une
**dimension croisée** explicitement documentée, jamais une population : mélanger les
deux modèles est la façon dont une équation cesse de s'équilibrer.

La divergence d'identifiant est calculée sur **l'ensemble** des reçus vérifiés avant
tout classement, et cette population est exclusive et prioritaire. Sous D-073 elle ne
voyait que la sous-population déjà utilisable : un reçu utilisable et un reçu malformé,
contradictoire ou historique partageant un identifiant passaient pour un fait unique.
Deux fixtures de test combinaient deux corpus en réutilisant les mêmes identifiants ;
elles sont corrigées, parce que le harnais tire chaque identifiant de
`secrets.token_hex(8)` et n'en réutilise jamais un.

**Aucune valeur malformée n'est reflétée.** Une sortie peut nommer un champ ou un
compteur ; elle ne recopie jamais la valeur d'un reçu structurellement invalide, ni
dans le JSON complet de `status`, ni dans la sortie humaine, ni dans les observations
de couverture, ni dans les raisons, ni dans les conflits.

**Une correction de cohérence interne.** Un `markets_mapped` **absent** n'est plus une
contradiction. Le contrat structurel traite toutes les projections comme facultatives
et `contradictions()` les lisait autrement, si bien qu'un reçu omettant simplement une
projection paraissait se contredire. Défaut antérieur à cette tranche, sur le chemin de
la preuve, donc corrigé ici.

**Compatibilité.** Schémas v2 et v3 : toujours lus, vérifiés, honorés comme autorité de
chaînage, jamais réécrits ni re-signés, et ne qualifiant rien. Les reçus v4 portant le
protocole 3 deviennent **historiques non qualifiants** — c'est le prix assumé d'un
changement d'admissibilité, et aucun reçu réel n'existe sous protocole 3. Aucun reçu
n'est migré, ouvert, re-signé ni supprimé.

**Ce que cette décision ne fait pas.** Aucun appel fournisseur, aucun endpoint, aucune
tentative, aucun crédit, aucune promotion, aucun changement de statut métier :
l'adaptateur reste `IMPLEMENTED_UNVERIFIED`, les modèles `BACKTEST_ONLY`,
l'incertitude `UNAVAILABLE` hors démo, `Challenge` `PARTIAL` et désactivé. Le plafond
machine reste `CRITERIA_MET_AWAITING_HUMAN_REVIEW`. Aucune preuve réelle n'existe sous
protocole 4 : l'état courant est `INSUFFICIENT_EVIDENCE` avec zéro reçu utilisable.

### D-075 — Une preuve de réponse exige une réponse

> **Supersédée pour la frontière de confiance par D-076**, et seulement sur les points
> que D-076 remplace : la validation et le cycle de vie du secret, la pureté effective
> de l'évaluateur, la frontière du *répertoire* (et non du seul nom final), le
> traitement des erreurs de persistance, la lecture de `command`, le découpage du seau
> de coût « non établi », l'exclusion des reçus rejetés de tout compteur sémantique, la
> vérification bidirectionnelle du catalogue et les bornes de la quarantaine. Ce que
> D-075 établit et que D-076 ne remplace pas : l'atteinte du fournisseur comme
> précondition de toute preuve de réponse, l'état de tentative à trois valeurs, la
> cascade symétrique `core`/`additional`, le canon sémantique dédupliqué, les
> invariants positifs par statut, et le caractère non bloquant de
> `confirmed_attempts_not_sent`.

D-074 avait raison sur la phase et s'est trompée sur ce qu'une phase établit. Un quatrième
audit indépendant, en lecture seule et avant tout appel, a trouvé **un P1** : la porte
`CRITERIA_MET_AWAITING_HUMAN_REVIEW` était atteignable alors que **toutes** les
observations de mapping du corpus portaient `may_have_reached_provider = false` — une
affirmation signée que la requête n'avait jamais atteint le fournisseur. Le drapeau
n'était lu que par le recensement du coût ; le mapping, la couverture et la fraîcheur ne
le regardaient pas. Détail qui dit tout : un drapeau **absent ou mal typé** était
correctement refusé, et seule la valeur la plus explicite passait. Cinq P2 accompagnaient
ce P1. Cette décision les ferme. D-074 reste lisible, annotée.

**Protocole 5, adaptateur 1, schéma 4.** Les règles d'admissibilité, la population du coût
et les états publiés changent, donc `PROVIDER_VALIDATION_PROTOCOL_VERSION = 5`. Ni le
parseur fournisseur ni le mapping du payload ne changent, donc
`PROVIDER_ADAPTER_EVIDENCE_VERSION` reste `1` ; aucun champ signé nouveau n'est requis,
donc `RECEIPT_SCHEMA_VERSION` reste `4`. Nouvelle date d'effet, choisie une seule fois
après le préflight et avant la première correction :
`QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC = "2026-08-10T14:00:37+00:00"`, écrite au caractère
près dans le code, ici, dans le protocole, le runbook et la feuille de route, et jamais
recalculée au runtime.

**L'atteinte du fournisseur est une précondition, pas une note de bas de page.**
`provider_was_reached` exige une tentative confirmée **et** `may_have_reached_provider is
true`, et il garde désormais `admissible_for`, `mapping_observation_is_sound`, les
observations de couverture et les dimensions historiques de `activation status`. Un statut
qui **implique** une réponse — `DISCOVERY_VERIFIED`, `CORE_LIVE_VERIFIED`,
`ADDITIONAL_LIVE_VERIFIED`, `ADDITIONAL_PARTIAL_COVERAGE`, `COVERAGE_MISSING`,
`SCHEMA_MISMATCH`, `COST_MISMATCH`, `COST_UNVERIFIED`, `AUTH_FAILED` — sur un reçu dont
l'atteinte n'est pas établie est **contradictoire**, pas seulement non qualifiant : les deux
champs sont les nôtres et signés, donc l'un est faux et nous ne savons pas lequel.
`PROVIDER_UNAVAILABLE` n'en fait pas partie, parce qu'un timeout et un 5xx sont deux issues
différentes et que le harnais ne prétend pas savoir laquelle.

Le corpus qui franchissait la porte — huit preuves de mapping à `reach=false` plus six coûts
honnêtes — reste désormais sous la porte avec **zéro** mapping admissible.

**L'état de tentative a trois valeurs.** `AttemptState` : `NOT_ATTEMPTED` quand
`network_attempted is false` **et** `attempts == 0` ; `CONFIRMED_ATTEMPT` quand le drapeau
est exactement `true` **et** `attempts ≥ 1` ; `ATTEMPT_STATE_UNESTABLISHED` autrement,
drapeau absent, mal typé, ou incohérent avec le compte. D-074 écrivait cette lecture
`network_attempted is not False`, si bien qu'un champ **absent** devenait un fait :
`execution_state` rapportait `CORE_ATTEMPTED` et la population s'appelait « tentatives
payantes réelles ». Une mesure manquante n'est ni une mesure de zéro ni une mesure de un.

Les deux états qui manquaient sont ajoutés :
`ExecutionState.NETWORK_ATTEMPT_STATE_UNESTABLISHED` et
`PaidActivationState.PAID_ATTEMPT_STATE_UNESTABLISHED`. La rétention reste prudente et
bloquante — le reçu ne disparaît pas des raisons —, mais il n'est jamais décrit comme tenté,
réel ou exécuté.

**Une tentative confirmée non envoyée ne bloque pas, et ne qualifie rien.** Décision de
propriétaire, écrite : un pas `core`/`additional` avec `network_attempted is true` et
`may_have_reached_provider is false` est une **tentative locale confirmée non envoyée**.
Elle n'a mesuré aucun tarif, donc elle ne contribue pas aux six appels conformes, elle
n'entre ni dans « non conforme » ni dans « non établi », elle est recensée séparément sous
`confirmed_attempts_not_sent`, et elle ne bloque pas `COST_CONFORMITY`. La raison : une
requête certainement non envoyée ne mesure pas le tarif du fournisseur, et elle ne doit pas
invalider six observations réellement servies et conformes. Cette tolérance ne tient que
parce que les deux drapeaux sont des booléens exacts et cohérents ; dès que l'un ne l'est
pas, le reçu retombe dans une catégorie bloquante. Elle ne peut jamais produire mapping,
couverture, fraîcheur, crédit observé ni statut `*_LIVE_VERIFIED` admissible.

**`COST_UNVERIFIED` signifie coût non établi.** Pas coût non conforme. D-074 le rangeait
sous « non conforme », si bien que le même reçu changeait de sens selon le bloc consulté.
`COST_MISMATCH` alimente la catégorie non conforme, `COST_UNVERIFIED` la catégorie non
établie, les deux bloquent, et aucun bloc, enum, texte ou tableau ne leur donne un sens
différent.

**La cascade des états payants est symétrique.** D-074 testait
`any(command == "additional")` avant tout le reste, donc la seule présence d'un reçu
`additional` rapportait `ADDITIONAL_EXECUTED` pour un `AUTH_FAILED`, un `COST_MISMATCH`, un
`PROVIDER_UNAVAILABLE` non servi ou une couverture jamais classifiée — alors que les mêmes
issues en `core` rapportaient correctement `PAID_ATTEMPT_INCONCLUSIVE`. L'ordre est
désormais les faits d'abord : aucune tentative, état non établi, tentative confirmée sans
rien d'établi, puis seulement les étiquettes positives. `ADDITIONAL_EXECUTED` a une
définition — une preuve `additional` classifiée et valide qui établit effectivement
couverture ou mapping — et cette définition est publiée.

**Un statut positif ne peut pas être satisfait à vide.** `set(states) == set(requested)` est
vrai quand les deux sont vides, donc un `CORE_LIVE_VERIFIED` sans marché demandé, sans
carte, sans fraîcheur et à zéro sélection était bien formé, utilisable, et comptait comme
appel payant conforme — six d'entre eux fournissaient la moitié « coût » du corpus qui
franchissait la porte. Chaque statut classifié porte désormais ses invariants positifs,
dérivés du producteur : marchés demandés non vides, bookmaker observé, au moins un marché
cartographié et une sélection pour les statuts positifs ; toutes les cartes pour
`ADDITIONAL_LIVE_VERIFIED` ; un marché cartographié **et** un qui ne l'est pas pour
`ADDITIONAL_PARTIAL_COVERAGE` ; une absence réellement observée pour `COVERAGE_MISSING` ; au
moins un marché rejeté pour `SCHEMA_MISMATCH`.

**La déduplication sémantique est universelle.** D-074 la décrivait comme une dimension
croisée, ce qui était vrai des seuils de mapping et des appels conformes et faux partout
ailleurs : sept copies byte-à-byte d'un `COST_MISMATCH` rapportaient **63 crédits**
dépensés, sept appels non conformes contre un seuil qui doit valoir zéro, et sept
observations de couverture d'un seul événement. Après vérification des signatures et
exclusion des identifiants divergents, toute lecture sémantique passe par une collection
dédupliquée par identifiant et empreinte scellée. Les comptes de fichiers physiques restent
disponibles sous trois noms qui disent qu'ils sont physiques, et aucun n'est une preuve
métier. Les crédits d'un reçu que le contrat rejette sont publiés à part, sous
`rejected_receipt_credits_not_counted`.

**La publication est atomique.** `O_CREAT | O_EXCL` est atomique sur l'existence et muette
sur le contenu : le nom final apparaissait vide et était rempli ensuite, donc une
interruption laissait un fichier de zéro octet — et la republication du **même** reçu était
refusée définitivement sous « contenu signé différent », ce qui était faux et rendait la
preuve d'un appel payant réel à jamais inenregistrable. Les octets existent maintenant en
entier avant le nom : temporaire du même répertoire, `fsync`, puis publication par lien dur
qui échoue au lieu de remplacer, puis `fsync` du répertoire. Un fichier incomplet est nommé
comme tel et `quarantine_incomplete_receipt` le met de côté sans perdre un octet, ce qui
libère le nom et permet la reprise à l'identique.

**La frontière tient au moment de l'ouverture.** Décision de propriétaire : les courses de
liens sont dans le périmètre d'intégrité, et la documentation ne se contente pas de réduire
la promesse. Une primitive unique ouvre relativement à un descripteur de répertoire, avec
`O_NOFOLLOW`, vérifie par `fstat` qu'il s'agit d'un fichier régulier et lit **depuis ce
descripteur**. Un `resolve()` antérieur ne prouvait rien : un probe déterministe remplaçait
un reçu régulier par un lien vers l'extérieur dans la fenêtre entre le contrôle et la
lecture, et le contenu étranger devenait un reçu vérifié, sentinelle comprise. Sur une
plateforme sans `O_NOFOLLOW`, le répertoire n'est pas lu — échec fermé. `receipt_secret`
utilise la même primitive, parce que ce fichier *est* le secret et que D-074 le lisait
encore avec `Path.read_text` après un `O_EXCL` échoué.

**Mapping et coût sont deux axes indépendants, et la porte exige les deux.** Un
`observed_credits` hors plafond n'annule pas une preuve de mapping saine — ce sont deux
questions — mais il rend le coût non conforme ou non établi et bloque la porte globale.
Aucun corpus au coût défaillant n'atteint les huit critères.

**Ce que cette décision ne fait pas.** Aucun appel fournisseur, aucun endpoint, aucune
tentative, aucun crédit, aucune promotion, aucun changement de statut métier :
l'adaptateur reste `IMPLEMENTED_UNVERIFIED`, les modèles `BACKTEST_ONLY`, l'incertitude
`UNAVAILABLE` hors démo, `Challenge` `PARTIAL` et désactivé. Le plafond machine reste
`CRITERIA_MET_AWAITING_HUMAN_REVIEW`. Aucune preuve réelle n'existe sous protocole 5 :
l'état courant est `INSUFFICIENT_EVIDENCE` avec zéro reçu utilisable. Les reçus protocole 4
deviennent historiques non qualifiants, et aucun reçu n'est migré, ouvert, re-signé ni
supprimé.

### D-076 — La frontière de confiance est un descripteur, un format et un type

> **Supersédée pour la provenance et le journal d'intents par D-077**, et seulement sur
> les points que D-077 remplace : la constructibilité du type de provenance,
> l'immutabilité d'un reçu admis, la frontière de `load_parent`, la distinction entre une
> frontière absente et une frontière indisponible, le contrat et le rapprochement des
> intents, le périmètre de la quarantaine, la classification des erreurs de stockage, la
> politique de la variable de secret et les permissions du fichier, et la validation des
> deux scalaires de `evaluate`. Tout le reste de D-076 — le format du secret, le
> descripteur unique du répertoire, l'ordre de publication, le domaine fermé de
> `CommandState`, les six populations de coût, l'exclusion des reçus rejetés des
> compteurs sémantiques et le catalogue vérifié dans les deux sens — reste en vigueur.

**Contexte.** Cinq réaudits indépendants en lecture seule ont chacun trouvé des défauts
réels après une CI verte. Le cinquième, sur `e43851e`, a reproduit **un P1, cinq P2 et
douze P3**, et tous portaient sur le même endroit : la frontière entre ce qui est sur le
disque et ce que le programme accepte de croire.

Le P1 est le plus net. Rien ne validait le secret de signature. Un fichier vide, un
retour à la ligne, un caractère, le mot `secret`, soixante-quatre caractères non
hexadécimaux, cent mille caractères : tous acceptés, tous utilisés pour signer, tous
vérifiés. Un corpus synthétique signé avec une telle clé atteignait
`CRITERIA_MET_AWAITING_HUMAN_REVIEW`. Et une route ne demandait aucun adversaire : une
première exécution interrompue entre la création exclusive et l'écriture laissait un
fichier de zéro octet que chaque exécution suivante lisait comme une clé vide, pour
toujours.

**Décision.** Protocole **6**, preuve adaptateur **1**, schéma de reçu **4**, instant
d'effet unique et littéral `2026-08-11T04:50:40+00:00`. Les preuves de protocole 5
deviennent historiques non qualifiantes. `TheOddsApiProvider` reste
`IMPLEMENTED_UNVERIFIED` ; le plafond machine reste
`CRITERIA_MET_AWAITING_HUMAN_REVIEW` ; aucun statut global de vérification n'est créé.

Neuf changements, chacun accompagné d'un test qui échoue sur `e43851e` :

1. **Le secret est un format.** Exactement 64 caractères hexadécimaux minuscules, dans
   le fichier comme dans la variable d'environnement. Pas de `strip()` — c'est lui qui
   transformait `"\n"` en clé — pas de tolérance de casse, pas de longueur voisine. Un
   secret existant invalide fait échouer l'opération **fermée** et n'est jamais réécrit :
   le réécrire invaliderait silencieusement tous les reçus déjà signés, ce qui
   transformerait la preuve d'un opérateur en bruit. Deux verbes séparés :
   `load_receipt_secret` lit sans créer, `ensure_receipt_secret` crée — et seuls les
   chemins qui vont signer l'appellent. La création est atomique : octets complets dans
   un temporaire, `fchmod(0600)`, `fsync`, publication sans écrasement, `fsync` du
   répertoire. Deux créateurs concurrents obtiennent la même clé complète.
2. **Le répertoire est un descripteur.** Ouvert une fois, composant par composant, avec
   `O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC` relativement au parent déjà sûr, validé par
   `fstat`, conservé pour tout le cycle. Listing, lecture, publication, `link`,
   `unlink`, quarantine et `fsync` passent par lui. Sans ces garanties du noyau, le
   répertoire n'est pas lu.
3. **La provenance est un type.** `audit_receipts` est le seul endroit où une signature
   est vérifiée et le seul qui frappe un `VerifiedReceipt`. `qualification.evaluate` est
   effectivement pur — aucun environnement, aucune horloge, aucun fichier, aucun HMAC —
   et refuse une liste de mappings brute au lieu de la vérifier lui-même, ce qui est
   exactement ce qui traînait le secret dans un module documenté comme pur.
4. **Un intent avant le réseau.** Écrit et `fsync`-é avant chaque requête, résolu
   seulement après la publication durable du reçu, bloquant tant qu'il subsiste,
   idempotent au rapprochement, et dépourvu de clé, d'URL, d'événement en clair et de
   payload. C'est la réponse au trou que la v5 laissait : cinq crédits engagés, la
   publication en échec, et aucune trace qu'une requête avait été tentée.
5. **Une erreur de persistance est un résultat métier.** Les cinq sites de publication
   passent par un point unique qui rapporte, en JSON comme en texte, avec un code de
   sortie non nul, l'identifiant de tentative, la commande, l'état d'atteinte, les
   crédits comptabilisés et la nature de l'échec — assainis. Aucun `OSError` nu
   n'atteint l'opérateur. La durabilité n'est plus supprimée, et l'ordre documenté est
   l'ordre exécuté.
6. **La commande est un domaine fermé.** `CommandState` à cinq valeurs. Seul `discover`
   exact rapporte `DISCOVERY_ATTEMPTED` ; seuls `core` et `additional` entrent dans le
   dénominateur payant ; `Core`, `" core "`, `sync`, `7` et un champ absent sont une
   faute structurelle.
7. **Six populations de coût.** Le seau « non établi » de la v5 affirmait dans son nom
   une atteinte que deux de ses trois alimentations démentaient. Il est scindé, et les
   deux moitiés bloquent.
8. **Un reçu rejeté n'alimente aucun compteur sémantique.** Il alimente les raisons, les
   populations, `rejected_receipt_credits_not_counted`, `rejected_paid_receipts` et un
   recensement médico-légal distinct. La conséquence est énoncée : deux des six
   populations de coût ne peuvent naître que d'un reçu hors contrat, donc elles restent à
   zéro dans le recensement sémantique — le contrat structurel n'est pas affaibli pour
   rendre un seau atteignable.
9. **Le catalogue est vérifié dans les deux sens.** Contre les vrais chemins de commande,
   pilotés par un transport factice. La v5 déclarait `discover/SCHEMA_MISMATCH` sans
   producteur et ignorait `discover/COST_UNVERIFIED` et `discover/COST_MISMATCH`, que
   `run_discovery` écrit par `_settle_cost` — un reçu honnête classé « couple inconnu »
   faisait basculer un corpus entier en `EVIDENCE_CONFLICT`. La table contient
   désormais **26 couples** et **30 formes**, dont **21** persistés et **5** non
   persistés, et la quarantaine est exposée par
   `receipts quarantine --name`.

**Ce que cette décision n'établit pas.** Aucune preuve réelle n'existe sous protocole 6 :
zéro appel fournisseur, zéro endpoint, zéro tentative, zéro crédit, zéro reçu utilisable.
Un secret valide et une frontière tenue ne disent rien de la couverture d'un bookmaker ;
ils disent seulement que ce que le programme affirme sur ses propres preuves peut être
cru.

### D-077 — Une provenance est une preuve, une frontière indisponible n'est pas une frontière vide

**Contexte.** Six réaudits indépendants en lecture seule ont chacun trouvé des défauts
réels après une CI verte. Le sixième, sur `9adfb8f`, a reproduit **quatre P1, huit P2 et
onze P3**. Les quatre P1 disent la même chose sous quatre angles : la v6 a nommé la
provenance sans l'imposer.

`VerifiedReceipt` était un constructeur public qui ne vérifiait rien. Huit reçus dont la
clé `signature` avait été *supprimée*, emballés à la main, atteignaient
`CRITERIA_MET_AWAITING_HUMAN_REVIEW` avec `eligible_for_human_promotion_review` à vrai —
par un lot, par une liste nue et par un tuple ; un corpus signé par une clé que
l'installation ne possède pas faisait de même. `require_verified` interrogeait
`isinstance` ; rien n'interrogeait le HMAC.

Le type n'était gelé qu'au premier niveau. `__init__` faisait `dict(payload)`, donc
chaque dictionnaire et chaque liste imbriqués restaient partagés avec ceux de
l'appelant, et `__getitem__` rendait l'objet vivant. Une seule écriture par l'API
`Mapping` documentée — `reçu["freshness"][marché] = 300` — faisait passer un corpus de
`INSUFFICIENT_EVIDENCE` à la porte de revue humaine, pendant que la signature du reçu ne
vérifiait plus, et rien ne relisait le sceau.

`reconcile_intents` construisait son ensemble d'identifiants publiés avec
`_read_receipt_payloads`, qui analyse du JSON et ne vérifie **rien**. Un fichier de deux
clés suffisait à effacer un intent et à rouvrir la porte, et treize formes forgées —
non signée, clé étrangère, schéma inconnu, commande inconnue, sport, bookmaker, tag,
coût, protocole antérieur — résolvaient **toutes**.

`receipts quarantine --name` n'avait aucun périmètre. `--name <id>.intent` rendait 0
sans `--force` et faisait passer la porte de `EVIDENCE_CONFLICT` à
`CRITERIA_MET_AWAITING_HUMAN_REVIEW` : un conflit supprimé sans qu'aucun reçu existe.
`--name signing-key.secret` rendait 0 aussi, après quoi huit reçus vérifiés devenaient
huit reçus invérifiables.

Et `audit_receipts` terminait par `except StoreRefused: return lot((), 0), 0`, donc un
répertoire de reçus atteint par un lien symbolique rapportait exactement ce que
rapporte une installation vide, pendant que `load_parent` — entièrement par chemin, avec
`resolve()` qui suit précisément les liens que le store refuse — lisait ce même
répertoire et autorisait un appel payant.

**Décision.** Protocole **7**, preuve adaptateur **1**, schéma de reçu **4**, instant
d'effet unique et littéral `2026-08-11T14:20:00+00:00`. Les preuves de protocole 6
deviennent historiques non qualifiantes. `TheOddsApiProvider` reste
`IMPLEMENTED_UNVERIFIED` ; le plafond machine reste
`CRITERIA_MET_AWAITING_HUMAN_REVIEW` ; aucun statut global de vérification n'est créé.
Aucun critère, seuil, taxonomie de coût, règle de déduplication ni équation de
population ne change.

Neuf changements, numérotés.

1. **La provenance n'est pas constructible.** `VerifiedReceipt`,
   `VerifiedReceiptBatch` et `AuditResult` prennent un jeton privé en premier argument
   positionnel : l'orthographe naturelle lève `UnverifiedProvenance`. `trust()` et
   `require_verified()` sont **supprimés** — une fabrique qui prend la clé de
   l'appelant est exactement le trou. Le seul chemin est
   `receipt_store.audit_directory`, qui reçoit un répertoire déjà ouvert composant par
   composant et fait lui-même la lecture, le contrôle de schéma et le HMAC contre le
   secret de l'installation. La revendication est étroite et testable : **aucun point
   d'entrée exporté du dépôt ne produit une provenance admise sans vérification de
   signature**. Du code déjà en cours d'exécution dans le processus peut atteindre un
   nom privé ou réécrire du bytecode ; rien ici ne prétend l'empêcher.
2. **Un reçu admis est une valeur gelée récursivement.** La première rédaction de ce
   point écrivait les conteneurs scellés comme une sous-classe de `dict` et une
   sous-classe de `list` redéfinissant chaque mutateur, pour que rien en aval ne change
   de vocabulaire, et déclarait `dict.__setitem__(gelé, k, v)` comme une **limite
   acceptée**. C'était une erreur de la même famille que le défaut corrigé : redéfinir
   un mutateur ne le supprime pas, la méthode de la classe de base restant joignable par
   l'objet classe. Mesuré sur un reçu réellement admis par l'audit, les **quinze** appels
   `dict.__setitem__`, `dict.update`, `dict.pop`, `dict.setdefault`, `dict.clear`,
   `dict.__ior__`, `list.__setitem__`, `list.append`, `list.extend`, `list.insert`,
   `list.pop`, `list.clear`, `list.__iadd__`, `list.sort` et `list.reverse`
   **réussissaient**, et le premier d'entre eux rouvrait la porte de revue humaine sur un
   corpus périmé. La compatibilité nominale avec `dict` et `list` ne prévaut pas sur la
   frontière de preuve. `FrozenMapping` implémente donc `Mapping` **sans hériter d'aucun
   conteneur mutable**, les séquences deviennent des `tuple`, et les quinze appels lèvent.
   Le prix est payé explicitement : les contrôles structurels qui demandaient
   `isinstance(value, list)` demandent une `Sequence` non-`str`, et un reçu admis se
   re-sérialise par `to_builtin()`. Reste `object.__setattr__` sur l'unique slot : l'audit
   enregistre une empreinte sha256 non clée de chaque reçu admis et `require_audited` les
   recalcule, donc un reçu substitué n'est pas lu. La limite, énoncée plutôt que
   sous-entendue : réécrire **à la fois** le contenu et l'empreinte enregistrée défait ce
   contrôle, parce que Python n'a pas de types intégrés scellés.
3. **`load_parent` passe par le descripteur.** L'argument de la ligne de commande est
   réduit **textuellement** à un nom de base du répertoire autorisé — jamais par
   `resolve`, `is_symlink` ou `is_file` — puis lu par le même `SecureDirectory` que
   l'audit. Un lien dur vers un inode extérieur reste accepté si le fichier est
   régulier, signé par le secret local et de portée exacte : la frontière garantit le
   nom et l'inode ouverts dans ce répertoire, pas l'histoire de création de l'inode.
4. **Trois états de frontière.** `ABSENT` (aucun répertoire), `AVAILABLE` (répertoire
   sûr, les comptes valent quelque chose) et `UNAVAILABLE` (le répertoire existe et
   n'est pas lisible sans ambiguïté). `UNAVAILABLE` est un conflit de preuve, bloque la
   porte, et apparaît dans le JSON **et** le rendu humain sous une catégorie assainie
   de `BOUNDARY_REASONS` — jamais un chemin.
5. **Un intent a un contrat positif fermé.** Identifiant par `fullmatch` de 8 à 64
   hexadécimaux minuscules ; corps aux neuf champs exacts, types et bornes vérifiés,
   identifiant du corps égal au nom. Publication idempotente **sur octets identiques
   seulement** : une portée divergente, une cible vide, tronquée, lien ou répertoire est
   un refus typé **avant réseau**. Un intent invalide ou illisible reste bloquant et est
   réduit à son nom local et à `UNREADABLE_OR_INVALID` : plus rien de son contenu
   n'est réfléchi.
6. **Le rapprochement exige un reçu réel.** Les candidats viennent de
   `audit_receipts` — lus par le descripteur, de schéma accepté, vérifiés contre le
   secret local — et doivent porter le même identifiant, la même commande, le même
   sport, le même bookmaker, le même tag éventuel, un coût compatible avec le plafond de
   l'intent, un couple réellement persistable du catalogue, aucune faute structurelle,
   aucune contradiction et la **même lignée** de versions.

   Deux questions distinctes, jamais déduites l'une de l'autre. La **résolution
   comptable** demande si un reçu durable et vérifié consigne l'issue de cette
   tentative : elle exige la même lignée — schéma, protocole, preuve adaptateur —
   **non** l'instant d'effet. L'**admissibilité à la qualification** demande si ce reçu
   soutient un critère préenregistré : elle exige en plus l'instant, et un reçu
   antérieur reste historique non qualifiant.

   Exiger l'instant des deux côtés ferait qu'un changement de protocole orpheline les
   intents en vol — un intent qu'aucun reçu ne peut plus résoudre bloque la porte pour
   toujours, ce qui transformerait une correction en déni durable. Conséquence voulue :
   un reçu de la bonne lignée peut résoudre son intent **sans contribuer à aucun
   critère**. Le compteur d'intents non résolus retombe, celui des historiques non
   qualifiants monte, et les deux faits sont publiés séparément.
7. **La quarantaine est une commande de reçu.** Seul un nom de base finissant par
   `.json` est accepté. Le secret, tout `*.intent`, tout temporaire et tout autre
   fichier sont refusés, **avec ou sans `--force`** ; `--force` ne sert qu'à archiver un
   reçu signé complet.
8. **Toute erreur de stockage a une catégorie.** Une signature mal formée rend le reçu
   invérifiable au lieu de faire lever `hmac.compare_digest` ; de l'UTF-8 invalide
   devient `ContentUndecodable`, et `SecretInvalid` pour le secret ; `exists` ne traite
   plus que `ENOENT` comme « absent » ; l'échec de création du temporaire devient une
   erreur de durabilité ; et les cinq sites de publication capturent le graphe réel des
   exceptions, non seulement `PersistenceFailed`.
9. **La politique du secret et les deux scalaires.** Une variable **présente mais vide**
   est une valeur invalide, plus une absence ; seule l'absence réelle autorise le
   fichier ou la création. Sur POSIX, un secret non régulier, d'un autre UID ou
   accordant un droit au groupe ou à tous est refusé — attendu `0600` — et la limite de
   plateforme est écrite. `unverifiable` et `unresolved_intents` sont des entiers Python
   exacts, non booléens, positifs ou nuls : `None` et `False` ne valent jamais zéro
   implicitement.

**Conséquences.** Toute preuve antérieure au protocole 7 est historique. Les suites de
qualification n'obtiennent plus leur provenance par un raccourci : elles écrivent des
reçus signés dans un répertoire jetable et appellent le vrai audit, comme la production.
`audit_receipts` rend un `AuditResult` qui ne se déballe pas en deux valeurs, parce que
le déballer est précisément ce qui a fait perdre l'état de frontière. Les deux compteurs
de fichiers invérifiables lisent désormais **un seul** audit et ne peuvent plus
divergerement : avoir deux provenances pour un même nombre était le défaut, non la
fonctionnalité.

**Ce que cette décision n'autorise pas.** Aucun appel fournisseur, aucune activation,
aucune promotion d'adaptateur ou de modèle, aucun changement de critère ou de seuil.

### D-078 — Le modèle de menace de la provenance des reçus, énoncé normativement

**Statut.** Adoptée. Clarifie le modèle de menace de D-077 **sans** modifier
l'admissibilité des preuves : protocole **7**, schéma de reçu **4**, preuve adaptateur
**1** et instant d'effet `2026-08-11T14:20:00+00:00` sont **inchangés**. Il n'y a ni
protocole 8 ni nouvel instant.

**Pourquoi cette décision existe.** Sept tranches de suite, un audit indépendant a trouvé
que la formulation dépassait le code. La dernière l'a mesuré : sur `4408e70`, quatre voies
ordinaires — le jeton `_PROVENANCE_TOKEN` lu au niveau module, `object.__new__`, une
sous-classe dont `__init__` n'appelle pas `super()`, et la réécriture simultanée du contenu
et de son empreinte — amenaient huit reçus **dont la clé `signature` avait été supprimée**
à `CRITERIA_MET_AWAITING_HUMAN_REVIEW` avec `eligible = true`. La frontière elle-même était
saine : `audit_directory` refusait les huit et les comptait invérifiables. Ce qui était faux,
c'était la phrase « la provenance n'est plus constructible ».

Le défaut n'était donc pas dans l'audit, il était dans la promesse. On ne le corrige pas en
cachant mieux un jeton : on le corrige en disant ce qui est garanti.

**La propriété garantie, littéralement.**

> Dans le pipeline applicatif supporté, seuls les reçus dont le HMAC a été vérifié par
> `audit_directory` sont transmis à l'évaluation. L'objet de provenance est un marqueur
> interne et un contrôle contre les erreurs d'utilisation ; il ne constitue pas une sandbox
> contre du code Python arbitraire exécuté dans le même processus.

**Dans le périmètre de sécurité.** Fichiers de reçus, intents et payloads fournisseur
hostiles ou malformés ; reçus sans signature ou signés avec une autre clé ; écritures
interrompues et erreurs de stockage ; liens symboliques, substitutions de chemins et courses
de système de fichiers ; appelant utilisant les API publiques et documentées ; erreurs
accidentelles du code applicatif ; processus extérieur ne possédant ni le secret HMAC ni la
capacité d'exécuter du code dans le processus Betmaxxing.

**Hors du périmètre de sécurité.** Exécution arbitraire de Python dans le processus
Betmaxxing ; accès réflexif aux attributs privés ; `object.__new__`,
`object.__setattr__`, monkeypatching, modification du bytecode ou des modules ;
modification du code source exécuté ; debugger ou processus compromis sous l'identité de
l'application ; accès direct au secret HMAC.

**Justification normative.** Un acteur capable d'exécuter arbitrairement du Python dans le
même interpréteur peut remplacer `evaluate`, neutraliser le vérificateur ou lire le secret.
Aucun constructeur privé, jeton, type ou somme de contrôle exprimable en Python ne peut
former une frontière cryptographique contre cet acteur. Exiger le contraire, c'est exiger
une isolation par processus ou par service — hors périmètre de 03C-1.

**Vocabulaire retiré.** « Non-forgeable », « non constructible », « impossible à
fabriquer », « aucun objet mutable » et « preuve cryptographique portée par le type » ne
sont plus employés comme garanties. L'authenticité vient du **HMAC vérifié à l'ingestion**.
Le type et la somme de contrôle ne font que **préserver** cet invariant dans le pipeline de
confiance ; ils ne le rétablissent pas. Le sujet du septième commit —
« Make receipt provenance and intents non-forgeable » — est une formulation historique trop
forte : le message d'un commit est immuable et n'est pas réécrit, il est **supersédé** par
la présente décision.

**Durcissement effectivement livré**, en défense en profondeur et sans prétention
anti-réflexion :

1. `_PROVENANCE_TOKEN` **supprimé** ; il n'existe plus aucune valeur de jeton accessible au
   niveau module, et il n'en est pas introduit de « mieux cachée » ;
2. les trois constructeurs de provenance refusent **inconditionnellement** ; la création
   passe par des fonctions privées du module, appelées uniquement par l'audit ;
3. `FrozenMapping`, `VerifiedReceipt`, `VerifiedReceiptBatch` et `AuditResult` **refusent le
   sous-classement** ;
4. les frontières internes comparent une **identité de type exacte** (`type(x) is …`) au lieu
   d'un `isinstance` qu'un sosie satisfait ;
5. `audit_directory` reste la seule fabrique utilisée par le graphe applicatif, et un test
   lit les sources pour le vérifier : un seul site de frappe, situé après le contrôle HMAC ;
6. `fingerprint` devient **`content_checksum`** et `AuditResult.seals` devient
   **`AuditResult.checksums`** : ce sont des contrôles d'intégrité contre une mutation
   accidentelle, pas des preuves d'origine.

**Ce qui est documenté comme limite, non comme garantie.** `FrozenMapping` n'expose aucun
mutateur **public** ; les séquences sont des `tuple` ; la somme de contrôle détecte une
mutation accidentelle survenue après l'audit ; une réécriture réflexive simultanée du
contenu **et** de la somme de contrôle est hors modèle de menace ; l'origine authentique
reste établie uniquement par le HMAC au moment de l'audit. Le docstring qui affirmait que les
conteneurs scellés étaient bâtis « only from objects that have no mutating API at all » est
corrigé : la garantie porte sur l'API publique ordinaire, pas sur les primitives réflexives.

**Traitement des constats du réaudit quattuordecies.** P1-F1 : observation **confirmée**,
reclassée **hors modèle** pour les voies exigeant l'exécution arbitraire dans le processus ;
les deux voies simples — jeton exporté et sous-classement — sont néanmoins **fermées**.
P2-F2 : la somme de contrôle non secrète n'est plus présentée comme une authentification.
P3-F3 : documentation corrigée sur la mutabilité réflexive du dictionnaire privé. P3-F4 :
les affirmations absolues sont supprimées ou supersédées. P3-F5 : l'incident des deux
écritures du corps de PR devient une trace permanente dans la PR.

**Ce que cette décision n'autorise pas.** Aucun appel fournisseur, aucune activation, aucune
promotion d'adaptateur ou de modèle, aucun changement de critère, de seuil, de protocole, de
schéma ou d'instant d'effet.
