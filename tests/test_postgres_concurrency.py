"""Concurrency guarantees, proven against a real PostgreSQL.

Why this file exists as a separate suite: the previous tranche claimed the
scheduler and the budget were safe for multiple workers, then admitted the proof
was SQLite-only. SQLite serialises *every* writer behind one database-level lock,
so it cannot distinguish a correct algorithm from an incorrect one — under SQLite,
``SELECT SUM(...)`` followed by ``INSERT`` looks atomic. Under PostgreSQL in
``READ COMMITTED`` it is not: two transactions read the same total and both
insert.

Every test here uses **separate sessions**, and the racing ones synchronise with
a ``threading.Barrier`` so the interleaving actually happens. Two sequential
calls are not a concurrency proof; they are two sequential calls.

No sports provider is contacted. The only network endpoint is a local, ephemeral
PostgreSQL holding test rows.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from betmaxxing.config import Settings
from betmaxxing.providers.base import BudgetExceeded
from betmaxxing.providers.budget import ProviderBudgetLedger
from betmaxxing.scheduler.ledger import (
    ClaimedJob,
    JobLedger,
    JobState,
    JobType,
    StaleLeaseError,
)
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import SchedulerJobRow

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
LEASE = timedelta(minutes=15)
EXPIRED = NOW + timedelta(minutes=20)

pytestmark = pytest.mark.postgres


def run_concurrently(count: int, body: Any) -> list[Any]:
    """Run ``body(index)`` in ``count`` threads released by one barrier.

    Returns per-thread ``(result, exception)``. The barrier is what makes this a
    race rather than a sequence.
    """
    barrier = threading.Barrier(count)
    results: list[Any] = [None] * count

    def wrapper(index: int) -> None:
        try:
            barrier.wait(timeout=30)
            results[index] = (body(index), None)
        except BaseException as exc:  # recorded, asserted by the caller
            results[index] = (None, exc)

    threads = [threading.Thread(target=wrapper, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "a worker thread never finished — likely a deadlock"
    return results


def dialect_of(settings: Settings) -> str:
    from betmaxxing.storage.db import get_engine

    return get_engine(settings).dialect.name


# ---------------------------------------------------------------------------
# Sanity: we really are on PostgreSQL
# ---------------------------------------------------------------------------
class TestBackendIsReallyPostgres:
    def test_dialect(self, pg_settings: Settings) -> None:
        assert dialect_of(pg_settings) == "postgresql"

    def test_server_version_is_supported(self, pg_settings: Settings) -> None:
        with session_scope(pg_settings) as session:
            version = session.execute(text("SHOW server_version")).scalar_one()
        major = int(str(version).split(".")[0])
        assert major >= 14, f"PostgreSQL {version} is older than the project supports"


# ---------------------------------------------------------------------------
# Scheduler: claiming, reclaiming, fencing
# ---------------------------------------------------------------------------
class TestConcurrentClaim:
    def test_eight_workers_racing_one_due_job_yield_one_winner(self, pg_settings: Settings) -> None:
        JobLedger(pg_settings).enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None
        )

        def claim(index: int) -> int:
            return len(JobLedger(pg_settings).claim_due(now=NOW, worker=f"w{index}"))

        outcomes = run_concurrently(8, claim)
        for _value, error in outcomes:
            assert error is None, error
        assert sum(value for value, _ in outcomes) == 1

    def test_two_workers_racing_one_expired_lease_yield_one_winner(
        self, pg_settings: Settings
    ) -> None:
        ledger = JobLedger(pg_settings, lease=LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        assert ledger.claim_due(now=NOW, worker="crashed")

        def reclaim(index: int) -> int:
            return len(
                JobLedger(pg_settings, lease=LEASE).claim_due(now=EXPIRED, worker=f"taker-{index}")
            )

        outcomes = run_concurrently(2, reclaim)
        for _value, error in outcomes:
            assert error is None, error
        assert sum(value for value, _ in outcomes) == 1, (
            "both workers reclaimed the same expired lease: the job would run twice"
        )

    def test_the_loser_leaves_no_trace(self, pg_settings: Settings) -> None:
        """A lost race must roll back cleanly: one attempt, one owner."""
        ledger = JobLedger(pg_settings, lease=LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        ledger.claim_due(now=NOW, worker="crashed")

        run_concurrently(
            4,
            lambda i: JobLedger(pg_settings, lease=LEASE).claim_due(
                now=EXPIRED, worker=f"taker-{i}"
            ),
        )

        with session_scope(pg_settings) as session:
            rows = session.query(SchedulerJobRow).all()
            assert len(rows) == 1
            assert rows[0].attempts == 2, f"attempts double-counted: {rows[0].attempts}"
            assert rows[0].lease_owner is not None

    def test_no_worker_blocks_indefinitely(self, pg_settings: Settings) -> None:
        """SKIP LOCKED means a loser returns empty-handed, it does not wait."""
        ledger = JobLedger(pg_settings)
        for minute in range(4):
            ledger.enqueue(
                job_type=JobType.EVENT_MILESTONE,
                scheduled_for=NOW - timedelta(minutes=minute + 1),
                scope_id=f"e{minute}",
            )

        outcomes = run_concurrently(
            4,
            lambda i: [
                job.job_id
                for job in JobLedger(pg_settings).claim_due(now=NOW, worker=f"w{i}", limit=4)
            ],
        )
        for _, error in outcomes:
            assert error is None, error
        claimed = [job_id for value, _ in outcomes for job_id in (value or [])]
        assert len(claimed) == len(set(claimed)), "the same job was claimed twice"
        assert len(claimed) == 4


class TestFencingOnPostgres:
    def _lose_the_lease(self, pg_settings: Settings) -> tuple[JobLedger, ClaimedJob]:
        ledger = JobLedger(pg_settings, lease=LEASE)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        stale = ledger.claim_due(now=NOW, worker="worker-a")[0]
        assert JobLedger(pg_settings, lease=LEASE).claim_due(now=EXPIRED, worker="worker-b")
        return ledger, stale

    def test_stale_ack_is_refused(self, pg_settings: Settings) -> None:
        ledger, stale = self._lose_the_lease(pg_settings)
        with pytest.raises(StaleLeaseError):
            ledger.mark_succeeded(stale, scan_id="stale", now=EXPIRED)
        assert ledger.get_state(stale.job_id) is JobState.RUNNING

    def test_stale_fail_is_refused(self, pg_settings: Settings) -> None:
        ledger, stale = self._lose_the_lease(pg_settings)
        with pytest.raises(StaleLeaseError):
            ledger.mark_failed(stale, error="late", now=EXPIRED)
        assert ledger.get_state(stale.job_id) is JobState.RUNNING

    def test_stale_renew_is_refused(self, pg_settings: Settings) -> None:
        ledger, stale = self._lose_the_lease(pg_settings)
        with pytest.raises(StaleLeaseError):
            ledger.renew_lease(stale, now=EXPIRED)

    def test_the_new_owner_can_still_finish(self, pg_settings: Settings) -> None:
        ledger, stale = self._lose_the_lease(pg_settings)
        with session_scope(pg_settings) as session:
            row = session.get(SchedulerJobRow, stale.job_id)
            assert row is not None
            owner, token = row.lease_owner, row.claim_token
        current = ClaimedJob(
            job_id=stale.job_id,
            job_type=stale.job_type,
            scheduled_for=stale.scheduled_for,
            scope_id=stale.scope_id,
            attempts=2,
            claim_token=str(token),
        )
        ledger.mark_succeeded(current, scan_id="real", now=EXPIRED)
        assert owner == "worker-b"
        assert ledger.get_state(stale.job_id) is JobState.SUCCEEDED


class TestConcurrentMaterialise:
    def test_eight_workers_materialising_create_each_occurrence_once(
        self, pg_settings: Settings
    ) -> None:
        outcomes = run_concurrently(
            8,
            lambda _i: JobLedger(pg_settings).materialise(
                now=NOW, daily_times=["08:00", "12:00", "18:00"], milestones=[]
            ),
        )
        for _, error in outcomes:
            assert error is None, error
        with session_scope(pg_settings) as session:
            rows = session.query(SchedulerJobRow).all()
            keys = {(r.job_type, r.scheduled_for, r.scope_id) for r in rows}
        assert len(rows) == len(keys)

    def test_eight_workers_enqueueing_one_occurrence_create_one_row(
        self, pg_settings: Settings
    ) -> None:
        outcomes = run_concurrently(
            8,
            lambda _i: JobLedger(pg_settings).enqueue(
                job_type=JobType.EVENT_MILESTONE, scheduled_for=NOW, scope_id="evt_x"
            ),
        )
        for _, error in outcomes:
            assert error is None, error
        created = [value for value, _ in outcomes if value]
        assert len(created) == 1, f"{len(created)} workers each believed they created the job"
        with session_scope(pg_settings) as session:
            assert session.query(SchedulerJobRow).count() == 1


class TestTerminalStatesBehaveIdentically:
    """The state machine must not depend on the engine."""

    def test_a_succeeded_job_is_never_reclaimed(self, pg_settings: Settings) -> None:
        ledger = JobLedger(pg_settings)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        claimed = ledger.claim_due(now=NOW, worker="w")[0]
        ledger.mark_succeeded(claimed, scan_id="s", now=NOW)
        assert JobLedger(pg_settings).claim_due(now=EXPIRED, worker="w2") == []

    def test_a_final_failure_is_never_reclaimed(self, pg_settings: Settings) -> None:
        ledger = JobLedger(pg_settings)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        claimed = ledger.claim_due(now=NOW, worker="w")[0]
        ledger.mark_failed(claimed, error="x", retryable=False, now=NOW)
        assert JobLedger(pg_settings).claim_due(now=EXPIRED, worker="w2") == []

    def test_terminal_rows_do_not_starve_a_due_job(self, pg_settings: Settings) -> None:
        ledger = JobLedger(pg_settings)
        for index in range(60):
            ledger.enqueue(
                job_type=JobType.EVENT_MILESTONE,
                scheduled_for=NOW - timedelta(minutes=500 - index),
                scope_id=f"old-{index}",
            )
            claimed = ledger.claim_due(now=NOW, worker="history", limit=1)
            ledger.mark_succeeded(claimed[0], scan_id=f"s{index}", now=NOW)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW - timedelta(minutes=1), scope_id=None
        )
        assert len(ledger.claim_due(now=NOW, worker="w", limit=10)) == 1


# ---------------------------------------------------------------------------
# Budget: the claim the audit disproved
# ---------------------------------------------------------------------------
def budget_settings(pg_settings: Settings, per_day: int) -> Settings:
    return pg_settings.model_copy(update={"provider_budget_per_day": per_day})


class TestConcurrentReservation:
    def test_two_racing_reservations_cannot_exceed_the_daily_ceiling(
        self, pg_settings: Settings
    ) -> None:
        """Each fits alone; together they do not. Exactly one must be refused.

        This is the exact scenario `SELECT SUM(...)` then `INSERT` gets wrong on
        PostgreSQL: both transactions read 0, both insert 3, the day spends 6
        against a ceiling of 5.
        """
        settings = budget_settings(pg_settings, per_day=5)

        def reserve(index: int) -> str:
            try:
                ProviderBudgetLedger(settings).reserve(
                    provider="the_odds_api",
                    cost=3,
                    request=f"odds-{index}",
                    now=NOW,
                )
            except BudgetExceeded:
                return "refused"
            return "granted"

        outcomes = run_concurrently(2, reserve)
        for _value, error in outcomes:
            assert error is None, error
        granted = [v for v, _ in outcomes if v == "granted"]
        assert len(granted) == 1, (
            f"{len(granted)} reservations of 3 credits were granted against a ceiling of 5 "
            "— the day's budget was overspent"
        )
        assert ProviderBudgetLedger(settings).spent_today("the_odds_api", NOW) <= 5

    def test_ten_racing_reservations_stop_exactly_at_the_ceiling(
        self, pg_settings: Settings
    ) -> None:
        settings = budget_settings(pg_settings, per_day=4)

        def reserve(index: int) -> str:
            try:
                ProviderBudgetLedger(settings).reserve(
                    provider="the_odds_api", cost=1, request=f"r{index}", now=NOW
                )
            except BudgetExceeded:
                return "refused"
            return "granted"

        outcomes = run_concurrently(10, reserve)
        for _value, error in outcomes:
            assert error is None, error
        granted = len([v for v, _ in outcomes if v == "granted"])
        assert granted == 4, f"{granted} of 10 reservations granted against a ceiling of 4"
        assert ProviderBudgetLedger(settings).spent_today("the_odds_api", NOW) == 4

    def test_reservation_and_reconciliation_may_race(self, pg_settings: Settings) -> None:
        """Reconciling one attempt while another reserves must keep the counter sane."""
        settings = budget_settings(pg_settings, per_day=100)
        ledger = ProviderBudgetLedger(settings)
        first = ledger.reserve(provider="the_odds_api", cost=4, request="first", now=NOW)

        def worker(index: int) -> None:
            if index == 0:
                ProviderBudgetLedger(settings).reconcile(first, observed_cost=1)
            else:
                ProviderBudgetLedger(settings).reserve(
                    provider="the_odds_api", cost=2, request=f"later-{index}", now=NOW
                )

        outcomes = run_concurrently(4, worker)
        for _, error in outcomes:
            assert error is None, error
        assert ProviderBudgetLedger(settings).verify_invariant("the_odds_api", NOW)

    def test_the_daily_counter_matches_the_detail_after_a_race(self, pg_settings: Settings) -> None:
        settings = budget_settings(pg_settings, per_day=50)
        run_concurrently(
            8,
            lambda i: ProviderBudgetLedger(settings).reserve(
                provider="the_odds_api", cost=2, request=f"r{i}", now=NOW
            ),
        )
        assert ProviderBudgetLedger(settings).verify_invariant("the_odds_api", NOW)


class TestRollbackConsistency:
    def test_a_refused_reservation_writes_no_detail_row(self, pg_settings: Settings) -> None:
        settings = budget_settings(pg_settings, per_day=2)
        ledger = ProviderBudgetLedger(settings)
        ledger.reserve(provider="the_odds_api", cost=2, request="ok", now=NOW)
        with pytest.raises(BudgetExceeded):
            ledger.reserve(provider="the_odds_api", cost=1, request="refused", now=NOW)

        entries = ledger.entries_for_day(NOW, "the_odds_api")
        assert [e.request for e in entries] == ["ok"]
        assert ledger.spent_today("the_odds_api", NOW) == 2
        assert ledger.verify_invariant("the_odds_api", NOW)

    def test_release_cannot_drive_the_counter_negative(self, pg_settings: Settings) -> None:
        settings = budget_settings(pg_settings, per_day=10)
        ledger = ProviderBudgetLedger(settings)
        reservation = ledger.reserve(provider="the_odds_api", cost=3, request="r", now=NOW)
        ledger.release(reservation)
        ledger.release(reservation)
        ledger.release(reservation)
        assert ledger.spent_today("the_odds_api", NOW) == 0
        assert ledger.verify_invariant("the_odds_api", NOW)

    def test_reconcile_is_idempotent(self, pg_settings: Settings) -> None:
        settings = budget_settings(pg_settings, per_day=10)
        ledger = ProviderBudgetLedger(settings)
        reservation = ledger.reserve(provider="the_odds_api", cost=4, request="r", now=NOW)
        ledger.reconcile(reservation, observed_cost=1)
        ledger.reconcile(reservation, observed_cost=1)
        ledger.reconcile(reservation, observed_cost=1)
        assert ledger.spent_today("the_odds_api", NOW) == 1
        assert ledger.verify_invariant("the_odds_api", NOW)

    def test_a_released_reservation_is_not_reconciled_afterwards(
        self, pg_settings: Settings
    ) -> None:
        settings = budget_settings(pg_settings, per_day=10)
        ledger = ProviderBudgetLedger(settings)
        reservation = ledger.reserve(provider="the_odds_api", cost=3, request="r", now=NOW)
        ledger.release(reservation)
        ledger.reconcile(reservation, observed_cost=3)
        assert ledger.spent_today("the_odds_api", NOW) == 0
        assert ledger.verify_invariant("the_odds_api", NOW)


# ---------------------------------------------------------------------------
# The bucket must inherit the spend that already happened
# ---------------------------------------------------------------------------
class TestBudgetBackfill:
    def test_existing_detail_rows_seed_the_counter(self, pg_settings: Settings) -> None:
        """Starting the bucket at zero would hand back a day already spent.

        The detail table survives the upgrade, so the counter is seeded from it.
        A deployment that burned its quota this morning must not get it back
        because a migration ran at lunchtime.
        """
        from betmaxxing.providers.budget import ProviderBudgetLedger, day_key
        from betmaxxing.storage.tables import ProviderBudgetDayRow, ProviderBudgetLedgerRow

        settings = budget_settings(pg_settings, per_day=10)
        with session_scope(settings) as session:
            for index, (reserved, observed, released) in enumerate(
                [(2, 2, False), (3, None, False), (4, 0, True)]
            ):
                session.add(
                    ProviderBudgetLedgerRow(
                        provider="the_odds_api",
                        day_utc=day_key(NOW),
                        request=f"legacy-{index}",
                        reserved_cost=reserved,
                        observed_cost=observed,
                        released=released,
                        created_at=NOW,
                    )
                )
            # Simulate the state right after the schema was created but before the
            # backfill: no bucket row at all.
            session.query(ProviderBudgetDayRow).delete()

        # The migration's arithmetic, applied to the same rows: 2 observed +
        # 3 unknown-so-charged-at-estimate + 0 released = 5.
        with session_scope(settings) as session:
            session.execute(
                text(
                    "INSERT INTO provider_budget_days"
                    " (provider, day_utc, reserved_total, observed_total, updated_at)"
                    " SELECT provider, day_utc,"
                    "        COALESCE(SUM(CASE WHEN released THEN 0"
                    "            ELSE COALESCE(observed_cost, reserved_cost) END), 0),"
                    "        COALESCE(SUM(CASE WHEN released THEN 0"
                    "            ELSE COALESCE(observed_cost, 0) END), 0),"
                    "        MAX(created_at)"
                    "   FROM provider_budget_ledger GROUP BY provider, day_utc"
                )
            )

        ledger = ProviderBudgetLedger(settings)
        assert ledger.spent_today("the_odds_api", NOW) == 5
        assert ledger.verify_invariant("the_odds_api", NOW)
        # 5 of 10 spent, so a 6-credit request must be refused.
        with pytest.raises(BudgetExceeded):
            ledger.reserve(provider="the_odds_api", cost=6, request="after", now=NOW)
