"""Challenge — Montante endpoints.

Disabled by default. Every route here 404s unless
``BETMAXXING_CHALLENGE_ENABLED=true``: this is a simulation module, and a
simulation module that is reachable by default is a trap.

State is durable (``challenges`` / ``challenge_steps``) with optimistic
versioning, so a restart does not erase a progression and two concurrent
requests cannot settle the same rung twice. Proposal and confirmation remain
separate calls — nothing advances without the user saying so.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from betmaxxing.challenge import Challenge, ChallengeConfig, ChallengeError, propose_step
from betmaxxing.challenge.repository import (
    ChallengeNotFound,
    ChallengeRepository,
    ConcurrentModification,
)
from betmaxxing.config import RunMode, Settings, get_settings
from betmaxxing.domain.enums import BetOutcome
from betmaxxing.engine.acquisition import run_scan
from betmaxxing.storage.db import create_all

router = APIRouter(prefix="/challenges", tags=["challenges"])

RESPONSIBLE_GAMBLING_NOTE = (
    "Module de simulation. Aucune garantie d'atteindre l'objectif. Aucun seuil "
    "n'est assoupli pour tenir une échéance, aucune stratégie de récupération "
    "n'est proposée après une défaite. Vous pouvez arrêter à tout moment."
)

DISABLED_DETAIL = (
    "Challenge — Montante désactivé. Activez-le explicitement avec "
    "BETMAXXING_CHALLENGE_ENABLED=true. C'est un module de simulation ; il n'est "
    "jamais actif par défaut."
)


def _require_enabled() -> Settings:
    settings = get_settings()
    if not settings.challenge_enabled:
        raise HTTPException(status_code=404, detail=DISABLED_DETAIL)
    create_all(settings)
    return settings


def _repository() -> ChallengeRepository:
    return ChallengeRepository(_require_enabled())


class CreateChallengeRequest(BaseModel):
    initial_bank: float = Field(gt=0)
    target_bank: float = Field(gt=0)
    currency: str = "EUR"
    allowed_sports: list[str] = Field(default_factory=list)
    allowed_markets: list[str] = Field(default_factory=list)
    min_odds: float = Field(default=1.20, gt=1.0)
    max_odds: float = Field(default=3.00, gt=1.0)
    max_loss: float = Field(default=0.0, ge=0)
    fraction_per_step: float = Field(
        default=0.25,
        gt=0,
        le=1.0,
        description="Fraction of the current bank per rung. Never defaults to 100%.",
    )
    acknowledged_total_loss_risk: bool = Field(
        default=False,
        description="Required above 50% per rung — the risk must be chosen, not inherited.",
    )
    stop_on_first_loss: bool = True
    max_steps: int = Field(default=20, ge=1, le=100)


class ConfirmRequest(BaseModel):
    accepted_odds: float = Field(gt=1.0, description="La cote réellement acceptée.")


class SettleRequest(BaseModel):
    outcome: BetOutcome
    proof: str = Field(min_length=1, description="Preuve vérifiable du résultat.")


def _load(challenge_id: str) -> tuple[Challenge, int]:
    try:
        return _repository().load(challenge_id)
    except ChallengeNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"challenge {challenge_id} introuvable"
        ) from exc


def _persist(challenge: Challenge, version: int) -> None:
    try:
        _repository().save(challenge, version)
    except ConcurrentModification as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _view(challenge: Challenge) -> dict[str, Any]:
    return {
        **challenge.to_dict(),
        "next_stake": challenge.next_stake_cents() / 100.0,
        "estimated_remaining_steps_at_2_00": challenge.estimate_remaining_steps(2.0),
        "trajectory_at_2_00": challenge.trajectory(2.0),
        "total_loss_risk": challenge.total_loss_risk_note,
        "note": RESPONSIBLE_GAMBLING_NOTE,
    }


@router.post("")
def create_challenge(request: CreateChallengeRequest) -> dict[str, Any]:
    try:
        config = ChallengeConfig(
            initial_bank=request.initial_bank,
            target_bank=request.target_bank,
            currency=request.currency,
            allowed_sports=tuple(request.allowed_sports),
            allowed_markets=tuple(request.allowed_markets),
            min_odds=request.min_odds,
            max_odds=request.max_odds,
            max_loss=request.max_loss,
            fraction_per_step=request.fraction_per_step,
            stop_on_first_loss=request.stop_on_first_loss,
            max_steps=request.max_steps,
            acknowledged_total_loss_risk=request.acknowledged_total_loss_risk,
        )
    except ChallengeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    challenge = _repository().create(Challenge.create(config))
    return _view(challenge)


@router.get("")
def list_challenges() -> list[dict[str, Any]]:
    repo = _repository()
    return [_view(repo.load(cid)[0]) for cid in repo.list_ids()]


@router.get("/{challenge_id}")
def get_challenge(challenge_id: str) -> dict[str, Any]:
    return _view(_load(challenge_id)[0])


@router.post("/{challenge_id}/activate")
def activate(challenge_id: str) -> dict[str, Any]:
    challenge, version = _load(challenge_id)
    try:
        challenge.activate()
    except ChallengeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _persist(challenge, version)
    return _view(challenge)


@router.post("/{challenge_id}/propose")
def propose(challenge_id: str) -> dict[str, Any]:
    """Run a scan and offer at most one qualified candidate, or ``WAIT``."""
    settings = _require_enabled()
    challenge, version = _load(challenge_id)
    result = run_scan(settings)
    step = propose_step(challenge, result.candidates)
    if step is None:
        return {
            "decision": "WAIT",
            "reason": (
                "Aucun candidat qualifié ne satisfait aussi les contraintes du challenge. "
                "Aucun seuil n'est abaissé pour produire un pari."
            ),
            "scan_id": result.scan_id,
            "scan_status": str(result.status),
            "collection_status": str(result.collection_status),
            "challenge": _view(challenge),
        }
    _persist(challenge, version)
    return {
        "decision": "PROPOSED",
        "scan_id": result.scan_id,
        "mode": str(settings.mode),
        # Demo candidates are synthetic. Flagged so a progression built on them
        # can never be mistaken for one built on real prices.
        "synthetic_data": settings.mode is RunMode.DEMO,
        "step": {
            "index": step.index,
            "bank_before": step.bank_before_cents / 100.0,
            "stake": step.stake_cents / 100.0,
            "detected_odds": step.detected_odds,
            "potential_return": step.potential_return_cents / 100.0,
            "projected_bank": step.projected_bank_cents / 100.0,
            "event": step.event_label,
            "selection": step.selection_label,
            "model_probability": step.model_probability,
            "ev": step.ev,
            "risks": list(step.risks),
        },
        "requires_manual_confirmation": True,
        "challenge": _view(challenge),
    }


@router.post("/{challenge_id}/confirm")
def confirm(challenge_id: str, request: ConfirmRequest) -> dict[str, Any]:
    """Record that the user placed the bet, at the price they actually got."""
    challenge, version = _load(challenge_id)
    try:
        challenge.confirm(request.accepted_odds)
    except ChallengeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _persist(challenge, version)
    return _view(challenge)


@router.post("/{challenge_id}/settle")
def settle(challenge_id: str, request: SettleRequest) -> dict[str, Any]:
    challenge, version = _load(challenge_id)
    try:
        challenge.settle(request.outcome, proof=request.proof)
    except ChallengeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Optimistic versioning is what stops a rung being settled twice by two
    # concurrent requests: the second write sees a moved version and 409s.
    _persist(challenge, version)
    return _view(challenge)


@router.post("/{challenge_id}/stop")
def stop(challenge_id: str) -> dict[str, Any]:
    """Immediate voluntary stop. Always available."""
    challenge, version = _load(challenge_id)
    challenge.stop("Arrêt volontaire immédiat demandé par l'utilisateur.")
    _persist(challenge, version)
    return _view(challenge)
