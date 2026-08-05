"""Manual, timestamped odds import.

This is the sanctioned path for any bookmaker without an authorized programmatic
feed — Winamax included. The user types (or pastes) prices they read themselves,
with the instant they read them, and the engine treats the result as a normal
immutable snapshot that is honestly labelled as manually captured.

What this module explicitly does **not** do: scrape, log in, or reverse-engineer
a private endpoint. See docs/source-matrix.md for why that line is drawn here.

CSV columns (header required)::

    bookmaker,sport,competition,stage,home,away,start_time_utc,market,period,
    line,selection_code,selection_label,decimal_odds,observed_at_utc

``start_time_utc`` and ``observed_at_utc`` are ISO-8601 with an explicit offset.
A naive timestamp is rejected: guessing a timezone would be inventing data.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from betmaxxing.domain.enums import MarketType, Period, ProviderHealth, Sport
from betmaxxing.domain.ids import event_canonical_id, participant_id
from betmaxxing.domain.models import (
    CanonicalEvent,
    OddsSnapshot,
    Participant,
    ProviderStatus,
    Selection,
)
from betmaxxing.domain.timeutil import ensure_utc, is_in_window, utc_now
from betmaxxing.providers.base import CollectionBatch, collect_via_listing

REQUIRED_COLUMNS = (
    "bookmaker",
    "sport",
    "competition",
    "home",
    "away",
    "start_time_utc",
    "market",
    "period",
    "selection_code",
    "selection_label",
    "decimal_odds",
    "observed_at_utc",
)

PROVIDER_NAME = "manual_csv"


class ManualImportError(ValueError):
    """The file could not be parsed into valid snapshots."""


@dataclass(frozen=True, slots=True)
class ImportReport:
    events: list[CanonicalEvent]
    snapshots: list[OddsSnapshot]
    #: (row number, reason) for every rejected row — quarantined, never dropped.
    quarantined: list[tuple[int, str]]


def _parse_datetime(value: str, field: str, row_no: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ManualImportError(f"row {row_no}: {field} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ManualImportError(
            f"row {row_no}: {field} has no UTC offset — a timezone is never assumed"
        )
    return ensure_utc(parsed)


def parse_rows(rows: Iterable[dict[str, str]]) -> ImportReport:
    """Parse already-read CSV rows into events and snapshots."""
    events: dict[str, CanonicalEvent] = {}
    snapshots: list[OddsSnapshot] = []
    quarantined: list[tuple[int, str]] = []
    received_at = utc_now()

    for index, row in enumerate(rows, start=2):  # row 1 is the header
        try:
            missing = [c for c in REQUIRED_COLUMNS if not (row.get(c) or "").strip()]
            if missing:
                raise ManualImportError(f"row {index}: missing column(s) {', '.join(missing)}")

            sport = Sport(row["sport"].strip().lower())
            market = MarketType(row["market"].strip().lower())
            period = Period(row["period"].strip().lower())
            start = _parse_datetime(row["start_time_utc"], "start_time_utc", index)
            observed = _parse_datetime(row["observed_at_utc"], "observed_at_utc", index)

            raw_line = (row.get("line") or "").strip()
            line = Decimal(raw_line) if raw_line else None

            odds = float(row["decimal_odds"].strip().replace(",", "."))
            if odds <= 1.0:
                raise ManualImportError(f"row {index}: decimal odds must be > 1.0, got {odds}")

            home_name = row["home"].strip()
            away_name = row["away"].strip()
            canonical = event_canonical_id(str(sport), home_name, away_name, start)

            if canonical not in events:
                events[canonical] = CanonicalEvent(
                    internal_id=canonical,
                    sport=sport,
                    competition=row["competition"].strip(),
                    stage=(row.get("stage") or "").strip() or None,
                    surface=(row.get("surface") or "").strip() or None,
                    sets_to_win=int(row["sets_to_win"])
                    if (row.get("sets_to_win") or "").strip()
                    else None,
                    home=Participant(
                        canonical_id=participant_id(str(sport), home_name), name=home_name
                    ),
                    away=Participant(
                        canonical_id=participant_id(str(sport), away_name), name=away_name
                    ),
                    start_time_utc=start,
                    source_ids={PROVIDER_NAME: canonical},
                )

            selection = Selection(
                market=market,
                period=period,
                code=row["selection_code"].strip().lower(),
                label=row["selection_label"].strip(),
                line=line,
            )
            snapshots.append(
                OddsSnapshot(
                    provider=PROVIDER_NAME,
                    bookmaker=row["bookmaker"].strip(),
                    event_internal_id=canonical,
                    event_source_id=canonical,
                    selection=selection,
                    decimal_odds=odds,
                    currency=(row.get("currency") or "EUR").strip() or "EUR",
                    provider_updated_at=None,
                    observed_at=observed,
                    received_at=received_at,
                    source_meta={"import": "manual_csv", "row": str(index)},
                )
            )
        except (ManualImportError, ValueError) as exc:
            quarantined.append((index, str(exc)))

    return ImportReport(events=list(events.values()), snapshots=snapshots, quarantined=quarantined)


def load_csv(path: str | Path) -> ImportReport:
    """Read a manual odds CSV from disk."""
    file_path = Path(path)
    if not file_path.exists():
        raise ManualImportError(f"file not found: {file_path}")
    with file_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ManualImportError("empty CSV: a header row is required")
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ManualImportError(f"missing required column(s): {', '.join(missing)}")
        return parse_rows(list(reader))


class ManualCsvOddsProvider:
    """Serves previously imported snapshots. Bookmaker is whatever the file said."""

    name = PROVIDER_NAME

    def __init__(self, report: ImportReport, bookmaker: str | None = None) -> None:
        self._report = report
        self.bookmaker = bookmaker or (
            report.snapshots[0].bookmaker if report.snapshots else "unknown"
        )

    def health(self) -> ProviderStatus:
        if not self._report.snapshots:
            return ProviderStatus(
                name=self.name,
                kind="odds",
                health=ProviderHealth.NOT_CONFIGURED,
                detail="Aucune cote importée manuellement.",
            )
        freshest = min((utc_now() - s.observed_at).total_seconds() for s in self._report.snapshots)
        return ProviderStatus(
            name=self.name,
            kind="odds",
            health=ProviderHealth.OK,
            detail=(
                f"Import manuel horodaté ({self.bookmaker}). "
                f"{len(self._report.quarantined)} ligne(s) en quarantaine."
            ),
            events_returned=len(self._report.events),
            freshest_observation_age_seconds=max(0.0, freshest),
        )

    def list_events(
        self, sports: list[Sport], window: tuple[datetime, datetime]
    ) -> list[CanonicalEvent]:
        wanted = set(sports)
        return [
            e
            for e in self._report.events
            if e.sport in wanted and is_in_window(e.start_time_utc, window)
        ]

    def collect(self, sports: list[Sport], window: tuple[datetime, datetime]) -> CollectionBatch:
        return collect_via_listing(self, sports, window, utc_now())

    def fetch_odds(self, events: list[CanonicalEvent]) -> list[OddsSnapshot]:
        wanted = {e.internal_id for e in events}
        return [s for s in self._report.snapshots if s.event_internal_id in wanted]
