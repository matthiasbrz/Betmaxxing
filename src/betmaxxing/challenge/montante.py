"""Challenge — Montante: a simulation-oriented, opt-in progression module.

This module is disabled by default and is the single riskiest feature in the
product, so its guarantees are stated as executable rules rather than intentions:

* **It never lowers a threshold to hit a target.** :func:`propose_step` takes
  already-qualified candidates and filters them further. It has no path to
  loosen the EV, uncertainty or quality gates, and no path to build an
  accumulator.
* **It never chases losses.** The default stop policy ends the run on the first
  loss. There is no recovery staking, no doubling, no "next one wins it back".
* **A loss cannot increase the next stake.** :func:`next_stake` derives the stake
  from the *current* bank and the configured fraction only — it never reads the
  result history. This is enforced by a test.
* **Nothing advances without explicit confirmation.** Recording a bet requires a
  separate confirm call, and state moves on verified results or a manually
  confirmed entry, never on an assumption.
* **The number of steps is an estimate, never a promise.** It is recomputed after
  every result and reported alongside the assumption it rests on.

Money is handled in cents internally so rounding cannot silently create or
destroy value across a progression.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime

from betmaxxing.domain.enums import BetOutcome, ChallengeState
from betmaxxing.domain.models import Candidate
from betmaxxing.domain.timeutil import utc_now

#: Outcomes that end the progression under the default policy.
LOSING_OUTCOMES = frozenset({BetOutcome.LOST, BetOutcome.HALF_LOST})
#: Outcomes that leave the bank unchanged and do not consume a step.
NEUTRAL_OUTCOMES = frozenset({BetOutcome.VOID, BetOutcome.CANCELLED, BetOutcome.POSTPONED})


class ChallengeError(RuntimeError):
    """Illegal transition or configuration."""


def to_cents(amount: float) -> int:
    """Round half-up to the cent — the convention a bookmaker slip uses."""
    return math.floor(amount * 100 + 0.5)


def from_cents(cents: int) -> float:
    return cents / 100.0


@dataclass(frozen=True, slots=True)
class ChallengeConfig:
    """User-declared parameters. Every risk limit is explicit and required."""

    initial_bank: float
    target_bank: float
    currency: str = "EUR"
    #: Optional deadline. Never used to relax a filter — only to report feasibility.
    deadline: datetime | None = None
    allowed_sports: tuple[str, ...] = ()
    allowed_markets: tuple[str, ...] = ()
    min_odds: float = 1.20
    max_odds: float = 3.00
    #: Hard floor: the run stops if the bank falls to or below this.
    max_loss: float = 0.0
    #: Fraction of the *current* bank exposed on one step.
    fraction_per_step: float = 1.0
    #: True = the whole progression ends on the first loss (default, recommended).
    stop_on_first_loss: bool = True
    max_steps: int = 20

    def __post_init__(self) -> None:
        if self.initial_bank <= 0:
            raise ChallengeError("initial bank must be > 0")
        if self.target_bank <= self.initial_bank:
            raise ChallengeError("target must exceed the initial bank")
        if not (0.0 < self.fraction_per_step <= 1.0):
            raise ChallengeError("fraction_per_step must lie in (0, 1]")
        if self.min_odds <= 1.0 or self.max_odds <= self.min_odds:
            raise ChallengeError("odds range is invalid")
        if self.max_loss < 0 or self.max_loss >= self.initial_bank:
            raise ChallengeError("max_loss must lie in [0, initial_bank)")


@dataclass(frozen=True, slots=True)
class Step:
    """One rung of the ladder, with detected and accepted odds kept apart."""

    index: int
    bank_before_cents: int
    stake_cents: int
    #: The price the engine saw when it proposed the step.
    detected_odds: float
    #: The price the user says they actually got. Recorded separately, always.
    accepted_odds: float | None = None
    candidate_id: str | None = None
    event_label: str = ""
    selection_label: str = ""
    model_probability: float | None = None
    ev: float | None = None
    risks: tuple[str, ...] = ()
    outcome: BetOutcome = BetOutcome.PENDING
    bank_after_cents: int | None = None
    result_proof: str = ""
    proposed_at: datetime | None = None
    settled_at: datetime | None = None

    @property
    def potential_return_cents(self) -> int:
        odds = self.accepted_odds if self.accepted_odds is not None else self.detected_odds
        return to_cents(from_cents(self.stake_cents) * odds)

    @property
    def projected_bank_cents(self) -> int:
        return self.bank_before_cents - self.stake_cents + self.potential_return_cents


@dataclass(slots=True)
class Challenge:
    """The aggregate. All transitions go through the methods below."""

    challenge_id: str
    config: ChallengeConfig
    state: ChallengeState
    bank_cents: int
    steps: list[Step] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    stop_reason: str = ""

    # -- construction -------------------------------------------------------
    @classmethod
    def create(cls, config: ChallengeConfig) -> Challenge:
        return cls(
            challenge_id=uuid.uuid4().hex[:16],
            config=config,
            state=ChallengeState.DRAFT,
            bank_cents=to_cents(config.initial_bank),
        )

    # -- derived views ------------------------------------------------------
    @property
    def bank(self) -> float:
        return from_cents(self.bank_cents)

    @property
    def is_terminal(self) -> bool:
        return self.state in {
            ChallengeState.TARGET_REACHED,
            ChallengeState.STOPPED,
            ChallengeState.LOST,
            ChallengeState.CANCELLED,
        }

    def next_stake_cents(self) -> int:
        """Stake for the next step.

        Depends only on the current bank and the configured fraction. It does
        **not** consult ``self.steps``, which is what makes a martingale
        structurally impossible here rather than merely discouraged.
        """
        return to_cents(from_cents(self.bank_cents) * self.config.fraction_per_step)

    def estimate_remaining_steps(self, assumed_odds: float) -> int | None:
        """Indicative rung count at an assumed price. ``None`` if unreachable.

        Explicitly an estimate: it assumes a qualified candidate exists at that
        price on every rung, which the engine never guarantees.
        """
        if assumed_odds <= 1.0:
            return None
        growth = 1.0 - self.config.fraction_per_step + self.config.fraction_per_step * assumed_odds
        if growth <= 1.0:
            return None
        needed = self.config.target_bank / max(from_cents(self.bank_cents), 0.01)
        if needed <= 1.0:
            return 0
        return math.ceil(math.log(needed) / math.log(growth))

    def trajectory(self, assumed_odds: float) -> list[dict[str, float | int]]:
        """Indicative bank path, recomputed from the *current* bank."""
        steps = self.estimate_remaining_steps(assumed_odds)
        if steps is None:
            return []
        out: list[dict[str, float | int]] = []
        bank = self.bank_cents
        for index in range(steps):
            stake = to_cents(from_cents(bank) * self.config.fraction_per_step)
            projected = bank - stake + to_cents(from_cents(stake) * assumed_odds)
            out.append(
                {
                    "step": len(self.steps) + index + 1,
                    "bank_before": from_cents(bank),
                    "stake": from_cents(stake),
                    "projected_bank": from_cents(projected),
                }
            )
            bank = projected
        return out

    # -- transitions --------------------------------------------------------
    def activate(self) -> None:
        if self.state is not ChallengeState.DRAFT:
            raise ChallengeError(f"cannot activate from {self.state}")
        self._set_state(ChallengeState.WAITING_FOR_CANDIDATE)

    def propose(self, candidate: Candidate) -> Step:
        """Offer one qualified candidate for the next rung.

        The candidate must already have passed the full eligibility gate; this
        only applies the *additional* challenge restrictions.
        """
        if self.state is not ChallengeState.WAITING_FOR_CANDIDATE:
            raise ChallengeError(f"cannot propose a step from {self.state}")
        if len(self.steps) >= self.config.max_steps:
            self.stop("Nombre maximal de paliers atteint.")
            raise ChallengeError("maximum number of steps reached")
        reason = self.rejects_candidate(candidate)
        if reason:
            raise ChallengeError(reason)

        step = Step(
            index=len(self.steps) + 1,
            bank_before_cents=self.bank_cents,
            stake_cents=self.next_stake_cents(),
            detected_odds=candidate.value.decimal_odds,
            candidate_id=candidate.candidate_id,
            event_label=candidate.event.label,
            selection_label=candidate.selection.label,
            model_probability=candidate.value.model_probability,
            ev=candidate.value.ev,
            risks=tuple(candidate.risks),
            proposed_at=utc_now(),
        )
        self.steps.append(step)
        self._set_state(ChallengeState.AWAITING_USER_CONFIRMATION)
        return step

    def rejects_candidate(self, candidate: Candidate) -> str | None:
        """Extra challenge-level restrictions. Never loosens the main gate."""
        odds = candidate.value.decimal_odds
        if not (self.config.min_odds <= odds <= self.config.max_odds):
            return (
                f"Cote {odds:.2f} hors de la plage du challenge "
                f"[{self.config.min_odds:.2f}, {self.config.max_odds:.2f}]."
            )
        sports = self.config.allowed_sports
        if sports and str(candidate.event.sport) not in sports:
            return f"Sport {candidate.event.sport} non autorisé pour ce challenge."
        if (
            self.config.allowed_markets
            and str(candidate.selection.market) not in self.config.allowed_markets
        ):
            return f"Marché {candidate.selection.market} non autorisé pour ce challenge."
        return None

    def confirm(self, accepted_odds: float, *, at: datetime | None = None) -> Step:
        """Record that the user actually placed the bet, at the price they got."""
        if self.state is not ChallengeState.AWAITING_USER_CONFIRMATION:
            raise ChallengeError(f"nothing awaiting confirmation in state {self.state}")
        if accepted_odds <= 1.0:
            raise ChallengeError("accepted odds must be > 1.0")
        step = replace(self.steps[-1], accepted_odds=accepted_odds, proposed_at=at or utc_now())
        self.steps[-1] = step
        self._set_state(ChallengeState.AWAITING_RESULT)
        return step

    def settle(self, outcome: BetOutcome, *, proof: str, at: datetime | None = None) -> Step:
        """Apply a verified result and move the state machine."""
        if self.state is not ChallengeState.AWAITING_RESULT:
            raise ChallengeError(f"no bet awaiting a result in state {self.state}")
        if outcome is BetOutcome.PENDING:
            raise ChallengeError("PENDING is not a settlement")

        step = self.steps[-1]
        odds = step.accepted_odds if step.accepted_odds is not None else step.detected_odds
        stake = step.stake_cents
        bank = step.bank_before_cents

        if outcome is BetOutcome.WON:
            bank_after = bank - stake + to_cents(from_cents(stake) * odds)
        elif outcome is BetOutcome.HALF_WON:
            half = stake // 2
            bank_after = bank - stake + half + to_cents(from_cents(half) * odds)
        elif outcome is BetOutcome.LOST:
            bank_after = bank - stake
        elif outcome is BetOutcome.HALF_LOST:
            bank_after = bank - stake + (stake - stake // 2)
        elif outcome in NEUTRAL_OUTCOMES:
            bank_after = bank
        else:  # pragma: no cover - BetOutcome is exhaustive above
            raise ChallengeError(f"unhandled outcome {outcome}")

        settled = replace(
            step,
            outcome=outcome,
            bank_after_cents=bank_after,
            result_proof=proof,
            settled_at=at or utc_now(),
        )
        self.steps[-1] = settled
        self.bank_cents = bank_after
        self._apply_stop_rules(outcome)
        return settled

    def stop(self, reason: str) -> None:
        self.stop_reason = reason
        self._set_state(ChallengeState.STOPPED)

    def cancel(self, reason: str = "Annulé par l'utilisateur.") -> None:
        self.stop_reason = reason
        self._set_state(ChallengeState.CANCELLED)

    # -- internals ----------------------------------------------------------
    def _apply_stop_rules(self, outcome: BetOutcome) -> None:
        if self.bank_cents >= to_cents(self.config.target_bank):
            self.stop_reason = "Objectif atteint."
            self._set_state(ChallengeState.TARGET_REACHED)
            return
        if self.bank_cents <= to_cents(self.config.max_loss):
            self.stop_reason = "Perte maximale atteinte."
            self._set_state(ChallengeState.LOST)
            return
        if outcome in LOSING_OUTCOMES and self.config.stop_on_first_loss:
            self.stop_reason = (
                "Défaite : la montante se termine. Aucune stratégie de récupération n'est proposée."
            )
            self._set_state(ChallengeState.LOST)
            return
        if len(self.steps) >= self.config.max_steps:
            self.stop_reason = "Nombre maximal de paliers atteint."
            self._set_state(ChallengeState.STOPPED)
            return
        self._set_state(ChallengeState.WAITING_FOR_CANDIDATE)

    def _set_state(self, state: ChallengeState) -> None:
        self.state = state
        self.updated_at = utc_now()

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> dict[str, object]:
        return {
            "challenge_id": self.challenge_id,
            "state": str(self.state),
            "bank": self.bank,
            "currency": self.config.currency,
            "initial_bank": self.config.initial_bank,
            "target_bank": self.config.target_bank,
            "stop_reason": self.stop_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "steps": [
                {
                    "index": s.index,
                    "bank_before": from_cents(s.bank_before_cents),
                    "stake": from_cents(s.stake_cents),
                    "detected_odds": s.detected_odds,
                    "accepted_odds": s.accepted_odds,
                    "potential_return": from_cents(s.potential_return_cents),
                    "projected_bank": from_cents(s.projected_bank_cents),
                    "bank_after": (
                        from_cents(s.bank_after_cents) if s.bank_after_cents is not None else None
                    ),
                    "event": s.event_label,
                    "selection": s.selection_label,
                    "model_probability": s.model_probability,
                    "ev": s.ev,
                    "risks": list(s.risks),
                    "outcome": str(s.outcome),
                    "result_proof": s.result_proof,
                }
                for s in self.steps
            ],
        }


def propose_step(challenge: Challenge, candidates: list[Candidate]) -> Step | None:
    """Pick at most one qualified candidate for the next rung.

    Returns ``None`` — meaning ``WAIT`` / ``NO_BET`` — when nothing qualifies.
    Waiting is always preferable to relaxing a criterion, and this function has
    no mechanism to do the latter.
    """
    if challenge.state is not ChallengeState.WAITING_FOR_CANDIDATE:
        return None
    eligible = [c for c in candidates if challenge.rejects_candidate(c) is None]
    if not eligible:
        return None
    best = max(eligible, key=lambda c: c.value.ev_conservative)
    return challenge.propose(best)
