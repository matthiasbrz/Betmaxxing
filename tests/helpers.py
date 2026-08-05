"""Factories and harnesses shared by more than one test module.

This module exists because ``tests/test_challenge_persistence.py`` used to do
``from tests.test_challenge import make_candidate``. That import resolves under
``python -m pytest`` (which puts the working directory on ``sys.path``) and
fails under the ``pytest`` console script — so CI was collecting nothing while
reporting success.

``tests`` is deliberately *not* a package. ``pyproject.toml`` declares
``pythonpath = ["tests"]``, which makes this module importable as ``helpers``
under both invocations without depending on the caller's working directory.
Nothing here imports a test module.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect

from betmaxxing.challenge import Challenge, ChallengeConfig
from betmaxxing.domain.enums import (
    MarketType,
    Period,
    Sport,
    UncertaintyStatus,
    ValidationStatus,
)
from betmaxxing.domain.models import (
    Candidate,
    CanonicalEvent,
    DataQuality,
    Participant,
    ProbabilityEstimate,
    Selection,
    UncertaintyEstimate,
    ValueAssessment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The initial delivery's schema — the revision a real deployment upgrades from.
REFERENCE_REVISION = "65c32b5e3f63"
#: The schema shipped by the previous tranche (commit ``f901d6e``).
PREVIOUS_TRANCHE_REVISION = "3ce123580afa"

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Alembic harness
# ---------------------------------------------------------------------------
def run_alembic(
    db_path: Path, *args: str, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run alembic against a throwaway SQLite file.

    Migrations run in a subprocess because ``alembic/env.py`` reads the database
    URL from settings rather than from ``alembic.ini`` — no connection string is
    ever committed.
    """
    env = {
        **os.environ,
        "BETMAXXING_DATABASE_URL": f"sqlite+pysqlite:///{db_path}",
        "BETMAXXING_MODE": "demo",
        **(env_overrides or {}),
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def table_names(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def column_names(db_path: Path, table: str) -> dict[str, dict[str, object]]:
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    try:
        return {c["name"]: c for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Challenge factories
# ---------------------------------------------------------------------------
def make_config(**overrides: object) -> ChallengeConfig:
    base: dict[str, object] = {
        "initial_bank": 100.0,
        "target_bank": 400.0,
        "min_odds": 1.20,
        "max_odds": 3.00,
        "max_loss": 0.0,
        # Most Challenge tests were written against the old implicit 100% stake.
        # It is no longer the default, so they ask for it explicitly — which is
        # exactly the behaviour change being pinned.
        "fraction_per_step": 1.0,
        "acknowledged_total_loss_risk": True,
    }
    base.update(overrides)
    return ChallengeConfig(**base)  # type: ignore[arg-type]


def make_candidate(odds: float = 2.0, sport: Sport = Sport.TENNIS) -> Candidate:
    """A complete candidate, usable by any Challenge test."""
    event = CanonicalEvent(
        internal_id="e1",
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
            win_probability=0.56,
            push_probability=0.0,
            conditional_win_probability=0.56,
            settlement_rule="WIN_LOSE",
            payoff_outcomes=[],
            fair_odds=1 / 0.56,
            ev=0.56 * odds - 1,
            ev_conservative=0.52 * odds - 1,
            min_acceptable_odds=1.05 / 0.56,
            ev_sensitivity_per_odds_tick=0.0056,
            overround=1.05,
        ),
        probability=ProbabilityEstimate(
            probability=0.56,
            model_id="m1",
            model_version="1.0.0",
            validation_status=ValidationStatus.BACKTEST_ONLY,
            uncertainty=UncertaintyEstimate(
                method="synthetic_wilson_demo",
                status=UncertaintyStatus.SYNTHETIC,
                lower=0.52,
                upper=0.60,
                effective_sample_size=300.0,
            ),
        ),
        data_quality=DataQuality(score=0.95, components={}),
        confidence={"score": 0.7, "label": "moyenne"},
        evidence=[],
        risks=["risque test"],
        missing_information=[],
        invalidation_conditions=[],
        model_id="m1",
        model_version="1.0.0",
        config_fingerprint="fp",
    )


def make_challenge(**overrides: object) -> Challenge:
    return Challenge.create(make_config(**overrides))
