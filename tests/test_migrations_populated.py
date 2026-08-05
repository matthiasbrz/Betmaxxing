"""Migrating a database that already contains rows.

``tests/test_migrations.py`` proves the schema *shape* is reachable. It does not
prove the upgrade is survivable, because it upgrades an empty (or nearly empty)
database. The failure this file reproduces only appears with data:

    ALTER TABLE challenges ADD COLUMN version INTEGER NOT NULL

has no value to give the rows that already exist, so the statement is rejected.
A deployment that ever created a Challenge could not be upgraded at all.

The rest of the file pins the backfills that must accompany the column additions:
an existing event needs its ``participant_pair_key``, its ``events.source_ids``
entries need to become ``event_source_map`` rows, and an existing priced line
needs a ``line_canonical`` computed with the domain's own normalisation.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

#: Shared helpers live in ``tests/helpers.py``, made importable by the explicit
#: ``pythonpath = ["tests"]`` entry in ``pyproject.toml``. A test module must
#: never import a sibling *test* module — see ``test_suite_reproducibility.py``.
from helpers import REFERENCE_REVISION, column_names, run_alembic, table_names

CHALLENGE_ID = "chal-legacy-1"
EVENT_ID = "legacy-evt-1"


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def seed_reference_database(
    db_path: Path, *, challenge_document: dict | None = None, include_step: bool = True
) -> None:
    """Populate a 65c32b5e3f63 database with one row of everything that matters."""
    result = run_alembic(db_path, "upgrade", REFERENCE_REVISION)
    assert result.returncode == 0, result.stderr

    document = (
        challenge_document if challenge_document is not None else _legacy_challenge_document()
    )
    connection = _connect(db_path)
    connection.executescript(
        """
        INSERT INTO events (canonical_id, sport, competition, home_name, away_name,
            home_canonical_id, away_canonical_id, start_time_utc, status,
            mapping_ambiguous, source_ids)
        VALUES ('legacy-evt-1', 'football', 'Ligue 1', 'Olympique Lyonnais',
            'Stade Rennais', 'football:olympique-lyonnais', 'football:stade-rennais',
            '2026-08-04 18:00:00', 'scheduled', 0,
            '{"the_odds_api": "prov-abc", "demo": "demo-1"}');

        INSERT INTO odds_snapshots (fingerprint, provider, bookmaker, event_canonical_id,
            event_source_id, selection_key, market, period, line, selection_code,
            selection_label, decimal_odds, currency, event_status, provider_updated_at,
            observed_at, received_at, source_meta)
        VALUES ('fp-1', 'the_odds_api', 'winamax_fr', 'legacy-evt-1', 'prov-abc',
            'legacy-evt-1|over_under|full_match|2.5|over', 'over_under', 'full_match',
            2.5, 'over', 'Plus de 2.5 buts', 1.86, 'EUR', 'scheduled',
            '2026-08-04 11:58:00', '2026-08-04 11:58:00', '2026-08-04 12:00:00', '{}');

        INSERT INTO odds_snapshots (fingerprint, provider, bookmaker, event_canonical_id,
            event_source_id, selection_key, market, period, line, selection_code,
            selection_label, decimal_odds, currency, event_status, provider_updated_at,
            observed_at, received_at, source_meta)
        VALUES ('fp-2', 'the_odds_api', 'winamax_fr', 'legacy-evt-1', 'prov-abc',
            'legacy-evt-1|1x2|full_match||home', '1x2', 'full_match',
            NULL, 'home', 'Olympique Lyonnais', 1.63, 'EUR', 'scheduled',
            '2026-08-04 11:58:00', '2026-08-04 11:58:00', '2026-08-04 12:00:00', '{}');

        INSERT INTO scan_runs (scan_id, status, mode, generated_at, window_from, window_to,
            config_fingerprint, candidate_count, rejection_count, document)
        VALUES ('scan-legacy-1', 'CANDIDATES_FOUND', 'demo', '2026-08-04 12:00:00',
            '2026-08-04 12:00:00', '2026-08-05 12:00:00', 'fp0000', 1, 0, '{}');

        INSERT INTO candidates (candidate_id, scan_id, alert_key, event_canonical_id,
            selection_key, bookmaker, decimal_odds, model_probability, ev,
            ev_conservative, data_quality, model_id, validation_status, observed_at,
            document)
        VALUES ('cand-legacy-1', 'scan-legacy-1', 'ak-1', 'legacy-evt-1',
            'legacy-evt-1|1x2|full_match||home', 'winamax_fr', 1.63, 0.65, 0.0595,
            0.0210, 0.80, 'football_dixon_coles', 'BACKTEST_ONLY',
            '2026-08-04 11:58:00', '{}');
        """
    )
    connection.execute(
        "INSERT INTO challenges (challenge_id, state, created_at, updated_at, document)"
        " VALUES (?, 'in_progress', '2026-08-01 09:00:00', '2026-08-03 09:00:00', ?)",
        (CHALLENGE_ID, json.dumps(document)),
    )
    if include_step:
        connection.execute(
            "INSERT INTO challenge_steps (challenge_id, step_index, document) VALUES (?, 0, ?)",
            (CHALLENGE_ID, json.dumps(_legacy_step_document())),
        )
    connection.commit()
    connection.close()


def _legacy_challenge_document() -> dict:
    return {
        "config": {
            "initial_bank": 100.0,
            "target_bank": 400.0,
            "currency": "EUR",
            "min_odds": 1.20,
            "max_odds": 3.00,
            "max_loss": 0.0,
            "fraction_per_step": 0.25,
            "stop_on_first_loss": True,
            "max_steps": 20,
            "acknowledged_total_loss_risk": True,
        }
    }


def _legacy_step_document() -> dict:
    """One settled winning rung: 100.00 € staked at 1.60 leaves 116.00 €."""
    return {
        "index": 0,
        "bank_before_cents": 10000,
        "stake_cents": 2500,
        "detected_odds": 1.60,
        "accepted_odds": 1.60,
        "outcome": "won",
        "bank_after_cents": 11600,
        "event_label": "Olympique Lyonnais - Stade Rennais",
        "selection_label": "Olympique Lyonnais",
        "risks": [],
        "result_proof": "manuel",
    }


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "populated.db"


@pytest.fixture
def populated(db_path: Path) -> Path:
    seed_reference_database(db_path)
    return db_path


def counts(db_path: Path) -> dict[str, int]:
    connection = _connect(db_path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in (
                "events",
                "odds_snapshots",
                "scan_runs",
                "candidates",
                "challenges",
                "challenge_steps",
            )
        }
    finally:
        connection.close()


class TestUpgradeSurvivesExistingRows:
    """The P0: the upgrade is impossible on any database that has been used."""

    def test_upgrade_to_head_succeeds(self, populated: Path) -> None:
        result = run_alembic(populated, "upgrade", "head")
        assert result.returncode == 0, (
            f"upgrading a populated reference database failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_no_row_is_lost(self, populated: Path) -> None:
        before = counts(populated)
        run_alembic(populated, "upgrade", "head")
        assert counts(populated) == before

    def test_relationships_still_resolve(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        connection = _connect(populated)
        try:
            orphan_candidates = connection.execute(
                "SELECT COUNT(*) AS n FROM candidates c"
                " LEFT JOIN scan_runs s ON s.scan_id = c.scan_id WHERE s.scan_id IS NULL"
            ).fetchone()["n"]
            orphan_snapshots = connection.execute(
                "SELECT COUNT(*) AS n FROM odds_snapshots o"
                " LEFT JOIN events e ON e.canonical_id = o.event_canonical_id"
                " WHERE e.canonical_id IS NULL"
            ).fetchone()["n"]
            orphan_steps = connection.execute(
                "SELECT COUNT(*) AS n FROM challenge_steps st"
                " LEFT JOIN challenges c ON c.challenge_id = st.challenge_id"
                " WHERE c.challenge_id IS NULL"
            ).fetchone()["n"]
        finally:
            connection.close()
        assert (orphan_candidates, orphan_snapshots, orphan_steps) == (0, 0, 0)

    def test_foreign_keys_pass_sqlite_integrity_check(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        connection = _connect(populated)
        try:
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
        assert violations == []
        assert integrity == "ok"


class TestChallengeBackfill:
    def test_version_is_backfilled_and_not_null(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        connection = _connect(populated)
        try:
            row = connection.execute(
                "SELECT version FROM challenges WHERE challenge_id = ?", (CHALLENGE_ID,)
            ).fetchone()
        finally:
            connection.close()
        assert row["version"] is not None
        assert row["version"] >= 1

    def test_bank_comes_from_the_last_settled_step(self, populated: Path) -> None:
        """Not from the initial bank: the progression already moved."""
        run_alembic(populated, "upgrade", "head")
        connection = _connect(populated)
        try:
            row = connection.execute(
                "SELECT bank_cents FROM challenges WHERE challenge_id = ?", (CHALLENGE_ID,)
            ).fetchone()
        finally:
            connection.close()
        assert row["bank_cents"] == 11600

    def test_columns_end_up_not_nullable(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        columns = column_names(populated, "challenges")
        assert columns["version"]["nullable"] is False
        assert columns["bank_cents"]["nullable"] is False

    def test_a_challenge_with_no_settled_step_falls_back_to_the_initial_bank(
        self, db_path: Path
    ) -> None:
        seed_reference_database(db_path)
        connection = _connect(db_path)
        connection.execute("DELETE FROM challenge_steps")
        connection.commit()
        connection.close()

        assert run_alembic(db_path, "upgrade", "head").returncode == 0
        connection = _connect(db_path)
        try:
            row = connection.execute(
                "SELECT bank_cents FROM challenges WHERE challenge_id = ?", (CHALLENGE_ID,)
            ).fetchone()
        finally:
            connection.close()
        assert row["bank_cents"] == 10000


class TestChallengeDocumentThatCannotBeInterpreted:
    """No bank may ever be invented. The policy is explicit and testable."""

    def test_migration_refuses_and_names_the_row(self, db_path: Path) -> None:
        seed_reference_database(
            db_path, challenge_document={"unexpected": True}, include_step=False
        )
        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode != 0, "an uninterpretable challenge document was accepted"
        assert CHALLENGE_ID in (result.stdout + result.stderr)

    def test_quarantine_is_available_and_opt_in(self, db_path: Path) -> None:
        seed_reference_database(
            db_path, challenge_document={"unexpected": True}, include_step=False
        )
        result = run_alembic(
            db_path,
            "upgrade",
            "head",
            env_overrides={"BETMAXXING_MIGRATION_UNUSABLE_CHALLENGE": "quarantine"},
        )
        assert result.returncode == 0, result.stderr
        connection = _connect(db_path)
        try:
            row = connection.execute(
                "SELECT state, bank_cents, stop_reason FROM challenges WHERE challenge_id = ?",
                (CHALLENGE_ID,),
            ).fetchone()
        finally:
            connection.close()
        assert row["state"] == "quarantined"
        assert row["bank_cents"] == 0
        assert "quarantaine" in (row["stop_reason"] or "").lower()


class TestEventSourceBackfill:
    def test_every_source_id_becomes_a_mapping_row(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        connection = _connect(populated)
        try:
            rows = connection.execute(
                "SELECT provider, provider_event_id, internal_id FROM event_source_map"
                " ORDER BY provider"
            ).fetchall()
        finally:
            connection.close()
        assert [tuple(r) for r in rows] == [
            ("demo", "demo-1", EVENT_ID),
            ("the_odds_api", "prov-abc", EVENT_ID),
        ]

    def test_internal_ids_are_preserved(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        connection = _connect(populated)
        try:
            ids = [r[0] for r in connection.execute("SELECT canonical_id FROM events")]
        finally:
            connection.close()
        assert ids == [EVENT_ID]

    def test_the_backfill_is_idempotent(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        run_alembic(populated, "downgrade", REFERENCE_REVISION)
        assert run_alembic(populated, "upgrade", "head").returncode == 0
        connection = _connect(populated)
        try:
            count = connection.execute("SELECT COUNT(*) FROM event_source_map").fetchone()[0]
        finally:
            connection.close()
        assert count == 2

    def test_a_mapping_collision_is_refused_not_overwritten(self, db_path: Path) -> None:
        """Two legacy events claiming the same provider id is unresolvable."""
        seed_reference_database(db_path)
        connection = _connect(db_path)
        connection.execute(
            "INSERT INTO events (canonical_id, sport, competition, home_name, away_name,"
            " home_canonical_id, away_canonical_id, start_time_utc, status,"
            " mapping_ambiguous, source_ids)"
            " VALUES ('legacy-evt-2', 'football', 'Ligue 1', 'X', 'Y', 'football:x',"
            " 'football:y', '2026-08-04 20:00:00', 'scheduled', 0,"
            ' \'{"the_odds_api": "prov-abc"}\')'
        )
        connection.commit()
        connection.close()

        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode != 0
        assert "prov-abc" in (result.stdout + result.stderr)

    def test_participant_pair_key_is_backfilled(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        connection = _connect(populated)
        try:
            key = connection.execute(
                "SELECT participant_pair_key FROM events WHERE canonical_id = ?", (EVENT_ID,)
            ).fetchone()[0]
        finally:
            connection.close()
        assert key == "football|olympique-lyonnais|stade-rennais"


class TestLineCanonicalBackfill:
    def test_a_priced_line_gets_its_canonical_text(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        connection = _connect(populated)
        try:
            value = connection.execute(
                "SELECT line_canonical FROM odds_snapshots WHERE fingerprint = 'fp-1'"
            ).fetchone()[0]
        finally:
            connection.close()
        assert value == "2.5"

    def test_a_market_without_a_line_stays_null(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        connection = _connect(populated)
        try:
            value = connection.execute(
                "SELECT line_canonical FROM odds_snapshots WHERE fingerprint = 'fp-2'"
            ).fetchone()[0]
        finally:
            connection.close()
        assert value is None

    @pytest.mark.parametrize("stored", [2.5, 2.50, 2.500])
    def test_equivalent_float_renderings_converge(self, db_path: Path, stored: float) -> None:
        seed_reference_database(db_path)
        connection = _connect(db_path)
        connection.execute(
            "UPDATE odds_snapshots SET line = ? WHERE fingerprint = 'fp-1'", (stored,)
        )
        connection.commit()
        connection.close()

        run_alembic(db_path, "upgrade", "head")
        connection = _connect(db_path)
        try:
            value = connection.execute(
                "SELECT line_canonical FROM odds_snapshots WHERE fingerprint = 'fp-1'"
            ).fetchone()[0]
        finally:
            connection.close()
        assert value == "2.5"

    def test_a_non_finite_line_stops_the_migration(self, db_path: Path) -> None:
        """Never invent a key for a value that cannot be represented."""
        seed_reference_database(db_path)
        connection = _connect(db_path)
        connection.execute("UPDATE odds_snapshots SET line = 1e999 WHERE fingerprint = 'fp-1'")
        connection.commit()
        connection.close()

        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode != 0
        assert "fp-1" in (result.stdout + result.stderr)


class TestMigrationMatrix:
    def test_empty_database_to_head(self, db_path: Path) -> None:
        assert run_alembic(db_path, "upgrade", "head").returncode == 0

    def test_empty_reference_schema_to_head(self, db_path: Path) -> None:
        run_alembic(db_path, "upgrade", REFERENCE_REVISION)
        assert run_alembic(db_path, "upgrade", "head").returncode == 0

    def test_populated_reference_schema_to_head(self, populated: Path) -> None:
        assert run_alembic(populated, "upgrade", "head").returncode == 0

    def test_a_database_already_at_f901d6e_accepts_the_corrective_migration(
        self, db_path: Path
    ) -> None:
        """The state of any deployment that applied the previous tranche."""
        run_alembic(db_path, "upgrade", "3ce123580afa")
        assert table_names(db_path) >= {"scheduler_jobs", "event_source_map"}
        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode == 0, result.stderr

    def test_alembic_check_reports_no_drift_on_a_populated_database(self, populated: Path) -> None:
        run_alembic(populated, "upgrade", "head")
        result = run_alembic(populated, "check")
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


#: (initial_bank as written in the document, expected cents). Every value sits
#: exactly on a half-cent, which is where binary rounding and ROUND_HALF_UP part
#: company.
HALF_UP_CASES = [
    (10.005, 1001),
    (0.005, 1),
    (2.675, 268),
    (1.005, 101),
    (8.045, 805),
    (1234.565, 123457),
    (0.145, 15),
]


class TestMoneyRoundingMatchesTheDomain:
    """`float(x) * 100` then `round()` is not `ROUND_HALF_UP` on a Decimal.

    `round()` is banker's rounding on a float that may already have drifted, so
    10.005 lands on 1000 or 1001 depending on the binary representation. A bank
    balance reconstructed by a migration must use exactly the domain's rule, or
    two code paths disagree about someone's money.
    """

    @pytest.mark.parametrize(("amount", "cents"), HALF_UP_CASES)
    def test_the_domain_rounds_half_up(self, amount: float, cents: int) -> None:
        from betmaxxing.challenge import to_cents

        assert to_cents(amount) == cents

    @pytest.mark.parametrize(("amount", "cents"), HALF_UP_CASES)
    def test_the_migration_agrees_with_the_domain(
        self, db_path: Path, amount: float, cents: int
    ) -> None:
        document = _legacy_challenge_document()
        document["config"]["initial_bank"] = amount
        seed_reference_database(db_path, challenge_document=document, include_step=False)

        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        connection = _connect(db_path)
        try:
            stored = connection.execute(
                "SELECT bank_cents FROM challenges WHERE challenge_id = ?", (CHALLENGE_ID,)
            ).fetchone()["bank_cents"]
        finally:
            connection.close()
        assert stored == cents

    @pytest.mark.parametrize(
        ("text_amount", "cents"), [("10.005", 1001), ("0.005", 1), ("100", 10000), ("2.5", 250)]
    )
    def test_a_textual_amount_rounds_identically(
        self, db_path: Path, text_amount: str, cents: int
    ) -> None:
        """Some legacy documents stored the bank as a JSON string."""
        document = _legacy_challenge_document()
        document["config"]["initial_bank"] = text_amount
        seed_reference_database(db_path, challenge_document=document, include_step=False)

        assert run_alembic(db_path, "upgrade", "head").returncode == 0
        connection = _connect(db_path)
        try:
            stored = connection.execute(
                "SELECT bank_cents FROM challenges WHERE challenge_id = ?", (CHALLENGE_ID,)
            ).fetchone()["bank_cents"]
        finally:
            connection.close()
        assert stored == cents

    @pytest.mark.parametrize("amount", ["nan", "inf", "-inf", "abc", ""])
    def test_a_non_finite_or_unparseable_bank_stops_the_migration(
        self, db_path: Path, amount: str
    ) -> None:
        document = _legacy_challenge_document()
        document["config"]["initial_bank"] = amount
        seed_reference_database(db_path, challenge_document=document, include_step=False)

        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode != 0, f"bank {amount!r} was silently accepted"
        assert CHALLENGE_ID in (result.stdout + result.stderr)


class TestDowngradePreservesSourceIds:
    """A downgrade that loses provider/event associations is data loss.

    They are the only thing linking a stored price to the fixture it was quoted
    for. `event_source_map` holds them after the upgrade; the column holds them
    before it. Going down must move them back, or refuse.
    """

    def _source_ids(self, db_path: Path) -> dict[str, dict[str, str]]:
        connection = _connect(db_path)
        try:
            return {
                row["canonical_id"]: json.loads(row["source_ids"])
                for row in connection.execute("SELECT canonical_id, source_ids FROM events")
            }
        finally:
            connection.close()

    def _mappings(self, db_path: Path) -> set[tuple[str, str, str]]:
        connection = _connect(db_path)
        try:
            return {
                (r["provider"], r["provider_event_id"], r["internal_id"])
                for r in connection.execute(
                    "SELECT provider, provider_event_id, internal_id FROM event_source_map"
                )
            }
        finally:
            connection.close()

    def test_the_round_trip_preserves_every_association(self, populated: Path) -> None:
        assert run_alembic(populated, "upgrade", "head").returncode == 0
        before_map = self._mappings(populated)
        before_ids = self._source_ids(populated)
        assert len(before_map) == 2

        down = run_alembic(populated, "downgrade", REFERENCE_REVISION)
        assert down.returncode == 0, down.stderr
        # At the reference revision the mapping table is gone, so the column is
        # the only carrier. It must still hold everything.
        assert self._source_ids(populated) == before_ids

        assert run_alembic(populated, "upgrade", "head").returncode == 0
        assert self._mappings(populated) == before_map
        assert self._source_ids(populated) == before_ids

    def test_a_mapping_added_after_the_upgrade_survives_the_round_trip(
        self, populated: Path
    ) -> None:
        """The realistic case: a cross-provider link created while at head."""
        assert run_alembic(populated, "upgrade", "head").returncode == 0
        connection = _connect(populated)
        connection.execute(
            "INSERT INTO event_source_map (provider, provider_event_id, internal_id)"
            " VALUES ('third_party', 'tp-77', ?)",
            (EVENT_ID,),
        )
        connection.commit()
        connection.close()

        assert run_alembic(populated, "downgrade", REFERENCE_REVISION).returncode == 0
        assert self._source_ids(populated)[EVENT_ID].get("third_party") == "tp-77", (
            "a mapping created after the upgrade was lost by the downgrade"
        )

        assert run_alembic(populated, "upgrade", "head").returncode == 0
        assert ("third_party", "tp-77", EVENT_ID) in self._mappings(populated)

    def test_the_intermediate_downgrade_keeps_the_column_authoritative(
        self, populated: Path
    ) -> None:
        """Stopping at b7c1e9d24a10's parent must already be safe."""
        assert run_alembic(populated, "upgrade", "head").returncode == 0
        before = self._source_ids(populated)
        assert run_alembic(populated, "downgrade", "3ce123580afa").returncode == 0
        assert self._source_ids(populated) == before
