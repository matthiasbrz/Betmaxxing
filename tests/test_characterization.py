"""Characterization tests for the defects found after the initial delivery.

These were written **before** the fixes, and each one failed against
d22f0778. They stay in the suite as regression guards.

Each test names the defect it pins in its docstring so the
defect -> test -> fix -> proof matrix in the report can be reconstructed from
the code alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import (
    MarketType,
    Period,
    Sport,
    UncertaintyStatus,
    ValidationStatus,
)
from betmaxxing.domain.models import CanonicalEvent, Participant, Selection
from betmaxxing.engine.payoff import (
    SettlementRule,
    draw_no_bet_outcomes,
    expected_value_from_outcomes,
    two_way_outcomes,
)
from betmaxxing.scheduler.ledger import JobLedger, JobType

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def make_event(hours: float = 5.0, name: str = "A") -> CanonicalEvent:
    return CanonicalEvent(
        internal_id=f"evt-{name}",
        sport=Sport.FOOTBALL,
        competition="Ligue 1",
        home=Participant(canonical_id="p1", name=name),
        away=Participant(canonical_id="p2", name="B"),
        start_time_utc=NOW + timedelta(hours=hours),
    )


# ---------------------------------------------------------------------------
# D-01 — the scheduler tick could never find work
# ---------------------------------------------------------------------------


class TestSchedulerFindsDueWork:
    """`plan(now)` dropped `run_at <= now`; `due_jobs(now)` kept only
    `run_at <= now`. Planning and selecting from the same instant made the
    intersection provably empty, so a real tick never executed anything."""

    def test_a_job_scheduled_in_the_past_is_due_now(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN,
            scheduled_for=NOW - timedelta(minutes=5),
            scope_id=None,
        )
        claimed = ledger.claim_due(now=NOW, worker="w1")
        assert len(claimed) == 1

    def test_a_job_scheduled_exactly_now_is_due(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings)
        ledger.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        assert len(ledger.claim_due(now=NOW, worker="w1")) == 1

    def test_a_future_job_is_not_due(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings)
        ledger.enqueue(
            job_type=JobType.DAILY_SCAN,
            scheduled_for=NOW + timedelta(minutes=5),
            scope_id=None,
        )
        assert ledger.claim_due(now=NOW, worker="w1") == []


# ---------------------------------------------------------------------------
# D-02 — scheduler idempotency lived in memory
# ---------------------------------------------------------------------------


class TestSchedulerStateSurvivesRestart:
    """`completed` was an in-process `set()`. A restart lost it, so the
    documented "resumes exactly where it left off" was not guaranteed."""

    def test_a_succeeded_job_is_not_reclaimed_by_a_new_process(self, db_settings: Settings) -> None:
        first = JobLedger(db_settings)
        first.enqueue(job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None)
        claimed = first.claim_due(now=NOW, worker="w1")
        first.mark_succeeded(claimed[0], scan_id="s1")

        # A brand new ledger stands in for a restarted process.
        restarted = JobLedger(db_settings)
        assert restarted.claim_due(now=NOW, worker="w2") == []

    def test_a_pending_job_survives_a_restart(self, db_settings: Settings) -> None:
        JobLedger(db_settings).enqueue(
            job_type=JobType.DAILY_SCAN, scheduled_for=NOW, scope_id=None
        )
        assert len(JobLedger(db_settings).claim_due(now=NOW, worker="w2")) == 1


# ---------------------------------------------------------------------------
# D-03 — milestone jobs did not target their event
# ---------------------------------------------------------------------------


class TestMilestoneTargetsItsEvent:
    """A milestone carried `event_canonical_id`, but execution ignored it and
    ran a global scan."""

    def test_milestone_job_carries_and_returns_its_scope(self, db_settings: Settings) -> None:
        ledger = JobLedger(db_settings)
        ledger.enqueue(job_type=JobType.EVENT_MILESTONE, scheduled_for=NOW, scope_id="evt-A")
        claimed = ledger.claim_due(now=NOW, worker="w1")
        assert claimed[0].scope_id == "evt-A"
        assert claimed[0].job_type is JobType.EVENT_MILESTONE


# ---------------------------------------------------------------------------
# D-05 — model status was hard-coded
# ---------------------------------------------------------------------------


class TestModelStatusComesFromTheRegistry:
    """`prediction_status()` deleted both arguments and always returned
    `BACKTEST_ONLY`, so a candidate's status was decoration, not provenance."""

    def test_status_reflects_the_registered_model(self) -> None:
        from betmaxxing.models_ml.football import FootballDixonColesModel
        from betmaxxing.models_ml.registry import ModelRegistry, RegisteredModel
        from betmaxxing.providers.demo.world import football_inputs

        model = FootballDixonColesModel(football_inputs(NOW))
        registry = ModelRegistry(
            models={
                Sport.FOOTBALL: RegisteredModel(
                    model=model,
                    version="1.0.0",
                    validation_status=ValidationStatus.PAPER_VALIDATED,
                )
            }
        )
        entry = registry.get(Sport.FOOTBALL)
        assert entry is not None
        assert entry.validation_status is ValidationStatus.PAPER_VALIDATED
        assert entry.model_id == model.model_id


