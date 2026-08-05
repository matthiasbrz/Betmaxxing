"""Challenge durability and concurrency.

The previous version kept challenges in a module-level dict inside the API: a
restart erased every progression, and two concurrent requests could settle the
same rung twice.
"""

from __future__ import annotations

import pytest
from tests.test_challenge import make_candidate

from betmaxxing.challenge import Challenge, ChallengeConfig
from betmaxxing.challenge.repository import (
    ChallengeNotFound,
    ChallengeRepository,
    ConcurrentModification,
)
from betmaxxing.config import Settings
from betmaxxing.domain.enums import BetOutcome, ChallengeState


def make_challenge() -> Challenge:
    return Challenge.create(
        ChallengeConfig(
            initial_bank=100.0,
            target_bank=400.0,
            max_odds=3.0,
            fraction_per_step=0.5,
        )
    )


class TestRoundTrip:
    def test_a_created_challenge_can_be_reloaded(self, db_settings: Settings) -> None:
        repo = ChallengeRepository(db_settings)
        created = repo.create(make_challenge())
        loaded, version = repo.load(created.challenge_id)
        assert loaded.challenge_id == created.challenge_id
        assert loaded.bank_cents == created.bank_cents
        assert version == 1

    def test_configuration_survives_the_round_trip(self, db_settings: Settings) -> None:
        repo = ChallengeRepository(db_settings)
        created = repo.create(make_challenge())
        loaded, _ = repo.load(created.challenge_id)
        assert loaded.config.target_bank == 400.0
        assert loaded.config.fraction_per_step == 0.5
        assert loaded.config.max_odds == 3.0

    def test_an_unknown_challenge_raises(self, db_settings: Settings) -> None:
        with pytest.raises(ChallengeNotFound):
            ChallengeRepository(db_settings).load("nope")

    def test_listing_returns_created_ids(self, db_settings: Settings) -> None:
        repo = ChallengeRepository(db_settings)
        first = repo.create(make_challenge())
        second = repo.create(make_challenge())
        assert set(repo.list_ids()) == {first.challenge_id, second.challenge_id}


class TestStateSurvivesRestart:
    def test_a_progression_is_not_lost(self, db_settings: Settings) -> None:
        repo = ChallengeRepository(db_settings)
        challenge = repo.create(make_challenge())
        challenge.activate()
        challenge.propose(make_candidate(2.0))
        challenge.confirm(1.98)
        repo.save(challenge, 1)

        # A brand new repository stands in for a restarted process.
        reloaded, _ = ChallengeRepository(db_settings).load(challenge.challenge_id)
        assert reloaded.state is ChallengeState.AWAITING_RESULT
        assert len(reloaded.steps) == 1
        assert reloaded.steps[0].accepted_odds == 1.98

    def test_settled_steps_survive(self, db_settings: Settings) -> None:
        repo = ChallengeRepository(db_settings)
        challenge = repo.create(make_challenge())
        challenge.activate()
        challenge.propose(make_candidate(2.0))
        challenge.confirm(2.0)
        challenge.settle(BetOutcome.WON, proof="ticket")
        repo.save(challenge, 1)

        reloaded, _ = repo.load(challenge.challenge_id)
        assert reloaded.bank == pytest.approx(150.0)
        assert reloaded.steps[0].outcome is BetOutcome.WON
        assert reloaded.steps[0].result_proof == "ticket"

    def test_detected_and_accepted_odds_both_survive(self, db_settings: Settings) -> None:
        repo = ChallengeRepository(db_settings)
        challenge = repo.create(make_challenge())
        challenge.activate()
        challenge.propose(make_candidate(2.10))
        challenge.confirm(1.95)
        repo.save(challenge, 1)

        reloaded, _ = repo.load(challenge.challenge_id)
        assert reloaded.steps[0].detected_odds == 2.10
        assert reloaded.steps[0].accepted_odds == 1.95


class TestOptimisticConcurrency:
    def test_a_stale_write_is_refused(self, db_settings: Settings) -> None:
        """Two readers, two writers: the second must not clobber the first."""
        repo = ChallengeRepository(db_settings)
        challenge = repo.create(make_challenge())

        first, version_a = repo.load(challenge.challenge_id)
        second, version_b = repo.load(challenge.challenge_id)
        assert version_a == version_b

        first.activate()
        repo.save(first, version_a)

        second.activate()
        with pytest.raises(ConcurrentModification):
            repo.save(second, version_b)

    def test_a_rung_cannot_be_settled_twice(self, db_settings: Settings) -> None:
        repo = ChallengeRepository(db_settings)
        challenge = repo.create(make_challenge())
        challenge.activate()
        challenge.propose(make_candidate(2.0))
        challenge.confirm(2.0)
        repo.save(challenge, 1)

        one, version_one = repo.load(challenge.challenge_id)
        two, version_two = repo.load(challenge.challenge_id)

        one.settle(BetOutcome.WON, proof="first")
        repo.save(one, version_one)

        two.settle(BetOutcome.WON, proof="second")
        with pytest.raises(ConcurrentModification):
            repo.save(two, version_two)

        final, _ = repo.load(challenge.challenge_id)
        assert final.bank == pytest.approx(150.0)  # settled once, not twice

    def test_the_version_advances_on_each_write(self, db_settings: Settings) -> None:
        repo = ChallengeRepository(db_settings)
        challenge = repo.create(make_challenge())
        loaded, version = repo.load(challenge.challenge_id)
        loaded.activate()
        repo.save(loaded, version)
        _, next_version = repo.load(challenge.challenge_id)
        assert next_version == version + 1


class TestDeletion:
    def test_deleting_removes_the_challenge_and_its_steps(self, db_settings: Settings) -> None:
        repo = ChallengeRepository(db_settings)
        challenge = repo.create(make_challenge())
        challenge.activate()
        challenge.propose(make_candidate(2.0))
        repo.save(challenge, 1)

        repo.delete(challenge.challenge_id)
        assert repo.list_ids() == []
        with pytest.raises(ChallengeNotFound):
            repo.load(challenge.challenge_id)
