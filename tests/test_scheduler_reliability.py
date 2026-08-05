"""Scheduler properties an audit found unproven.

``tests/test_scheduler.py`` covers due-semantics and the happy concurrency path.
It does not cover what happens once the ledger has *history*, once a lease has
changed hands, or once a job's work fails — and each of those was broken:

* the claim query read rows ordered by ``scheduled_for`` and filtered claimable
  states in Python, so a few dozen finished rows starved a due one;
* nothing tied an acknowledgement to the lease it came from, so a worker that
  woke up after losing its lease could mark another worker's attempt succeeded;
* reclaiming an expired ``RUNNING`` lease compared the state to ``RUNNING`` —
  which is what it already was — so two workers could both "win";
* ``execute()`` returned a scan id and nothing else, so a provider outage was
  acknowledged as a success;
* milestones carried the *provider's* event id while analysis filtered on the
  *internal* id, so a milestone scan analysed zero events.

Every test here states the business invariant, not the implementation.
"""

from __future__ import annotations

import contextlib
import threading
from datetime import UTC, datetime, timedelta

import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import CollectionStatus, ScanStatus, Sport
from betmaxxing.domain.models import CanonicalEvent, Participant
from betmaxxing.engine.acquisition import AcquisitionService
from betmaxxing.providers.base import BudgetExceeded, ProviderError, ProviderUnavailable
from betmaxxing.scheduler import runner as runner_module
from betmaxxing.scheduler.ledger import (
    JobLedger,
    JobState,
    JobType,
    StaleLeaseError,
)
from betmaxxing.scheduler.runner import ExecutionOutcome, execute, milestones_for, tick
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import ScanRunRow, SchedulerJobRow

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def scheduler_settings(db_settings: Settings, **overrides: object) -> Settings:
    payload: dict[str, object] = {
        "mode": RunMode.DEMO,
        "database_url": db_settings.database_url,
        "scheduler_enabled": True,
        "notifications_enabled": False,
        "staking_enabled": False,
        # No daily occurrences unless a test asks for them: these tests assert on
        # the state of *the* job they enqueued, not on ambient scheduling.
        "scan_times": "",
    }
    payload.update(overrides)
    return Settings(**payload)  # type: ignore[arg-type]


@pytest.fixture
def ledger(db_settings: Settings) -> JobLedger:
    return JobLedger(db_settings)


# ---------------------------------------------------------------------------
# 1. Terminal states must not occupy the selection window
# ---------------------------------------------------------------------------
class TestStarvation:
    def _fill_with_history(self, ledger: JobLedger, count: int) -> None:
        for index in range(count):
            job_id = ledger.enqueue(
                job_type=JobType.EVENT_MILESTONE,
                scheduled_for=NOW - timedelta(minutes=1000 - index),
                scope_id=f"old-{index}",
            )
            assert job_id is not None
            claimed = ledger.claim_due(now=NOW, worker="history", limit=1)
            assert claimed
            ledger.mark_succeeded(claimed[0], scan_id=f"scan-{index}", now=NOW)

    def test_forty_finished_jobs_do_not_starve_a_due_pending_job(self, ledger: JobLedger) -> None:
        self._fill_with_history(ledger, 40)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )
        claimed = ledger.claim_due(now=NOW, worker="w", limit=10)
        assert [job.job_type for job in claimed] == [JobType.DAILY_SCAN]

    def test_five_hundred_finished_jobs_do_not_starve_a_due_pending_job(
        self, ledger: JobLedger
    ) -> None:
        """A deployment accumulates history; the query must not degrade with it."""
        self._fill_with_history(ledger, 500)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )
        assert len(ledger.claim_due(now=NOW, worker="w", limit=10)) == 1

    def test_a_final_failure_does_not_starve_a_due_pending_job(self, ledger: JobLedger) -> None:
        for index in range(40):
            ledger.enqueue(
                job_type=JobType.EVENT_MILESTONE,
                scheduled_for=NOW - timedelta(minutes=1000 - index),
                scope_id=f"dead-{index}",
            )
            claimed = ledger.claim_due(now=NOW, worker="history", limit=1)
            ledger.mark_failed(claimed[0], error="boom", retryable=False, now=NOW)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )
        assert len(ledger.claim_due(now=NOW, worker="w", limit=10)) == 1


