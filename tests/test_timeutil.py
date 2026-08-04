"""Time and the 24-hour window.

Acceptance criterion: the window and the timezone handling are tested across
daylight-saving transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from betmaxxing.domain.timeutil import (
    PARIS,
    age_seconds,
    ensure_utc,
    format_display,
    is_in_window,
    scan_window,
    to_display,
)

#: Spring forward: 02:00 -> 03:00 local on 29 March 2026.
DST_SPRING = datetime(2026, 3, 29, 0, 0, tzinfo=UTC)
#: Fall back: 03:00 -> 02:00 local on 25 October 2026.
DST_AUTUMN = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)


class TestEnsureUtc:
    def test_converts_an_aware_datetime(self) -> None:
        local = datetime(2026, 8, 4, 14, 0, tzinfo=PARIS)
        assert ensure_utc(local) == datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    def test_rejects_a_naive_datetime(self) -> None:
        # Assuming a timezone would be inventing data.
        with pytest.raises(ValueError, match="naive datetime"):
            ensure_utc(datetime(2026, 8, 4, 14, 0))


class TestDisplayConversion:
    def test_summer_offset_is_two_hours(self) -> None:
        moment = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
        assert to_display(moment).hour == 14
        assert "CEST" in format_display(moment)

    def test_winter_offset_is_one_hour(self) -> None:
        moment = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        assert to_display(moment).hour == 13
        assert "CET" in format_display(moment)


class TestScanWindow:
    def test_window_is_exactly_the_configured_duration(self) -> None:
        now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
        start, end = scan_window(now, 24)
        assert end - start == timedelta(hours=24)

    def test_lower_bound_is_exclusive(self) -> None:
        now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
        window = scan_window(now, 24)
        assert not is_in_window(now, window)

    def test_upper_bound_is_inclusive(self) -> None:
        now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
        window = scan_window(now, 24)
        assert is_in_window(now + timedelta(hours=24), window)

    def test_event_just_past_the_upper_bound_is_excluded(self) -> None:
        now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
        window = scan_window(now, 24)
        assert not is_in_window(now + timedelta(hours=24, seconds=1), window)

    @pytest.mark.parametrize("transition", [DST_SPRING, DST_AUTUMN])
    def test_window_stays_24_absolute_hours_across_a_dst_change(self, transition: datetime) -> None:
        """A Paris "day" may be 23 or 25 hours; the scan window is neither.

        It is an absolute 24-hour lookahead, so the number of local hours it
        spans changes but its duration does not.
        """
        start, end = scan_window(transition, 24)
        assert end - start == timedelta(hours=24)

    def test_spring_forward_window_covers_23_local_hours(self) -> None:
        start, end = scan_window(DST_SPRING, 24)
        local_span = to_display(end).replace(tzinfo=None) - to_display(start).replace(tzinfo=None)
        assert local_span == timedelta(hours=25)

    def test_autumn_fallback_window_covers_25_local_hours(self) -> None:
        start, end = scan_window(DST_AUTUMN, 24)
        local_span = to_display(end).replace(tzinfo=None) - to_display(start).replace(tzinfo=None)
        assert local_span == timedelta(hours=23)

    def test_event_across_a_dst_boundary_is_classified_correctly(self) -> None:
        # 20:00 Paris on the evening of the spring-forward day.
        event_local = datetime(2026, 3, 29, 20, 0, tzinfo=PARIS)
        window = scan_window(DST_SPRING, 24)
        assert is_in_window(event_local, window)


class TestAgeSeconds:
    def test_computes_elapsed_time(self) -> None:
        now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
        observed = now - timedelta(minutes=5)
        assert age_seconds(observed, now) == pytest.approx(300.0)

    def test_never_returns_a_negative_age(self) -> None:
        now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
        assert age_seconds(now + timedelta(minutes=5), now) == 0.0
