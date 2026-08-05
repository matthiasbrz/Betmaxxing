"""The single acquisition path: collect, persist, analyse, persist.

Every caller — API, CLI, scheduler — goes through this class. Previously each
built its own sequence and all three persisted only the scan document, so the
events and odds snapshots a real provider returned were dropped. Snapshots are
the one thing that cannot be re-downloaded; losing them destroys the ability to
backtest anything that was collected.

Ordering, and why it is this way
--------------------------------
1. **Collect** — an HTTP call, made with no transaction open.
2. **Persist the source data** — events resolved onto stable identity, then
   immutable snapshots. This happens *before* any model is consulted, so real
   data survives even when nothing can price it.
3. **Resolve models** from the versioned registry.
4. **Analyse**, possibly producing candidates.
5. **Persist the scan**, its rejections and its diagnostics.

Step 2 committing before step 5 is deliberate. A crash between them loses the
analysis — which is reproducible — and keeps the prices, which are not. Re-running
is idempotent because snapshots deduplicate on their natural fingerprint, not on
an in-memory cache.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from betmaxxing import DISCLAIMER
from betmaxxing.config import RunMode, Settings, get_settings
from betmaxxing.domain.enums import CollectionStatus, RejectionCode, ScanStatus, Sport
from betmaxxing.domain.models import (
    CanonicalEvent,
    DataHealth,
    OddsSnapshot,
    ProviderStatus,
    Rejection,
    ScanResult,
)
from betmaxxing.domain.timeutil import is_in_window, scan_window, utc_now
from betmaxxing.engine.scan import AnalysisOutput, analyse
from betmaxxing.ingestion.identity import EventIdentityService, ResolvedEvent
from betmaxxing.ingestion.normalize import assemble_books
from betmaxxing.providers.base import (
    BudgetExceeded,
    CollectionBatch,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderUnavailable,
    collect_via_listing,
)
from betmaxxing.providers.factory import ProviderBundle, build_providers
from betmaxxing.storage.db import create_all, session_scope
from betmaxxing.storage.repositories import (
    BatchRepository,
    EventRepository,
    OddsRepository,
    ScanRepository,
)

logger = logging.getLogger("betmaxxing.acquisition")

SPORTS_IN_SCOPE: list[Sport] = [Sport.FOOTBALL, Sport.TENNIS]


class FailureKind(StrEnum):
    """Why a collection failed, at the granularity a caller must act on.

    The scheduler needs this to decide between "retry later", "stop retrying"
    and "wait for the next budget window"; a bare ``PROVIDER_ERROR`` status
    cannot distinguish a 503 from a missing API key.
    """

    #: Timeout, transport failure, 5xx, or a partial failure that became total.
    TRANSIENT = "TRANSIENT"
    #: Missing/invalid key, 401/403, 422, unusable configuration. Retrying will
    #: fail identically until a human changes something.
    CONFIGURATION = "CONFIGURATION"
    #: Scan or daily credit ceiling reached. Retrying now cannot succeed.
    BUDGET = "BUDGET"


def classify_failure(error: Exception) -> FailureKind:
    """Map a provider exception onto the action the caller should take."""
    # Order matters: ProviderQuotaExceeded subclasses ProviderUnavailable.
    if isinstance(error, BudgetExceeded | ProviderQuotaExceeded):
        return FailureKind.BUDGET
    if isinstance(error, ProviderUnavailable):
        return FailureKind.CONFIGURATION
    return FailureKind.TRANSIENT


@dataclass(slots=True)
class AcquisitionResult:
    """What a run produced, including the batch actually written."""

    scan: ScanResult
    batch: CollectionBatch
    events_persisted: int
    snapshots_persisted: int
    #: ``None`` on any completed collection, including one that found nothing.
    failure: FailureKind | None = None

    @property
    def data_health(self) -> DataHealth:
        return self.scan.data_health


class AcquisitionService:
    """Collect, store, analyse, store. Used identically by every entry point."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        create_all(self._settings)
        self._identity = EventIdentityService(self._settings)

    # -- public API ---------------------------------------------------------
    def run(
        self,
        *,
        now: datetime | None = None,
        scope_event_id: str | None = None,
        manual_odds_path: str | None = None,
        bundle: ProviderBundle | None = None,
        persist: bool = True,
    ) -> AcquisitionResult:
        """Execute one acquisition + analysis cycle.

        ``scope_event_id`` restricts analysis to a single event, which is what a
        pre-event milestone job needs: the previous scheduler carried the event
        id on the job and then ignored it, running a global scan instead.
        """
        settings = self._settings
        moment = now or utc_now()
        scan_id = uuid.uuid4().hex[:16]
        window = scan_window(moment, settings.window_hours)

        try:
            providers = bundle or build_providers(settings, moment, manual_odds_path)
        except ProviderUnavailable as exc:
            return self._unavailable(scan_id, moment, window, exc, persist=persist)

        try:
            batch = self._collect(providers, window, moment)
        except ProviderError as exc:
            logger.warning("collection failed: %s", exc)
            return self._unavailable(scan_id, moment, window, exc, persist=persist)

        # --- persist source data first -------------------------------------
        events_written = snapshots_written = 0
        unattributable: list[CanonicalEvent] = []
        if persist:
            batch, unattributable = self._resolve_identity(batch)
            events_written, snapshots_written = self._persist_batch(batch, settings)

        in_window = [e for e in batch.events if is_in_window(e.start_time_utc, window)]
        if scope_event_id:
            in_window = [e for e in in_window if e.internal_id == scope_event_id]

        # --- analyse --------------------------------------------------------
        normalized = assemble_books(batch.snapshots, moment)
        analysis = analyse(
            settings=settings,
            events=in_window,
            all_events=batch.events,
            books=normalized.books,
            snapshots=batch.snapshots,
            models=providers.models,
            context=providers.context,
            now=moment,
            scan_id=scan_id,
            window=window,
        )
        analysis.rejections.extend(self._ambiguity_rejections(unattributable))

        collection_status = self._classify(batch, providers, analysis, normalized.books)
        status = ScanStatus.CANDIDATES_FOUND if analysis.candidates else ScanStatus.NO_CANDIDATE
        if collection_status is CollectionStatus.PROVIDER_ERROR:
            status = ScanStatus.DATA_UNAVAILABLE

        health = DataHealth(
            providers=self._provider_statuses(providers, batch),
            events_discovered=len(batch.events),
            events_in_window=len(in_window),
            markets_evaluated=analysis.markets_evaluated,
            selections_priced=analysis.selections_priced,
            stale_snapshots=analysis.stale,
            quarantined_records=len(normalized.quarantined),
            events_persisted=events_written,
            snapshots_persisted=snapshots_written,
        )

        result = self._build_result(
            scan_id=scan_id,
            moment=moment,
            window=window,
            status=status,
            collection_status=collection_status,
            health=health,
            analysis=analysis,
            batch=batch,
            warnings=list(providers.warnings) + batch.partial_errors,
        )

        if persist:
            with session_scope(settings) as session:
                ScanRepository(session).save(result)

        return AcquisitionResult(
            scan=result,
            batch=batch,
            events_persisted=events_written,
            snapshots_persisted=snapshots_written,
        )

    # -- internals ----------------------------------------------------------
    def _collect(
        self,
        providers: ProviderBundle,
        window: tuple[datetime, datetime],
        moment: datetime,
    ) -> CollectionBatch:
        collector = getattr(providers.odds, "collect", None)
        if callable(collector):
            return collector(SPORTS_IN_SCOPE, window)
        return collect_via_listing(providers.odds, SPORTS_IN_SCOPE, window, moment)

    def resolve_identities(
        self, events: Iterable[CanonicalEvent], *, provider: str
    ) -> list[CanonicalEvent]:
        """Rewrite events onto internal identity, dropping unusable ones.

        Exposed so the scheduler can plan milestones against **internal** ids.
        Planning against a provider id is what made every milestone scan analyse
        zero events: the analysis filter compares internal ids.
        """
        out: list[CanonicalEvent] = []
        for event, resolution in self._resolve_each(events, provider):
            if resolution.usable:
                out.append(event.model_copy(update={"internal_id": resolution.internal_id}))
        return out

    def _resolve_each(
        self, events: Iterable[CanonicalEvent], provider: str
    ) -> list[tuple[CanonicalEvent, ResolvedEvent]]:
        resolved: list[tuple[CanonicalEvent, ResolvedEvent]] = []
        for event in events:
            source_id = event.source_ids.get(provider) or event.internal_id
            resolution = self._identity.resolve(
                provider=provider,
                provider_event_id=source_id,
                sport=event.sport,
                competition=event.competition,
                home_name=event.home.name,
                away_name=event.away.name,
                start_time_utc=event.start_time_utc,
                status=event.status,
                stage=event.stage,
                season=event.season,
            )
            resolved.append((event, resolution))
        return resolved

    def _resolve_identity(
        self, batch: CollectionBatch
    ) -> tuple[CollectionBatch, list[CanonicalEvent]]:
        """Map provider events onto stable internal ids and rewrite the batch.

        Three outcomes, and only one of them keeps data:

        * resolved or created — the event and its snapshots are rewritten onto
          the internal id and persisted;
        * **ambiguous** — the event is dropped from the batch entirely and its
          snapshots with it. Attaching them to one of the candidate fixtures
          would fabricate an attribution; the case is already queued for review
          by the identity service. The dropped events are returned separately so
          the scan can reject them explicitly rather than omit them silently;
        * rejected — same, with a different diagnosis.

        Snapshots are rewritten too, so a snapshot can never reference an event
        that was not resolved and stored.
        """
        remap: dict[str, str] = {}
        resolved_events: list[CanonicalEvent] = []
        unattributable: list[CanonicalEvent] = []

        for event, resolution in self._resolve_each(batch.events, batch.provider):
            if resolution.internal_id is not None:
                remap[event.internal_id] = resolution.internal_id
                resolved_events.append(
                    event.model_copy(update={"internal_id": resolution.internal_id})
                )
                continue

            unattributable.append(event.model_copy(update={"mapping_ambiguous": True}))
            batch.partial_errors.append(resolution.detail)

        resolved_snapshots: list[OddsSnapshot] = []
        for snapshot in batch.snapshots:
            target = remap.get(snapshot.event_internal_id)
            if target is None:
                # A snapshot with no resolved event is dropped and reported,
                # never persisted against a dangling id or a guessed one.
                batch.partial_errors.append(
                    f"snapshot non rattaché (identité indéterminée) : {snapshot.selection.key}"
                )
                continue
            resolved_snapshots.append(
                snapshot.model_copy(
                    update={"event_internal_id": target, "source_meta": snapshot.source_meta}
                )
            )

        batch.events = resolved_events
        batch.snapshots = resolved_snapshots
        return batch, unattributable

    def _ambiguity_rejections(self, events: Sequence[CanonicalEvent]) -> list[Rejection]:
        """Say out loud that a fixture was seen and deliberately not priced."""
        return [
            Rejection(
                event_internal_id=event.internal_id,
                event_label=f"{event.home.name} - {event.away.name}",
                selection_key="",
                code=RejectionCode.EVENT_MAPPING_AMBIGUOUS,
                detail=(
                    "Identité de l'événement indéterminée : plusieurs rencontres "
                    "existantes correspondent. Aucune cote n'a été rattachée ; le cas "
                    "est en file de revue (event_mapping_reviews)."
                ),
            )
            for event in events
        ]

    def _persist_batch(self, batch: CollectionBatch, settings: Settings) -> tuple[int, int]:
        """Store events then snapshots. Idempotent on natural keys."""
        with session_scope(settings) as session:
            events_repo = EventRepository(session)
            for event in batch.events:
                events_repo.upsert(event)
            session.flush()
            written = OddsRepository(session).store(batch.snapshots, batch_id=batch.batch_id)
            BatchRepository(session).save(
                batch,
                mode=str(settings.mode),
                events_persisted=len(batch.events),
                snapshots_persisted=written,
            )
        return len(batch.events), written

    def _classify(
        self,
        batch: CollectionBatch,
        providers: ProviderBundle,
        analysis: AnalysisOutput,
        books: Sequence[object],
    ) -> CollectionStatus:
        """Say precisely why the scan produced what it produced."""
        if batch.coverage is CollectionStatus.COVERAGE_MISSING and not batch.snapshots:
            return CollectionStatus.COVERAGE_MISSING
        if providers.models.is_empty:
            return CollectionStatus.COLLECTED_NO_MODEL
        if analysis.candidates:
            return CollectionStatus.OK
        if books and analysis.selections_priced == 0 and analysis.stale > 0:
            return CollectionStatus.DATA_STALE
        return CollectionStatus.NO_CANDIDATE

    def _provider_statuses(
        self, providers: ProviderBundle, batch: CollectionBatch
    ) -> list[ProviderStatus]:
        statuses: list[ProviderStatus] = []
        for provider in (providers.odds, providers.context, providers.results):
            health = getattr(provider, "health", None)
            if health is None:
                continue
            status = health()
            if provider is providers.odds:
                status = status.model_copy(
                    update={
                        "quota_remaining": batch.quota.remaining,
                        "quota_used": batch.quota.used,
                        "last_request_cost": batch.quota.last_cost,
                    }
                )
            statuses.append(status)
        return statuses

    def _build_result(
        self,
        *,
        scan_id: str,
        moment: datetime,
        window: tuple[datetime, datetime],
        status: ScanStatus,
        collection_status: CollectionStatus,
        health: DataHealth,
        analysis: AnalysisOutput,
        batch: CollectionBatch | None,
        warnings: list[str],
    ) -> ScanResult:
        summary: dict[str, int] = {}
        for rejection in analysis.rejections:
            summary[rejection.code.value] = summary.get(rejection.code.value, 0) + 1
        return ScanResult(
            scan_id=scan_id,
            status=status,
            collection_status=collection_status,
            mode=str(self._settings.mode),
            generated_at=moment,
            window={"from": window[0], "to": window[1]},
            data_health=health,
            candidates=sorted(analysis.candidates, key=lambda c: c.value.ev, reverse=True),
            rejections=analysis.rejections,
            rejections_summary=dict(sorted(summary.items())),
            thresholds=self._settings.eligibility_thresholds(),
            config_fingerprint=self._settings.fingerprint(),
            disclaimer=DISCLAIMER,
            batch_id=batch.batch_id if batch else None,
            warnings=warnings,
        )

    def _unavailable(
        self,
        scan_id: str,
        moment: datetime,
        window: tuple[datetime, datetime],
        error: Exception,
        *,
        persist: bool = True,
        status: CollectionStatus = CollectionStatus.PROVIDER_ERROR,
    ) -> AcquisitionResult:
        """Build — and persist — the scan document for a failed collection.

        The previous version returned this document without storing it, so the
        only durable trace of an outage was a log line. An error scan carries the
        diagnosis, the window it was trying to cover and the configuration
        fingerprint; it is exactly what an operator needs afterwards, and it
        costs one row.
        """
        from betmaxxing.domain.enums import ProviderHealth

        reason = str(error)
        health = DataHealth(
            providers=[
                ProviderStatus(
                    name=self._settings.odds_provider or "none",
                    kind="odds",
                    health=ProviderHealth.UNAVAILABLE,
                    detail=reason,
                )
            ],
            events_discovered=0,
            events_in_window=0,
            markets_evaluated=0,
            selections_priced=0,
            stale_snapshots=0,
            quarantined_records=0,
        )
        empty = CollectionBatch(provider="none", collected_at=moment)
        result = self._build_result(
            scan_id=scan_id,
            moment=moment,
            window=window,
            status=ScanStatus.DATA_UNAVAILABLE,
            collection_status=status,
            health=health,
            analysis=AnalysisOutput(candidates=[], rejections=[]),
            batch=None,
            warnings=[reason],
        )
        if persist:
            with session_scope(self._settings) as session:
                ScanRepository(session).save(result)
        return AcquisitionResult(
            scan=result,
            batch=empty,
            events_persisted=0,
            snapshots_persisted=0,
            failure=classify_failure(error),
        )


def run_scan(
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
    manual_odds_path: str | None = None,
    bundle: ProviderBundle | None = None,
    scope_event_id: str | None = None,
    persist: bool = True,
) -> ScanResult:
    """Convenience wrapper returning just the scan document."""
    service = AcquisitionService(settings)
    return service.run(
        now=now,
        manual_odds_path=manual_odds_path,
        bundle=bundle,
        scope_event_id=scope_event_id,
        persist=persist,
    ).scan


def scan_is_demo(settings: Settings) -> bool:
    return settings.mode is RunMode.DEMO


#: Rejection codes that indicate a data problem rather than a value judgement.
DATA_PROBLEM_CODES = frozenset(
    {
        RejectionCode.ODDS_STALE,
        RejectionCode.MARKET_INCOMPLETE,
        RejectionCode.LOW_DATA_QUALITY,
        RejectionCode.EVENT_MAPPING_AMBIGUOUS,
        RejectionCode.BOOKMAKER_COVERAGE_MISSING,
    }
)


def rejection_is_data_problem(rejection: Rejection) -> bool:
    return rejection.code in DATA_PROBLEM_CODES