# ---------------------------------------------------------------------------
# D-06 — Wilson bounds were presented as model uncertainty
# ---------------------------------------------------------------------------


class TestUncertaintyIsNotFabricatedOutsideDemo:
    """A Wilson interval describes an observed binomial proportion. Applied
    around `p_model` with `n x INFORMATION_PER_MATCH` it propagated neither
    parameter uncertainty nor calibration, yet gated real candidates."""

    @pytest.mark.parametrize("mode", [RunMode.PAPER, RunMode.LIVE_ANALYSIS])
    def test_real_modes_report_uncertainty_as_unavailable(self, mode: RunMode) -> None:
        from betmaxxing.engine.uncertainty import uncertainty_for_mode

        estimate = uncertainty_for_mode(
            mode=mode, probability=0.6, effective_sample_size=420.0, z=1.6449
        )
        assert estimate.status is UncertaintyStatus.UNAVAILABLE
        assert estimate.lower is None
        assert estimate.upper is None

    def test_demo_uncertainty_is_marked_synthetic(self) -> None:
        from betmaxxing.engine.uncertainty import uncertainty_for_mode

        estimate = uncertainty_for_mode(
            mode=RunMode.DEMO, probability=0.6, effective_sample_size=420.0, z=1.6449
        )
        assert estimate.status is UncertaintyStatus.SYNTHETIC
        assert estimate.lower is not None and estimate.upper is not None
        assert "SYNTHETIC" in estimate.warning


# ---------------------------------------------------------------------------
# D-07 — event identity was derived from date + participants
# ---------------------------------------------------------------------------


class TestEventIdentityIsStable:
    """Identity derived from `(sport, UTC date, participants)` meant a
    postponement across midnight minted a *new* event, and two legs on one day
    collided into one."""

    def test_a_postponement_keeps_the_same_internal_event(self, db_settings: Settings) -> None:
        from betmaxxing.ingestion.identity import EventIdentityService

        service = EventIdentityService(db_settings)
        first = service.resolve(
            provider="p",
            provider_event_id="X1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Lyon",
            away_name="Rennes",
            start_time_utc=datetime(2026, 8, 4, 23, 30, tzinfo=UTC),
        )
        # Pushed past midnight UTC — the old scheme changed the date component.
        second = service.resolve(
            provider="p",
            provider_event_id="X1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Lyon",
            away_name="Rennes",
            start_time_utc=datetime(2026, 8, 5, 0, 30, tzinfo=UTC),
        )
        assert first.internal_id == second.internal_id

    def test_two_distinct_fixtures_stay_distinct(self, db_settings: Settings) -> None:
        from betmaxxing.ingestion.identity import EventIdentityService

        service = EventIdentityService(db_settings)
        leg_one = service.resolve(
            provider="p",
            provider_event_id="L1",
            sport=Sport.TENNIS,
            competition="ATP",
            home_name="A",
            away_name="B",
            start_time_utc=datetime(2026, 8, 4, 10, 0, tzinfo=UTC),
        )
        leg_two = service.resolve(
            provider="p",
            provider_event_id="L2",
            sport=Sport.TENNIS,
            competition="ATP",
            home_name="A",
            away_name="B",
            start_time_utc=datetime(2026, 8, 4, 20, 0, tzinfo=UTC),
        )
        assert leg_one.internal_id != leg_two.internal_id


# ---------------------------------------------------------------------------
# D-08 — market line identity depended on a float
# ---------------------------------------------------------------------------


