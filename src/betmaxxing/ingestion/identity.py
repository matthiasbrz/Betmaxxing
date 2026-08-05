"""Stable event identity.

The previous scheme derived an event's id from ``(sport, UTC date, normalised
participants)``. Two failures follow directly from that:

* **Postponement.** A 23:30 UTC kick-off pushed to 00:30 changes the date
  component, so the same fixture became a second event with no shared history.
* **Collision.** Two legs of a tie, or two matches between the same players on
  one day, hashed to the same id and were silently merged.

Identity is now opaque and assigned once. Resolution works in two steps:

1. **Authoritative.** ``(provider, provider_event_id)`` is looked up in a mapping
   table. A provider that keeps its own id stable across a postponement gives us
   a stable internal id for free — this is the path that fixes reschedules.
2. **Cross-provider match.** Only when the pair is unknown: same sport, same
   normalised participants, and a kick-off within a tight tolerance. Exactly one
   match links; more than one is recorded as **ambiguous** and refused, because
   guessing which fixture a price belongs to is worse than declining to price it.

Kick-off times and statuses are appended to a history table rather than
overwritten, so a reschedule is visible after the fact.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from betmaxxing.config import Settings
from betmaxxing.domain.enums import EventStatus, Sport
from betmaxxing.domain.ids import normalize_participant
from betmaxxing.domain.timeutil import ensure_utc, from_storage, utc_now
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import EventRow, EventScheduleHistoryRow, EventSourceMapRow

#: How far a kick-off may move and still be considered the same fixture when
#: matching *across providers*. Tight on purpose: a wide window would merge two
#: legs played on the same day, which is the collision we are fixing.
CROSS_PROVIDER_TOLERANCE = timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class ResolvedEvent:
    """Outcome of resolving a provider's event onto internal identity."""

    internal_id: str
    created: bool
    #: True when more than one existing event matched; the caller must refuse.
    ambiguous: bool
    ambiguity_detail: str = ""
    #: True when the kick-off moved relative to what we had stored.
    rescheduled: bool = False


def new_internal_id() -> str:
    """Opaque identity. No date, no participants, no semantics to drift."""
    return f"evt_{uuid.uuid4().hex[:20]}"


def participant_pair_key(sport: Sport, home: str, away: str) -> str:
    """Order-sensitive participant key used for cross-provider matching."""
    return f"{sport}|{normalize_participant(home)}|{normalize_participant(away)}"


class EventIdentityService:
    """Resolves provider events onto stable internal ids."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve(
        self,
        *,
        provider: str,
        provider_event_id: str,
        sport: Sport,
        competition: str,
        home_name: str,
        away_name: str,
        start_time_utc: datetime,
        status: EventStatus = EventStatus.SCHEDULED,
    ) -> ResolvedEvent:
        """Map a provider's event onto an internal id, creating one if needed."""
        start = ensure_utc(start_time_utc)
        pair_key = participant_pair_key(sport, home_name, away_name)

        with session_scope(self._settings) as session:
            mapped = session.scalar(
                select(EventSourceMapRow).where(
                    EventSourceMapRow.provider == provider,
                    EventSourceMapRow.provider_event_id == provider_event_id,
                )
            )
            if mapped is not None:
                # Authoritative path. A moved kick-off is the *same* event.
                row = session.get(EventRow, mapped.internal_id)
                rescheduled = False
                if row is not None:
                    previous = from_storage(row.start_time_utc)
                    if previous != start or row.status != str(status):
                        rescheduled = previous != start
                        session.add(
                            EventScheduleHistoryRow(
                                internal_id=row.canonical_id,
                                start_time_utc=start,
                                status=str(status),
                                recorded_at=utc_now(),
                                previous_start_time_utc=previous,
                            )
                        )
                        row.start_time_utc = start
                        row.status = str(status)
                return ResolvedEvent(
                    internal_id=mapped.internal_id,
                    created=False,
                    ambiguous=False,
                    rescheduled=rescheduled,
                )

            # Cross-provider matching, deliberately narrow.
            lo, hi = start - CROSS_PROVIDER_TOLERANCE, start + CROSS_PROVIDER_TOLERANCE
            candidates = list(
                session.scalars(
                    select(EventRow).where(
                        EventRow.sport == str(sport),
                        EventRow.participant_pair_key == pair_key,
                        EventRow.start_time_utc >= lo,
                        EventRow.start_time_utc <= hi,
                    )
                ).all()
            )

            # A provider is authoritative about its own catalogue. If it already
            # gave us an event under a *different* id, this is a different
            # fixture — two legs of a tie, a rematch — not the same one. Merging
            # them would resurrect exactly the collision this design removes.
            already_mapped = set(
                session.scalars(
                    select(EventSourceMapRow.internal_id).where(
                        EventSourceMapRow.provider == provider
                    )
                ).all()
            )
            candidates = [c for c in candidates if c.canonical_id not in already_mapped]

            if len(candidates) > 1:
                detail = (
                    f"{len(candidates)} événements existants correspondent à "
                    f"{pair_key} autour de {start.isoformat()} — rapprochement refusé."
                )
                return ResolvedEvent(
                    internal_id=candidates[0].canonical_id,
                    created=False,
                    ambiguous=True,
                    ambiguity_detail=detail,
                )

            if len(candidates) == 1:
                internal_id = candidates[0].canonical_id
                session.add(
                    EventSourceMapRow(
                        provider=provider,
                        provider_event_id=provider_event_id,
                        internal_id=internal_id,
                    )
                )
                return ResolvedEvent(internal_id=internal_id, created=False, ambiguous=False)

            internal_id = new_internal_id()
            session.add(
                EventRow(
                    canonical_id=internal_id,
                    sport=str(sport),
                    competition=competition,
                    home_name=home_name,
                    away_name=away_name,
                    home_canonical_id=f"{sport}:{normalize_participant(home_name)}",
                    away_canonical_id=f"{sport}:{normalize_participant(away_name)}",
                    participant_pair_key=pair_key,
                    start_time_utc=start,
                    status=str(status),
                    mapping_ambiguous=False,
                    source_ids={provider: provider_event_id},
                )
            )
            session.flush()
            session.add(
                EventSourceMapRow(
                    provider=provider,
                    provider_event_id=provider_event_id,
                    internal_id=internal_id,
                )
            )
            session.add(
                EventScheduleHistoryRow(
                    internal_id=internal_id,
                    start_time_utc=start,
                    status=str(status),
                    recorded_at=utc_now(),
                    previous_start_time_utc=None,
                )
            )
            return ResolvedEvent(internal_id=internal_id, created=True, ambiguous=False)

    def schedule_history(self, internal_id: str) -> list[dict[str, object]]:
        """Recorded kick-off and status changes for one event."""
        with session_scope(self._settings) as session:
            rows = session.scalars(
                select(EventScheduleHistoryRow)
                .where(EventScheduleHistoryRow.internal_id == internal_id)
                .order_by(EventScheduleHistoryRow.recorded_at)
            ).all()
            return [
                {
                    "start_time_utc": r.start_time_utc.isoformat(),
                    "previous_start_time_utc": (
                        r.previous_start_time_utc.isoformat() if r.previous_start_time_utc else None
                    ),
                    "status": r.status,
                    "recorded_at": r.recorded_at.isoformat(),
                }
                for r in rows
            ]
