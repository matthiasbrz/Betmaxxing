"""A historical migration must keep giving the answer it gave the day it ran.

``3ce123580afa`` reconstructs a bank balance with ``betmaxxing.challenge.to_cents``
and ``b7c1e9d24a10`` derives matching keys with ``betmaxxing.domain.ids`` and
``betmaxxing.domain.models``. Both import the *live* application package, so the
result of replaying either revision is whatever the domain happens to mean at
replay time — not what it meant when the revision was written.

That coupling has already bitten once. ``to_cents`` was wrong: ``1.005`` rounded
to 100 cents instead of 101, and the previous tranche fixed it. Any database
migrated before that fix therefore carries a different ``bank_cents`` than a
database migrated after it, from byte-identical input, with no record of which
rule applied. The migration is not reproducible, and a money value that depends
on when you ran the upgrade is not an audit trail.

The failure mode does not stop at wrong answers. Rename ``to_cents``, move
``canonical_line``, split ``betmaxxing.domain`` — each is an ordinary
refactor, and each turns an old revision into an ``ImportError`` on a database
that still needs it. A version script is a historical record; it should depend
on nothing that is allowed to change.

The fix, in this tranche's Phase 6: inline frozen copies into the revisions and
forbid the import. These tests describe that state. They fail on ``d7063db``.

Scope: ``alembic/versions/*.py`` only. ``alembic/env.py`` is *not* a version
script — it reads the database URL from settings and the metadata from the ORM,
so it imports the application by design and is deliberately exempt.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from helpers import REPO_ROOT

VERSIONS_DIR = REPO_ROOT / "alembic" / "versions"

#: The two revisions this tranche freezes, by revision id.
CHALLENGE_REVISION = "3ce123580afa"
BACKFILL_REVISION = "b7c1e9d24a10"

#: The application package that a version script may not reach into.
LIVE_PACKAGE = "betmaxxing"


def version_files() -> list[Path]:
    files = sorted(p for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("_"))
    assert files, f"no migration scripts found under {VERSIONS_DIR}"
    return files


def revision_path(revision: str) -> Path:
    matches = [p for p in version_files() if p.name.startswith(revision)]
    assert len(matches) == 1, f"expected exactly one script for {revision}, got {matches}"
    return matches[0]


def load_revision(revision: str) -> types.ModuleType:
    """Import a version script by path, the way Alembic does."""
    path = revision_path(revision)
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def imported_roots(path: Path) -> set[str]:
    """Top-level package of every module a script imports, statically."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


# ---------------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------------
class TestNoVersionScriptImportsTheLivePackage:
    """The characterisation the instruction asks for, stated once per script."""

    @pytest.mark.parametrize("path", version_files(), ids=lambda p: p.name[:12])
    def test_the_application_package_is_not_imported(self, path: Path) -> None:
        assert LIVE_PACKAGE not in imported_roots(path), (
            f"{path.name} imports `{LIVE_PACKAGE}`. A migration that calls into the live "
            "domain replays with today's semantics, not the semantics it was written "
            "against, and breaks outright when the domain is renamed. Inline a frozen "
            "copy of what it needs."
        )

    def test_the_challenge_revision_is_covered_by_that_guard(self) -> None:
        """Named explicitly so the guard cannot be satisfied by deleting a file."""
        assert LIVE_PACKAGE not in imported_roots(revision_path(CHALLENGE_REVISION))

    def test_the_backfill_revision_is_covered_by_that_guard(self) -> None:
        assert LIVE_PACKAGE not in imported_roots(revision_path(BACKFILL_REVISION))

    @pytest.mark.parametrize("path", version_files(), ids=lambda p: p.name[:12])
    def test_no_loaded_symbol_belongs_to_the_live_package(self, path: Path) -> None:
        """Belt and braces: catches a rebound alias or a deferred import too.

        The static check reads import statements; this one reads the module the
        interpreter actually built, so ``to_cents = _lookup("to_cents")`` would
        still be caught.
        """
        module = load_revision(path.name.split("_")[0])
        leaked = sorted(
            name
            for name, value in vars(module).items()
            if getattr(value, "__module__", "").split(".")[0] == LIVE_PACKAGE
        )
        assert not leaked, f"{path.name} holds live-domain objects: {leaked}"


