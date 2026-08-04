"""Challenge — Montante: state machine, money rounding, and the safety
properties that make this module acceptable at all."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from betmaxxing.challenge import (
    Challenge,
    ChallengeConfig,
    ChallengeError,
    from_cents,
    propose_step,
    to_cents,
)
from betmaxxing.domain.enums import (
    BetOutcome,
    ChallengeState,
    MarketType,
    Period,
    Sport,
    ValidationStatus,
)
from betmaxxing.domain.models import (
    Candidate,
    CanonicalEvent,
    DataQuality,
    Participant,
    ProbabilityEstimate,
    Selection,
    ValueAssessment,
)

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


def make_config(**overrides: object) -> ChallengeConfig:
    base: dict[str, object] = {
        "initial_bank": 100.0,
        "target_bank": 400.0,
        "min_odds": 1.20,
        "max_odds": 3.00,
        "max_loss": 0.0,
    }
    base.update(overrides)
    return ChallengeConfig(**base)  # type: ignore[arg-type]


def make_candidate(odds: float = 2.0, sport: Sport = Sport.TENNIS) -> Candidate:
    event = CanonicalEvent(
        canonical_id="e1",
        sport=sport,
        competition="ATP",
        home=Participant(canonical_id="p1", name="A"),
        away=Participant(canonical_id="p2", name="B"),
        start_time_utc=NOW,
    )
    selection = Selection(
        market=MarketType.MATCH_WINNER, period=Period.FULL_TIME, code="home", label="A"
    )
    return Candidate(
        candidate_id="c1",
        event=event,
        selection=selection,
        bookmaker="DEMO_BOOK",
        provider="demo",
        observed_at=NOW,
        odds_age_seconds=30.0,
        value=ValueAssessment(
            decimal_odds=odds,
            implied_probability_raw=1 / odds,
            implied_probability_novig=1 / odds - 0.02,
            devig_method="shin",
            model_probability=0.56,
            model_probability_lower=0.52,
            model_probability_upper=0.60,
            fair_odds=1 / 0.56,
            ev=0.56 * odds - 1,
            ev_conservative=0.52 * odds - 1,
            min_acceptable_odds=1.05 / 0.56,
            ev_sensitivity_per_odds_tick=0.0056,
            overround=1.05,
        ),
        probability=ProbabilityEstimate(
            probability=0.56,
            lower=0.52,
            upper=0.60,
            effective_sample_size=300.0,
            model_id="m1",
            validation_status=ValidationStatus.BACKTEST_ONLY,
        ),
        data_quality=DataQuality(score=0.95, components={}),
        confidence={"score": 0.7, "label": "moyenne"},
        evidence=[],
        risks=["risque test"],
        missing_information=[],
        invalidation_conditions=[],
        model_id="m1",
        config_fingerprint="fp",
    )


@pytest.fixture
def challenge() -> Challenge:
    c = Challenge.create(make_config())
    c.activate()
    return c


class TestMoneyRounding:
    def test_cents_round_half_up(self) -> None:
        assert to_cents(10.005) == 1001
        assert to_cents(10.004) == 1000
        assert to_cents(0.1 + 0.2) == 30

    def test_round_trip_is_stable(self) -> None:
        for amount in (0.01, 1.0, 33.33, 99.99, 1234.56):
            assert from_cents(to_cents(amount)) == pytest.approx(amount)

    def test_progression_does_not_leak_value_through_rounding(self) -> None:
        c = Challenge.create(make_config(initial_bank=33.33, target_bank=1000.0))
        c.activate()
        for _ in range(4):
            if c.is_terminal:
                break
            c.propose(make_candidate(odds=1.87))
            c.confirm(1.87)
            c.settle(BetOutcome.WON, proof="test")
        # Every rung's arithmetic must reconcile exactly in integer cents.
        for step in c.steps:
            if step.outcome is BetOutcome.WON:
                expected = (
                    step.bank_before_cents
                    - step.stake_cents
                    + to_cents(from_cents(step.stake_cents) * (step.accepted_odds or 0))
                )
                assert step.bank_after_cents == expected


class TestConfigValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"initial_bank": 0.0},
            {"target_bank": 50.0},
            {"fraction_per_step": 0.0},
            {"fraction_per_step": 1.5},
            {"min_odds": 1.0},
            {"max_odds": 1.1},
            {"max_loss": 100.0},
        ],
    )
    def test_invalid_configuration_is_refused(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ChallengeError):
            make_config(**overrides)


class TestStateMachine:
    def test_starts_as_draft(self) -> None:
        assert Challenge.create(make_config()).state is ChallengeState.DRAFT

    def test_activation_moves_to_waiting(self, challenge: Challenge) -> None:
        assert challenge.state is ChallengeState.WAITING_FOR_CANDIDATE

    def test_cannot_activate_twice(self, challenge: Challenge) -> None:
        with pytest.raises(ChallengeError):
            challenge.activate()

    def test_full_happy_path(self, challenge: Challenge) -> None:
        challenge.propose(make_candidate(2.0))
        assert challenge.state is ChallengeState.AWAITING_USER_CONFIRMATION
        challenge.confirm(1.98)
        assert challenge.state is ChallengeState.AWAITING_RESULT
        challenge.settle(BetOutcome.WON, proof="capture d'écran")
        assert challenge.state is ChallengeState.WAITING_FOR_CANDIDATE
        assert challenge.bank == pytest.approx(198.0)

    def test_cannot_confirm_without_a_proposal(self, challenge: Challenge) -> None:
        with pytest.raises(ChallengeError):
            challenge.confirm(2.0)

    def test_cannot_settle_without_a_confirmation(self, challenge: Challenge) -> None:
        challenge.propose(make_candidate(2.0))
        with pytest.raises(ChallengeError):
            challenge.settle(BetOutcome.WON, proof="x")

    def test_pending_is_not_a_settlement(self, challenge: Challenge) -> None:
        challenge.propose(make_candidate(2.0))
        challenge.confirm(2.0)
        with pytest.raises(ChallengeError):
            challenge.settle(BetOutcome.PENDING, proof="x")


class TestManualConfirmationIsRequired:
    def test_proposal_alone_does_not_move_the_bank(self, challenge: Challenge) -> None:
        before = challenge.bank_cents
        challenge.propose(make_candidate(2.0))
        assert challenge.bank_cents == before

    def test_accepted_odds_are_recorded_separately_from_detected_odds(
        self, challenge: Challenge
    ) -> None:
        challenge.propose(make_candidate(2.10))
        step = challenge.confirm(1.95)
        assert step.detected_odds == 2.10
        assert step.accepted_odds == 1.95

    def test_settlement_uses_the_accepted_odds(self, challenge: Challenge) -> None:
        challenge.propose(make_candidate(2.10))
        challenge.confirm(1.95)
        challenge.settle(BetOutcome.WON, proof="ticket")
        assert challenge.bank == pytest.approx(195.0)

    def test_invalid_accepted_odds_are_refused(self, challenge: Challenge) -> None:
        challenge.propose(make_candidate(2.0))
        with pytest.raises(ChallengeError):
            challenge.confirm(0.9)


class TestOutcomes:
    @pytest.mark.parametrize(
        ("outcome", "expected_bank"),
        [
            (BetOutcome.WON, 200.0),
            (BetOutcome.LOST, 0.0),
            (BetOutcome.VOID, 100.0),
            (BetOutcome.CANCELLED, 100.0),
            (BetOutcome.POSTPONED, 100.0),
            (BetOutcome.HALF_WON, 150.0),
            (BetOutcome.HALF_LOST, 50.0),
        ],
    )
    def test_each_outcome_settles_correctly(
        self, outcome: BetOutcome, expected_bank: float
    ) -> None:
        c = Challenge.create(make_config(max_loss=0.0))
        c.activate()
        c.propose(make_candidate(2.0))
        c.confirm(2.0)
        c.settle(outcome, proof="test")
        assert c.bank == pytest.approx(expected_bank)

    def test_void_does_not_end_the_progression(self) -> None:
        c = Challenge.create(make_config())
        c.activate()
        c.propose(make_candidate(2.0))
        c.confirm(2.0)
        c.settle(BetOutcome.VOID, proof="match reporté")
        assert c.state is ChallengeState.WAITING_FOR_CANDIDATE
        assert c.bank == pytest.approx(100.0)


class TestStopRules:
    def test_a_loss_ends_the_progression_by_default(self) -> None:
        """Staking half the bank, so the loss rule fires rather than the floor.

        With the default full-bank stake a loss also trips ``max_loss``; this
        isolates the first-loss policy itself.
        """
        c = Challenge.create(make_config(fraction_per_step=0.5, max_loss=0.0))
        c.activate()
        c.propose(make_candidate(2.0))
        c.confirm(2.0)
        c.settle(BetOutcome.LOST, proof="résultat")
        assert c.state is ChallengeState.LOST
        assert c.bank == pytest.approx(50.0)
        assert "récupération" in c.stop_reason

    def test_first_loss_policy_can_be_disabled_but_still_stops_at_the_floor(self) -> None:
        c = Challenge.create(
            make_config(fraction_per_step=0.5, max_loss=0.0, stop_on_first_loss=False)
        )
        c.activate()
        c.propose(make_candidate(2.0))
        c.confirm(2.0)
        c.settle(BetOutcome.LOST, proof="résultat")
        assert c.state is ChallengeState.WAITING_FOR_CANDIDATE
        assert c.bank == pytest.approx(50.0)

    def test_reaching_the_target_stops_the_progression(self) -> None:
        c = Challenge.create(make_config(initial_bank=100.0, target_bank=150.0))
        c.activate()
        c.propose(make_candidate(2.0))
        c.confirm(2.0)
        c.settle(BetOutcome.WON, proof="résultat")
        assert c.state is ChallengeState.TARGET_REACHED

    def test_max_loss_floor_stops_the_progression(self) -> None:
        c = Challenge.create(make_config(initial_bank=100.0, max_loss=60.0, fraction_per_step=0.5))
        c.activate()
        c.propose(make_candidate(2.0))
        c.confirm(2.0)
        c.settle(BetOutcome.LOST, proof="résultat")
        assert c.state is ChallengeState.LOST
        assert c.bank == pytest.approx(50.0)

    def test_voluntary_stop_is_always_available(self, challenge: Challenge) -> None:
        challenge.stop("Arrêt volontaire.")
        assert challenge.state is ChallengeState.STOPPED
        assert challenge.is_terminal

    def test_max_steps_stops_the_progression(self) -> None:
        c = Challenge.create(make_config(initial_bank=100.0, target_bank=1e6, max_steps=2))
        c.activate()
        for _ in range(2):
            c.propose(make_candidate(1.5))
            c.confirm(1.5)
            c.settle(BetOutcome.WON, proof="résultat")
        assert c.state is ChallengeState.STOPPED


class TestNoMartingale:
    def test_stake_never_depends_on_previous_results(self) -> None:
        """The defining safety property of this module.

        After a half-loss the bank is smaller, so the next stake must be smaller
        too. A martingale would raise it. ``next_stake_cents`` reads only the
        current bank, which makes the recovery bet unrepresentable.
        """
        c = Challenge.create(make_config(fraction_per_step=0.5, max_loss=0.0))
        c.activate()
        first_stake = c.next_stake_cents()
        c.propose(make_candidate(2.0))
        c.confirm(2.0)
        c.settle(BetOutcome.HALF_LOST, proof="résultat")
        assert c.state is ChallengeState.LOST  # default policy ends it

        # With the stop disabled, the next stake still falls with the bank.
        c2 = Challenge.create(make_config(fraction_per_step=0.5, stop_on_first_loss=False))
        c2.activate()
        c2.propose(make_candidate(2.0))
        c2.confirm(2.0)
        c2.settle(BetOutcome.HALF_LOST, proof="résultat")
        assert c2.bank_cents < to_cents(100.0)
        assert c2.next_stake_cents() < first_stake

    def test_next_stake_is_a_pure_function_of_the_current_bank(self) -> None:
        c = Challenge.create(make_config(fraction_per_step=0.4))
        c.activate()
        assert c.next_stake_cents() == to_cents(100.0 * 0.4)
        c.bank_cents = to_cents(250.0)
        assert c.next_stake_cents() == to_cents(250.0 * 0.4)


class TestNoThresholdRelaxation:
    def test_candidates_outside_the_odds_range_are_refused(self, challenge: Challenge) -> None:
        with pytest.raises(ChallengeError, match="hors de la plage"):
            challenge.propose(make_candidate(odds=5.0))

    def test_disallowed_sport_is_refused(self) -> None:
        c = Challenge.create(make_config(allowed_sports=("tennis",)))
        c.activate()
        with pytest.raises(ChallengeError, match="non autorisé"):
            c.propose(make_candidate(odds=2.0, sport=Sport.FOOTBALL))

    def test_propose_step_waits_rather_than_lowering_the_bar(self, challenge: Challenge) -> None:
        """No qualifying candidate must yield WAIT, never a relaxed pick."""
        assert propose_step(challenge, [make_candidate(odds=6.0)]) is None
        assert challenge.state is ChallengeState.WAITING_FOR_CANDIDATE

    def test_propose_step_with_no_candidates_returns_none(self, challenge: Challenge) -> None:
        assert propose_step(challenge, []) is None

    def test_propose_step_picks_the_best_conservative_ev(self, challenge: Challenge) -> None:
        low = make_candidate(odds=1.50)
        high = make_candidate(odds=2.50)
        step = propose_step(challenge, [low, high])
        assert step is not None
        assert step.detected_odds == 2.50

    def test_only_one_bet_per_rung(self, challenge: Challenge) -> None:
        challenge.propose(make_candidate(2.0))
        with pytest.raises(ChallengeError):
            challenge.propose(make_candidate(2.0))


class TestTrajectory:
    def test_step_estimate_is_recomputed_from_the_current_bank(self) -> None:
        c = Challenge.create(make_config(initial_bank=100.0, target_bank=400.0))
        c.activate()
        before = c.estimate_remaining_steps(2.0)
        assert before == 2  # 100 -> 200 -> 400
        c.propose(make_candidate(2.0))
        c.confirm(2.0)
        c.settle(BetOutcome.WON, proof="x")
        assert c.estimate_remaining_steps(2.0) == 1

    def test_estimate_is_none_when_the_target_is_unreachable(self) -> None:
        c = Challenge.create(make_config())
        c.activate()
        assert c.estimate_remaining_steps(1.0) is None

    def test_trajectory_matches_the_step_estimate(self) -> None:
        c = Challenge.create(make_config(initial_bank=100.0, target_bank=400.0))
        c.activate()
        assert len(c.trajectory(2.0)) == c.estimate_remaining_steps(2.0)

    def test_trajectory_reaches_the_target(self) -> None:
        c = Challenge.create(make_config(initial_bank=100.0, target_bank=400.0))
        c.activate()
        assert c.trajectory(2.0)[-1]["projected_bank"] >= 400.0


class TestSerialisation:
    def test_dict_exposes_detected_and_accepted_odds_separately(self, challenge: Challenge) -> None:
        challenge.propose(make_candidate(2.10))
        challenge.confirm(1.95)
        payload = challenge.to_dict()
        step = payload["steps"][0]  # type: ignore[index]
        assert step["detected_odds"] == 2.10
        assert step["accepted_odds"] == 1.95

    def test_dict_reports_every_required_step_field(self, challenge: Challenge) -> None:
        challenge.propose(make_candidate(2.0))
        step = challenge.to_dict()["steps"][0]  # type: ignore[index]
        for key in (
            "bank_before",
            "stake",
            "detected_odds",
            "accepted_odds",
            "potential_return",
            "projected_bank",
            "model_probability",
            "ev",
            "risks",
            "outcome",
            "result_proof",
        ):
            assert key in step
