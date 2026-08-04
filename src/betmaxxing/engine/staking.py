"""Stake sizing.

Design constraints, in priority order:

1. Suggestions are **off** unless a bankroll and limits have been configured.
2. Kelly is computed on the *conservative* probability, never the point estimate.
3. A hard percentage cap on bankroll always wins over Kelly's output.
4. An over-uncertain probability yields exactly zero, not a small stake.
5. No martingale, no loss chasing, no "recovery" sizing anywhere in this module —
   the stake depends only on the current edge and the configured limits, never on
   previous results.
"""

from __future__ import annotations

from betmaxxing.config import Settings
from betmaxxing.domain.models import StakeSuggestion
from betmaxxing.engine.ev import kelly_fraction

#: Money is rounded to the cent; unit display to two decimals.
_MONEY_DP = 2
_UNIT_DP = 2


def compute_stake(
    *,
    settings: Settings,
    odds: float,
    probability_conservative: float,
    probability_half_width: float,
    already_exposed: float = 0.0,
) -> StakeSuggestion:
    """Suggest a simulated stake for one candidate.

    ``already_exposed`` is the amount already committed today; it is used to
    enforce the daily exposure ceiling. Returns a zero stake with a stated reason
    rather than raising, so a scan never fails because of staking.
    """
    currency = settings.currency
    zero = StakeSuggestion(
        units=0.0,
        amount=0.0,
        currency=currency,
        kelly_full_fraction=0.0,
        kelly_applied_fraction=0.0,
        capped_by=None,
        rationale="",
    )

    if not settings.staking_enabled:
        return zero.model_copy(
            update={
                "capped_by": "staking_disabled",
                "rationale": "Suggestions de mise désactivées dans la configuration.",
            }
        )
    if settings.bankroll <= 0:
        return zero.model_copy(
            update={
                "capped_by": "no_bankroll",
                "rationale": "Aucune bankroll configurée — aucune mise suggérée.",
            }
        )
    if probability_half_width > settings.max_prob_half_width:
        return zero.model_copy(
            update={
                "capped_by": "uncertainty",
                "rationale": (
                    f"Incertitude trop élevée (demi-largeur {probability_half_width:.3f} > "
                    f"{settings.max_prob_half_width:.3f}) — mise nulle."
                ),
            }
        )

    full_kelly = kelly_fraction(probability_conservative, odds)
    if full_kelly <= 0:
        return zero.model_copy(
            update={
                "kelly_full_fraction": full_kelly,
                "capped_by": "no_edge_conservative",
                "rationale": "Aucun avantage sur la borne prudente de p — mise nulle.",
            }
        )

    fractional = full_kelly * settings.kelly_fraction
    capped_by: str | None = None

    hard_cap = settings.max_stake_pct_of_bankroll
    if fractional > hard_cap:
        fractional = hard_cap
        capped_by = "max_stake_pct_of_bankroll"

    # Daily exposure ceiling.
    daily_room_amount = settings.bankroll * settings.max_daily_exposure_pct - already_exposed
    if daily_room_amount <= 0:
        return zero.model_copy(
            update={
                "kelly_full_fraction": full_kelly,
                "capped_by": "daily_exposure",
                "rationale": "Plafond d'exposition quotidienne atteint — mise nulle.",
            }
        )
    room_fraction = daily_room_amount / settings.bankroll
    if fractional > room_fraction:
        fractional = room_fraction
        capped_by = "max_daily_exposure_pct"

    amount = round(settings.bankroll * fractional, _MONEY_DP)
    unit_value = settings.bankroll * settings.unit_pct_of_bankroll
    units = round(amount / unit_value, _UNIT_DP) if unit_value > 0 else 0.0

    if amount <= 0:
        return zero.model_copy(
            update={
                "kelly_full_fraction": full_kelly,
                "capped_by": capped_by or "rounding",
                "rationale": "Mise arrondie à zéro — pas de suggestion.",
            }
        )

    cap_note = f" Plafonné par {capped_by}." if capped_by else ""
    return StakeSuggestion(
        units=units,
        amount=amount,
        currency=currency,
        kelly_full_fraction=full_kelly,
        kelly_applied_fraction=fractional,
        capped_by=capped_by,
        rationale=(
            f"Kelly {settings.kelly_fraction:.0%} sur p prudente "
            f"({probability_conservative:.3f}) à la cote {odds:.2f}."
            f"{cap_note} Mise simulée uniquement."
        ),
    )