class TestAVersionScriptStandsAlone:
    """It must import with the application package unavailable.

    Not a hypothetical: the package is renamed, or the revision is replayed from
    a checkout that predates a module move, or a recovery runs against an
    installed wheel that no longer exports the symbol. Alembic will still try to
    import every script in the directory to build the revision map, so one
    unreachable import makes *every* migration command fail, including the ones
    that have nothing to do with that revision.
    """

    RUNNER = """
import importlib.util, sys

class Blocker:
    def find_module(self, name, path=None):
        return None
    def find_spec(self, name, path=None, target=None):
        if name == %(package)r or name.startswith(%(package)r + "."):
            raise ImportError(f"blocked for this test: {name}")
        return None

sys.meta_path.insert(0, Blocker())
for name in [n for n in sys.modules if n == %(package)r or n.startswith(%(package)r + ".")]:
    del sys.modules[name]

spec = importlib.util.spec_from_file_location("_isolated_migration", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.revision)
"""

    @pytest.mark.slow
    @pytest.mark.parametrize("revision", [CHALLENGE_REVISION, BACKFILL_REVISION])
    def test_it_imports_without_the_application_on_the_path(
        self, tmp_path: Path, revision: str
    ) -> None:
        runner = tmp_path / "isolate.py"
        runner.write_text(self.RUNNER % {"package": LIVE_PACKAGE}, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(runner), str(revision_path(revision))],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"revision {revision} cannot be imported without `{LIVE_PACKAGE}`:\n{result.stderr}"
        )
        assert result.stdout.strip() == revision


# ---------------------------------------------------------------------------
# Freezing must not change the answer
# ---------------------------------------------------------------------------
#: Amounts that sit exactly on a half-cent — where binary rounding and
#: ROUND_HALF_UP part company, and the values the instruction names explicitly.
HALF_UP_CASES = [
    (10.005, 1001),
    (0.005, 1),
    (2.675, 268),
    (1.005, 101),
    (8.045, 805),
    (1234.565, 123457),
    (0.145, 15),
]


class TestTheFrozenMoneyRuleMatchesTheDomain:
    """A frozen copy is only safe if it is a *copy*, verified against the original.

    The equivalence is asserted here, in the suite, rather than assumed. If the
    domain ever changes its rule deliberately, this test fails and the choice
    becomes explicit: either the migration was wrong and needs a corrective
    revision, or the domain moved on and history stays as it was.
    """

    @pytest.mark.parametrize(("amount", "cents"), HALF_UP_CASES)
    def test_the_frozen_helper_produces_the_documented_cents(
        self, amount: float, cents: int
    ) -> None:
        module = load_revision(CHALLENGE_REVISION)
        assert module._to_cents(amount) == cents

    @pytest.mark.parametrize(("amount", "cents"), HALF_UP_CASES)
    def test_the_frozen_helper_agrees_with_the_live_domain_today(
        self, amount: float, cents: int
    ) -> None:
        from betmaxxing.challenge import to_cents

        module = load_revision(CHALLENGE_REVISION)
        assert module._to_cents(amount) == to_cents(amount) == cents

    @pytest.mark.parametrize(
        ("text_amount", "cents"), [("10.005", 1001), ("0.005", 1), ("100", 10000), ("2.5", 250)]
    )
    def test_a_textual_amount_rounds_identically(self, text_amount: str, cents: int) -> None:
        module = load_revision(CHALLENGE_REVISION)
        assert module._to_cents(text_amount) == cents

    @pytest.mark.parametrize(
        "amount",
        [True, False, None, "nan", "inf", "-inf", float("nan"), float("inf"), "abc", "", "  "],
        ids=[
            "true",
            "false",
            "none",
            "nan-text",
            "inf-text",
            "minus-inf-text",
            "nan-float",
            "inf-float",
            "garbage",
            "empty",
            "blank",
        ],
    )
    def test_an_unusable_amount_is_refused_without_inventing_one(self, amount: object) -> None:
        module = load_revision(CHALLENGE_REVISION)
        with pytest.raises(module.UnusableChallengeDocument):
            module._to_cents(amount)


