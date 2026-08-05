"""What happens when the day's provider budget is gone.

The previous tranche returned a flat six-hour delay and called it "pushed past
midnight". At 08:00 UTC that lands at 14:00 — squarely inside the same budget
window, where the retry cannot possibly succeed. Worse, each deferral consumed
one of the three provider-failure attempts, so three budget refusals parked a
perfectly healthy job as ``FAILED_FINAL``.

The policy pinned here:

* a budget refusal never consumes the provider-failure attempt counter;
* the next attempt is the next **UTC reset boundary**, plus a small deterministic
  jitter so a fleet of workers does not stampede at 00:00:00;
* a job that will be worthless after the reset — its event has started, or its
  catch-up window has closed — is finished as ``SKIPPED_BUDGET`` with a reason
  and an audit scan, rather than deferred into irrelevance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.providers.base import BudgetExceeded
from betmaxxing.scheduler import runner as runner_module
from betmaxxing.scheduler.ledger import (
    MAX_ATTEMPTS,
    JobLedger,
    JobState,
    JobType,
)
from betmaxxing.scheduler.runner import tick
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import ScanRunRow, SchedulerJobRow

#: Resolved leniently so this module collects on 5d2109f, where the two states
#: this tranche introduces do not exist yet.
DEFERRED = getattr(JobState, "DEFERRED", "DEFERRED")
SKIPPED_BUDGET = getattr(JobState, "SKIPPED_BUDGET", "SKIPPED_BUDGET")


def next_budget_reset(moment: datetime, *, job_id: str) -> datetime:
    """Call-time import: introduced by this tranche."""
    from betmaxxing.scheduler.runner import next_budget_reset as implementation

    return implementation(moment, job_id=job_id)


def reset_settings(db_settings: Settings, **overrides: object) -> Settings:
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


class _BudgetlessOdds:
    name = "the_odds_api"
    bookmaker = "winamax_fr"

    def collect(self, sports: list[object], window: tuple[datetime, datetime]) -> object:
        raise BudgetExceeded("budget journalier de 450 crédits atteint — appel refusé.")

    def list_events(self, sports: list[object], window: tuple[datetime, datetime]) -> list[object]:
        raise BudgetExceeded("budget journalier atteint")


@pytest.fixture
def exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    from betmaxxing.providers.factory import build_providers as real_build

    def failing(conf: Settings, now: datetime, manual_odds_path: str | None = None) -> object:
        bundle = real_build(conf, now, manual_odds_path)
        bundle.odds = _BudgetlessOdds()
        return bundle

    monkeypatch.setattr("betmaxxing.engine.acquisition.build_providers", failing)
    monkeypatch.setattr(runner_module, "discover_events", lambda *_a, **_k: [])


# ---------------------------------------------------------------------------
# The reset boundary itself
# ---------------------------------------------------------------------------
class TestNextBudgetReset:
    @pytest.mark.parametrize(
        ("moment", "expected_day"),
        [
            (datetime(2026, 8, 4, 0, 1, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)),
            (datetime(2026, 8, 4, 8, 0, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)),
            (datetime(2026, 8, 4, 23, 59, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)),
            (datetime(2026, 8, 4, 0, 0, tzinfo=UTC), datetime(2026, 8, 5, tzinfo=UTC)),
            (datetime(2026, 12, 31, 23, 59, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
        ],
        ids=["00:01", "08:00", "23:59", "midnight", "year-boundary"],
    )
    def test_it_is_the_next_utc_midnight(self, moment: datetime, expected_day: datetime) -> None:
        reset = next_budget_reset(moment, job_id="")
        assert reset.date() == expected_day.date()
        assert reset >= expected_day

    def test_it_is_always_in_the_future(self) -> None:
        for hour in range(24):
            moment = datetime(2026, 8, 4, hour, 30, tzinfo=UTC)
            assert next_budget_reset(moment, job_id="abc") > moment

    def test_the_jitter_is_deterministic_per_job(self) -> None:
        moment = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
        first = next_budget_reset(moment, job_id="job-a")
        again = next_budget_reset(moment, job_id="job-a")
        other = next_budget_reset(moment, job_id="job-b")
        assert first == again
        assert first != other

    def test_the_jitter_stays_small(self) -> None:
        moment = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
        boundary = datetime(2026, 8, 5, tzinfo=UTC)
        for index in range(50):
            reset = next_budget_reset(moment, job_id=f"job-{index}")
            assert timedelta(0) <= reset - boundary < timedelta(minutes=15)

    def test_a_moment_just_before_midnight_does_not_defer_a_whole_day(self) -> None:
        moment = datetime(2026, 8, 4, 23, 59, tzinfo=UTC)
        assert next_budget_reset(moment, job_id="j") - moment < timedelta(hours=1)


# ---------------------------------------------------------------------------
# What the runner does with it
# ---------------------------------------------------------------------------
def far_milestone(settings: Settings, ledger: JobLedger, moment: datetime) -> str:
    """A milestone whose event is comfortably past the next reset boundary.

    The deferral cases need a job that is still *worth* running tomorrow. A daily
    scan is not: its catch-up grace closes two hours after it was planned, so by
    the next UTC midnight it is stale by the ledger's own rule — which is why it
    is skipped rather than deferred (see the next class).
    """
    from betmaxxing.domain.enums import Sport
    from betmaxxing.ingestion.identity import EventIdentityService

    resolution = EventIdentityService(settings).resolve(
        provider="p",
        provider_event_id="e-far",
        sport=Sport.FOOTBALL,
        competition="Ligue 1",
        home_name="A",
        away_name="B",
        # Two days out: still valuable after tomorrow's budget reset.
        start_time_utc=moment + timedelta(days=2),
    )
    job_id = ledger.enqueue(
        job_type=JobType.EVENT_MILESTONE,
        scheduled_for=moment - timedelta(minutes=1),
        scope_id=str(resolution.internal_id),
    )
    assert job_id is not None
    return job_id


class TestBudgetExhaustionIsNotAProviderFailure:
    MOMENT = datetime(2026, 8, 4, 8, 1, tzinfo=UTC)

    def test_the_job_is_deferred_not_failed(self, db_settings: Settings, exhausted: None) -> None:
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        job_id = far_milestone(settings, ledger, self.MOMENT)
        tick(settings, self.MOMENT, ledger=ledger, worker="w", clock=lambda: self.MOMENT)

        assert ledger.get_state(job_id) is DEFERRED

    def test_it_does_not_consume_the_failure_counter(
        self, db_settings: Settings, exhausted: None
    ) -> None:
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        job_id = far_milestone(settings, ledger, self.MOMENT)
        tick(settings, self.MOMENT, ledger=ledger, worker="w", clock=lambda: self.MOMENT)

        with session_scope(settings) as session:
            row = session.get(SchedulerJobRow, job_id)
            assert row is not None
            assert row.attempts == 0, (
                f"a budget refusal consumed attempt {row.attempts} of {MAX_ATTEMPTS}"
            )

    def test_repeated_budget_refusals_never_reach_final_failure(
        self, db_settings: Settings, exhausted: None
    ) -> None:
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        job_id = far_milestone(settings, ledger, self.MOMENT)
        moment = self.MOMENT
        for _ in range(MAX_ATTEMPTS + 2):
            frozen = moment
            tick(settings, frozen, ledger=ledger, worker="w", clock=lambda f=frozen: f)
            moment += timedelta(days=1)

        assert ledger.get_state(job_id) is not JobState.FAILED_FINAL

    def test_the_next_attempt_is_after_the_reset_boundary(
        self, db_settings: Settings, exhausted: None
    ) -> None:
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        job_id = far_milestone(settings, ledger, self.MOMENT)
        tick(settings, self.MOMENT, ledger=ledger, worker="w", clock=lambda: self.MOMENT)

        with session_scope(settings) as session:
            row = session.get(SchedulerJobRow, job_id)
            assert row is not None
            assert row.next_attempt_at is not None
            next_at = row.next_attempt_at.replace(tzinfo=UTC)
        assert next_at >= datetime(2026, 8, 5, tzinfo=UTC), (
            f"the retry at {next_at.isoformat()} is inside the same UTC budget window"
        )

    def test_it_is_not_claimable_before_the_reset(
        self, db_settings: Settings, exhausted: None
    ) -> None:
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        far_milestone(settings, ledger, self.MOMENT)
        tick(settings, self.MOMENT, ledger=ledger, worker="w", clock=lambda: self.MOMENT)

        assert ledger.claim_due(now=datetime(2026, 8, 4, 20, 0, tzinfo=UTC), worker="w2") == []

    def test_it_becomes_claimable_after_the_reset(
        self, db_settings: Settings, exhausted: None
    ) -> None:
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        far_milestone(settings, ledger, self.MOMENT)
        tick(settings, self.MOMENT, ledger=ledger, worker="w", clock=lambda: self.MOMENT)

        later = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)
        assert len(ledger.claim_due(now=later, worker="w2")) == 1

    def test_a_reclaim_after_the_reset_starts_from_attempt_one(
        self, db_settings: Settings, exhausted: None
    ) -> None:
        """The deferral gave the attempt back, so the retry is attempt 1 again."""
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        far_milestone(settings, ledger, self.MOMENT)
        tick(settings, self.MOMENT, ledger=ledger, worker="w", clock=lambda: self.MOMENT)

        claimed = ledger.claim_due(now=datetime(2026, 8, 5, 1, 0, tzinfo=UTC), worker="w2")
        assert claimed and claimed[0].attempts == 1

    def test_an_audit_scan_is_persisted(self, db_settings: Settings, exhausted: None) -> None:
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        far_milestone(settings, ledger, self.MOMENT)
        tick(settings, self.MOMENT, ledger=ledger, worker="w", clock=lambda: self.MOMENT)

        with session_scope(settings) as session:
            assert session.query(ScanRunRow).count() == 1

    def test_the_reason_names_the_budget(self, db_settings: Settings, exhausted: None) -> None:
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        job_id = far_milestone(settings, ledger, self.MOMENT)
        tick(settings, self.MOMENT, ledger=ledger, worker="w", clock=lambda: self.MOMENT)

        with session_scope(settings) as session:
            row = session.get(SchedulerJobRow, job_id)
            assert row is not None
            assert row.error and "budget" in row.error.lower()


class TestAJobThatExpiresBeforeTheResetIsSkipped:
    def test_a_milestone_whose_event_has_started_is_skipped(
        self, db_settings: Settings, exhausted: None
    ) -> None:
        """Deferring it past midnight would run it after kick-off — useless."""
        from betmaxxing.domain.enums import Sport
        from betmaxxing.ingestion.identity import EventIdentityService

        settings = reset_settings(db_settings)
        identity = EventIdentityService(settings)
        resolution = identity.resolve(
            provider="p",
            provider_event_id="e1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="A",
            away_name="B",
            start_time_utc=datetime(2026, 8, 4, 18, 0, tzinfo=UTC),
        )
        ledger = JobLedger(settings)
        job_id = ledger.enqueue(
            job_type=JobType.EVENT_MILESTONE,
            scheduled_for=datetime(2026, 8, 4, 16, 0, tzinfo=UTC),
            scope_id=str(resolution.internal_id),
        )
        moment = datetime(2026, 8, 4, 16, 1, tzinfo=UTC)
        tick(settings, moment, ledger=ledger, worker="w", clock=lambda: moment)

        assert ledger.get_state(str(job_id)) is SKIPPED_BUDGET

    def test_a_skipped_job_records_its_reason(self, db_settings: Settings, exhausted: None) -> None:
        from betmaxxing.domain.enums import Sport
        from betmaxxing.ingestion.identity import EventIdentityService

        settings = reset_settings(db_settings)
        resolution = EventIdentityService(settings).resolve(
            provider="p",
            provider_event_id="e1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="A",
            away_name="B",
            start_time_utc=datetime(2026, 8, 4, 18, 0, tzinfo=UTC),
        )
        ledger = JobLedger(settings)
        job_id = ledger.enqueue(
            job_type=JobType.EVENT_MILESTONE,
            scheduled_for=datetime(2026, 8, 4, 16, 0, tzinfo=UTC),
            scope_id=str(resolution.internal_id),
        )
        moment = datetime(2026, 8, 4, 16, 1, tzinfo=UTC)
        tick(settings, moment, ledger=ledger, worker="w", clock=lambda: moment)

        with session_scope(settings) as session:
            row = session.get(SchedulerJobRow, str(job_id))
            assert row is not None
            assert row.error and "budget" in row.error.lower()

    def test_a_skipped_job_is_terminal(self, db_settings: Settings, exhausted: None) -> None:
        from betmaxxing.domain.enums import Sport
        from betmaxxing.ingestion.identity import EventIdentityService

        settings = reset_settings(db_settings)
        resolution = EventIdentityService(settings).resolve(
            provider="p",
            provider_event_id="e1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="A",
            away_name="B",
            start_time_utc=datetime(2026, 8, 4, 18, 0, tzinfo=UTC),
        )
        ledger = JobLedger(settings)
        ledger.enqueue(
            job_type=JobType.EVENT_MILESTONE,
            scheduled_for=datetime(2026, 8, 4, 16, 0, tzinfo=UTC),
            scope_id=str(resolution.internal_id),
        )
        moment = datetime(2026, 8, 4, 16, 1, tzinfo=UTC)
        tick(settings, moment, ledger=ledger, worker="w", clock=lambda: moment)

        assert ledger.claim_due(now=datetime(2026, 8, 6, tzinfo=UTC), worker="w2") == []

    def test_a_daily_scan_is_skipped_rather_than_deferred_past_its_grace(
        self, db_settings: Settings, exhausted: None
    ) -> None:
        """A daily scan's value expires two hours after it was planned.

        The ledger already refuses to *materialise* an occurrence older than the
        catch-up grace, because replaying a stale scan burns quota to produce a
        stale analysis. Deferring one to the next midnight would resurrect
        exactly what that rule forbids, so the occurrence is finished as
        ``SKIPPED_BUDGET``. Tomorrow's occurrences are materialised normally —
        budget exhaustion costs one scan, not the schedule.
        """
        settings = reset_settings(db_settings)
        ledger = JobLedger(settings)
        job_id = ledger.enqueue(
            job_type=JobType.DAILY_SCAN,
            scheduled_for=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
            scope_id=None,
        )
        moment = datetime(2026, 8, 4, 8, 1, tzinfo=UTC)
        tick(settings, moment, ledger=ledger, worker="w", clock=lambda: moment)

        assert ledger.get_state(str(job_id)) is SKIPPED_BUDGET

    def test_tomorrows_daily_scan_is_unaffected(
        self, db_settings: Settings, exhausted: None
    ) -> None:
        settings = reset_settings(db_settings, scan_times="08:00")
        ledger = JobLedger(settings)
        skipped = ledger.enqueue(
            job_type=JobType.DAILY_SCAN,
            scheduled_for=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
            scope_id=None,
        )
        moment = datetime(2026, 8, 4, 8, 1, tzinfo=UTC)
        tick(settings, moment, ledger=ledger, worker="w", clock=lambda: moment)
        assert ledger.get_state(str(skipped)) is SKIPPED_BUDGET

        # Tomorrow's 08:00 Paris occurrence exists and is untouched: skipping one
        # occurrence costs one scan, not the schedule.
        with session_scope(settings) as session:
            pending = [
                row
                for row in session.query(SchedulerJobRow).all()
                if row.state == str(JobState.PENDING)
                and row.scheduled_for.replace(tzinfo=UTC) > moment
            ]
        assert pending, "budget exhaustion removed the following days' scans"
