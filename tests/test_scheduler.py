"""Scan planning: schedule construction, DST behaviour and idempotency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import Sport
from betmaxxing.domain.models import CanonicalEvent, Participant
from betmaxxing.domain.timeutil import PARIS, to_display
from betmaxxing.scheduler.planner import (
    daily_jobs,
    due_jobs,
    milestone_jobs,
    plan,
    should_rescore,
)

NOW = datetime(2026, 8, 4, 6, 0, tzinfo=UTC)


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
        canonical_id=f"e-{name}-{hours_ahead}",
        sport=Sport.FOOTBALL,
        competition="Ligue 1",
        home=Participant(canonical_id="p1", name=name),
        away=Participant(canonical_id="p2", name="B"),
        start_time_utc=NOW + timedelta(hours=hours_ahead),
    )


class TestDailyJobs:
    def test_creates_a_job_per_configured_time(self) -> None:
        jobs = daily_jobs(scheduler_settings(), NOW, days=0)
        # 08:00 Paris is 06:00 UTC == now, so only 12:00 and 18:00 remain today.
        assert len(jobs) == 2

    def test_times_are_interpreted_in_the_display_timezone(self) -> None:
        jobs = daily_jobs(scheduler_settings(scan_times="18:00"), NOW, days=0)
        assert to_display(jobs[0].run_at_utc, PARIS).hour == 18

    def test_past_times_today_are_skipped(self) -> None:
        late = datetime(2026, 8, 4, 20, 0, tzinfo=UTC)
        jobs = daily_jobs(scheduler_settings(), late, days=0)
        assert jobs == []

    def test_malformed_entries_are_ignored_not_fatal(self) -> None:
        jobs = daily_jobs(scheduler_settings(scan_times="12:00,not-a-time"), NOW, days=0)
        assert len(jobs) == 1

    def test_jobs_are_sorted_chronologically(self) -> None:
        jobs = daily_jobs(scheduler_settings(), NOW, days=2)
        assert jobs == sorted(jobs, key=lambda j: j.run_at_utc)


class TestDaylightSaving:
    def test_local_scan_time_is_preserved_across_the_spring_change(self) -> None:
        """08:00 in Paris stays 08:00 in Paris, even though the UTC offset moves."""
        before = daily_jobs(
            scheduler_settings(scan_times="08:00"),
            datetime(2026, 3, 28, 0, 0, tzinfo=UTC),
            days=0,
        )
        after = daily_jobs(
            scheduler_settings(scan_times="08:00"),
            datetime(2026, 3, 30, 0, 0, tzinfo=UTC),
            days=0,
        )
        assert to_display(before[0].run_at_utc, PARIS).hour == 8
        assert to_display(after[0].run_at_utc, PARIS).hour == 8
        # The UTC hour differs precisely because the offset changed.
        assert before[0].run_at_utc.hour != after[0].run_at_utc.hour

    def test_local_scan_time_is_preserved_across_the_autumn_change(self) -> None:
        before = daily_jobs(
            scheduler_settings(scan_times="08:00"),
            datetime(2026, 10, 24, 0, 0, tzinfo=UTC),
            days=0,
        )
        after = daily_jobs(
            scheduler_settings(scan_times="08:00"),
            datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
            days=0,
        )
        assert to_display(before[0].run_at_utc, PARIS).hour == 8
        assert to_display(after[0].run_at_utc, PARIS).hour == 8


class TestMilestoneJobs:
    def test_creates_future_milestones_only(self) -> None:
        jobs = milestone_jobs(scheduler_settings(), NOW, [event(5.0)])
        # T-24h and T-12h are already in the past for an event 5 hours away.
        assert {j.detail.split()[1] for j in jobs} == {"T-2h", "T-1h", "T-0.25h"}

    def test_no_milestones_for_an_event_already_started(self) -> None:
        assert milestone_jobs(scheduler_settings(), NOW, [event(-1.0)]) == []

    def test_milestones_are_attached_to_their_event(self) -> None:
        target = event(5.0)
        jobs = milestone_jobs(scheduler_settings(), NOW, [target])
        assert all(j.event_canonical_id == target.canonical_id for j in jobs)

    def test_multiple_events_each_get_milestones(self) -> None:
        jobs = milestone_jobs(scheduler_settings(), NOW, [event(5.0, "A"), event(8.0, "B")])
        assert len({j.event_canonical_id for j in jobs}) == 2


class TestPlan:
    def test_disabled_scheduler_plans_nothing(self) -> None:
        assert plan(scheduler_settings(scheduler_enabled=False), NOW, [event(5.0)]) == []

    def test_combines_daily_and_milestone_jobs(self) -> None:
        jobs = plan(scheduler_settings(), NOW, [event(5.0)])
        assert {j.kind for j in jobs} == {"daily", "milestone"}

    def test_job_keys_are_unique(self) -> None:
        jobs = plan(scheduler_settings(), NOW, [event(5.0), event(5.0)])
        keys = [j.job_key for j in jobs]
        assert len(keys) == len(set(keys))

    def test_job_keys_are_deterministic(self) -> None:
        first = plan(scheduler_settings(), NOW, [event(5.0)])
        second = plan(scheduler_settings(), NOW, [event(5.0)])
        assert [j.job_key for j in first] == [j.job_key for j in second]


class TestDueJobsIdempotency:
    def test_only_jobs_whose_time_has_come_are_due(self) -> None:
        jobs = plan(scheduler_settings(), NOW, [event(5.0)])
        assert due_jobs(jobs, NOW, set()) == []

    def test_completed_jobs_are_never_rerun(self) -> None:
        """The property that makes a restart mid-run safe."""
        jobs = plan(scheduler_settings(), NOW, [event(5.0)])
        later = NOW + timedelta(hours=12)
        first_pass = due_jobs(jobs, later, set())
        assert first_pass
        completed = {j.job_key for j in first_pass}
        assert due_jobs(jobs, later, completed) == []

    def test_a_partially_completed_pass_resumes_correctly(self) -> None:
        jobs = plan(scheduler_settings(), NOW, [event(5.0)])
        later = NOW + timedelta(hours=12)
        all_due = due_jobs(jobs, later, set())
        completed = {all_due[0].job_key}
        remaining = due_jobs(jobs, later, completed)
        assert len(remaining) == len(all_due) - 1


class TestRescoreTrigger:
    def test_a_material_move_triggers_a_rescore(self) -> None:
        assert should_rescore(2.00, 2.06)

    def test_a_negligible_move_does_not(self) -> None:
        assert not should_rescore(2.00, 2.01)

    def test_direction_does_not_matter(self) -> None:
        assert should_rescore(2.00, 1.94)

    def test_threshold_is_configurable(self) -> None:
        assert should_rescore(2.00, 2.01, threshold=0.001)
