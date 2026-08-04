"""Scan orchestration — the end-to-end pipeline.

    discover events -> filter window -> fetch odds -> normalise into books
      -> de-vig -> price with the model -> compute value -> gate -> explain

Every priced selection ends up either in ``candidates`` or in ``rejections``;
nothing is dropped without a code. The scan returns ``NO_BET`` when no candidate
survives, which is a normal outcome and not an error, and ``DATA_UNAVAILABLE``
when the providers could not supply enough to decide.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from betmaxxing import DISCLAIMER
from betmaxxing.config import RunMode, Settings, get_settings
from betmaxxing.domain.enums import (
    EXPECTED_SELECTION_COUNT,
    MARKETS_BY_SPORT,
    PARTITION_MARKETS,
    EventStatus,
    RejectionCode,
    ScanStatus,
    Sport,
)
from betmaxxing.domain.ids import candidate_id
from betmaxxing.domain.models import (
    Candidate,
    CanonicalEvent,
    DataHealth,
    EvidenceItem,
    MarketBook,
    OddsSnapshot,
    ProbabilityEstimate,
    ProviderStatus,
    Rejection,
    ScanResult,
    ValueAssessment,
)
from betmaxxing.domain.timeutil import age_seconds, is_in_window, scan_window, utc_now
from betmaxxing.engine import eligibility, explain
from betmaxxing.engine.ev import ValueMath
from betmaxxing.engine.margin import DevigError, devig
from betmaxxing.engine.quality import score_confidence, score_data_quality
from betmaxxing.engine.staking import compute_stake
from betmaxxing.engine.uncertainty import wilson_interval
from betmaxxing.ingestion.normalize import assemble_books, is_book_complete, odds_movement
from betmaxxing.models_ml.base import MarketPrediction
from betmaxxing.models_ml.registry import ModelRegistry
from betmaxxing.providers.base import ProviderUnavailable
from betmaxxing.providers.factory import ProviderBundle, build_providers

SPORTS_IN_SCOPE: list[Sport] = [Sport.FOOTBALL, Sport.TENNIS]


@dataclass(slots=True)
class _Workspace:
    """Mutable bookkeeping for one scan."""

    candidates: list[Candidate]
    rejections: list[Rejection]
    stale: int = 0
    markets_evaluated: int = 0
    selections_priced: int = 0


def run_scan(
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
    manual_odds_path: str | None = None,
    bundle: ProviderBundle | None = None,
) -> ScanResult:
    """Execute one full scan and return its stable result contract."""
    settings = settings or get_settings()
    moment = now or utc_now()
    scan_id = uuid.uuid4().hex[:16]
    window = scan_window(moment, settings.window_hours)

    try:
        providers = bundle or build_providers(settings, moment, manual_odds_path)
    except ProviderUnavailable as exc:
        return _unavailable(settings, scan_id, moment, window, str(exc))

    events = providers.odds.list_events(SPORTS_IN_SCOPE, window)  # type: ignore[attr-defined]
    in_window = [e for e in events if is_in_window(e.start_time_utc, window)]

    workspace = _Workspace(candidates=[], rejections=[])

    # Events discovered but outside the window are recorded, not forgotten.
    for event in events:
        if event not in in_window:
            workspace.rejections.append(
                Rejection(
                    event_canonical_id=event.canonical_id,
                    event_label=event.label,
                    selection_key="-",
                    code=RejectionCode.OUTSIDE_WINDOW,
                    detail=(
                        f"Début {event.start_time_utc.isoformat()} hors fenêtre "
                        f"de {settings.window_hours:g} h."
                    ),
                )
            )

    snapshots: list[OddsSnapshot] = (
        providers.odds.fetch_odds(in_window) if in_window else []  # type: ignore[attr-defined]
    )
    normalized = assemble_books(snapshots, moment)

    if not in_window or not normalized.books:
        health = _health(
            providers,
            events_discovered=len(events),
            events_in_window=len(in_window),
            workspace=workspace,
            quarantined=len(normalized.quarantined),
        )
        status = ScanStatus.DATA_UNAVAILABLE if not snapshots and in_window else ScanStatus.NO_BET
        return _result(settings, scan_id, moment, window, status, health, workspace)

    events_by_id = {e.canonical_id: e for e in in_window}
    history_by_selection = _history_index(snapshots)

    for book in normalized.books:
        event = events_by_id.get(book.event_canonical_id)
        if event is None:
            continue
        workspace.markets_evaluated += 1
        _score_book(
            book=book,
            event=event,
            settings=settings,
            models=providers.models,
            context=providers.context,
            moment=moment,
            scan_id=scan_id,
            workspace=workspace,
            history=history_by_selection,
        )

    health = _health(
        providers,
        events_discovered=len(events),
        events_in_window=len(in_window),
        workspace=workspace,
        quarantined=len(normalized.quarantined),
    )
    status = ScanStatus.CANDIDATES_FOUND if workspace.candidates else ScanStatus.NO_BET
    return _result(settings, scan_id, moment, window, status, health, workspace)


def _history_index(snapshots: list[OddsSnapshot]) -> dict[tuple[str, str, str], list[OddsSnapshot]]:
    index: dict[tuple[str, str, str], list[OddsSnapshot]] = {}
    for snapshot in snapshots:
        key = (snapshot.event_canonical_id, snapshot.bookmaker, snapshot.selection.key)
        index.setdefault(key, []).append(snapshot)
    return index


def _score_book(
    *,
    book: MarketBook,
    event: CanonicalEvent,
    settings: Settings,
    models: ModelRegistry,
    context: object,
    moment: datetime,
    scan_id: str,
    workspace: _Workspace,
    history: dict[tuple[str, str, str], list[OddsSnapshot]],
) -> None:
    """Price every selection of one book and gate each one."""
    complete = is_book_complete(book)
    expected = EXPECTED_SELECTION_COUNT.get(book.market, len(book.snapshots))

    # De-vig only complete partition markets. Overlapping markets (double chance)
    # and one-sided markets (wins-a-set) keep p_novig = None and say so.
    novig: dict[str, float] | None = None
    devig_name: str | None = None
    if complete and book.market in PARTITION_MARKETS:
        try:
            odds_list = [s.decimal_odds for s in book.snapshots]
            probs = devig(odds_list, settings.devig_method)
            novig = {s.selection.code: p for s, p in zip(book.snapshots, probs, strict=True)}
            devig_name = str(settings.devig_method)
        except DevigError as exc:
            complete = False
            for snapshot in book.snapshots:
                workspace.rejections.append(
                    Rejection(
                        event_canonical_id=event.canonical_id,
                        event_label=event.label,
                        selection_key=snapshot.selection.key,
                        code=RejectionCode.MARKET_INCOMPLETE,
                        detail=f"Retrait de marge impossible : {exc}",
                    )
                )
            return

    model = models.get(event.sport)
    if model is None:
        for snapshot in book.snapshots:
            workspace.rejections.append(
                Rejection(
                    event_canonical_id=event.canonical_id,
                    event_label=event.label,
                    selection_key=snapshot.selection.key,
                    code=RejectionCode.NO_MODEL_AVAILABLE,
                    detail=f"Aucun modèle enregistré pour {event.sport}.",
                )
            )
        return

    prediction: MarketPrediction | None = model.predict(event, book.market, book.period, book.line)
    if prediction is None:
        for snapshot in book.snapshots:
            workspace.rejections.append(
                Rejection(
                    event_canonical_id=event.canonical_id,
                    event_label=event.label,
                    selection_key=snapshot.selection.key,
                    code=RejectionCode.NO_MODEL_AVAILABLE,
                    detail=(
                        f"{model.model_id} ne price pas {book.market}/{book.period}"
                        + (f" ligne {book.line:g}" if book.line is not None else "")
                        + "."
                    ),
                )
            )
        return

    evidence = _evidence_for(context, event, prediction)
    in_scope = book.market in MARKETS_BY_SPORT.get(event.sport, frozenset())

    for snapshot in book.snapshots:
        workspace.selections_priced += 1
        _score_selection(
            snapshot=snapshot,
            book=book,
            event=event,
            prediction=prediction,
            novig=novig,
            devig_name=devig_name,
            complete=complete,
            expected=expected,
            in_scope=in_scope,
            model_id=model.model_id,
            settings=settings,
            moment=moment,
            scan_id=scan_id,
            workspace=workspace,
            evidence=evidence,
            history=history,
        )


def _score_selection(
    *,
    snapshot: OddsSnapshot,
    book: MarketBook,
    event: CanonicalEvent,
    prediction: MarketPrediction,
    novig: dict[str, float] | None,
    devig_name: str | None,
    complete: bool,
    expected: int,
    in_scope: bool,
    model_id: str,
    settings: Settings,
    moment: datetime,
    scan_id: str,
    workspace: _Workspace,
    evidence: list[EvidenceItem],
    history: dict[tuple[str, str, str], list[OddsSnapshot]],
) -> None:
    selection = snapshot.selection
    probability = prediction.probabilities.get(selection.code)
    if probability is None or not (0.0 < probability < 1.0):
        workspace.rejections.append(
            Rejection(
                event_canonical_id=event.canonical_id,
                event_label=event.label,
                selection_key=selection.key,
                code=RejectionCode.NO_MODEL_AVAILABLE,
                detail=(
                    "Le modèle ne fournit pas de probabilité exploitable pour "
                    f"« {selection.code} »."
                ),
            )
        )
        return

    age = age_seconds(snapshot.observed_at, moment)
    if age > settings.max_odds_age_seconds:
        workspace.stale += 1

    interval = wilson_interval(
        probability, prediction.effective_sample_size, settings.prob_interval_z
    )
    value_math = ValueMath(
        odds=snapshot.decimal_odds,
        probability=probability,
        probability_lower=interval.lower,
        probability_upper=interval.upper,
        ev_threshold=settings.min_ev,
    )

    quality = score_data_quality(
        odds_age_seconds=age,
        max_odds_age_seconds=float(settings.max_odds_age_seconds),
        selections_present=len(book.snapshots),
        selections_expected=expected,
        mapping_ambiguous=event.mapping_ambiguous,
        feature_completeness=prediction.feature_completeness,
        source_agreement=1.0,
    )

    gate = eligibility.evaluate(
        eligibility.GateInput(
            ev=value_math.ev,
            ev_conservative=value_math.ev_conservative,
            probability_half_width=interval.half_width,
            odds=snapshot.decimal_odds,
            odds_age_seconds=age,
            data_quality=quality.score,
            market_complete=complete,
            mapping_ambiguous=event.mapping_ambiguous,
            in_window=True,
            in_scope=in_scope,
            event_scheduled=event.status is EventStatus.SCHEDULED,
            validation_status=prediction_status(model_id, settings),
            mode=settings.mode,
        ),
        settings,
    )

    if not gate.passed:
        for code, detail in zip(gate.codes, gate.details, strict=True):
            workspace.rejections.append(
                Rejection(
                    event_canonical_id=event.canonical_id,
                    event_label=event.label,
                    selection_key=selection.key,
                    code=code,
                    detail=detail,
                )
            )
        return

    estimate = ProbabilityEstimate(
        probability=probability,
        lower=interval.lower,
        upper=interval.upper,
        effective_sample_size=prediction.effective_sample_size,
        model_id=model_id,
        validation_status=prediction_status(model_id, settings),
    )
    assessment = ValueAssessment(
        decimal_odds=snapshot.decimal_odds,
        implied_probability_raw=value_math.implied_raw,
        implied_probability_novig=(novig or {}).get(selection.code),
        devig_method=devig_name,
        model_probability=probability,
        model_probability_lower=interval.lower,
        model_probability_upper=interval.upper,
        fair_odds=value_math.fair,
        ev=value_math.ev,
        ev_conservative=value_math.ev_conservative,
        min_acceptable_odds=value_math.min_odds,
        ev_sensitivity_per_odds_tick=value_math.sensitivity,
        overround=book.overround if complete else None,
    )
    confidence = score_confidence(
        data_quality=quality.score,
        probability_half_width=interval.half_width,
        max_half_width=settings.max_prob_half_width,
        ev=value_math.ev,
        min_ev=settings.min_ev,
        model_validated=prediction_status(model_id, settings).value != "BACKTEST_ONLY",
    )
    stake = compute_stake(
        settings=settings,
        odds=snapshot.decimal_odds,
        probability_conservative=interval.lower,
        probability_half_width=interval.half_width,
    )

    model_evidence = _model_evidence(prediction, moment)
    all_evidence = (model_evidence + evidence)[:5]

    candidate = Candidate(
        candidate_id=candidate_id(scan_id, event.canonical_id, selection.key, snapshot.bookmaker),
        event=event,
        selection=selection,
        bookmaker=snapshot.bookmaker,
        provider=snapshot.provider,
        observed_at=snapshot.observed_at,
        odds_age_seconds=age,
        value=assessment,
        probability=estimate,
        data_quality=quality,
        confidence=confidence,
        evidence=all_evidence,
        risks=explain.build_risks(
            event=event,
            selection=selection,
            probability=estimate,
            value=assessment,
            data_quality=quality,
        ),
        missing_information=explain.build_missing_information(all_evidence),
        invalidation_conditions=explain.build_invalidation_conditions(assessment, event),
        odds_movement=odds_movement(
            history.get((event.canonical_id, snapshot.bookmaker, selection.key), [])
        ),
        stake=stake,
        model_id=model_id,
        config_fingerprint=settings.fingerprint(),
    )
    workspace.candidates.append(
        candidate.model_copy(update={"explanation": explain.render_explanation(candidate)})
    )


def prediction_status(model_id: str, settings: Settings):  # type: ignore[no-untyped-def]
    """Validation status attached to a produced probability.

    Kept as a function so the promotion rules stay in one place once a model
    registry backed by the validation protocol replaces the hard-coded default.
    """
    from betmaxxing.domain.enums import ValidationStatus

    del model_id, settings
    return ValidationStatus.BACKTEST_ONLY


def _model_evidence(prediction: MarketPrediction, moment: datetime) -> list[EvidenceItem]:
    """Turn model diagnostics into sourced evidence items."""
    items: list[EvidenceItem] = []
    for key, value in list(prediction.diagnostics.items())[:3]:
        items.append(
            EvidenceItem(
                text=f"{key} = {value}",
                source="betmaxxing:model-diagnostics",
                as_of=moment,
                kind="fact",
            )
        )
    return items


def _evidence_for(
    context: object, event: CanonicalEvent, prediction: MarketPrediction
) -> list[EvidenceItem]:
    del prediction
    getter = getattr(context, "context_for", None)
    if getter is None:
        return []
    try:
        return list(getter(event))
    except Exception:  # pragma: no cover - a context failure must never kill a scan
        return []


def _health(
    providers: ProviderBundle,
    *,
    events_discovered: int,
    events_in_window: int,
    workspace: _Workspace,
    quarantined: int,
) -> DataHealth:
    statuses: list[ProviderStatus] = []
    for provider in (providers.odds, providers.context, providers.results):
        health = getattr(provider, "health", None)
        if health is not None:
            statuses.append(health())
    return DataHealth(
        providers=statuses,
        events_discovered=events_discovered,
        events_in_window=events_in_window,
        markets_evaluated=workspace.markets_evaluated,
        selections_priced=workspace.selections_priced,
        stale_snapshots=workspace.stale,
        quarantined_records=quarantined,
    )


def _result(
    settings: Settings,
    scan_id: str,
    moment: datetime,
    window: tuple[datetime, datetime],
    status: ScanStatus,
    health: DataHealth,
    workspace: _Workspace,
) -> ScanResult:
    summary: dict[str, int] = {}
    for rejection in workspace.rejections:
        summary[rejection.code.value] = summary.get(rejection.code.value, 0) + 1
    return ScanResult(
        scan_id=scan_id,
        status=status,
        mode=str(settings.mode),
        generated_at=moment,
        window={"from": window[0], "to": window[1]},
        data_health=health,
        candidates=sorted(workspace.candidates, key=lambda c: c.value.ev, reverse=True),
        rejections=workspace.rejections,
        rejections_summary=dict(sorted(summary.items())),
        thresholds=settings.eligibility_thresholds(),
        config_fingerprint=settings.fingerprint(),
        disclaimer=DISCLAIMER,
    )


def _unavailable(
    settings: Settings,
    scan_id: str,
    moment: datetime,
    window: tuple[datetime, datetime],
    reason: str,
) -> ScanResult:
    health = DataHealth(
        providers=[
            ProviderStatus(
                name=settings.odds_provider or "none",
                kind="odds",
                health="unavailable",  # type: ignore[arg-type]
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
    return _result(
        settings,
        scan_id,
        moment,
        window,
        ScanStatus.DATA_UNAVAILABLE,
        health,
        _Workspace(candidates=[], rejections=[]),
    )


def scan_is_demo(settings: Settings) -> bool:
    return settings.mode is RunMode.DEMO
