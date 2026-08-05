"""Durable Challenge storage.

The previous version kept challenges in a module-level dict inside the API,
which meant a restart erased every progression and two workers saw different
state. The tables existed but nothing wrote to them.

Concurrency is handled with optimistic versioning: every mutation reads the
stored ``version``, writes ``version + 1`` conditioned on the value it read, and
raises :class:`ConcurrentModification` when the row moved underneath it. That is
what stops the same rung being settled twice by two concurrent requests.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from betmaxxing.challenge.montante import Challenge, ChallengeConfig, Step
from betmaxxing.config import Settings
from betmaxxing.domain.enums import BetOutcome, ChallengeState
from betmaxxing.domain.timeutil import ensure_utc, from_storage, utc_now
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import ChallengeRow, ChallengeStepRow


class ChallengeNotFound(LookupError):
    """No challenge with that id."""


class ConcurrentModification(RuntimeError):
    """The challenge changed between read and write."""


def _config_to_dict(config: ChallengeConfig) -> dict[str, Any]:
    return {
        "initial_bank": config.initial_bank,
        "target_bank": config.target_bank,
        "currency": config.currency,
        "deadline": config.deadline.isoformat() if config.deadline else None,
        "allowed_sports": list(config.allowed_sports),
        "allowed_markets": list(config.allowed_markets),
        "min_odds": config.min_odds,
        "max_odds": config.max_odds,
        "max_loss": config.max_loss,
        "fraction_per_step": config.fraction_per_step,
        "stop_on_first_loss": config.stop_on_first_loss,
        "max_steps": config.max_steps,
        "acknowledged_total_loss_risk": config.acknowledged_total_loss_risk,
    }


def _config_from_dict(payload: dict[str, Any]) -> ChallengeConfig:
    deadline = payload.get("deadline")
    return ChallengeConfig(
        initial_bank=float(payload["initial_bank"]),
        target_bank=float(payload["target_bank"]),
        currency=str(payload.get("currency", "EUR")),
        deadline=datetime.fromisoformat(str(deadline)) if deadline else None,
        allowed_sports=tuple(payload.get("allowed_sports") or ()),
        allowed_markets=tuple(payload.get("allowed_markets") or ()),
        min_odds=float(payload.get("min_odds", 1.20)),
        max_odds=float(payload.get("max_odds", 3.00)),
        max_loss=float(payload.get("max_loss", 0.0)),
        fraction_per_step=float(payload.get("fraction_per_step", 0.25)),
        stop_on_first_loss=bool(payload.get("stop_on_first_loss", True)),
        max_steps=int(payload.get("max_steps", 20)),
        acknowledged_total_loss_risk=bool(payload.get("acknowledged_total_loss_risk", False)),
    )


def _step_to_dict(step: Step) -> dict[str, Any]:
    return {
        "index": step.index,
        "bank_before_cents": step.bank_before_cents,
        "stake_cents": step.stake_cents,
        "detected_odds": step.detected_odds,
        "accepted_odds": step.accepted_odds,
        "candidate_id": step.candidate_id,
        "event_label": step.event_label,
        "selection_label": step.selection_label,
        "model_probability": step.model_probability,
        "ev": step.ev,
        "risks": list(step.risks),
        "outcome": str(step.outcome),
        "bank_after_cents": step.bank_after_cents,
        "result_proof": step.result_proof,
        "proposed_at": step.proposed_at.isoformat() if step.proposed_at else None,
        "settled_at": step.settled_at.isoformat() if step.settled_at else None,
    }


def _step_from_dict(payload: dict[str, Any]) -> Step:
    def _dt(key: str) -> datetime | None:
        raw = payload.get(key)
        return datetime.fromisoformat(str(raw)) if raw else None

    return Step(
        index=int(payload["index"]),
        bank_before_cents=int(payload["bank_before_cents"]),
        stake_cents=int(payload["stake_cents"]),
        detected_odds=float(payload["detected_odds"]),
        accepted_odds=(float(payload["accepted_odds"]) if payload.get("accepted_odds") else None),
        candidate_id=payload.get("candidate_id"),
        event_label=str(payload.get("event_label", "")),
        selection_label=str(payload.get("selection_label", "")),
        model_probability=(
            float(payload["model_probability"]) if payload.get("model_probability") else None
        ),
        ev=float(payload["ev"]) if payload.get("ev") is not None else None,
        risks=tuple(payload.get("risks") or ()),
        outcome=BetOutcome(str(payload.get("outcome", "pending"))),
        bank_after_cents=(
            int(payload["bank_after_cents"])
            if payload.get("bank_after_cents") is not None
            else None
        ),
        result_proof=str(payload.get("result_proof", "")),
        proposed_at=_dt("proposed_at"),
        settled_at=_dt("settled_at"),
    )


class ChallengeRepository:
    """Load/store challenges with optimistic concurrency control."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self, challenge: Challenge) -> Challenge:
        with session_scope(self._settings) as session:
            session.add(
                ChallengeRow(
                    challenge_id=challenge.challenge_id,
                    state=str(challenge.state),
                    created_at=ensure_utc(challenge.created_at),
                    updated_at=ensure_utc(challenge.updated_at),
                    version=1,
                    bank_cents=challenge.bank_cents,
                    stop_reason=challenge.stop_reason,
                    document=json.loads(
                        json.dumps({"config": _config_to_dict(challenge.config)}, default=str)
                    ),
                )
            )
        return challenge

    def load(self, challenge_id: str) -> tuple[Challenge, int]:
        """Return the challenge and the version it was read at."""
        with session_scope(self._settings) as session:
            row = session.get(ChallengeRow, challenge_id)
            if row is None:
                raise ChallengeNotFound(challenge_id)
            steps = session.scalars(
                select(ChallengeStepRow)
                .where(ChallengeStepRow.challenge_id == challenge_id)
                .order_by(ChallengeStepRow.step_index)
            ).all()
            challenge = Challenge(
                challenge_id=row.challenge_id,
                config=_config_from_dict(dict(row.document)["config"]),
                state=ChallengeState(row.state),
                bank_cents=row.bank_cents,
                steps=[_step_from_dict(dict(s.document)) for s in steps],
                created_at=from_storage(row.created_at),
                updated_at=from_storage(row.updated_at),
                stop_reason=row.stop_reason or "",
            )
            return challenge, row.version

    def save(self, challenge: Challenge, expected_version: int) -> None:
        """Persist a mutation, refusing if the row moved since it was read."""
        with session_scope(self._settings) as session:
            result = session.execute(
                update(ChallengeRow)
                .where(
                    ChallengeRow.challenge_id == challenge.challenge_id,
                    ChallengeRow.version == expected_version,
                )
                .values(
                    state=str(challenge.state),
                    updated_at=utc_now(),
                    version=expected_version + 1,
                    bank_cents=challenge.bank_cents,
                    stop_reason=challenge.stop_reason,
                )
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                raise ConcurrentModification(
                    f"challenge {challenge.challenge_id} was modified concurrently"
                )

            existing = {
                row.step_index: row
                for row in session.scalars(
                    select(ChallengeStepRow).where(
                        ChallengeStepRow.challenge_id == challenge.challenge_id
                    )
                ).all()
            }
            for step in challenge.steps:
                payload = json.loads(json.dumps(_step_to_dict(step), default=str))
                row = existing.get(step.index)
                if row is None:
                    session.add(
                        ChallengeStepRow(
                            challenge_id=challenge.challenge_id,
                            step_index=step.index,
                            document=payload,
                        )
                    )
                else:
                    row.document = payload

    def list_ids(self) -> list[str]:
        with session_scope(self._settings) as session:
            return list(session.scalars(select(ChallengeRow.challenge_id)).all())

    def delete(self, challenge_id: str) -> None:
        with session_scope(self._settings) as session:
            for step_row in session.scalars(
                select(ChallengeStepRow).where(ChallengeStepRow.challenge_id == challenge_id)
            ).all():
                session.delete(step_row)
            challenge_row = session.get(ChallengeRow, challenge_id)
            if challenge_row is not None:
                session.delete(challenge_row)
