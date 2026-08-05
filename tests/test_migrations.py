"""Alembic migrations.

Two paths must both work, and both are exercised here:

* a **fresh** database upgraded to head;
* a database at the **reference schema** (65c32b5e3f63, the initial delivery)
  upgraded to head — the path an existing deployment actually takes.

Migrations run in a subprocess with ``BETMAXXING_DATABASE_URL`` pointing at a
temporary file, because ``alembic/env.py`` reads the URL from settings rather
than from ``alembic.ini`` (so no connection string is ever committed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import REFERENCE_REVISION, column_names, run_alembic, table_names

#: Tables that must exist at head.
EXPECTED_TABLES = {
    "alerts",
    "candidates",
    "challenge_steps",
    "challenges",
    "collection_batches",
    "event_schedule_history",
    "event_source_map",
    "events",
    "model_registry",
    "odds_snapshots",
    "participant_aliases",
    "rejections",
    "scan_runs",
    "scheduler_jobs",
}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "migrate.db"


class TestFreshDatabase:
    def test_upgrade_head_succeeds(self, db_path: Path) -> None:
        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode == 0, result.stderr

    def test_every_expected_table_exists(self, db_path: Path) -> None:
        run_alembic(db_path, "upgrade", "head")
        assert table_names(db_path) >= EXPECTED_TABLES


class TestUpgradeFromTheReferenceSchema:
    """The path an existing deployment takes — the one that can lose data."""

    def test_stepwise_upgrade_succeeds(self, db_path: Path) -> None:
        first = run_alembic(db_path, "upgrade", REFERENCE_REVISION)
        assert first.returncode == 0, first.stderr
        second = run_alembic(db_path, "upgrade", "head")
        assert second.returncode == 0, second.stderr
        assert table_names(db_path) >= EXPECTED_TABLES

    def test_new_columns_are_added_to_existing_tables(self, db_path: Path) -> None:
        run_alembic(db_path, "upgrade", REFERENCE_REVISION)
        run_alembic(db_path, "upgrade", "head")

        assert "line_canonical" in column_names(db_path, "odds_snapshots")
        assert "batch_id" in column_names(db_path, "odds_snapshots")
        assert "participant_pair_key" in column_names(db_path, "events")
        assert "collection_status" in column_names(db_path, "scan_runs")
        assert "model_version" in column_names(db_path, "candidates")
        assert "uncertainty_status" in column_names(db_path, "candidates")
        assert "version" in column_names(db_path, "challenges")

    def test_conservative_ev_becomes_nullable(self, db_path: Path) -> None:
        """D-019 requires "no defensible uncertainty" to be representable."""
        run_alembic(db_path, "upgrade", REFERENCE_REVISION)
        before = column_names(db_path, "candidates")["ev_conservative"]
        assert before["nullable"] is False

        run_alembic(db_path, "upgrade", "head")
        after = column_names(db_path, "candidates")["ev_conservative"]
        assert after["nullable"] is True

    def test_existing_rows_survive_the_upgrade(self, db_path: Path) -> None:
        """Widening a column must not drop data."""
        import sqlite3

        run_alembic(db_path, "upgrade", REFERENCE_REVISION)
        connection = sqlite3.connect(db_path)
        connection.execute(
            "INSERT INTO events (canonical_id, sport, competition, home_name, away_name,"
            " home_canonical_id, away_canonical_id, start_time_utc, status,"
            " mapping_ambiguous, source_ids)"
            " VALUES ('legacy-1', 'football', 'Ligue 1', 'A', 'B', 'f:a', 'f:b',"
            " '2026-08-04 12:00:00', 'scheduled', 0, '{}')"
        )
        connection.commit()
        connection.close()

        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode == 0, result.stderr

        connection = sqlite3.connect(db_path)
        rows = connection.execute("SELECT canonical_id, competition FROM events").fetchall()
        connection.close()
        assert rows == [("legacy-1", "Ligue 1")]


class TestDowngrade:
    def test_head_downgrades_to_the_reference_revision(self, db_path: Path) -> None:
        run_alembic(db_path, "upgrade", "head")
        result = run_alembic(db_path, "downgrade", REFERENCE_REVISION)
        assert result.returncode == 0, result.stderr
        remaining = table_names(db_path)
        assert "scheduler_jobs" not in remaining
        assert "events" in remaining

    def test_downgrade_then_upgrade_round_trips(self, db_path: Path) -> None:
        run_alembic(db_path, "upgrade", "head")
        run_alembic(db_path, "downgrade", REFERENCE_REVISION)
        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        assert table_names(db_path) >= EXPECTED_TABLES


class TestSchemaMatchesModels:
    def test_no_pending_autogenerate_diff(self, db_path: Path) -> None:
        """Head must already describe the ORM: a drift here means a missing
        migration, which would only surface in production."""
        run_alembic(db_path, "upgrade", "head")
        result = run_alembic(db_path, "check")
        assert result.returncode == 0, (
            "alembic check found schema drift — a migration is missing:\n"
            f"{result.stdout}\n{result.stderr}"
        )
