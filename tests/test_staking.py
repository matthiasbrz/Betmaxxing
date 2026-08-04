"""Stake sizing and its safety properties."""

from __future__ import annotations

import pytest

from betmaxxing.config import RunMode, Settings
from betmaxxing.engine.staking import compute_stake


def staking_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "mode": RunMode.DEMO,
        "staking_enabled": True,
        "bankroll": 1000.0,
        "unit_pct_of_bankroll": 0.01,
        "kelly_fraction": 0.25,
        "max_stake_pct_of_bankroll": 0.01,
        "max_daily_exposure_pct": 0.05,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestDisabledByDefault:
    def test_no_stake_when_staking_is_disabled(self) -> None:
        stake = compute_stake(
            settings=Settings(mode=RunMode.DEMO, staking_enabled=False),
            odds=2.0,
            probability_conservative=0.6,
            probability_half_width=0.02,
        )
        assert stake.amount == 0.0
        assert stake.capped_by == "staking_disabled"

    def test_no_stake_without_a_bankroll(self) -> None:
        stake = compute_stake(
            settings=staking_settings(bankroll=0.0),
            odds=2.0,
            probability_conservative=0.6,
            probability_half_width=0.02,
        )
        assert stake.amount == 0.0
        assert stake.capped_by == "no_bankroll"


class TestUncertaintyProducesZero:
    def test_over_uncertain_probability_yields_exactly_zero(self) -> None:
        """Not a small stake — zero. A probability we cannot pin down is not
        a probability we should bet on."""
        stake = compute_stake(
            settings=staking_settings(),
            odds=2.0,
            probability_conservative=0.6,
            probability_half_width=0.50,
        )
        assert stake.amount == 0.0
        assert stake.units == 0.0
        assert stake.capped_by == "uncertainty"


class TestEdgeRequired:
    def test_no_stake_without_a_conservative_edge(self) -> None:
        stake = compute_stake(
            settings=staking_settings(),
            odds=2.0,
            probability_conservative=0.45,
            probability_half_width=0.02,
        )
        assert stake.amount == 0.0
        assert stake.capped_by == "no_edge_conservative"

    def test_stake_uses_the_conservative_probability(self) -> None:
        # Full Kelly on p=0.60 at 2.0 is 0.20; a quarter of that is 0.05, which
        # the 1% hard cap then binds.
        stake = compute_stake(
            settings=staking_settings(),
            odds=2.0,
            probability_conservative=0.60,
            probability_half_width=0.02,
        )
        assert stake.kelly_full_fraction == pytest.approx(0.20)
        assert stake.capped_by == "max_stake_pct_of_bankroll"


class TestCaps:
    def test_hard_bankroll_cap_wins_over_kelly(self) -> None:
        stake = compute_stake(
            settings=staking_settings(max_stake_pct_of_bankroll=0.01),
            odds=3.0,
            probability_conservative=0.60,
            probability_half_width=0.02,
        )
        assert stake.amount == pytest.approx(10.0)
        assert stake.kelly_applied_fraction == pytest.approx(0.01)

    def test_fractional_kelly_applies_when_below_the_cap(self) -> None:
        stake = compute_stake(
            settings=staking_settings(max_stake_pct_of_bankroll=0.10),
            odds=2.0,
            probability_conservative=0.55,
            probability_half_width=0.02,
        )
        # Full Kelly 0.10, quarter Kelly 0.025 -> 25 EUR on a 1000 bankroll.
        assert stake.kelly_applied_fraction == pytest.approx(0.025)
        assert stake.amount == pytest.approx(25.0)
        assert stake.capped_by is None

    def test_daily_exposure_ceiling_binds(self) -> None:
        stake = compute_stake(
            settings=staking_settings(max_daily_exposure_pct=0.02),
            odds=2.0,
            probability_conservative=0.60,
            probability_half_width=0.02,
            already_exposed=19.0,
        )
        assert stake.amount == pytest.approx(1.0)
        assert stake.capped_by == "max_daily_exposure_pct"

    def test_exhausted_daily_exposure_yields_zero(self) -> None:
        stake = compute_stake(
            settings=staking_settings(max_daily_exposure_pct=0.02),
            odds=2.0,
            probability_conservative=0.60,
            probability_half_width=0.02,
            already_exposed=20.0,
        )
        assert stake.amount == 0.0
        assert stake.capped_by == "daily_exposure"


class TestUnits:
    def test_units_are_expressed_against_the_configured_unit_size(self) -> None:
        stake = compute_stake(
            settings=staking_settings(max_stake_pct_of_bankroll=0.02),
            odds=2.0,
            probability_conservative=0.60,
            probability_half_width=0.02,
        )
        # 1 unit == 1% of a 1000 bankroll == 10 EUR; the stake is 20 EUR.
        assert stake.amount == pytest.approx(20.0)
        assert stake.units == pytest.approx(2.0)


class TestNoLossChasing:
    def test_stake_is_independent_of_prior_results(self) -> None:
        """There is no argument by which a past loss can raise the next stake.

        ``compute_stake`` has no parameter carrying result history, so a
        martingale cannot be expressed through it. This test pins the signature
        as much as the behaviour.
        """
        import inspect

        parameters = set(inspect.signature(compute_stake).parameters)
        assert parameters == {
            "settings",
            "odds",
            "probability_conservative",
            "probability_half_width",
            "already_exposed",
        }
        # `already_exposed` can only ever *reduce* the stake.
        base = compute_stake(
            settings=staking_settings(max_stake_pct_of_bankroll=0.02),
            odds=2.0,
            probability_conservative=0.60,
            probability_half_width=0.02,
        )
        after_exposure = compute_stake(
            settings=staking_settings(max_stake_pct_of_bankroll=0.02),
            odds=2.0,
            probability_conservative=0.60,
            probability_half_width=0.02,
            already_exposed=45.0,
        )
        assert after_exposure.amount <= base.amount


class TestRationaleIsAlwaysStated:
    def test_every_outcome_explains_itself(self) -> None:
        for kwargs in (
            {"probability_conservative": 0.45},
            {"probability_half_width": 0.9},
            {"probability_conservative": 0.60},
        ):
            stake = compute_stake(
                settings=staking_settings(),
                odds=2.0,
                probability_conservative=kwargs.get("probability_conservative", 0.6),  # type: ignore[arg-type]
                probability_half_width=kwargs.get("probability_half_width", 0.02),  # type: ignore[arg-type]
            )
            assert stake.rationale