class TestTheFrozenBackfillHelpersMatchTheDomain:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Olympique Lyonnais", "olympique-lyonnais"),
            ("Stade Rennais", "stade-rennais"),
            ("FC Barcelona", "barcelona"),
            ("Bayern München", "bayern-munchen"),
            ("  Paris   Saint-Germain  ", "paris-saint-germain"),
            ("FC", "fc"),
            ("Real Madrid CF", "real-madrid"),
        ],
    )
    def test_participant_normalisation_is_identical(self, name: str, expected: str) -> None:
        from betmaxxing.domain.ids import normalize_participant

        module = load_revision(BACKFILL_REVISION)
        assert module._normalize_participant(name) == normalize_participant(name) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("2.5", "2.5"), ("2.50", "2.5"), ("2.500", "2.5"), ("0", "0"), ("-1.25", "-1.25")],
    )
    def test_line_canonicalisation_is_identical(self, value: str, expected: str) -> None:
        from betmaxxing.domain.models import canonical_line

        module = load_revision(BACKFILL_REVISION)
        assert module._canonical_line(value) == canonical_line(value) == expected

    @pytest.mark.parametrize("value", ["nan", "inf", "-inf", "abc", "2.5001"])
    def test_an_unrepresentable_line_is_refused(self, value: str) -> None:
        module = load_revision(BACKFILL_REVISION)
        with pytest.raises(ValueError):
            module._canonical_line(value)


# ---------------------------------------------------------------------------
# Freezing must not change the migration either
# ---------------------------------------------------------------------------
CHALLENGE_ID = "chal-frozen-1"
EVENT_ID = "frozen-evt-1"


