"""Snapshot deduplication, book assembly and quarantine.

Two things happen here, and nowhere else:

1. **Deduplication.** The same price observed twice is one fact, not two. The
   snapshot fingerprint (book + selection + price + instant) is the key.
2. **Book assembly.** Snapshots are grouped into ``MarketBook`` objects keyed by
   (event, bookmaker, market, period, line). Prices from two different bookmakers
   are never merged into one book: settlement rules differ, and mixing them would
   produce a market that nobody actually offers.

Records that cannot be trusted are *quarantined* — kept, with a reason — rather
than silently discarded, so a scan can always explain what it did not use.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from betmaxxing.domain.enums import EXPECTED_SELECTION_COUNT, MarketType, Period
from betmaxxing.domain.models import MarketBook, OddsSnapshot
from betmaxxing.domain.timeutil import ensure_utc

BookKey = tuple[str, str, MarketType, Period, float | None]


@dataclass(slots=True)
class QuarantineRecord:
    snapshot: OddsSnapshot
    reason: str


@dataclass(slots=True)
class NormalizationResult:
    books: list[MarketBook]
    duplicates_dropped: int = 0
    quarantined: list[QuarantineRecord] = field(default_factory=list)

    @property
    def snapshot_count(self) -> int:
        return sum(len(b.snapshots) for b in self.books)


def deduplicate(snapshots: list[OddsSnapshot]) -> tuple[list[OddsSnapshot], int]:
    """Drop exact repeats, keeping first occurrence. Returns (kept, dropped)."""
    seen: set[str] = set()
    kept: list[OddsSnapshot] = []
    dropped = 0
    for snapshot in snapshots:
        fingerprint = snapshot.fingerprint
        if fingerprint in seen:
            dropped += 1
            continue
        seen.add(fingerprint)
        kept.append(snapshot)
    return kept, dropped


def latest_per_selection(snapshots: list[OddsSnapshot]) -> list[OddsSnapshot]:
    """Keep only the most recent observation per (book, selection).

    History is preserved elsewhere (the odds-movement trail); this is the view the
    scorer uses, and it must contain exactly one price per selection.
    """
    best: dict[tuple[str, str, str], OddsSnapshot] = {}
    for snapshot in snapshots:
        key = (snapshot.bookmaker, snapshot.event_canonical_id, snapshot.selection.key)
        current = best.get(key)
        if current is None or snapshot.observed_at > current.observed_at:
            best[key] = snapshot
    return list(best.values())


def _validate(snapshot: OddsSnapshot, now: datetime) -> str | None:
    """Return a quarantine reason, or ``None`` when the snapshot is usable."""
    if snapshot.decimal_odds <= 1.0:
        return f"cote décimale invalide ({snapshot.decimal_odds})"
    if snapshot.observed_at > ensure_utc(now):
        return "observed_at dans le futur — horodatage incohérent"
    if snapshot.received_at < snapshot.observed_at:
        return "received_at antérieur à observed_at"
    if snapshot.selection.market in (MarketType.TOTAL_GOALS, MarketType.TOTAL_GAMES):
        line = snapshot.selection.line
        if line is None:
            return "ligne manquante sur un marché over/under"
        if abs(line - round(line)) < 1e-9:
            return f"ligne entière ({line}) non supportée en V1 — remboursement possible"
    return None


def assemble_books(snapshots: list[OddsSnapshot], now: datetime) -> NormalizationResult:
    """Validate, deduplicate and group snapshots into per-bookmaker books."""
    deduped, dropped = deduplicate(snapshots)

    usable: list[OddsSnapshot] = []
    quarantined: list[QuarantineRecord] = []
    for snapshot in deduped:
        reason = _validate(snapshot, now)
        if reason is None:
            usable.append(snapshot)
        else:
            quarantined.append(QuarantineRecord(snapshot=snapshot, reason=reason))

    current = latest_per_selection(usable)

    grouped: dict[BookKey, list[OddsSnapshot]] = defaultdict(list)
    for snapshot in current:
        key: BookKey = (
            snapshot.event_canonical_id,
            snapshot.bookmaker,
            snapshot.selection.market,
            snapshot.selection.period,
            snapshot.selection.line,
        )
        grouped[key].append(snapshot)

    books = [
        MarketBook(
            event_canonical_id=event_id,
            bookmaker=bookmaker,
            market=market,
            period=period,
            line=line,
            snapshots=sorted(items, key=lambda s: s.selection.code),
        )
        for (event_id, bookmaker, market, period, line), items in sorted(
            grouped.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]), str(kv[0][3]))
        )
    ]
    return NormalizationResult(books=books, duplicates_dropped=dropped, quarantined=quarantined)


def is_book_complete(book: MarketBook) -> bool:
    """Whether every selection the market requires has a price."""
    expected = EXPECTED_SELECTION_COUNT.get(book.market)
    if expected is None:  # pragma: no cover - MarketType is exhaustive
        return False
    codes = {s.selection.code for s in book.snapshots}
    return len(codes) == expected == len(book.snapshots)


def odds_movement(history: list[OddsSnapshot]) -> list[dict[str, object]]:
    """Chronological price trail for one selection, oldest first."""
    ordered = sorted(history, key=lambda s: s.observed_at)
    return [
        {
            "observed_at": s.observed_at.isoformat(),
            "decimal_odds": s.decimal_odds,
            "bookmaker": s.bookmaker,
        }
        for s in ordered
    ]
