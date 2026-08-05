"""Ambiguity reviews and participant aliases, administrable without SQL.

Both mechanisms existed after the previous tranche and neither was usable: an
ambiguity landed in ``event_mapping_reviews`` with no way to look at it or act on
it, and the alias table was consulted by the matcher while nothing could ever put
a row in it. A control that requires hand-written SQL to operate is not a control.

The rules being pinned, beyond "the commands exist":

* **no automatic resolution.** The operator names the target event; the tool
  validates and records, it never guesses;
* resolution is one transaction — mapping created *and* review closed, or neither;
* who decided, when, and what they decided is kept;
* the alias import is idempotent and quarantines bad rows instead of failing
  wholesale;
* resolving a review never rewrites snapshots that already exist.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from betmaxxing.cli import app
from betmaxxing.config import Settings
from betmaxxing.domain.enums import Sport
from betmaxxing.ingestion.identity import EventIdentityService
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import (
    EventMappingReviewRow,
    EventSourceMapRow,
    ParticipantAliasRow,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
runner = CliRunner()


@pytest.fixture
def cli_env(db_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The CLI reads settings from the environment, like a real invocation."""
    monkeypatch.setenv("BETMAXXING_MODE", "demo")
    monkeypatch.setenv("BETMAXXING_DATABASE_URL", db_settings.database_url)
    monkeypatch.setenv("BETMAXXING_NOTIFICATIONS_ENABLED", "false")
    from betmaxxing.config import reset_settings_cache

    reset_settings_cache()
    return db_settings


def make_ambiguity(settings: Settings) -> tuple[str, str]:
    """Two plausible fixtures, then a third provider that cannot be attributed."""
    identity = EventIdentityService(settings)
    first = identity.resolve(
        provider="provider_a",
        provider_event_id="a-1",
        sport=Sport.FOOTBALL,
        competition="Ligue 1",
        home_name="Olympique Lyonnais",
        away_name="Stade Rennais",
        start_time_utc=NOW + timedelta(hours=6),
    )
    second = identity.resolve(
        provider="provider_a",
        provider_event_id="a-2",
        sport=Sport.FOOTBALL,
        competition="Ligue 1",
        home_name="Olympique Lyonnais",
        away_name="Stade Rennais",
        start_time_utc=NOW + timedelta(hours=9),
    )
    outcome = identity.resolve(
        provider="provider_b",
        provider_event_id="b-1",
        sport=Sport.FOOTBALL,
        competition="Ligue 1",
        home_name="Olympique Lyonnais",
        away_name="Stade Rennais",
        start_time_utc=NOW + timedelta(hours=7, minutes=30),
    )
    assert outcome.ambiguous
    return str(first.internal_id), str(second.internal_id)


def review_id(settings: Settings) -> int:
    with session_scope(settings) as session:
        row = session.query(EventMappingReviewRow).one()
        return int(row.id)


