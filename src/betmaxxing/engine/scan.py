"""Analysis: turn priced books into candidates or coded rejections.

Pure with respect to I/O — it receives already-collected events, books and
snapshots and returns candidates plus rejections. Collection and persistence live
in :mod:`betmaxxing.engine.acquisition`, so there is exactly one place that talks
to providers and exactly one place that decides value.

Every priced selection ends up either in ``candidates`` or in ``rejections`` with
a code. Nothing is dropped silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import (
    EXPECTED_SELECTION_COUNT,
    MARKETS_BY_SPORT,
    PARTITION_MARKETS,
    EventStatus,
    MarketType,
    RejectionCode,
    UncertaintyStatus,
)
from betmaxxing.domain.ids import candidate_id
from betmaxxing.domain.models import (
    Candidate,
    CanonicalEvent,
    EvidenceItem,
    MarketBook,
    OddsSnapshot,
    ProbabilityEstimate,
    Rejection,
    ValueAssessment,
)
from betmaxxing.domain.timeutil import age_seconds, is_in_window
from betmaxxing.engine import eligibility, explain
from betmaxxing.engine.margin import DevigError, devig
from betmaxxing.engine.payoff import (
    PayoffDistribution,
    PayoffError,
    draw_no_bet_outcomes,
    ev_sensitivity,
    min_acceptable_odds,
    two_way_outcomes,
)
from betmaxxing.engine.quality import score_confidence, score_data_quality
from betmaxxing.engine.staking import compute_stake
from betmaxxing.engine.uncertainty import uncertainty_for_mode
from betmaxxing.ingestion.normalize import is_book_complete, odds_movement
from betmaxxing.models_ml.base import MarketPrediction
from betmaxxing.models_ml.registry import ModelRegistry, RegisteredModel


@dataclass(slots=True)
class AnalysisOutput:
    candidates: list[Candidate]
    rejections: list[Rejection]
    markets_evaluated: int = 0
    selections_priced: int = 0
    stale: int = 0


@dataclass(slots=True)
class _BookContext:
    """Everything resolved once per book, before scoring its selections."""

    novig: dict[str, float] | None
    devig_method: str | None
    complete: bool
    expected_selections: int
    in_scope: bool
    prediction: MarketPrediction
    registered: RegisteredModel
    evidence: list[EvidenceItem]


def analyse(
    *,
    settings: Settings,
    events: list[CanonicalEvent],
    all_events: list[CanonicalEvent],
    books: list[MarketBook],
    snapshots: list[OddsSnapshot],
    models: ModelRegistry,
    context: object,
    now: datetime,
    scan_id: str,
    window: tuple[datetime, datetime],
) -> AnalysisOutput:
    """Score every book and return candidates plus coded rejections."""
    out = AnalysisOutput(candidates=[], rejections=[])
    in_window_ids = {e.internal_id for e in events}

    # Events discovered but out of window are recorded, never forgotten.
    for event in all_events:
        if event.internal_id not in in_window_ids and not is_in_window(
            event.start_time_utc, window
        ):
            out.rejections.append(
                Rejection(
                    event_internal_id=event.internal_id,
                    event_label=event.label,
                    selection_key="-",
                    code=RejectionCode.OUTSIDE_WINDOW,
                    detail=(
                        f"Début {event.start_time_utc.isoformat()} hors fenêtre "
                        f"de {settings.window_hours:g} h."
                    ),
                )
            )

    events_by_id = {e.internal_id: e for e in events}
    history = _history_index(snapshots)

    for book in books:
        matched = events_by_id.get(book.event_internal_id)
        if matched is None:
            continue
        out.markets_evaluated += 1
        _score_book(
            book=book,
            event=matched,
            settings=settings,
            models=models,
            context=context,
            now=now,
            scan_id=scan_id,
            out=out,
            history=history,
        )
    return out


def _history_index(
    snapshots: list[OddsSnapshot],
) -> dict[tuple[str, str, str], list[OddsSnapshot]]:
    index: dict[tuple[str, str, str], list[OddsSnapshot]] = {}
    for snapshot in snapshots:
        key = (snapshot.event_internal_id, snapshot.bookmaker, snapshot.selection.key)
        index.setdefault(key, []).append(snapshot)
    return index


def _reject_book(
    out: AnalysisOutput,
    book: MarketBook,
    event: CanonicalEvent,
    code: RejectionCode,
    detail: str,
) -> None:
    for snapshot in book.snapshots:
        out.rejections.append(
            Rejection(
                event_internal_id=event.internal_id,
                event_label=event.label,
                selection_key=snapshot.selection.key,
                code=code,
                detail=detail,
            )
        )


def _score_book(
    *,
    book: MarketBook,
    event: CanonicalEvent,
    settings: Settings,
    models: ModelRegistry,
    context: object,
    now: datetime,
    scan_id: str,
    out: AnalysisOutput,
    history: dict[tuple[str, str, str], list[OddsSnapshot]],
) -> None:
    complete = is_book_complete(book)
    expected = EXPECTED_SELECTION_COUNT.get(book.market, len(book.snapshots))

    novig: dict[str, float] | None = None
    devig_name: str | None = None
    if complete and book.market in PARTITION_MARKETS:
        try:
            probs = devig([s.decimal_odds for s in book.snapshots], settings.devig_method)
            novig = {s.selection.code: p for s, p in zip(book.snapshots, probs, strict=True)}
            devig_name = str(settings.devig_method)
        except DevigError as exc:
            _reject_book(
                out,
                book,
                event,
                RejectionCode.MARKET_INCOMPLETE,
                f"Retrait de marge impossible : {exc}",
            )
            return

    registered = models.get(event.sport)
    if registered is None:
        _reject_book(
            out,
            book,
            event,
            RejectionCode.NO_MODEL_AVAILABLE,
            f"Aucun modèle enregistré pour {event.sport}.",
        )
        return

    prediction = registered.model.predict(event, book.market, book.period, book.line)
    if prediction is None:
        line_note = f" ligne {book.line}" if book.line is not None else ""
        _reject_book(
            out,
            book,
            event,
            RejectionCode.NO_MODEL_AVAILABLE,
            f"{registered.model_id} ne price pas {book.market}/{book.period}{line_note}.",
        )
        return

    ctx = _BookContext(
        novig=novig,
        devig_method=devig_name,
        complete=complete,
        expected_selections=expected,
        in_scope=book.market in MARKETS_BY_SPORT.get(event.sport, frozenset()),
        prediction=prediction,
        registered=registered,
        evidence=_evidence_for(context, event),
    )

    for snapshot in book.snapshots:
        out.selections_priced += 1
        _score_selection(
            snapshot=snapshot,
            book=book,
            event=event,
            ctx=ctx,
            settings=settings,
            now=now,
            scan_id=scan_id,
            out=out,
            history=history,
        )


def _build_payoff(
    prediction: MarketPrediction, code: str, odds: float
) -> PayoffDistribution | None:
    """Build the settlement distribution for one selection.

    Draw-no-bet gets a real push branch. Everything else in V1 is win/lose —
    integer totals, which could push, are refused upstream.
    """
    p_win = prediction.probabilities.get(code)
    if p_win is None or not (0.0 < p_win < 1.0):
        return None
    p_push = prediction.push_for(code)
    try:
        if p_push > 0.0:
            p_loss = 1.0 - p_win - p_push
            if p_loss < -1e-9:
                return None
            return draw_no_bet_outcomes(
                p_win=p_win, p_push=p_push, p_loss=max(p_loss, 0.0), decimal_odds=odds
            )
        return two_way_outcomes(p_win=p_win, decimal_odds=odds)
    except PayoffError:
        return None


def _score_selection(
    *,
    snapshot: OddsSnapshot,
    book: MarketBook,
    event: CanonicalEvent,
    ctx: _BookContext,
    settings: Settings,
    now: datetime,
    scan_id: str,
    out: AnalysisOutput,
    history: dict[tuple[str, str, str], list[OddsSnapshot]],
) -> None:
    selection = snapshot.selection
    payoff = _build_payoff(ctx.prediction, selection.code, snapshot.decimal_odds)
    if payoff is None:
        out.rejections.append(
            Rejection(
                event_internal_id=event.internal_id,
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

    age = age_seconds(snapshot.observed_at, now)
    if age > settings.max_odds_age_seconds:
        out.stale += 1

    # The comparable figure: conditional on a decisive outcome, like a de-vigged
    # market price. Not the same thing as the unconditional win probability.
    p_comparable = payoff.conditional_win_probability
    uncertainty = uncertainty_for_mode(
        mode=settings.mode,
        probability=p_comparable,
        effective_sample_size=ctx.prediction.synthetic_sample_size,
        z=settings.prob_interval_z,
    )

    ev = payoff.expected_value
    ev_conservative: float | None = None
    if uncertainty.lower is not None:
        try:
            conservative = _rebuild_at_probability(payoff, uncertainty.lower)
            ev_conservative = conservative.expected_value
        except PayoffError:
            ev_conservative = None

    quality = score_data_quality(
        odds_age_seconds=age,
        max_odds_age_seconds=float(settings.max_odds_age_seconds),
        selections_present=len(book.snapshots),
        selections_expected=ctx.expected_selections,
        mapping_ambiguous=event.mapping_ambiguous,
        feature_completeness=ctx.prediction.feature_completeness,
        source_agreement=1.0,
    )

    gate = eligibility.evaluate(
        eligibility.GateInput(
            ev=ev,
            ev_conservative=ev_conservative,
            uncertainty_status=uncertainty.status,
            probability_half_width=uncertainty.half_width,
            odds=snapshot.decimal_odds,
            odds_age_seconds=age,
            data_quality=quality.score,
            market_complete=ctx.complete,
            mapping_ambiguous=event.mapping_ambiguous,
            in_window=True,
            in_scope=ctx.in_scope,
            event_scheduled=event.status is EventStatus.SCHEDULED,
            validation_status=ctx.registered.validation_status,
            mode=settings.mode,
        ),
        settings,
    )

    if not gate.passed:
        for code, detail in zip(gate.codes, gate.details, strict=True):
            out.rejections.append(
                Rejection(
                    event_internal_id=event.internal_id,
                    event_label=event.label,
                    selection_key=selection.key,
                    code=code,
                    detail=detail,
                )
            )
        return

    estimate = ProbabilityEstimate(
        probability=p_comparable,
        model_id=ctx.registered.model_id,
        model_version=ctx.registered.version,
        validation_status=ctx.registered.validation_status,
        uncertainty=uncertainty,
    )
    assessment = ValueAssessment(
        decimal_odds=snapshot.decimal_odds,
        implied_probability_raw=snapshot.implied_probability_raw,
        implied_probability_novig=(ctx.novig or {}).get(selection.code),
        devig_method=ctx.devig_method,
        win_probability=payoff.win_probability,
        push_probability=payoff.push_probability,
        conditional_win_probability=p_comparable,
        settlement_rule=str(payoff.rule),
        payoff_outcomes=[
            {"name": o.name, "probability": o.probability, "net_return": o.net_return}
            for o in payoff.outcomes
        ],
        fair_odds=payoff.fair_odds,
        ev=ev,
        ev_conservative=ev_conservative,
        min_acceptable_odds=min_acceptable_odds(payoff, settings.min_ev),
        ev_sensitivity_per_odds_tick=ev_sensitivity(payoff),
        overround=book.overround if ctx.complete else None,
    )
    confidence = score_confidence(
        data_quality=quality.score,
        probability_half_width=uncertainty.half_width,
        max_half_width=settings.max_prob_half_width,
        ev=ev,
        min_ev=settings.min_ev,
        model_validated=ctx.registered.validation_status.value != "BACKTEST_ONLY",
        uncertainty_status=uncertainty.status,
    )
    stake = compute_stake(
        settings=settings,
        odds=snapshot.decimal_odds,
        probability_conservative=uncertainty.lower,
        probability_half_width=uncertainty.half_width,
        uncertainty_status=uncertainty.status,
    )

    evidence = (_model_evidence(ctx.prediction, now) + ctx.evidence)[:5]
    candidate = Candidate(
        candidate_id=candidate_id(scan_id, event.internal_id, selection.key, snapshot.bookmaker),
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
        evidence=evidence,
        risks=explain.build_risks(
            event=event,
            selection=selection,
            probability=estimate,
            value=assessment,
            data_quality=quality,
        ),
        missing_information=explain.build_missing_information(evidence),
        invalidation_conditions=explain.build_invalidation_conditions(assessment, event),
        odds_movement=odds_movement(
            history.get((event.internal_id, snapshot.bookmaker, selection.key), [])
        ),
        stake=stake,
        model_id=ctx.registered.model_id,
        model_version=ctx.registered.version,
        config_fingerprint=settings.fingerprint(),
    )
    out.candidates.append(
        candidate.model_copy(update={"explanation": explain.render_explanation(candidate)})
    )


def _rebuild_at_probability(
    payoff: PayoffDistribution, conditional_lower: float
) -> PayoffDistribution:
    """Recompute the payoff at a pessimistic conditional probability.

    The push mass is held fixed and the decisive mass redistributed, so a
    conservative EV on a refundable market stays a valid settlement description
    rather than a rescaled point estimate.
    """
    decisive = 1.0 - payoff.push_probability
    p_win = conditional_lower * decisive
    p_loss = decisive - p_win
    if payoff.push_probability > 0.0:
        return draw_no_bet_outcomes(
            p_win=p_win,
            p_push=payoff.push_probability,
            p_loss=p_loss,
            decimal_odds=payoff.decimal_odds,
        )
    return two_way_outcomes(p_win=p_win, decimal_odds=payoff.decimal_odds)


def _model_evidence(prediction: MarketPrediction, moment: datetime) -> list[EvidenceItem]:
    return [
        EvidenceItem(
            text=f"{key} = {value}",
            source="betmaxxing:model-diagnostics",
            as_of=moment,
            kind="fact",
        )
        for key, value in list(prediction.diagnostics.items())[:3]
    ]


def _evidence_for(context: object, event: CanonicalEvent) -> list[EvidenceItem]:
    getter = getattr(context, "context_for", None)
    if getter is None:
        return []
    try:
        return list(getter(event))
    except Exception:  # pragma: no cover - a context failure must never kill a scan
        return []


#: Markets whose settlement can refund the stake, for documentation and tests.
REFUNDABLE_MARKETS = frozenset({MarketType.DRAW_NO_BET})


def demo_uncertainty_is_synthetic(settings: Settings) -> bool:
    """True when this run's uncertainty is a labelled placeholder."""
    return settings.mode is RunMode.DEMO


__all__ = [
    "REFUNDABLE_MARKETS",
    "AnalysisOutput",
    "UncertaintyStatus",
    "analyse",
    "demo_uncertainty_is_synthetic",
]
