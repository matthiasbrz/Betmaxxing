"""Manual, timestamped import adapters — the sanctioned path for bookmakers
without an authorized programmatic feed."""

from betmaxxing.providers.manual.csv_odds import (
    ImportReport,
    ManualCsvOddsProvider,
    ManualImportError,
    load_csv,
    parse_rows,
)

__all__ = [
    "ImportReport",
    "ManualCsvOddsProvider",
    "ManualImportError",
    "load_csv",
    "parse_rows",
]
