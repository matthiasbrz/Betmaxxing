"""Notification adapters and the alert deduplication rules.

Alerts are opt-in and idempotent. A new message goes out only on a *material*
change, which is defined here once so Telegram, e-mail and SMS cannot drift apart:

* a candidate entering the qualified zone;
* a material change of odds, EV or status on an already-alerted candidate;
* invalidation or expiry.

Everything else is silence. During tests no adapter ever performs I/O: the
concrete senders check ``settings.notifications_enabled`` and the test suite
leaves it false, while :class:`RecordingNotifier` captures messages in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time

from betmaxxing.domain.enums import ProviderHealth
from betmaxxing.domain.models import ProviderStatus
from betmaxxing.domain.timeutil import PARIS, to_display

#: Relative odds move considered material.
MATERIAL_ODDS_CHANGE = 0.02
#: Absolute EV move (in EV units) considered material.
MATERIAL_EV_CHANGE = 0.01


@dataclass(frozen=True, slots=True)
class AlertState:
    """What was last communicated for one candidate identity."""

    alert_key: str
    odds: float
    ev: float
    status: str
    sent_at: datetime


def is_material_change(previous: AlertState, odds: float, ev: float, status: str) -> bool:
    """Whether the change since ``previous`` justifies a new message."""
    if status != previous.status:
        return True
    if previous.odds > 0 and abs(odds - previous.odds) / previous.odds >= MATERIAL_ODDS_CHANGE:
        return True
    return abs(ev - previous.ev) >= MATERIAL_EV_CHANGE


def in_quiet_hours(moment: datetime, start_hour: int, end_hour: int) -> bool:
    """Quiet hours are evaluated in the display timezone, not UTC.

    A window that wraps midnight (23 -> 8) is handled explicitly.
    """
    local = to_display(moment, PARIS).time()
    start = time(hour=start_hour)
    end = time(hour=end_hour)
    if start <= end:
        return start <= local < end
    return local >= start or local < end


class RecordingNotifier:
    """In-memory notifier. The only one used by the test suite."""

    name = "recording"

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            kind="notification",
            health=ProviderHealth.OK,
            detail="Notifieur en mémoire — aucun envoi réel.",
        )

    def send(self, subject: str, body: str) -> bool:
        self.messages.append((subject, body))
        return True


class ConsoleNotifier:
    """Prints to stdout. Default channel, safe everywhere."""

    name = "console"

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            kind="notification",
            health=ProviderHealth.OK if self.enabled else ProviderHealth.NOT_CONFIGURED,
            detail="Sortie console.",
        )

    def send(self, subject: str, body: str) -> bool:
        if not self.enabled:
            return False
        print(f"\n=== {subject} ===\n{body}\n")
        return True


@dataclass(slots=True)
class AlertLedger:
    """Tracks what has already been sent so repeated scans stay quiet."""

    sent: dict[str, AlertState] = field(default_factory=dict)

    def should_send(self, alert_key: str, odds: float, ev: float, status: str) -> bool:
        previous = self.sent.get(alert_key)
        if previous is None:
            return True
        return is_material_change(previous, odds, ev, status)

    def record(self, alert_key: str, odds: float, ev: float, status: str, moment: datetime) -> None:
        self.sent[alert_key] = AlertState(
            alert_key=alert_key, odds=odds, ev=ev, status=status, sent_at=moment
        )

    def forget(self, alert_key: str) -> None:
        self.sent.pop(alert_key, None)
