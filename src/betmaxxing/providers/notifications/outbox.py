"""At-most-once external effects, keyed by the job that produced them.

A fencing token protects the *ledger*. It cannot protect the outside world: by
the time a worker discovers it lost its lease, any message it sent has already
arrived. So the previous tranche's claim — that fencing makes a re-executed job
safe — was only true of the bookkeeping.

The guard has to sit on the effect itself. Claiming a row here is what authorises
one delivery of one alert on one channel for one job occurrence; the unique
constraint on ``(job_id, alert_key, channel)`` is what makes a second execution
of the same occurrence silent instead of noisy.

Two deliberate choices:

* the key includes ``job_id``, not just ``alert_key``. A genuinely new occurrence
  (tomorrow's scan, the next milestone) *should* be able to re-alert on a
  material change; what must not happen is the same occurrence alerting twice
  because its lease changed hands;
* ``claim`` is separate from ``mark_sent``. The row is reserved before the send,
  so a crash mid-delivery leaves an unsent claim — visible, and never a silent
  duplicate. Losing one notification is recoverable; sending two identical
  betting alerts is the failure mode that erodes trust in every later one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from betmaxxing.config import Settings
from betmaxxing.domain.timeutil import ensure_utc, utc_now
from betmaxxing.storage.db import create_all, session_scope
from betmaxxing.storage.tables import NotificationOutboxRow

logger = logging.getLogger("betmaxxing.notifications")


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    job_id: str
    alert_key: str
    channel: str
    claimed_at: datetime
    sent_at: datetime | None

    @property
    def delivered(self) -> bool:
        return self.sent_at is not None


class NotificationOutbox:
    """Reserve-before-send bookkeeping for notifications."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        create_all(settings)

    def claim(
        self, *, job_id: str, alert_key: str, channel: str, now: datetime | None = None
    ) -> bool:
        """Reserve the right to send exactly once. ``False`` means already claimed.

        The unique constraint is the arbiter, not a prior ``SELECT``: two workers
        checking "does a row exist?" both see no, and both send. Letting the
        insert fail is what makes this safe under concurrency.
        """
        moment = ensure_utc(now or utc_now())
        try:
            with session_scope(self._settings) as session:
                session.add(
                    NotificationOutboxRow(
                        job_id=job_id,
                        alert_key=alert_key,
                        channel=channel,
                        claimed_at=moment,
                        sent_at=None,
                    )
                )
        except IntegrityError:
            logger.debug(
                "notification already claimed",
                extra={"job_key": job_id, "alert_key": alert_key, "channel": channel},
            )
            return False
        return True

    def mark_sent(
        self, *, job_id: str, alert_key: str, channel: str, now: datetime | None = None
    ) -> None:
        moment = ensure_utc(now or utc_now())
        with session_scope(self._settings) as session:
            session.execute(
                update(NotificationOutboxRow)
                .where(
                    NotificationOutboxRow.job_id == job_id,
                    NotificationOutboxRow.alert_key == alert_key,
                    NotificationOutboxRow.channel == channel,
                    NotificationOutboxRow.sent_at.is_(None),
                )
                .values(sent_at=moment)
            )

    def entries_for(self, job_id: str) -> list[OutboxEntry]:
        with session_scope(self._settings) as session:
            rows = session.scalars(
                select(NotificationOutboxRow)
                .where(NotificationOutboxRow.job_id == job_id)
                .order_by(NotificationOutboxRow.id)
            ).all()
            return [
                OutboxEntry(
                    job_id=row.job_id,
                    alert_key=row.alert_key,
                    channel=row.channel,
                    claimed_at=row.claimed_at,
                    sent_at=row.sent_at,
                )
                for row in rows
            ]

    def unsent(self) -> list[OutboxEntry]:
        """Claims that were never confirmed — a crash mid-delivery leaves these."""
        with session_scope(self._settings) as session:
            rows = session.scalars(
                select(NotificationOutboxRow)
                .where(NotificationOutboxRow.sent_at.is_(None))
                .order_by(NotificationOutboxRow.id)
            ).all()
            return [
                OutboxEntry(
                    job_id=row.job_id,
                    alert_key=row.alert_key,
                    channel=row.channel,
                    claimed_at=row.claimed_at,
                    sent_at=row.sent_at,
                )
                for row in rows
            ]


__all__ = ["NotificationOutbox", "OutboxEntry"]
