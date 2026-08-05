"""A job that outlives its lease must not be executed twice.

`renew_lease()` existed after the previous tranche, and nothing called it. The
fencing token stops the original worker from *acknowledging* — it does not undo
the provider requests, the rows it wrote, or the messages it sent. So a scan
lasting longer than the lease was executed twice, with two sets of side effects,
and only the bookkeeping was protected.

These tests use short leases and a deliberately slow unit of work, so a real
elapsed-time race happens rather than a simulated one.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import CollectionStatus
from betmaxxing.scheduler import runner as runner_module
from betmaxxing.scheduler.ledger import JobLedger, JobState, JobType, StaleLeaseError
from betmaxxing.scheduler.runner import tick
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import SchedulerJobRow

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def lease_guard(*args: object, **kwargs: object) -> object:
    """Imported at call time: the symbol is introduced by this tranche, and a
    module-level import would turn every test here into one collection error
    instead of individual, readable failures."""
    from betmaxxing.scheduler.runner import LeaseGuard

    return LeaseGuard(*args, **kwargs)  # type: ignore[arg-type]


#: Deliberately tiny so a test can outlive two of them without being slow.
SHORT_LEASE = timedelta(milliseconds=600)


def heartbeat_settings(db_settings: Settings, **overrides: object) -> Settings:
    payload: dict[str, object] = {
        "mode": RunMode.DEMO,
        "database_url": db_settings.database_url,
        "scheduler_enabled": True,
        "notifications_enabled": False,
        "staking_enabled": False,
        "scan_times": "",
    }
    payload.update(overrides)
    return Settings(**payload)  # type: ignore[arg-type]


class SlowService:
    """Stands in for AcquisitionService, with a controllable duration."""

    def __init__(self, duration: float, *, raises: Exception | None = None) -> None:
        self.duration = duration
        self.raises = raises
        self.calls: list[str | None] = []
        self._lock = threading.Lock()

    def resolve_identities(self, events: object, *, provider: str) -> list[object]:
        return []

    def run(self, *, scope_event_id: str | None = None, **_: object) -> object:
        with self._lock:
            self.calls.append(scope_event_id)
        time.sleep(self.duration)
        if self.raises is not None:
            raise self.raises
        return _FakeResult()


class _FakeScan:
    scan_id = "scan-slow"
    status = "NO_CANDIDATE"
    collection_status = CollectionStatus.NO_CANDIDATE
    candidates: ClassVar[list[object]] = []
    warnings: ClassVar[list[str]] = []


class _FakeResult:
    scan = _FakeScan()
    snapshots_persisted = 0
    failure = None


@pytest.fixture(autouse=True)
def _no_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module, "discover_events", lambda *_a, **_k: [])


# ---------------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------------
class TestLeaseGuard:
    def test_it_renews_before_the_lease_expires(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=SHORT_LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="holder")[0]

        with lease_guard(ledger, job) as guard:
            time.sleep(SHORT_LEASE.total_seconds() * 3)
            assert not guard.lost
            assert guard.renewals >= 2, f"only {guard.renewals} renewals in three lease spans"

    def test_a_second_worker_cannot_take_a_renewed_lease(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=SHORT_LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="holder")[0]

        with lease_guard(ledger, job):
            time.sleep(SHORT_LEASE.total_seconds() * 2.5)
            # Real wall-clock now, not the frozen planning instant.
            from betmaxxing.domain.timeutil import utc_now

            stolen = JobLedger(db_settings, lease=SHORT_LEASE).claim_due(
                now=utc_now(), worker="thief"
            )
        assert stolen == []

    def test_the_thread_is_joined_on_success(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=SHORT_LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="holder")[0]

        guard = lease_guard(ledger, job)
        with guard:
            time.sleep(0.05)
        assert not guard.running

    def test_the_thread_is_joined_on_exception(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=SHORT_LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="holder")[0]

        guard = lease_guard(ledger, job)
        with pytest.raises(RuntimeError), guard:
            raise RuntimeError("boom")
        assert not guard.running

    def test_the_thread_is_joined_when_the_lease_is_lost(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=SHORT_LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="holder")[0]

        guard = lease_guard(ledger, job)
        with guard:
            # Somebody else forcibly takes ownership: the token no longer matches.
            with session_scope(db_settings) as session:
                row = session.get(SchedulerJobRow, job.job_id)
                assert row is not None
                row.claim_token = "someone-elses-token"
            time.sleep(SHORT_LEASE.total_seconds() * 2)
        assert guard.lost
        assert not guard.running

    def test_the_renewal_cadence_is_shorter_than_the_lease(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=timedelta(seconds=30))
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="holder")[0]
        guard = lease_guard(ledger, job)
        assert guard.interval < timedelta(seconds=30)

    def test_a_lost_guard_refuses_to_certify_ownership(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings, lease=SHORT_LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="holder")[0]
        guard = lease_guard(ledger, job)
        with guard:
            with session_scope(db_settings) as session:
                row = session.get(SchedulerJobRow, job.job_id)
                assert row is not None
                row.claim_token = "gone"
            time.sleep(SHORT_LEASE.total_seconds() * 2)
            assert not guard.owns_lease()


# ---------------------------------------------------------------------------
# The runner, end to end
# ---------------------------------------------------------------------------
class TestWorkLongerThanTwoLeases:
    def test_the_job_runs_exactly_once(self, db_settings: Settings) -> None:
        """The scenario the audit described: work longer than two lease spans.

        The planning instant is the real clock here, not the fixed 2026 constant
        the rest of the file uses: this test is about elapsed time, and a claim
        stamped in the past would be reclaimable before the work even starts —
        which would test the initial-claim race, not the heartbeat.
        """
        from betmaxxing.domain.timeutil import utc_now

        settings = heartbeat_settings(db_settings)
        ledger = JobLedger(settings, lease=SHORT_LEASE)
        planning = utc_now()
        job_id = ledger.enqueue(
            job_type=JobType.DAILY_SCAN,
            scheduled_for=planning - timedelta(minutes=1),
            scope_id=None,
        )
        service = SlowService(duration=SHORT_LEASE.total_seconds() * 3)

        thief_saw: list[int] = []

        def steal() -> None:
            # Wait until the job is genuinely RUNNING, then hammer it for the rest
            # of the work. With a heartbeat the lease never lapses, so every
            # attempt must come back empty-handed.
            deadline = time.monotonic() + SHORT_LEASE.total_seconds() * 6
            while time.monotonic() < deadline:
                if ledger.get_state(str(job_id)) is JobState.RUNNING:
                    break
                time.sleep(0.02)
            while time.monotonic() < deadline:
                if ledger.get_state(str(job_id)) is not JobState.RUNNING:
                    return
                claimed = JobLedger(settings, lease=SHORT_LEASE).claim_due(
                    now=utc_now(), worker="thief"
                )
                if claimed:
                    thief_saw.append(len(claimed))
                    return
                time.sleep(0.05)

        thief = threading.Thread(target=steal)
        thief.start()
        executed = tick(settings, planning, ledger=ledger, service=service, worker="holder")
        thief.join(timeout=15)

        assert thief_saw == [], "a second worker claimed the job while it was still running"
        assert len(service.calls) == 1, f"the work ran {len(service.calls)} times"
        assert job_id in {job.job_id for job in executed}
        assert ledger.get_state(str(job_id)) is JobState.SUCCEEDED

    def test_a_lost_lease_prevents_acknowledgement(self, db_settings: Settings) -> None:
        """Losing the lease mid-scan must not produce a SUCCEEDED job."""
        from betmaxxing.domain.timeutil import utc_now

        settings = heartbeat_settings(db_settings)
        ledger = JobLedger(settings, lease=SHORT_LEASE)
        planning = utc_now()
        job_id = ledger.enqueue(
            job_type=JobType.DAILY_SCAN,
            scheduled_for=planning - timedelta(minutes=1),
            scope_id=None,
        )
        service = SlowService(duration=SHORT_LEASE.total_seconds() * 3)

        def steal_ownership() -> None:
            time.sleep(SHORT_LEASE.total_seconds() * 0.5)
            with session_scope(settings) as session:
                row = session.get(SchedulerJobRow, str(job_id))
                assert row is not None
                row.claim_token = "hijacked"
                row.lease_owner = "other"

        thief = threading.Thread(target=steal_ownership)
        thief.start()
        executed = tick(settings, planning, ledger=ledger, service=service, worker="holder")
        thief.join(timeout=10)

        assert executed == [], "the job was acknowledged under a lost lease"
        assert ledger.get_state(str(job_id)) is not JobState.SUCCEEDED

    def test_the_completion_uses_the_current_clock_not_the_planning_instant(
        self, db_settings: Settings
    ) -> None:
        settings = heartbeat_settings(db_settings)
        ledger = JobLedger(settings, lease=SHORT_LEASE)
        job_id = ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )
        tick(
            settings,
            NOW,
            ledger=ledger,
            service=SlowService(duration=0.2),
            worker="holder",
        )
        with session_scope(settings) as session:
            row = session.get(SchedulerJobRow, str(job_id))
            assert row is not None
            finished = row.finished_at
        assert finished is not None
        # NOW is a fixed 2026 instant; a real clock cannot equal it.
        assert finished.replace(tzinfo=UTC) != NOW


class TestNotificationsAreNotDuplicated:
    def test_the_outbox_admits_one_entry_per_job_and_key(self, db_settings: Settings) -> None:
        from betmaxxing.providers.notifications.outbox import NotificationOutbox

        outbox = NotificationOutbox(db_settings)
        first = outbox.claim(job_id="job-1", alert_key="alert-1", channel="console", now=NOW)
        second = outbox.claim(job_id="job-1", alert_key="alert-1", channel="console", now=NOW)
        assert first is True
        assert second is False

    def test_a_second_execution_of_the_same_job_sends_nothing_new(
        self, db_settings: Settings
    ) -> None:
        from betmaxxing.providers.notifications.outbox import NotificationOutbox

        outbox = NotificationOutbox(db_settings)
        for _attempt in range(3):
            outbox.claim(job_id="job-1", alert_key="alert-1", channel="console", now=NOW)
        from betmaxxing.storage.tables import NotificationOutboxRow

        with session_scope(db_settings) as session:
            assert session.query(NotificationOutboxRow).count() == 1

    def test_different_channels_are_separate_effects(self, db_settings: Settings) -> None:
        from betmaxxing.providers.notifications.outbox import NotificationOutbox

        outbox = NotificationOutbox(db_settings)
        assert outbox.claim(job_id="j", alert_key="a", channel="console", now=NOW)
        assert outbox.claim(job_id="j", alert_key="a", channel="telegram", now=NOW)

    def test_concurrent_claims_admit_exactly_one(self, db_settings: Settings) -> None:
        from betmaxxing.providers.notifications.outbox import NotificationOutbox

        results: list[bool] = []
        lock = threading.Lock()
        barrier = threading.Barrier(6)

        def claim() -> None:
            barrier.wait(timeout=20)
            granted = NotificationOutbox(db_settings).claim(
                job_id="j", alert_key="a", channel="console", now=NOW
            )
            with lock:
                results.append(granted)

        threads = [threading.Thread(target=claim) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert results.count(True) == 1

    def test_a_worker_without_the_lease_cannot_publish(self, db_settings: Settings) -> None:
        """Publishing is an external effect: it needs a valid lease, not just a row."""
        ledger = JobLedger(db_settings, lease=SHORT_LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        job = ledger.claim_due(now=NOW, worker="holder")[0]
        with session_scope(db_settings) as session:
            row = session.get(SchedulerJobRow, job.job_id)
            assert row is not None
            row.claim_token = "hijacked"

        with pytest.raises(StaleLeaseError):
            ledger.assert_owns(job)


class TestOutcomeTaxonomyIncludesLeaseLoss:
    def test_lease_lost_is_its_own_outcome(self) -> None:
        from betmaxxing.scheduler.runner import ExecutionOutcome

        assert ExecutionOutcome.LEASE_LOST in set(ExecutionOutcome)

    def test_lease_loss_is_not_a_success(self) -> None:
        from betmaxxing.scheduler.runner import ExecutionOutcome, ExecutionResult

        result = ExecutionResult(
            outcome=ExecutionOutcome.LEASE_LOST, scan_id=None, collection_status=None
        )
        assert not result.is_success
