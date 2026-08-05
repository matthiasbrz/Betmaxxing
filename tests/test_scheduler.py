"""Scheduler: due-work semantics, durability, concurrency and DST.

The defect these replace: ``plan(now)`` dropped occurrences at or before ``now``
while ``due_jobs(now)`` kept only occurrences at or before ``now``, so a real
tick could never find work. The ledger separates *when an occurrence exists*
from *when it becomes claimable*, which is what makes "due" expressible at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import Sport
from betmaxxing.domain.models import CanonicalEvent, Participant
from betmaxxing.domain.timeutil import PARIS, to_display
from betmaxxing.scheduler.ledger import (
    DEFAULT_CATCHUP_GRACE,
    MAX_ATTEMPTS,
    JobLedger,
    JobState,
    JobType,
    occurrence_id,
)
from betmaxxing.scheduler.planner import daily_instants, milestone_instants, should_rescore

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def scheduler_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "mode": RunMode.DEMO,
        "scheduler_enabled": True,
        "scan_times": "08:00,12:00,18:00",
        "milestones_hours_before": "24,12,6,2,1,0.25",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def event(hours_ahead: float, name: str = "A") -> CanonicalEvent:
    return CanonicalEvent(
        internal_id=f"evt-{name}-{hours_ahead}",
        sport=Sport.FOOTBALL,
        competition="Ligue 1",
        home=Participant(canonical_id="p1", name=name),
        away=Participant(canonical_id="p2", name="B"),
        start_time_utc=NOW + timedelta(hours=hours_ahead),
    )


@pytest.fixture
def ledger(db_settings: Settings) -> JobLedger:
    return JobLedger(db_settings)


class TestDueSemantics:
    """The core regression: a tick must actually find work."""

    def test_a_past_occurrence_is_due(self, ledger: JobLedger) -> None:
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN,
            scheduled_for=NOW - timedelta(minutes=5),
            scope_id=None,
        )
        assert len(ledger.claim_due(now=NOW, worker="w1")) == 1

    def test_an_occurrence_exactly_now_is_due(self, ledger: JobLedger) -> None:
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        assert len(ledger.claim_due(now=NOW, worker="w1")) == 1

    def test_a_future_occurrence_is_not_due(self, ledger: JobLedger) -> None:
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN,
            scheduled_for=NOW + timedelta(minutes=1),
            scope_id=None,
        )
        assert ledger.claim_due(now=NOW, worker="w1") == []

    def test_materialise_then_claim_finds_work_after_the_first_time_passes(
        self, ledger: JobLedger
    ) -> None:
        """End-to-end shape of a real tick."""
        ledger.materialise(now=NOW, daily_times=["18:00"], milestones=[])
        assert ledger.claim_due(now=NOW, worker="w1") == []
        # 18:00 Paris == 16:00 UTC in August.
        later = NOW.replace(hour=17)
        assert len(ledger.claim_due(now=later, worker="w1")) == 1


class TestIdempotency:
    def test_the_same_occurrence_is_enqueued_once(self, ledger: JobLedger) -> None:
        first = ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        second = ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        assert first is not None
        assert second is None

    def test_two_identical_ticks_create_no_duplicates(self, ledger: JobLedger) -> None:
        created_first = ledger.materialise(now=NOW, daily_times=["18:00"], milestones=[])
        created_again = ledger.materialise(now=NOW, daily_times=["18:00"], milestones=[])
        assert created_first > 0
        assert created_again == 0

    def test_occurrence_id_is_deterministic(self) -> None:
        a = occurrence_id(JobType.DAILY_SCAN, NOW, "")
        b = occurrence_id(JobType.DAILY_SCAN, NOW, "")
        assert a == b

    def test_occurrence_id_separates_scopes(self) -> None:
        assert occurrence_id(JobType.EVENT_MILESTONE, NOW, "e1") != occurrence_id(
            JobType.EVENT_MILESTONE, NOW, "e2"
        )

    def test_seconds_do_not_split_an_occurrence(self) -> None:
        assert occurrence_id(JobType.DAILY_SCAN, NOW, "") == occurrence_id(
            JobType.DAILY_SCAN, NOW.replace(second=42), ""
        )


class TestRestartDurability:
    def test_a_succeeded_job_is_not_reclaimed_after_restart(self, db_settings: Settings) -> None:
        first = JobLedger(db_settings)
        first.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        claimed = first.claim_due(now=NOW, worker="w1")
        first.mark_succeeded(claimed[0], scan_id="s1")

        restarted = JobLedger(db_settings)
        assert restarted.claim_due(now=NOW, worker="w2") == []

    def test_a_pending_job_survives_restart(self, db_settings: Settings) -> None:
        JobLedger(db_settings).enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None
        )
        assert len(JobLedger(db_settings).claim_due(now=NOW, worker="w2")) == 1

    def test_an_expired_running_lease_is_reclaimed(self, db_settings: Settings) -> None:
        """The crashed-worker path: the lease expires, the work is not lost."""
        ledger = JobLedger(db_settings, lease=timedelta(minutes=15))
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        first = ledger.claim_due(now=NOW, worker="crashed")
        assert len(first) == 1

        # Before the lease expires nobody may take it.
        assert ledger.claim_due(now=NOW + timedelta(minutes=5), worker="other") == []
        # After it expires, another worker may.
        recovered = ledger.claim_due(now=NOW + timedelta(minutes=20), worker="other")
        assert len(recovered) == 1
        assert recovered[0].attempts == 2

    def test_a_crash_between_collection_and_ack_leaves_the_job_retryable(
        self, db_settings: Settings
    ) -> None:
        ledger = JobLedger(db_settings)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        claimed = ledger.claim_due(now=NOW, worker="w1")
        # Simulate a failure after the work started but before acknowledgement.
        ledger.mark_failed(claimed[0], error="boom", now=NOW)
        assert ledger.get_state(claimed[0].job_id) is JobState.FAILED_RETRYABLE
        # Retryable, but not immediately: the backoff exists so the runner does
        # not claim-fail-claim in a tight loop.
        assert ledger.claim_due(now=NOW, worker="w2") == []
        assert len(ledger.claim_due(now=NOW + timedelta(hours=1), worker="w2")) == 1

    def test_repeated_failure_is_parked_as_final(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        moment = NOW
        for _ in range(MAX_ATTEMPTS):
            claimed = ledger.claim_due(now=moment, worker="w")
            if not claimed:
                break
            ledger.mark_failed(claimed[0], error="boom", now=moment)
            moment += timedelta(hours=1)  # past the retry backoff
        assert ledger.claim_due(now=moment, worker="w") == []
        assert ledger.counts_by_state().get(str(JobState.FAILED_FINAL)) == 1


class TestConcurrency:
    def test_two_workers_do_not_execute_the_same_occurrence(self, db_settings: Settings) -> None:
        """Claiming is a conditional UPDATE; the loser sees zero rows changed."""
        ledger_a = JobLedger(db_settings)
        ledger_b = JobLedger(db_settings)
        ledger_a.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)

        first = ledger_a.claim_due(now=NOW, worker="worker-a")
        second = ledger_b.claim_due(now=NOW, worker="worker-b")

        assert len(first) == 1
        assert second == []

    def test_two_workers_share_a_queue_of_distinct_jobs(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings)
        for minutes in (1, 2, 3, 4):
            ledger.enqueue(
                job_type=JobType.EVENT_MILESTONE,
                scheduled_for=NOW - timedelta(minutes=minutes),
                scope_id=f"e{minutes}",
            )
        a = ledger.claim_due(now=NOW, worker="a", limit=2)
        b = ledger.claim_due(now=NOW, worker="b", limit=2)
        assert len(a) == 2
        assert len(b) == 2
        assert {j.job_id for j in a}.isdisjoint({j.job_id for j in b})


class TestMilestoneScoping:
    def test_a_milestone_carries_its_event(self, ledger: JobLedger) -> None:
        ledger.enqueue(job_type=JobType.EVENT_MILESTONE, scheduled_for=NOW, scope_id="evt-42")
        claimed = ledger.claim_due(now=NOW, worker="w1")
        assert claimed[0].scope_id == "evt-42"
        assert claimed[0].is_event_scoped

    def test_a_daily_scan_is_not_event_scoped(self, ledger: JobLedger) -> None:
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        claimed = ledger.claim_due(now=NOW, worker="w1")
        assert claimed[0].scope_id is None
        assert not claimed[0].is_event_scoped

    def test_milestones_for_two_events_stay_separate(self, ledger: JobLedger) -> None:
        created = ledger.materialise(
            now=NOW,
            daily_times=[],
            milestones=[("e1", NOW + timedelta(hours=1)), ("e2", NOW + timedelta(hours=1))],
        )
        assert created == 2


class TestCatchUpPolicy:
    def test_a_long_outage_does_not_replay_a_burst(self, ledger: JobLedger) -> None:
        """Replaying a day of missed scans would burn quota for stale analyses."""
        much_later = NOW + timedelta(days=1)
        created = ledger.materialise(
            now=much_later, daily_times=["08:00", "12:00", "18:00"], milestones=[]
        )
        due = ledger.claim_due(now=much_later, worker="w", limit=100)
        assert created > 0
        # Only occurrences inside the grace window are replayed.
        assert len(due) <= 3

    def test_occurrences_older_than_the_grace_window_are_skipped(self, ledger: JobLedger) -> None:
        stale = NOW - DEFAULT_CATCHUP_GRACE - timedelta(hours=5)
        assert ledger.materialise(now=NOW, daily_times=[], milestones=[("e1", stale)]) == 0


class TestDaylightSaving:
    @pytest.mark.parametrize(
        "moment",
        [
            datetime(2026, 3, 28, 0, 0, tzinfo=UTC),
            datetime(2026, 3, 30, 0, 0, tzinfo=UTC),
            datetime(2026, 10, 24, 0, 0, tzinfo=UTC),
            datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
        ],
    )
    def test_local_scan_time_is_preserved_across_transitions(self, moment: datetime) -> None:
        """08:00 in Paris stays 08:00 in Paris; its UTC hour is what moves."""
        instants = daily_instants(scheduler_settings(scan_times="08:00"), moment, days=0)
        assert instants
        assert all(to_display(i, PARIS).hour == 8 for i in instants)

    def test_utc_hour_differs_either_side_of_the_spring_change(self) -> None:
        before = daily_instants(
            scheduler_settings(scan_times="08:00"),
            datetime(2026, 3, 28, 0, 0, tzinfo=UTC),
            days=0,
        )
        after = daily_instants(
            scheduler_settings(scan_times="08:00"),
            datetime(2026, 3, 30, 0, 0, tzinfo=UTC),
            days=0,
        )
        assert before[0].hour != after[0].hour

    def test_ledger_stores_utc_instants(self, ledger: JobLedger) -> None:
        ledger.materialise(now=NOW, daily_times=["18:00"], milestones=[])
        claimed = ledger.claim_due(now=NOW.replace(hour=23), worker="w")
        assert claimed
        assert claimed[0].scheduled_for.tzinfo is not None
        assert claimed[0].scheduled_for.utcoffset() == timedelta(0)


class TestPlannerArithmetic:
    def test_daily_instants_are_in_the_future(self) -> None:
        for instant in daily_instants(scheduler_settings(), NOW, days=1):
            assert instant > NOW

    def test_malformed_times_are_ignored(self) -> None:
        assert len(daily_instants(scheduler_settings(scan_times="12:00,nope"), NOW, days=0)) <= 1

    def test_milestones_are_future_only(self) -> None:
        pairs = milestone_instants(scheduler_settings(), NOW, [event(5.0)])
        assert pairs
        assert all(when > NOW for _, when in pairs)

    def test_no_milestones_for_a_started_event(self) -> None:
        assert milestone_instants(scheduler_settings(), NOW, [event(-1.0)]) == []

    def test_milestones_are_attached_to_their_event(self) -> None:
        target = event(5.0)
        pairs = milestone_instants(scheduler_settings(), NOW, [target])
        assert all(event_id == target.internal_id for event_id, _ in pairs)


class TestRescoreTrigger:
    def test_a_material_move_triggers_a_rescore(self) -> None:
        assert should_rescore(2.00, 2.06)

    def test_a_negligible_move_does_not(self) -> None:
        assert not should_rescore(2.00, 2.01)

    def test_direction_does_not_matter(self) -> None:
        assert should_rescore(2.00, 1.94)

    def test_threshold_is_configurable(self) -> None:
        assert should_rescore(2.00, 2.01, threshold=0.001)