class TestLineIdentityIsNotAFloat:
    """`line` was a `float` rendered with `%g` into a text key, so identity
    depended on binary floating-point rendering."""

    def test_equivalent_decimal_spellings_share_one_identity(self) -> None:
        a = Selection(
            market=MarketType.TOTAL_GOALS,
            period=Period.FULL_TIME,
            code="over",
            label="+2.5",
            line=Decimal("2.5"),
        )
        b = Selection(
            market=MarketType.TOTAL_GOALS,
            period=Period.FULL_TIME,
            code="over",
            label="+2.50",
            line=Decimal("2.500"),
        )
        assert a.key == b.key
        assert a.line_canonical == "2.5"

    def test_genuinely_different_lines_stay_distinct(self) -> None:
        a = Selection(
            market=MarketType.TOTAL_GOALS,
            period=Period.FULL_TIME,
            code="over",
            label="+2.5",
            line=Decimal("2.5"),
        )
        b = Selection(
            market=MarketType.TOTAL_GOALS,
            period=Period.FULL_TIME,
            code="over",
            label="+2.75",
            line=Decimal("2.75"),
        )
        assert a.key != b.key

    def test_line_is_rejected_when_not_representable_exactly(self) -> None:
        with pytest.raises(ValueError):
            Selection(
                market=MarketType.TOTAL_GOALS,
                period=Period.FULL_TIME,
                code="over",
                label="bad",
                line=Decimal("NaN"),
            )


# ---------------------------------------------------------------------------
# D-09 — draw-no-bet EV ignored the void outcome
# ---------------------------------------------------------------------------


class TestDrawNoBetEvUsesThePayoff:
    """DNB EV was `p_conditional * o - 1`, i.e. a Bernoulli with no push. The
    draw refunds the stake, so the true EV per unit staked is smaller in
    magnitude by exactly the decisive-outcome mass."""

    def test_ev_accounts_for_the_refunded_draw(self) -> None:
        p_win, p_draw, p_loss = 0.4846, 0.2629, 0.2525
        odds = 1.46
        outcomes = draw_no_bet_outcomes(
            p_win=p_win, p_push=p_draw, p_loss=p_loss, decimal_odds=odds
        )
        ev = expected_value_from_outcomes(outcomes)

        # Correct payoff: win pays (o-1), draw returns the stake, loss costs 1.
        assert ev == pytest.approx(p_win * (odds - 1) - p_loss)

        # The old conditional formula overstated the magnitude.
        p_conditional = p_win / (p_win + p_loss)
        naive = p_conditional * odds - 1
        assert abs(naive) > abs(ev)
        # Exact algebraic relation: EV = (1 - p_push) x EV_conditional.
        assert ev == pytest.approx((p_win + p_loss) * naive)

    def test_a_market_without_push_is_unchanged(self) -> None:
        """Regression guard: the fix must not move 1X2 or half-line totals."""
        p, odds = 0.6573, 1.63
        outcomes = two_way_outcomes(p_win=p, decimal_odds=odds)
        assert expected_value_from_outcomes(outcomes) == pytest.approx(p * odds - 1)

    def test_probabilities_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError):
            draw_no_bet_outcomes(p_win=0.5, p_push=0.3, p_loss=0.4, decimal_odds=2.0)

    def test_settlement_rule_is_recorded(self) -> None:
        outcomes = draw_no_bet_outcomes(p_win=0.48, p_push=0.26, p_loss=0.26, decimal_odds=1.9)
        assert outcomes.rule is SettlementRule.STAKE_REFUNDED_ON_PUSH


# ---------------------------------------------------------------------------
# D-10 — the Challenge was announced complete but lived in memory
# ---------------------------------------------------------------------------


class TestChallengeIsOffByDefault:
    """It had no feature flag, its state was a module-level dict, its tables
    were never wired, and the default staked 100% of the bank."""

    def test_disabled_by_default(self) -> None:
        assert Settings().challenge_enabled is False

    def test_default_fraction_is_not_the_whole_bank(self) -> None:
        from betmaxxing.challenge import ChallengeConfig

        config = ChallengeConfig(initial_bank=100.0, target_bank=200.0)
        assert config.fraction_per_step < 1.0


# ---------------------------------------------------------------------------
# D-11 — real collection had no persistence path
# ---------------------------------------------------------------------------


class TestSourceDataIsPersisted:
    """`run_scan()` fetched events and snapshots, but every caller persisted
    only the scan document. The source data — the one thing that cannot be
    re-downloaded — was dropped."""

    def test_a_scan_persists_events_and_snapshots(self, db_settings: Settings) -> None:
        from betmaxxing.engine.acquisition import AcquisitionService
        from betmaxxing.storage.db import session_scope
        from betmaxxing.storage.repositories import EventRepository, OddsRepository

        result = AcquisitionService(db_settings).run(now=NOW)
        assert result.batch.snapshots

        with session_scope(db_settings) as session:
            assert OddsRepository(session).count() == len(result.batch.snapshots)
            assert EventRepository(session).count() >= result.data_health.events_in_window
