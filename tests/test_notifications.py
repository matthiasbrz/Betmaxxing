"""Alerting: deduplication, materiality, quiet hours, and no real sends."""

from __future__ import annotations

from datetime import UTC, datetime

from betmaxxing.config import RunMode, Settings
from betmaxxing.providers.notifications import (
    AlertLedger,
    AlertState,
    EmailNotifier,
    RecordingNotifier,
    SmsNotifier,
    TelegramNotifier,
    in_quiet_hours,
    is_material_change,
)

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


class TestMateriality:
    def _state(self, odds: float = 2.0, ev: float = 0.05) -> AlertState:
        return AlertState(alert_key="k", odds=odds, ev=ev, status="QUALIFIED", sent_at=NOW)

    def test_status_change_is_material(self) -> None:
        assert is_material_change(self._state(), 2.0, 0.05, "INVALIDATED")

    def test_significant_odds_move_is_material(self) -> None:
        assert is_material_change(self._state(2.00), 2.06, 0.05, "QUALIFIED")

    def test_small_odds_move_is_not_material(self) -> None:
        assert not is_material_change(self._state(2.00), 2.01, 0.05, "QUALIFIED")

    def test_significant_ev_move_is_material(self) -> None:
        assert is_material_change(self._state(ev=0.05), 2.0, 0.07, "QUALIFIED")

    def test_small_ev_move_is_not_material(self) -> None:
        assert not is_material_change(self._state(ev=0.05), 2.0, 0.055, "QUALIFIED")


class TestAlertLedger:
    def test_first_sighting_always_alerts(self) -> None:
        assert AlertLedger().should_send("k", 2.0, 0.05, "QUALIFIED")

    def test_repeat_scan_stays_quiet(self) -> None:
        ledger = AlertLedger()
        ledger.record("k", 2.0, 0.05, "QUALIFIED", NOW)
        assert not ledger.should_send("k", 2.0, 0.05, "QUALIFIED")

    def test_material_change_re_alerts(self) -> None:
        ledger = AlertLedger()
        ledger.record("k", 2.0, 0.05, "QUALIFIED", NOW)
        assert ledger.should_send("k", 2.10, 0.05, "QUALIFIED")

    def test_invalidation_re_alerts(self) -> None:
        ledger = AlertLedger()
        ledger.record("k", 2.0, 0.05, "QUALIFIED", NOW)
        assert ledger.should_send("k", 2.0, 0.05, "EXPIRED")

    def test_forgetting_restores_the_first_sighting_behaviour(self) -> None:
        ledger = AlertLedger()
        ledger.record("k", 2.0, 0.05, "QUALIFIED", NOW)
        ledger.forget("k")
        assert ledger.should_send("k", 2.0, 0.05, "QUALIFIED")

    def test_repeated_identical_scans_send_exactly_once(self) -> None:
        ledger = AlertLedger()
        sent = 0
        for _ in range(10):
            if ledger.should_send("k", 2.0, 0.05, "QUALIFIED"):
                ledger.record("k", 2.0, 0.05, "QUALIFIED", NOW)
                sent += 1
        assert sent == 1


class TestQuietHours:
    def test_window_wrapping_midnight_is_handled(self) -> None:
        # 23:00 -> 08:00 Paris. 02:00 UTC == 04:00 CEST in August, inside.
        assert in_quiet_hours(datetime(2026, 8, 4, 2, 0, tzinfo=UTC), 23, 8)

    def test_daytime_is_outside_a_wrapping_window(self) -> None:
        # 12:00 UTC == 14:00 CEST, outside.
        assert not in_quiet_hours(datetime(2026, 8, 4, 12, 0, tzinfo=UTC), 23, 8)

    def test_late_evening_is_inside_a_wrapping_window(self) -> None:
        # 22:00 UTC == 00:00 CEST next day, inside.
        assert in_quiet_hours(datetime(2026, 8, 4, 22, 0, tzinfo=UTC), 23, 8)

    def test_non_wrapping_window_is_handled(self) -> None:
        # 10:00 -> 12:00 Paris; 09:00 UTC == 11:00 CEST, inside.
        assert in_quiet_hours(datetime(2026, 8, 4, 9, 0, tzinfo=UTC), 10, 12)
        assert not in_quiet_hours(datetime(2026, 8, 4, 11, 0, tzinfo=UTC), 10, 12)

    def test_quiet_hours_use_local_time_not_utc(self) -> None:
        """13:00 UTC is 15:00 in Paris — outside a 13:00-14:00 local window."""
        assert not in_quiet_hours(datetime(2026, 8, 4, 13, 0, tzinfo=UTC), 13, 14)


class TestNoRealSendsInTests:
    """Every channel must refuse to transmit unless explicitly enabled."""

    def _disabled(self) -> Settings:
        return Settings(mode=RunMode.DEMO, notifications_enabled=False)

    def test_telegram_refuses_when_notifications_are_disabled(self) -> None:
        assert TelegramNotifier(self._disabled()).send("s", "b") is False

    def test_telegram_refuses_without_credentials(self) -> None:
        enabled = Settings(mode=RunMode.DEMO, notifications_enabled=True)
        assert TelegramNotifier(enabled).send("s", "b") is False
        assert TelegramNotifier(enabled).health().health.value == "not_configured"

    def test_email_refuses_when_notifications_are_disabled(self) -> None:
        assert EmailNotifier(self._disabled()).send("s", "b") is False

    def test_email_refuses_without_smtp_configuration(self) -> None:
        enabled = Settings(mode=RunMode.DEMO, notifications_enabled=True)
        assert EmailNotifier(enabled).send("s", "b") is False

    def test_sms_never_sends_in_v1(self) -> None:
        # Behind the interface deliberately: per-message cost.
        enabled = Settings(
            mode=RunMode.DEMO,
            notifications_enabled=True,
        )
        assert SmsNotifier(enabled).send("s", "b") is False
        assert "coût" in SmsNotifier(enabled).health().detail


class TestRecordingNotifier:
    def test_captures_messages_in_memory(self) -> None:
        notifier = RecordingNotifier()
        assert notifier.send("sujet", "corps") is True
        assert notifier.messages == [("sujet", "corps")]

    def test_reports_healthy(self) -> None:
        assert RecordingNotifier().health().health.value == "ok"


class TestChannelHealthReporting:
    def test_configured_but_disabled_is_reported_as_not_configured(self) -> None:
        settings = Settings(
            mode=RunMode.DEMO,
            notifications_enabled=False,
            telegram_bot_token="x",
            telegram_chat_id="y",
        )
        status = TelegramNotifier(settings).health()
        assert status.health.value == "not_configured"
        assert "désactivées" in status.detail

    def test_secrets_never_appear_in_health_output(self) -> None:
        settings = Settings(
            mode=RunMode.DEMO,
            notifications_enabled=True,
            telegram_bot_token="SUPER_SECRET_TOKEN",
            telegram_chat_id="123",
        )
        status = TelegramNotifier(settings).health()
        assert "SUPER_SECRET_TOKEN" not in status.detail
        assert "SUPER_SECRET_TOKEN" not in status.model_dump_json()
