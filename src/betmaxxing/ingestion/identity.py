"""Stable event identity.

The original scheme derived an event's id from ``(sport, UTC date, normalised
participants)``. Two failures follow directly from that:

* **Postponement.** A 23:30 UTC kick-off pushed to 00:30 changes the date
  component, so the same fixture became a second event with no shared history.
* **Collision.** Two legs of a tie, or two matches between the same players on
  one day, hashed to the same id and were silently merged.

Identity is now opaque and assigned once. Resolution works in two steps:

1. **Authoritative.** ``(provider, provider_event_id)`` is looked up in a mapping
   table. A provider that keeps its own id stable across a postponement gives us
   a stable internal id for free — this is the path that fixes reschedules.
2. **Cross-provider match.** Only when the pair is unknown. Every signal that is
   present on *both* sides has to agree: sport, canonical participants (through
   the provider's declared aliases), competition, season, stage, and a kick-off
   inside a documented tolerance. A signal missing on either side is not
   evidence and is skipped rather than treated as a match.

Ambiguity resolves to **nothing**
---------------------------------
When more than one stored fixture survives that filter, the previous version
returned ``candidates[0]`` while flagging the result ambiguous — so a price was
still attributed to whichever row happened to sort first, and a snapshot was
persisted against it. Resolution now returns
:data:`ResolutionStatus.AMBIGUOUS` with **no** internal id: no mapping row is
created, no candidate event is touched, no snapshot can be attached, and the
case is queued in ``event_mapping_reviews`` for a human. Declining to price a
match is a normal outcome; guessing which match a price belongs to is not.

Kick-off times and statuses are appended to a history table rather than
overwritten, so a reschedule is visible after the fact.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from betmaxxing.config import Settings
from betmaxxing.domain.enums import EventStatus, Sport
from betmaxxing.domain.ids import normalize_participant
from betmaxxing.domain.timeutil import ensure_utc, from_storage, utc_now
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import (
    EventMappingReviewRow,
    EventRow,
    EventScheduleHistoryRow,
    EventSourceMapRow,
    ParticipantAliasRow,
)

#: How far a kick-off may move and still be considered the same fixture when
#: matching *across providers*. Tight on purpose: a wide window would merge two
#: legs played on the same day, which is the collision this design removes.
CROSS_PROVIDER_TOLERANCE = timedelta(hours=6)


class ResolutionStatus(StrEnum):
    """The four possible answers. Only two of them carry an internal id."""

    #: Matched an existing event (authoritatively or across providers).
    RESOLVED = "RESOLVED"
    #: No match; a new internal identity was assigned.
    CREATED = "CREATED"
    #: Several plausible matches. Nothing was written except a review entry.
    AMBIGUOUS = "AMBIGUOUS"
    #: The payload could not be used at all (missing participants, bad time).
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ResolvedEvent:
    """Outcome of resolving a provider's event onto internal identity."""

    status: ResolutionStatus
    #: ``None`` for AMBIGUOUS and REJECTED — deliberately, so a caller cannot
    #: accidentally attach data to a guess.
    internal_id: str | None = None
    detail: str = ""
    #: Existing events that matched, for the review queue. Never a choice.
    candidate_internal_ids: tuple[str, ...] = ()
    #: True when the kick-off moved relative to what we had stored.
    rescheduled: bool = False

    @property
    def created(self) -> bool:
        return self.status is ResolutionStatus.CREATED

    @property
    def ambiguous(self) -> bool:
        return self.status is ResolutionStatus.AMBIGUOUS

    @property
    def usable(self) -> bool:
        return self.internal_id is not None


def new_internal_id() -> str:
    """Opaque identity. No date, no participants, no semantics to drift."""
    return f"evt_{uuid.uuid4().hex[:20]}"


def participant_pair_key(sport: Sport, home: str, away: str) -> str:
    """Order-sensitive participant key used for cross-provider matching."""
    return f"{sport}|{normalize_participant(home)}|{normalize_participant(away)}"