def seed(db_path: Path, *, initial_bank: object = 1.005) -> None:
    """A reference-schema database with one challenge and one priced event."""
    import sqlite3

    from helpers import REFERENCE_REVISION, run_alembic

    assert run_alembic(db_path, "upgrade", REFERENCE_REVISION).returncode == 0
    document = {
        "config": {
            "initial_bank": initial_bank,
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
    connection = sqlite3.connect(db_path)
    connection.execute(
        "INSERT INTO events (canonical_id, sport, competition, home_name, away_name,"
        " home_canonical_id, away_canonical_id, start_time_utc, status,"
        " mapping_ambiguous, source_ids)"
        " VALUES (?, 'football', 'Ligue 1', 'Olympique Lyonnais', 'FC Barcelona',"
        " 'football:olympique-lyonnais', 'football:barcelona', '2026-08-04 18:00:00',"
        " 'scheduled', 0, '{\"the_odds_api\": \"prov-frozen\"}')",
        (EVENT_ID,),
    )
    connection.execute(
        "INSERT INTO odds_snapshots (fingerprint, provider, bookmaker, event_canonical_id,"
        " event_source_id, selection_key, market, period, line, selection_code,"
        " selection_label, decimal_odds, currency, event_status, provider_updated_at,"
        " observed_at, received_at, source_meta)"
        " VALUES ('fp-frozen', 'the_odds_api', 'winamax_fr', ?, 'prov-frozen',"
        " 'k', 'over_under', 'full_match', 2.500, 'over', 'Plus de 2.5 buts', 1.86,"
        " 'EUR', 'scheduled', '2026-08-04 11:58:00', '2026-08-04 11:58:00',"
        " '2026-08-04 12:00:00', '{}')",
        (EVENT_ID,),
    )
    connection.execute(
        "INSERT INTO challenges (challenge_id, state, created_at, updated_at, document)"
        " VALUES (?, 'in_progress', '2026-08-01 09:00:00', '2026-08-03 09:00:00', ?)",
        (CHALLENGE_ID, json.dumps(document)),
    )
    connection.commit()
    connection.close()


def read_state(db_path: Path) -> dict[str, object]:
    import sqlite3

    connection = sqlite3.connect(db_path)
    try:
        bank = connection.execute(
            "SELECT bank_cents FROM challenges WHERE challenge_id = ?", (CHALLENGE_ID,)
        ).fetchone()[0]
        pair = connection.execute(
            "SELECT participant_pair_key FROM events WHERE canonical_id = ?", (EVENT_ID,)
        ).fetchone()[0]
        line = connection.execute(
            "SELECT line_canonical FROM odds_snapshots WHERE fingerprint = 'fp-frozen'"
        ).fetchone()[0]
        sources = sorted(
            tuple(row)
            for row in connection.execute(
                "SELECT provider, provider_event_id, internal_id FROM event_source_map"
            )
        )
    finally:
        connection.close()
    return {"bank_cents": bank, "pair_key": pair, "line_canonical": line, "sources": sources}


#: What the frozen revisions must produce, spelled out rather than recomputed.
EXPECTED_STATE: dict[str, object] = {
    "bank_cents": 101,  # 1.005 € under ROUND_HALF_UP
    "pair_key": "football|olympique-lyonnais|barcelona",  # "FC" is a noise token
    "line_canonical": "2.5",  # 2.500 collapses
    "sources": [("the_odds_api", "prov-frozen", EVENT_ID)],
}


class TestTheFrozenMigrationProducesTheSameDatabase:
    """Freezing is a refactor of the revisions. The observable result is fixed.

    These run the real Alembic matrix the instruction names — empty database,
    populated database, downgrade then upgrade — and assert one explicit
    expected state rather than comparing a run against itself.
    """

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        return tmp_path / "frozen.db"

    @pytest.mark.slow
    def test_an_empty_database_reaches_head(self, db_path: Path) -> None:
        from helpers import run_alembic

        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode == 0, result.stderr

    @pytest.mark.slow
    def test_a_populated_database_backfills_the_expected_values(self, db_path: Path) -> None:
        from helpers import run_alembic

        seed(db_path)
        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        assert read_state(db_path) == EXPECTED_STATE

    @pytest.mark.slow
    def test_downgrade_then_upgrade_leaves_the_same_values(self, db_path: Path) -> None:
        from helpers import REFERENCE_REVISION, run_alembic

        seed(db_path)
        assert run_alembic(db_path, "upgrade", "head").returncode == 0
        before = read_state(db_path)

        assert run_alembic(db_path, "downgrade", REFERENCE_REVISION).returncode == 0
        assert run_alembic(db_path, "upgrade", "head").returncode == 0

        after = read_state(db_path)
        assert after == before == EXPECTED_STATE

    @pytest.mark.slow
    def test_the_refuse_policy_is_preserved(self, db_path: Path) -> None:
        from helpers import run_alembic

        seed(db_path, initial_bank="pas un montant")
        result = run_alembic(db_path, "upgrade", "head")
        assert result.returncode != 0, "an uninterpretable bank was accepted"
        assert CHALLENGE_ID in (result.stdout + result.stderr)

    @pytest.mark.slow
    def test_the_quarantine_policy_is_preserved(self, db_path: Path) -> None:
        import sqlite3

        from helpers import run_alembic

        seed(db_path, initial_bank="pas un montant")
        result = run_alembic(
            db_path,
            "upgrade",
            "head",
            env_overrides={"BETMAXXING_MIGRATION_UNUSABLE_CHALLENGE": "quarantine"},
        )
        assert result.returncode == 0, result.stderr
        connection = sqlite3.connect(db_path)
        try:
            state, bank = connection.execute(
                "SELECT state, bank_cents FROM challenges WHERE challenge_id = ?", (CHALLENGE_ID,)
            ).fetchone()
        finally:
            connection.close()
        assert (state, bank) == ("quarantined", 0)