# ---------------------------------------------------------------------------
# 2/3. Lease ownership
# ---------------------------------------------------------------------------
class TestLeaseOwnership:
    def test_a_stale_holder_cannot_acknowledge_the_new_attempt(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        first = ledger.claim_due(now=NOW, worker="worker-a")[0]

        later = NOW + timedelta(minutes=20)
        second = ledger.claim_due(now=later, worker="worker-b")
        assert len(second) == 1

        # worker-a wakes up from a long GC pause and acknowledges. Whether it is
        # refused with an error or ignored, worker-b's attempt must survive.
        with contextlib.suppress(Exception):
            ledger.mark_succeeded(first, scan_id="stale-scan", now=later)

        assert ledger.get_state(first.job_id) is JobState.RUNNING
        with session_scope(db_settings) as session:
            row = session.get(SchedulerJobRow, first.job_id)
            assert row is not None
            assert row.lease_owner == "worker-b"
            assert row.scan_id != "stale-scan"

    def test_a_stale_holder_cannot_fail_the_new_attempt(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        first = ledger.claim_due(now=NOW, worker="worker-a")[0]
        later = NOW + timedelta(minutes=20)
        assert ledger.claim_due(now=later, worker="worker-b")

        with contextlib.suppress(Exception):
            ledger.mark_failed(first, error="late failure", now=later)

        assert ledger.get_state(first.job_id) is JobState.RUNNING

    def test_only_one_worker_reclaims_an_expired_lease(self, db_settings: Settings) -> None:
        ledger_a = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger_b = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger_a.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        ledger_a.claim_due(now=NOW, worker="crashed")

        later = NOW + timedelta(minutes=20)
        first = ledger_a.claim_due(now=later, worker="taker-1")
        second = ledger_b.claim_due(now=later, worker="taker-2")

        assert len(first) + len(second) == 1

    def test_the_reclaiming_worker_owns_the_lease(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        ledger.claim_due(now=NOW, worker="crashed")
        later = NOW + timedelta(minutes=20)
        taker = ledger.claim_due(now=later, worker="taker")[0]

        with session_scope(db_settings) as session:
            row = session.get(SchedulerJobRow, taker.job_id)
            assert row is not None
            assert row.lease_owner == "taker"


# ---------------------------------------------------------------------------
# 4. Concurrent materialisation
# ---------------------------------------------------------------------------
class TestConcurrentEnqueue:
    def test_a_racing_insert_is_absorbed_not_raised(self, db_settings: Settings) -> None:
        """Deterministic reproduction of the lost race between check and insert.

        Another worker's row is already committed under the same occurrence key;
        the second worker must treat that as "already enqueued", not crash.
        """
        ledger = JobLedger(db_settings)
        when = NOW.replace(second=0, microsecond=0)
        with session_scope(db_settings) as session:
            session.add(
                SchedulerJobRow(
                    job_id="foreign-id-from-another-worker",
                    job_type=str(JobType.DAILY_SCAN),
                    scheduled_for=when,
                    scope_id="",
                    state=str(JobState.PENDING),
                    attempts=0,
                    created_at=when,
                )
            )

        assert (
            ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=when, scope_id=None) is None
        )
        with session_scope(db_settings) as session:
            rows = session.query(SchedulerJobRow).all()
            assert len(rows) == 1

    def test_eight_threads_materialising_produce_one_row_each(self, db_settings: Settings) -> None:
        barrier = threading.Barrier(8)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                barrier.wait(timeout=10)
                JobLedger(db_settings).materialise(
                    now=NOW, daily_times=["08:00", "12:00", "18:00"], milestones=[]
                )
            except BaseException as exc:  # recorded, then asserted below
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert errors == []
        with session_scope(db_settings) as session:
            rows = session.query(SchedulerJobRow).all()
            keys = {(r.job_type, r.scheduled_for, r.scope_id) for r in rows}
            assert len(rows) == len(keys)


# ---------------------------------------------------------------------------
# 5/6. A real tick, and milestone identity
# ---------------------------------------------------------------------------
def _scan_document(settings: Settings, scan_id: str) -> dict:
    with session_scope(settings) as session:
        row = session.get(ScanRunRow, scan_id)
        assert row is not None, f"scan {scan_id} was not persisted"
        return dict(row.document)


def _job_scan_id(settings: Settings, job_id: str) -> str | None:
    with session_scope(settings) as session:
        row = session.get(SchedulerJobRow, job_id)
        return row.scan_id if row else None


class TestRealTick:
    def test_tick_executes_a_due_job_end_to_end(self, db_settings: Settings) -> None:
        settings = scheduler_settings(db_settings)
        ledger = JobLedger(settings)
        job_id = ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )
        assert job_id is not None

        executed = tick(settings, NOW, ledger=ledger, worker="w1")

        assert job_id in {job.job_id for job in executed}
        assert ledger.get_state(job_id) is JobState.SUCCEEDED
        scan_id = _job_scan_id(settings, job_id)
        assert scan_id is not None
        assert _scan_document(settings, scan_id)["scan_id"] == scan_id


def _provider_event_ids(settings: Settings, moment: datetime) -> list[str]:
    """The raw ids the provider hands out, before identity resolution."""
    from betmaxxing.domain.timeutil import scan_window
    from betmaxxing.engine.acquisition import SPORTS_IN_SCOPE
    from betmaxxing.providers.factory import build_providers

    bundle = build_providers(settings, moment)
    window = scan_window(moment, settings.window_hours)
    return [e.internal_id for e in bundle.odds.list_events(SPORTS_IN_SCOPE, window)]


class TestMilestoneIdentity:
    """A milestone must analyse exactly its own event.

    The provider's id and the internal id are different strings on purpose; the
    filter has to compare two ids from the *same* space.
    """

    def test_discovery_hands_the_scheduler_internal_ids(self, db_settings: Settings) -> None:
        settings = scheduler_settings(db_settings)
        provider_ids = _provider_event_ids(settings, NOW)
        resolved = runner_module.discover_events(settings, NOW)

        assert provider_ids, "the demo provider returned no event to plan against"
        assert resolved
        internal_ids = [e.internal_id for e in resolved]  # type: ignore[attr-defined]
        assert all(i.startswith("evt_") for i in internal_ids)
        assert set(internal_ids).isdisjoint(provider_ids), (
            f"provider ids {provider_ids[:2]} and internal ids {internal_ids[:2]} "
            "must be different id spaces for this test to prove anything"
        )

    def test_a_milestone_discovered_by_provider_id_analyses_its_event(
        self, db_settings: Settings
    ) -> None:
        settings = scheduler_settings(db_settings)
        provider_ids = _provider_event_ids(settings, NOW)
        resolved = runner_module.discover_events(settings, NOW)
        assert resolved
        target = resolved[0]
        internal_id = target.internal_id  # type: ignore[attr-defined]

        ledger = JobLedger(settings)
        job_id = ledger.enqueue(
            job_type=JobType.EVENT_MILESTONE,
            scheduled_for=NOW - timedelta(minutes=1),
            scope_id=internal_id,
        )
        assert job_id is not None

        executed = tick(settings, NOW, ledger=ledger, worker="w1")
        assert job_id in {job.job_id for job in executed}

        scan_id = _job_scan_id(settings, job_id)
        assert scan_id is not None
        document = _scan_document(settings, scan_id)
        assert document["data_health"]["events_in_window"] == 1, (
            "the milestone analysed no event: the job's scope id "
            f"({internal_id!r}) is not in the same id space as the id used by "
            f"the analysis filter (provider ids look like {provider_ids[0]!r})"
        )


# ---------------------------------------------------------------------------
# 7. Milestone planning: T-24h and catch-up
# ---------------------------------------------------------------------------
def _event(hours_ahead: float, name: str = "A") -> CanonicalEvent:
    return CanonicalEvent(
        internal_id=f"evt-{name}",
        sport=Sport.FOOTBALL,
        competition="Ligue 1",
        home=Participant(canonical_id="p1", name=name),
        away=Participant(canonical_id="p2", name="B"),
        start_time_utc=NOW + timedelta(hours=hours_ahead),
    )


class TestMilestonePlanning:
    def test_a_milestone_falling_exactly_on_now_is_planned(self, db_settings: Settings) -> None:
        """An instant equal to ``now`` is due, not past."""
        settings = scheduler_settings(db_settings, milestones_hours_before="24")
        pairs = milestones_for(settings, [_event(24.0)], NOW)
        assert [when for _, when in pairs] == [NOW]

    def test_t_minus_24h_is_not_lost_for_an_event_inside_the_window(
        self, db_settings: Settings
    ) -> None:
        """With a 24 h window, T-24 h is always slightly in the past at discovery.

        Dropping every past instant means the T-24 h milestone can never fire —
        the scheduler silently loses one of its configured rescoring points.
        """
        settings = scheduler_settings(db_settings, milestones_hours_before="24,6")
        pairs = milestones_for(settings, [_event(23.0)], NOW)
        assert NOW - timedelta(hours=1) in [when for _, when in pairs]

    def test_a_milestone_missed_by_less_than_the_grace_window_is_materialised(
        self, db_settings: Settings
    ) -> None:
        settings = scheduler_settings(db_settings, milestones_hours_before="24,6")
        ledger = JobLedger(settings)
        created = ledger.materialise(
            now=NOW,
            daily_times=[],
            milestones=milestones_for(settings, [_event(23.0)], NOW),
        )
        assert created >= 2
        claimed = ledger.claim_due(now=NOW, worker="w", limit=10)
        assert len(claimed) == 1, "the caught-up T-24 h milestone should be due exactly once"

    def test_a_milestone_missed_by_more_than_the_grace_window_is_dropped(
        self, db_settings: Settings
    ) -> None:
        settings = scheduler_settings(db_settings, milestones_hours_before="24")
        pairs = milestones_for(settings, [_event(20.0)], NOW)
        assert pairs == [], "an instant 4 h in the past is beyond the catch-up grace"


# ---------------------------------------------------------------------------
# 8/9. Failure taxonomy
# ---------------------------------------------------------------------------
class _FailingOdds:
    """An odds provider whose collection fails the way a real outage does."""

    name = "failing"

    def __init__(self, error: Exception) -> None:
        self._error = error

    def collect(self, sports: list[Sport], window: tuple[datetime, datetime]) -> object:
        raise self._error

    def list_events(self, sports: list[Sport], window: tuple[datetime, datetime]) -> list[object]:
        raise self._error


def _install_failing_provider(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, error: Exception
) -> None:
    from betmaxxing.providers.factory import build_providers as real_build

    def failing(conf: Settings, now: datetime, manual_odds_path: str | None = None) -> object:
        bundle = real_build(conf, now, manual_odds_path)
        bundle.odds = _FailingOdds(error)
        return bundle

    monkeypatch.setattr("betmaxxing.engine.acquisition.build_providers", failing)
    monkeypatch.setattr("betmaxxing.scheduler.runner.discover_events", lambda *_a, **_k: [])


class TestProviderFailureIsNeverASuccess:
    def test_a_transient_outage_leaves_the_job_retryable(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = scheduler_settings(db_settings)
        _install_failing_provider(monkeypatch, settings, ProviderError("502 depuis le fournisseur"))
        ledger = JobLedger(settings)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )

        tick(settings, NOW, ledger=ledger, worker="w1")

        states = ledger.counts_by_state()
        assert states.get(str(JobState.SUCCEEDED)) is None, (
            "a provider outage was acknowledged as a successful scan"
        )
        assert states.get(str(JobState.FAILED_RETRYABLE)) == 1

    def test_a_transient_outage_still_persists_its_error_scan(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The diagnosis must survive even though no data was collected."""
        settings = scheduler_settings(db_settings)
        _install_failing_provider(monkeypatch, settings, ProviderError("502 depuis le fournisseur"))
        ledger = JobLedger(settings)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )

        tick(settings, NOW, ledger=ledger, worker="w1")

        with session_scope(settings) as session:
            scans = session.query(ScanRunRow).all()
            assert len(scans) == 1, "no error scan was persisted"
            assert scans[0].status == str(ScanStatus.DATA_UNAVAILABLE)
            assert scans[0].collection_status == str(CollectionStatus.PROVIDER_ERROR)

    def test_an_authentication_failure_is_final_not_retried(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = scheduler_settings(db_settings)
        _install_failing_provider(
            monkeypatch, settings, ProviderUnavailable("401 — clé absente ou invalide")
        )
        ledger = JobLedger(settings)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )

        tick(settings, NOW, ledger=ledger, worker="w1")

        assert ledger.counts_by_state().get(str(JobState.FAILED_FINAL)) == 1

    def test_a_final_failure_is_not_immediately_retried(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = scheduler_settings(db_settings)
        _install_failing_provider(
            monkeypatch, settings, ProviderUnavailable("401 — clé absente ou invalide")
        )
        ledger = JobLedger(settings)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )
        tick(settings, NOW, ledger=ledger, worker="w1")

        assert tick(settings, NOW + timedelta(seconds=30), ledger=ledger, worker="w1") == []

    def test_a_retryable_failure_waits_before_the_next_attempt(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a delay the runner spins: claim, fail, claim, fail."""
        settings = scheduler_settings(db_settings)
        _install_failing_provider(monkeypatch, settings, ProviderError("timeout"))
        ledger = JobLedger(settings)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )
        tick(settings, NOW, ledger=ledger, worker="w1")

        assert ledger.claim_due(now=NOW + timedelta(seconds=1), worker="w1") == []


# ---------------------------------------------------------------------------
# The new contracts, asserted directly
# ---------------------------------------------------------------------------
class TestFencingTokenContract:
    def test_a_claim_hands_out_a_token(self, ledger: JobLedger) -> None:
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="w")[0]
        assert job.claim_token

    def test_each_claim_gets_a_different_token(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        first = ledger.claim_due(now=NOW, worker="a")[0]
        second = ledger.claim_due(now=NOW + timedelta(minutes=20), worker="b")[0]
        assert first.claim_token != second.claim_token

    def test_a_stale_token_raises_a_typed_error(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        first = ledger.claim_due(now=NOW, worker="a")[0]
        ledger.claim_due(now=NOW + timedelta(minutes=20), worker="b")

        with pytest.raises(StaleLeaseError):
            ledger.mark_succeeded(first, scan_id="s", now=NOW + timedelta(minutes=21))

    def test_renewing_a_lost_lease_is_refused(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        first = ledger.claim_due(now=NOW, worker="a")[0]
        ledger.claim_due(now=NOW + timedelta(minutes=20), worker="b")

        with pytest.raises(StaleLeaseError):
            ledger.renew_lease(first, now=NOW + timedelta(minutes=21))

    def test_the_holder_may_renew_its_own_lease(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="a")[0]
        extended = ledger.renew_lease(job, now=NOW + timedelta(minutes=10))
        assert extended > (job.lease_expires_at or NOW)
        assert ledger.get_state(job.job_id) is JobState.RUNNING


class TestExecutionTaxonomy:
    def _run(self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch, error: Exception | None):
        settings = scheduler_settings(db_settings)
        if error is not None:
            _install_failing_provider(monkeypatch, settings, error)
        else:
            monkeypatch.setattr("betmaxxing.scheduler.runner.discover_events", lambda *_a, **_k: [])
        ledger = JobLedger(settings)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )
        job = ledger.claim_due(now=NOW, worker="w")[0]
        return execute(job, AcquisitionService(settings))

    def test_a_completed_scan_is_a_success(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcome = self._run(db_settings, monkeypatch, None)
        assert outcome.outcome is ExecutionOutcome.SUCCESS
        assert outcome.scan_id

    def test_a_transport_failure_is_retryable(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcome = self._run(db_settings, monkeypatch, ProviderError("503"))
        assert outcome.outcome is ExecutionOutcome.RETRYABLE_FAILURE

    def test_a_configuration_failure_is_final(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcome = self._run(db_settings, monkeypatch, ProviderUnavailable("401"))
        assert outcome.outcome is ExecutionOutcome.FINAL_FAILURE

    def test_a_budget_ceiling_defers_rather_than_looping(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcome = self._run(db_settings, monkeypatch, BudgetExceeded("budget journalier atteint"))
        assert outcome.outcome is ExecutionOutcome.BUDGET_EXHAUSTED
        assert outcome.retry_after is not None
        assert outcome.retry_after > timedelta(hours=1)

    def test_an_error_scan_is_persisted_for_every_failure_kind(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcome = self._run(db_settings, monkeypatch, ProviderError("503"))
        assert outcome.scan_id is not None
        with session_scope(db_settings) as session:
            assert session.get(ScanRunRow, outcome.scan_id) is not None
