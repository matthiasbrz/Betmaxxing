"""Ingestion: deduplication, book assembly, quarantine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from betmaxxing.domain.enums import MarketType, Period
from betmaxxing.domain.models import OddsSnapshot, Selection
from betmaxxing.ingestion.normalize import (
    assemble_books,
    deduplicate,
    is_book_complete,
    latest_per_selection,
    odds_movement,
)

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
EVENT_ID = "football-20260804-abc"


def snapshot(
    code: str,
    odds: float,
    *,
    observed: datetime | None = None,
    bookmaker: str = "DEMO_BOOK",
    market: MarketType = MarketType.MATCH_RESULT_1X2,
    period: Period = Period.FULL_TIME,
    line: float | None = None,
) -> OddsSnapshot:
    moment = observed or NOW
    return OddsSnapshot(
        provider="demo",
        bookmaker=bookmaker,
        event_canonical_id=EVENT_ID,
        event_source_id="src",
        selection=Selection(market=market, period=period, code=code, label=code.title(), line=line),
        decimal_odds=odds,
        observed_at=moment,
        received_at=NOW,
    )


FULL_BOOK = [snapshot("home", 1.63), snapshot("draw", 4.20), snapshot("away", 5.00)]


class TestDeduplicate:
    def test_identical_observations_collapse(self) -> None:
        kept, dropped = deduplicate([snapshot("home", 1.63), snapshot("home", 1.63)])
        assert len(kept) == 1
        assert dropped == 1

    def test_a_price_change_is_not_a_duplicate(self) -> None:
        kept, dropped = deduplicate([snapshot("home", 1.63), snapshot("home", 1.64)])
        assert len(kept) == 2
        assert dropped == 0

    def test_the_same_price_at_a_later_instant_is_a_new_observation(self) -> None:
        later = snapshot("home", 1.63, observed=NOW + timedelta(minutes=1))
        kept, dropped = deduplicate([snapshot("home", 1.63), later])
        assert len(kept) == 2
        assert dropped == 0


class TestLatestPerSelection:
    def test_keeps_only_the_most_recent_price(self) -> None:
        old = snapshot("home", 1.70, observed=NOW - timedelta(minutes=10))
        new = snapshot("home", 1.63)
        latest = latest_per_selection([old, new])
        assert len(latest) == 1
        assert latest[0].decimal_odds == 1.63

    def test_keeps_one_price_per_bookmaker(self) -> None:
        latest = latest_per_selection(
            [snapshot("home", 1.63), snapshot("home", 1.68, bookmaker="OTHER")]
        )
        assert len(latest) == 2


class TestAssembleBooks:
    def test_groups_a_complete_market(self) -> None:
        result = assemble_books(FULL_BOOK, NOW)
        assert len(result.books) == 1
        assert is_book_complete(result.books[0])

    def test_never_merges_two_bookmakers_into_one_book(self) -> None:
        """Settlement rules differ between books; a merged market exists nowhere."""
        mixed = [*FULL_BOOK, snapshot("home", 1.68, bookmaker="OTHER")]
        result = assemble_books(mixed, NOW)
        assert len(result.books) == 2
        assert {b.bookmaker for b in result.books} == {"DEMO_BOOK", "OTHER"}

    def test_separates_periods(self) -> None:
        mixed = [*FULL_BOOK, snapshot("home", 2.04, period=Period.FIRST_HALF)]
        result = assemble_books(mixed, NOW)
        assert len(result.books) == 2

    def test_separates_lines(self) -> None:
        totals = [
            snapshot("over", 1.86, market=MarketType.TOTAL_GOALS, line=2.5),
            snapshot("under", 1.98, market=MarketType.TOTAL_GOALS, line=2.5),
            snapshot("over", 2.60, market=MarketType.TOTAL_GOALS, line=3.5),
            snapshot("under", 1.50, market=MarketType.TOTAL_GOALS, line=3.5),
        ]
        result = assemble_books(totals, NOW)
        assert len(result.books) == 2
        assert {b.line for b in result.books} == {2.5, 3.5}

    def test_incomplete_book_is_detected(self) -> None:
        result = assemble_books(FULL_BOOK[:2], NOW)
        assert not is_book_complete(result.books[0])

    def test_overround_and_margin_are_computed(self) -> None:
        book = assemble_books(FULL_BOOK, NOW).books[0]
        assert book.overround == pytest.approx(1 / 1.63 + 1 / 4.20 + 1 / 5.00)
        assert book.margin == pytest.approx(book.overround - 1.0)


class TestQuarantine:
    def test_future_observation_is_quarantined(self) -> None:
        result = assemble_books([snapshot("home", 1.63, observed=NOW + timedelta(hours=1))], NOW)
        assert len(result.quarantined) == 1
        assert "futur" in result.quarantined[0].reason

    def test_integer_over_under_line_is_quarantined(self) -> None:
        # An integer line can void; it is a different bet and V1 does not price it.
        result = assemble_books(
            [snapshot("over", 1.90, market=MarketType.TOTAL_GOALS, line=3.0)], NOW
        )
        assert len(result.quarantined) == 1
        assert "ligne entière" in result.quarantined[0].reason

    def test_quarantined_records_are_kept_not_discarded(self) -> None:
        result = assemble_books(
            [*FULL_BOOK, snapshot("home", 1.63, observed=NOW + timedelta(hours=1))], NOW
        )
        assert len(result.quarantined) == 1
        assert result.quarantined[0].snapshot is not None
        assert len(result.books) == 1


class TestOddsMovement:
    def test_returns_a_chronological_trail(self) -> None:
        history = [
            snapshot("home", 1.70, observed=NOW - timedelta(minutes=30)),
            snapshot("home", 1.63, observed=NOW),
            snapshot("home", 1.66, observed=NOW - timedelta(minutes=15)),
        ]
        trail = odds_movement(history)
        assert [entry["decimal_odds"] for entry in trail] == [1.70, 1.66, 1.63]

    def test_empty_history_yields_an_empty_trail(self) -> None:
        assert odds_movement([]) == []
