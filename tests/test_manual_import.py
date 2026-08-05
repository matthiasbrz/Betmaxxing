"""Manual odds import — the sanctioned path for bookmakers without an
authorized feed (Winamax included)."""

from __future__ import annotations

from pathlib import Path

import pytest

from betmaxxing.domain.enums import MarketType, Period
from betmaxxing.providers.manual import ManualCsvOddsProvider, ManualImportError, load_csv

HEADER = (
    "bookmaker,sport,competition,stage,home,away,start_time_utc,market,period,"
    "line,selection_code,selection_label,decimal_odds,observed_at_utc\n"
)
ROW_HOME = (
    "Winamax,football,Ligue 1,J3,Olympique Lyonnais,Stade Rennais,"
    "2026-08-04T17:00:00+00:00,1x2,full_time,,home,Olympique Lyonnais,1.63,"
    "2026-08-04T09:00:00+00:00\n"
)
ROW_DRAW = (
    "Winamax,football,Ligue 1,J3,Olympique Lyonnais,Stade Rennais,"
    "2026-08-04T17:00:00+00:00,1x2,full_time,,draw,Match nul,4.20,"
    "2026-08-04T09:00:00+00:00\n"
)
ROW_AWAY = (
    "Winamax,football,Ligue 1,J3,Olympique Lyonnais,Stade Rennais,"
    "2026-08-04T17:00:00+00:00,1x2,full_time,,away,Stade Rennais,5.00,"
    "2026-08-04T09:00:00+00:00\n"
)


def write_csv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "odds.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


class TestValidImport:
    def test_reads_a_complete_book(self, tmp_path: Path) -> None:
        report = load_csv(write_csv(tmp_path, ROW_HOME + ROW_DRAW + ROW_AWAY))
        assert len(report.events) == 1
        assert len(report.snapshots) == 3
        assert report.quarantined == []

    def test_preserves_the_declared_bookmaker(self, tmp_path: Path) -> None:
        report = load_csv(write_csv(tmp_path, ROW_HOME))
        assert report.snapshots[0].bookmaker == "Winamax"
        assert report.snapshots[0].provider == "manual_csv"

    def test_marks_snapshots_as_manually_imported(self, tmp_path: Path) -> None:
        report = load_csv(write_csv(tmp_path, ROW_HOME))
        assert report.snapshots[0].source_meta["import"] == "manual_csv"

    def test_observation_time_is_taken_from_the_file(self, tmp_path: Path) -> None:
        report = load_csv(write_csv(tmp_path, ROW_HOME))
        assert report.snapshots[0].observed_at.isoformat() == "2026-08-04T09:00:00+00:00"

    def test_rows_of_one_event_collapse_to_one_canonical_event(self, tmp_path: Path) -> None:
        report = load_csv(write_csv(tmp_path, ROW_HOME + ROW_DRAW + ROW_AWAY))
        assert len({s.event_internal_id for s in report.snapshots}) == 1

    def test_over_under_line_is_parsed(self, tmp_path: Path) -> None:
        row = (
            "Winamax,football,Ligue 1,J3,Lyon,Rennes,2026-08-04T17:00:00+00:00,"
            "total_goals,full_time,2.5,over,Plus de 2.5 buts,1.86,"
            "2026-08-04T09:00:00+00:00\n"
        )
        report = load_csv(write_csv(tmp_path, row))
        selection = report.snapshots[0].selection
        assert selection.market is MarketType.TOTAL_GOALS
        assert selection.line_canonical == "2.5"

    def test_comma_decimal_separator_is_accepted(self, tmp_path: Path) -> None:
        row = ROW_HOME.replace(",1.63,", ',"1,63",')
        report = load_csv(write_csv(tmp_path, row))
        assert report.snapshots[0].decimal_odds == pytest.approx(1.63)


class TestQuarantine:
    def test_naive_timestamp_is_quarantined_not_assumed(self, tmp_path: Path) -> None:
        """Guessing a timezone would be inventing data."""
        row = ROW_HOME.replace("2026-08-04T09:00:00+00:00", "2026-08-04T09:00:00")
        report = load_csv(write_csv(tmp_path, row))
        assert len(report.quarantined) == 1
        assert "UTC offset" in report.quarantined[0][1]

    def test_invalid_odds_are_quarantined(self, tmp_path: Path) -> None:
        row = ROW_HOME.replace(",1.63,", ",0.95,")
        report = load_csv(write_csv(tmp_path, row))
        assert len(report.quarantined) == 1
        assert "must be > 1.0" in report.quarantined[0][1]

    def test_unknown_market_is_quarantined(self, tmp_path: Path) -> None:
        row = ROW_HOME.replace(",1x2,", ",correct_score,")
        report = load_csv(write_csv(tmp_path, row))
        assert len(report.quarantined) == 1

    def test_missing_line_on_over_under_is_quarantined(self, tmp_path: Path) -> None:
        row = (
            "Winamax,football,Ligue 1,J3,Lyon,Rennes,2026-08-04T17:00:00+00:00,"
            "total_goals,full_time,,over,Plus de buts,1.86,2026-08-04T09:00:00+00:00\n"
        )
        report = load_csv(write_csv(tmp_path, row))
        assert len(report.quarantined) == 1

    def test_a_bad_row_does_not_discard_the_good_ones(self, tmp_path: Path) -> None:
        bad = ROW_DRAW.replace(",4.20,", ",0.5,")
        report = load_csv(write_csv(tmp_path, ROW_HOME + bad + ROW_AWAY))
        assert len(report.snapshots) == 2
        assert len(report.quarantined) == 1

    def test_quarantine_reports_the_row_number(self, tmp_path: Path) -> None:
        bad = ROW_DRAW.replace(",4.20,", ",0.5,")
        report = load_csv(write_csv(tmp_path, ROW_HOME + bad))
        assert report.quarantined[0][0] == 3


class TestFileLevelErrors:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ManualImportError, match="file not found"):
            load_csv(tmp_path / "absent.csv")

    def test_missing_required_column_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.csv"
        path.write_text("bookmaker,sport\nWinamax,football\n", encoding="utf-8")
        with pytest.raises(ManualImportError, match="missing required column"):
            load_csv(path)

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ManualImportError):
            load_csv(path)


class TestProviderAdapter:
    def test_serves_imported_events_in_window(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime

        from betmaxxing.domain.enums import Sport

        report = load_csv(write_csv(tmp_path, ROW_HOME + ROW_DRAW + ROW_AWAY))
        provider = ManualCsvOddsProvider(report)
        window = (
            datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
            datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
        )
        events = provider.list_events([Sport.FOOTBALL], window)
        assert len(events) == 1
        assert len(provider.fetch_odds(events)) == 3

    def test_health_names_the_bookmaker_and_flags_manual_origin(self, tmp_path: Path) -> None:
        report = load_csv(write_csv(tmp_path, ROW_HOME))
        status = ManualCsvOddsProvider(report).health()
        assert "Winamax" in status.detail
        assert "manuel" in status.detail

    def test_empty_import_reports_not_configured(self, tmp_path: Path) -> None:
        report = load_csv(write_csv(tmp_path, ""))
        assert ManualCsvOddsProvider(report).health().health.value == "not_configured"


class TestPeriodSupport:
    def test_first_half_market_is_parsed(self, tmp_path: Path) -> None:
        row = ROW_HOME.replace(",full_time,", ",first_half,")
        report = load_csv(write_csv(tmp_path, row))
        assert report.snapshots[0].selection.period is Period.FIRST_HALF