def _normalise_attribute(value: str | None) -> str:
    return (value or "").strip().casefold()


def _attributes_conflict(stored: str | None, incoming: str | None) -> bool:
    """True when both sides state a value and the values differ.

    A value present on one side only is silence, not disagreement: providers
    populate these fields inconsistently, and treating an absent competition as
    "a different competition" would split every fixture in two.
    """
    left, right = _normalise_attribute(stored), _normalise_attribute(incoming)
    return bool(left) and bool(right) and left != right


class EventIdentityService:
    """Resolves provider events onto stable internal ids."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # -- aliases ------------------------------------------------------------
    def _alias_keys(self, session: Session, sport: Sport, name: str, provider: str) -> list[str]:
        """Every normalised spelling this name could canonically be.

        Always includes the plain normalisation. Aliases declared by *this*
        provider come first, then aliases from any source, so a provider's own
        short form resolves even when another provider declared a different one.
        """
        keys = [normalize_participant(name)]
        rows = session.scalars(
            select(ParticipantAliasRow).where(
                ParticipantAliasRow.sport == str(sport),
                ParticipantAliasRow.alias == name,
            )
        ).all()
        ordered = sorted(rows, key=lambda r: r.source != provider)
        for row in ordered:
            canonical = row.canonical_participant_id.split(":", 1)[-1]
            if canonical not in keys:
                keys.append(canonical)
        return keys

    def _candidate_pair_keys(
        self,
        session: Session,
        sport: Sport,
        home_name: str,
        away_name: str,
        provider: str,
    ) -> list[str]:
        homes = self._alias_keys(session, sport, home_name, provider)
        aways = self._alias_keys(session, sport, away_name, provider)
        return [f"{sport}|{home}|{away}" for home in homes for away in aways]

    # -- resolution ---------------------------------------------------------
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
        stage: str | None = None,
        season: str | None = None,
    ) -> ResolvedEvent:
        """Map a provider's event onto an internal id, creating one if needed."""
        if not provider_event_id or not home_name.strip() or not away_name.strip():
            return ResolvedEvent(
                status=ResolutionStatus.REJECTED,
                detail="identifiant fournisseur ou participants manquants.",
            )
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
                return self._refresh_mapped(session, mapped.internal_id, start, status)

            candidates = self._match(
                session,
                provider=provider,
                sport=sport,
                competition=competition,
                home_name=home_name,
                away_name=away_name,
                start=start,
                stage=stage,
                season=season,
            )

            if len(candidates) > 1:
                return self._record_ambiguity(
                    session,
                    provider=provider,
                    provider_event_id=provider_event_id,
                    sport=sport,
                    competition=competition,
                    home_name=home_name,
                    away_name=away_name,
                    start=start,
                    candidates=candidates,
                    pair_key=pair_key,
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
                return ResolvedEvent(status=ResolutionStatus.RESOLVED, internal_id=internal_id)

            return self._create(
                session,
                provider=provider,
                provider_event_id=provider_event_id,
                sport=sport,
                competition=competition,
                home_name=home_name,
                away_name=away_name,
                start=start,
                status=status,
                stage=stage,
                season=season,
                pair_key=pair_key,
            )

    # -- internals ----------------------------------------------------------
    def _refresh_mapped(
        self, session: Session, internal_id: str, start: datetime, status: EventStatus
    ) -> ResolvedEvent:
        """Authoritative path. A moved kick-off is the *same* event."""
        row = session.get(EventRow, internal_id)
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
            status=ResolutionStatus.RESOLVED,
            internal_id=internal_id,
            rescheduled=rescheduled,
        )

    def _match(
        self,
        session: Session,
        *,
        provider: str,
        sport: Sport,
        competition: str,
        home_name: str,
        away_name: str,
        start: datetime,
        stage: str | None,
        season: str | None,
    ) -> list[EventRow]:
        """Cross-provider matching, deliberately narrow."""
        lo, hi = start - CROSS_PROVIDER_TOLERANCE, start + CROSS_PROVIDER_TOLERANCE
        pair_keys = self._candidate_pair_keys(session, sport, home_name, away_name, provider)

        candidates = list(
            session.scalars(
                select(EventRow).where(
                    EventRow.sport == str(sport),
                    EventRow.participant_pair_key.in_(pair_keys),
                    EventRow.start_time_utc >= lo,
                    EventRow.start_time_utc <= hi,
                )
            ).all()
        )

        # A provider is authoritative about its own catalogue. If it already
        # gave us an event under a *different* id, this is a different fixture —
        # two legs of a tie, a rematch — not the same one. Merging them would
        # resurrect exactly the collision this design removes.
        already_mapped = set(
            session.scalars(
                select(EventSourceMapRow.internal_id).where(EventSourceMapRow.provider == provider)
            ).all()
        )
        candidates = [c for c in candidates if c.canonical_id not in already_mapped]

        return [
            row
            for row in candidates
            if not _attributes_conflict(row.competition, competition)
            and not _attributes_conflict(row.stage, stage)
            and not _attributes_conflict(row.season, season)
        ]

    def _record_ambiguity(
        self,
        session: Session,
        *,
        provider: str,
        provider_event_id: str,
        sport: Sport,
        competition: str,
        home_name: str,
        away_name: str,
        start: datetime,
        candidates: list[EventRow],
        pair_key: str,
    ) -> ResolvedEvent:
        """Queue the case and write nothing else."""
        ids = tuple(sorted(row.canonical_id for row in candidates))
        detail = (
            f"{len(ids)} événements existants correspondent à {pair_key} autour de "
            f"{start.isoformat()} — rapprochement refusé, aucun rattachement effectué."
        )
        existing = session.scalar(
            select(EventMappingReviewRow).where(
                EventMappingReviewRow.provider == provider,
                EventMappingReviewRow.provider_event_id == provider_event_id,
            )
        )
        if existing is None:
            session.add(
                EventMappingReviewRow(
                    provider=provider,
                    provider_event_id=provider_event_id,
                    sport=str(sport),
                    competition=competition,
                    home_name=home_name,
                    away_name=away_name,
                    start_time_utc=start,
                    candidate_internal_ids=list(ids),
                    detail=detail,
                    recorded_at=utc_now(),
                    resolved=False,
                )
            )
        else:
            existing.candidate_internal_ids = list(ids)
            existing.detail = detail
            existing.recorded_at = utc_now()
        return ResolvedEvent(
            status=ResolutionStatus.AMBIGUOUS,
            internal_id=None,
            detail=detail,
            candidate_internal_ids=ids,
        )

    def _create(
        self,
        session: Session,
        *,
        provider: str,
        provider_event_id: str,
        sport: Sport,
        competition: str,
        home_name: str,
        away_name: str,
        start: datetime,
        status: EventStatus,
        stage: str | None,
        season: str | None,
        pair_key: str,
    ) -> ResolvedEvent:
        internal_id = new_internal_id()
        session.add(
            EventRow(
                canonical_id=internal_id,
                sport=str(sport),
                competition=competition,
                stage=stage,
                season=season,
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
        return ResolvedEvent(status=ResolutionStatus.CREATED, internal_id=internal_id)

    # -- inspection ---------------------------------------------------------
    def pending_review(self) -> list[dict[str, object]]:
        """Ambiguities awaiting a human decision."""
        with session_scope(self._settings) as session:
            rows = session.scalars(
                select(EventMappingReviewRow)
                .where(EventMappingReviewRow.resolved.is_(False))
                .order_by(EventMappingReviewRow.recorded_at)
            ).all()
            return [
                {
                    "provider": row.provider,
                    "provider_event_id": row.provider_event_id,
                    "sport": row.sport,
                    "competition": row.competition,
                    "label": f"{row.home_name} - {row.away_name}",
                    "start_time_utc": row.start_time_utc.isoformat(),
                    "candidate_internal_ids": list(row.candidate_internal_ids),
                    "detail": row.detail,
                }
                for row in rows
            ]

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
