"""Time handling. One rule: everything is stored and computed in UTC; only the
presentation layer converts to ``Europe/Paris``.

DST is handled by :mod:`zoneinfo`; the 24-hour window is expressed as an absolute
timedelta so it stays exactly 24 hours across a clock change (a "day" in Paris may
be 23 or 25 hours, but the scan window is not a calendar day).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def utc_now() -> datetime:
    """Current instant, timezone-aware, in UTC."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalise any datetime to an aware UTC datetime.

    A naive datetime is rejected rather than silently assumed to be UTC: guessing
    a timezone is exactly the kind of invented data this project forbids.
    """
    if value.tzinfo is None:
        raise ValueError(f"naive datetime is not accepted: {value!r}")
    return value.astimezone(UTC)


def to_display(value: datetime, tz: ZoneInfo = PARIS) -> datetime:
    """Convert a UTC instant to the display timezone."""
    return ensure_utc(value).astimezone(tz)


def format_display(value: datetime, tz: ZoneInfo = PARIS) -> str:
    """Human-readable local timestamp, always carrying its UTC offset."""
    return to_display(value, tz).strftime("%Y-%m-%d %H:%M %Z")


def scan_window(now: datetime, hours: float) -> tuple[datetime, datetime]:
    """Half-open window ``]now, now + hours]`` in UTC.

    Returned as ``(from, to)``; membership is tested with
    :func:`is_in_window` so the exclusive lower bound is applied consistently.
    """
    start = ensure_utc(now)
    return start, start + timedelta(hours=hours)


def is_in_window(start_time: datetime, window: tuple[datetime, datetime]) -> bool:
    """True when ``start_time`` falls in ``]from, to]``."""
    lo, hi = window
    t = ensure_utc(start_time)
    return lo < t <= hi


def age_seconds(observed_at: datetime, now: datetime) -> float:
    """Seconds elapsed since an observation. Never negative."""
    return max(0.0, (ensure_utc(now) - ensure_utc(observed_at)).total_seconds())