# ---------------------------------------------------------------------------
# Listing and showing
# ---------------------------------------------------------------------------
class TestReviewListing:
    def test_an_empty_queue_says_so(self, cli_env: Settings) -> None:
        result = runner.invoke(app, ["identity", "reviews", "list"])
        assert result.exit_code == 0
        assert "aucune" in result.stdout.lower()

    def test_a_pending_ambiguity_is_listed(self, cli_env: Settings) -> None:
        make_ambiguity(cli_env)
        result = runner.invoke(app, ["identity", "reviews", "list"])
        assert result.exit_code == 0
        assert "provider_b" in result.stdout
        assert "b-1" in result.stdout

    def test_the_listing_is_machine_readable(self, cli_env: Settings) -> None:
        make_ambiguity(cli_env)
        result = runner.invoke(app, ["identity", "reviews", "list", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload[0]["provider"] == "provider_b"
        assert len(payload[0]["candidate_internal_ids"]) == 2

    def test_show_lists_the_candidates(self, cli_env: Settings) -> None:
        first, second = make_ambiguity(cli_env)
        result = runner.invoke(app, ["identity", "reviews", "show", str(review_id(cli_env))])
        assert result.exit_code == 0
        assert first in result.stdout
        assert second in result.stdout

    def test_show_refuses_an_unknown_id(self, cli_env: Settings) -> None:
        result = runner.invoke(app, ["identity", "reviews", "show", "4242"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Resolving
# ---------------------------------------------------------------------------
class TestReviewResolution:
    def test_the_operator_names_the_event_and_the_mapping_is_created(
        self, cli_env: Settings
    ) -> None:
        first, _second = make_ambiguity(cli_env)
        result = runner.invoke(
            app,
            [
                "identity",
                "reviews",
                "resolve",
                str(review_id(cli_env)),
                "--event-id",
                first,
                "--operator",
                "matthias",
            ],
        )
        assert result.exit_code == 0, result.stdout
        with session_scope(cli_env) as session:
            mapping = (
                session.query(EventSourceMapRow)
                .filter(EventSourceMapRow.provider == "provider_b")
                .one()
            )
            assert mapping.provider_event_id == "b-1"
            assert mapping.internal_id == first

    def test_the_review_is_closed_with_an_audit_trail(self, cli_env: Settings) -> None:
        first, _ = make_ambiguity(cli_env)
        identifier = review_id(cli_env)
        runner.invoke(
            app,
            [
                "identity",
                "reviews",
                "resolve",
                str(identifier),
                "--event-id",
                first,
                "--operator",
                "matthias",
            ],
        )
        with session_scope(cli_env) as session:
            row = session.get(EventMappingReviewRow, identifier)
            assert row is not None
            assert row.resolved is True
            assert row.resolved_by == "matthias"
            assert row.resolved_internal_id == first
            assert row.resolved_at is not None

    def test_a_resolved_review_disappears_from_the_queue(self, cli_env: Settings) -> None:
        first, _ = make_ambiguity(cli_env)
        runner.invoke(
            app,
            [
                "identity",
                "reviews",
                "resolve",
                str(review_id(cli_env)),
                "--event-id",
                first,
                "--operator",
                "op",
            ],
        )
        result = runner.invoke(app, ["identity", "reviews", "list", "--json"])
        assert json.loads(result.stdout) == []

    def test_resolving_twice_is_refused(self, cli_env: Settings) -> None:
        first, _ = make_ambiguity(cli_env)
        identifier = review_id(cli_env)
        args = [
            "identity",
            "reviews",
            "resolve",
            str(identifier),
            "--event-id",
            first,
            "--operator",
            "op",
        ]
        assert runner.invoke(app, args).exit_code == 0
        second = runner.invoke(app, args)
        assert second.exit_code != 0
        assert "déjà" in second.stdout.lower() or "resolved" in second.stdout.lower()

    def test_an_event_outside_the_candidates_is_refused(self, cli_env: Settings) -> None:
        """The operator may only pick one of the fixtures that actually matched."""
        make_ambiguity(cli_env)
        result = runner.invoke(
            app,
            [
                "identity",
                "reviews",
                "resolve",
                str(review_id(cli_env)),
                "--event-id",
                "evt_not_a_candidate",
                "--operator",
                "op",
            ],
        )
        assert result.exit_code != 0

    def test_a_colliding_mapping_is_refused_and_changes_nothing(self, cli_env: Settings) -> None:
        first, second = make_ambiguity(cli_env)
        with session_scope(cli_env) as session:
            session.add(
                EventSourceMapRow(
                    provider="provider_b", provider_event_id="b-1", internal_id=second
                )
            )

        result = runner.invoke(
            app,
            [
                "identity",
                "reviews",
                "resolve",
                str(review_id(cli_env)),
                "--event-id",
                first,
                "--operator",
                "op",
            ],
        )
        assert result.exit_code != 0
        with session_scope(cli_env) as session:
            mapping = (
                session.query(EventSourceMapRow)
                .filter(EventSourceMapRow.provider == "provider_b")
                .one()
            )
            assert mapping.internal_id == second, "the existing mapping was overwritten"
            review = session.query(EventMappingReviewRow).one()
            assert review.resolved is False, "the review was closed despite the failure"

    def test_existing_snapshots_are_not_reattributed(self, cli_env: Settings) -> None:
        """Resolving decides the future, it does not rewrite recorded history."""
        from betmaxxing.storage.tables import OddsSnapshotRow

        first, second = make_ambiguity(cli_env)
        with session_scope(cli_env) as session:
            session.add(
                OddsSnapshotRow(
                    fingerprint="fp-existing",
                    provider="provider_a",
                    bookmaker="winamax_fr",
                    event_canonical_id=second,
                    event_source_id="a-2",
                    selection_key="k",
                    market="1x2",
                    period="full_time",
                    selection_code="home",
                    selection_label="A",
                    decimal_odds=1.8,
                    observed_at=NOW,
                    received_at=NOW,
                    source_meta={},
                )
            )
        runner.invoke(
            app,
            [
                "identity",
                "reviews",
                "resolve",
                str(review_id(cli_env)),
                "--event-id",
                first,
                "--operator",
                "op",
            ],
        )
        with session_scope(cli_env) as session:
            row = session.query(OddsSnapshotRow).one()
            assert row.event_canonical_id == second

    def test_there_is_no_automatic_resolution_command(self, cli_env: Settings) -> None:
        make_ambiguity(cli_env)
        result = runner.invoke(app, ["identity", "reviews", "resolve", "--help"])
        assert result.exit_code == 0
        assert "--event-id" in result.stdout
        for forbidden in ("--auto", "--best", "--guess"):
            assert forbidden not in result.stdout


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------
def write_csv(path: Path, rows: list[str]) -> Path:
    path.write_text(
        "sport,alias,canonical_participant_id,source\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    return path


class TestAliasImport:
    def test_a_valid_file_is_imported(self, cli_env: Settings, tmp_path: Path) -> None:
        csv = write_csv(
            tmp_path / "aliases.csv",
            [
                "football,OL,football:olympique-lyonnais,provider_b",
                "football,SRFC,football:stade-rennais,provider_b",
            ],
        )
        result = runner.invoke(app, ["identity", "aliases", "import", str(csv)])
        assert result.exit_code == 0, result.stdout
        with session_scope(cli_env) as session:
            assert session.query(ParticipantAliasRow).count() == 2

    def test_importing_the_same_file_twice_changes_nothing(
        self, cli_env: Settings, tmp_path: Path
    ) -> None:
        csv = write_csv(
            tmp_path / "aliases.csv", ["football,OL,football:olympique-lyonnais,provider_b"]
        )
        runner.invoke(app, ["identity", "aliases", "import", str(csv)])
        second = runner.invoke(app, ["identity", "aliases", "import", str(csv)])
        assert second.exit_code == 0
        with session_scope(cli_env) as session:
            assert session.query(ParticipantAliasRow).count() == 1

    def test_an_invalid_row_is_quarantined_not_fatal(
        self, cli_env: Settings, tmp_path: Path
    ) -> None:
        csv = write_csv(
            tmp_path / "aliases.csv",
            [
                "football,OL,football:olympique-lyonnais,provider_b",
                "handball,HBC,handball:x,provider_b",
                "football,,football:missing-alias,provider_b",
                "football,OM,,provider_b",
            ],
        )
        result = runner.invoke(app, ["identity", "aliases", "import", str(csv)])
        assert result.exit_code == 0, result.stdout
        assert "quarantaine" in result.stdout.lower()
        with session_scope(cli_env) as session:
            assert session.query(ParticipantAliasRow).count() == 1

    def test_the_report_names_each_rejected_row(self, cli_env: Settings, tmp_path: Path) -> None:
        csv = write_csv(tmp_path / "aliases.csv", ["handball,HBC,handball:x,provider_b"])
        result = runner.invoke(app, ["identity", "aliases", "import", str(csv), "--json"])
        payload = json.loads(result.stdout)
        assert payload["imported"] == 0
        assert len(payload["quarantined"]) == 1
        assert payload["quarantined"][0]["line"] == 2
        assert "handball" in payload["quarantined"][0]["reason"]

    def test_a_contradictory_alias_for_one_source_is_refused(
        self, cli_env: Settings, tmp_path: Path
    ) -> None:
        """The same provider cannot map one spelling onto two participants."""
        first = write_csv(
            tmp_path / "a.csv", ["football,OL,football:olympique-lyonnais,provider_b"]
        )
        runner.invoke(app, ["identity", "aliases", "import", str(first)])

        second = write_csv(
            tmp_path / "b.csv", ["football,OL,football:olympique-marseille,provider_b"]
        )
        result = runner.invoke(app, ["identity", "aliases", "import", str(second), "--json"])
        payload = json.loads(result.stdout)
        assert payload["imported"] == 0
        assert payload["quarantined"], "a contradictory alias was accepted"
        with session_scope(cli_env) as session:
            row = session.query(ParticipantAliasRow).one()
            assert row.canonical_participant_id == "football:olympique-lyonnais"

    def test_two_sources_may_declare_the_same_alias(
        self, cli_env: Settings, tmp_path: Path
    ) -> None:
        csv = write_csv(
            tmp_path / "aliases.csv",
            [
                "football,OL,football:olympique-lyonnais,provider_a",
                "football,OL,football:olympique-lyonnais,provider_b",
            ],
        )
        result = runner.invoke(app, ["identity", "aliases", "import", str(csv)])
        assert result.exit_code == 0
        with session_scope(cli_env) as session:
            assert session.query(ParticipantAliasRow).count() == 2

    def test_a_missing_file_is_a_clean_error(self, cli_env: Settings, tmp_path: Path) -> None:
        result = runner.invoke(app, ["identity", "aliases", "import", str(tmp_path / "nope.csv")])
        assert result.exit_code != 0


class TestAliasListing:
    def test_aliases_are_listed(self, cli_env: Settings, tmp_path: Path) -> None:
        csv = write_csv(
            tmp_path / "aliases.csv", ["football,OL,football:olympique-lyonnais,provider_b"]
        )
        runner.invoke(app, ["identity", "aliases", "import", str(csv)])
        result = runner.invoke(app, ["identity", "aliases", "list"])
        assert result.exit_code == 0
        assert "OL" in result.stdout

    def test_the_listing_filters_by_sport(self, cli_env: Settings, tmp_path: Path) -> None:
        csv = write_csv(
            tmp_path / "aliases.csv",
            [
                "football,OL,football:olympique-lyonnais,provider_b",
                "tennis,RAFA,tennis:rafael-nadal,provider_b",
            ],
        )
        runner.invoke(app, ["identity", "aliases", "import", str(csv)])
        result = runner.invoke(app, ["identity", "aliases", "list", "--sport", "tennis", "--json"])
        payload = json.loads(result.stdout)
        assert [row["alias"] for row in payload] == ["RAFA"]

    def test_the_listing_filters_by_source(self, cli_env: Settings, tmp_path: Path) -> None:
        csv = write_csv(
            tmp_path / "aliases.csv",
            [
                "football,OL,football:olympique-lyonnais,provider_a",
                "football,SRFC,football:stade-rennais,provider_b",
            ],
        )
        runner.invoke(app, ["identity", "aliases", "import", str(csv)])
        result = runner.invoke(
            app, ["identity", "aliases", "list", "--source", "provider_b", "--json"]
        )
        payload = json.loads(result.stdout)
        assert [row["alias"] for row in payload] == ["SRFC"]

    def test_an_imported_alias_is_used_by_the_matcher(
        self, cli_env: Settings, tmp_path: Path
    ) -> None:
        """The import is only worth having if resolution actually consults it."""
        csv = write_csv(
            tmp_path / "aliases.csv", ["football,OL,football:olympique-lyonnais,provider_b"]
        )
        runner.invoke(app, ["identity", "aliases", "import", str(csv)])

        identity = EventIdentityService(cli_env)
        first = identity.resolve(
            provider="provider_a",
            provider_event_id="a-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=6),
        )
        linked = identity.resolve(
            provider="provider_b",
            provider_event_id="b-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="OL",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=6, minutes=30),
        )
        assert linked.internal_id == first.internal_id
