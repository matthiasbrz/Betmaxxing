"""Mapping The Odds API v4 payloads onto Betmaxxing's domain.

The rule throughout: **an unrecognised market, period, unit or participant is
rejected explicitly, never guessed.** A wrong mapping does not produce a bad
price, it produces a confident price for a bet that does not exist.

Two mappings are deliberately refused:

``h2h_s1``
    Means *winner of the first set*, not "wins at least one set". They are
    different bets with very different probabilities. Until a source key for
    "wins a set" is confirmed, that market stays
    :data:`UNSUPPORTED_BY_PROVIDER`.

Derived prices
    Draw-no-bet, double chance and wins-a-set are **never** synthesised from
    other odds. A price the bookmaker did not offer is not a price. The model's
    own fair odds for those markets remain available and are clearly a model
    output, not a market quote.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from betmaxxing.domain.enums import MarketType, Period, Sport
from betmaxxing.domain.models import Selection, canonical_line
from betmaxxing.domain.timeutil import ensure_utc

#: Markets we know the provider names but deliberately do not map.
UNSUPPORTED_BY_PROVIDER: dict[str, str] = {
    "h2h_s1": (
        "h2h_s1 désigne le vainqueur du 1er set, pas « gagne au moins un set » — "
        "mapping refusé (marchés différents)."
    ),
    "player_wins_a_set": (
        "Aucun identifiant source confirmé pour « gagne au moins un set » — "
        "UNSUPPORTED_BY_PROVIDER."
    ),
}

#: (provider market key, sport) -> (MarketType, Period)
MARKET_MAP: dict[tuple[str, Sport], tuple[MarketType, Period]] = {
    ("h2h", Sport.FOOTBALL): (MarketType.MATCH_RESULT_1X2, Period.FULL_TIME),
    ("totals", Sport.FOOTBALL): (MarketType.TOTAL_GOALS, Period.FULL_TIME),
    ("draw_no_bet", Sport.FOOTBALL): (MarketType.DRAW_NO_BET, Period.FULL_TIME),
    ("double_chance", Sport.FOOTBALL): (MarketType.DOUBLE_CHANCE, Period.FULL_TIME),
    ("h2h_3_way_h1", Sport.FOOTBALL): (MarketType.MATCH_RESULT_1X2, Period.FIRST_HALF),
    ("totals_h1", Sport.FOOTBALL): (MarketType.TOTAL_GOALS, Period.FIRST_HALF),
    ("double_chance_h1", Sport.FOOTBALL): (MarketType.DOUBLE_CHANCE, Period.FIRST_HALF),
    ("h2h", Sport.TENNIS): (MarketType.MATCH_WINNER, Period.FULL_TIME),
    # Tennis `totals` is total *games* only if the response and documentation
    # confirm that semantics; the caller must opt in via `allow_tennis_totals`.
    ("totals", Sport.TENNIS): (MarketType.TOTAL_GAMES, Period.FULL_TIME),
}

#: Sport-key prefixes used to classify a provider sport key.
SPORT_PREFIXES: dict[str, Sport] = {"soccer_": Sport.FOOTBALL, "tennis_": Sport.TENNIS}


class MappingRejected(ValueError):
    """The payload could not be mapped without guessing."""


@dataclass(frozen=True, slots=True)
class MappedOutcome:
    selection: Selection
    decimal_odds: float


def classify_sport(sport_key: str) -> Sport | None:
    """Map a provider sport key onto a supported sport, or ``None``."""
    for prefix, sport in SPORT_PREFIXES.items():
        if sport_key.startswith(prefix):
            return sport
    return None


def parse_iso(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MappingRejected(f"{field} n'est pas une date ISO-8601 : {value!r}") from exc
    if parsed.tzinfo is None:
        raise MappingRejected(f"{field} sans décalage UTC — aucun fuseau n'est supposé")
    return ensure_utc(parsed)


def parse_price(raw: Any) -> float:
    """Decimal odds must be finite and strictly above 1."""
    try:
        price = float(raw)
    except (TypeError, ValueError) as exc:
        raise MappingRejected(f"cote illisible : {raw!r}") from exc
    if price != price or price in (float("inf"), float("-inf")):
        raise MappingRejected(f"cote non finie : {raw!r}")
    if price <= 1.0:
        raise MappingRejected(f"cote décimale <= 1.0 : {price}")
    return price


def parse_line(raw: Any) -> Decimal:
    try:
        return Decimal(canonical_line(str(raw)))
    except (InvalidOperation, ValueError) as exc:
        raise MappingRejected(f"ligne illisible : {raw!r}") from exc


def outcome_code(
    *,
    market: MarketType,
    name: str,
    home_team: str,
    away_team: str,
) -> str:
    """Resolve an outcome name onto a stable selection code.

    Matching is by exact team/player name as supplied in the same payload — never
    by position or by fuzzy similarity, because a mismatched side silently
    inverts the bet.
    """
    normalised = name.strip()
    if market in (
        MarketType.MATCH_RESULT_1X2,
        MarketType.MATCH_WINNER,
        MarketType.DRAW_NO_BET,
    ):
        if normalised == home_team:
            return "home"
        if normalised == away_team:
            return "away"
        if normalised.lower() == "draw":
            return "draw"
        raise MappingRejected(
            f"participant « {name} » absent de l'événement ({home_team} / {away_team})"
        )
    if market in (MarketType.TOTAL_GOALS, MarketType.TOTAL_GAMES):
        lowered = normalised.lower()
        if lowered == "over":
            return "over"
        if lowered == "under":
            return "under"
        raise MappingRejected(f"issue over/under inconnue : {name!r}")
    if market is MarketType.DOUBLE_CHANCE:
        lowered = normalised.lower()
        mapping = {
            f"{home_team} or draw".lower(): "home_or_draw",
            f"draw or {away_team}".lower(): "draw_or_away",
            f"{home_team} or {away_team}".lower(): "home_or_away",
        }
        code = mapping.get(lowered)
        if code is None:
            raise MappingRejected(f"issue double chance inconnue : {name!r}")
        return code
    raise MappingRejected(f"marché non supporté pour le mapping d'issue : {market}")


def map_market(
    *,
    provider_market_key: str,
    sport: Sport,
    outcomes: list[dict[str, Any]],
    home_team: str,
    away_team: str,
    allow_tennis_totals: bool = False,
) -> list[MappedOutcome]:
    """Map one provider market block. Raises rather than guessing."""
    if provider_market_key in UNSUPPORTED_BY_PROVIDER:
        raise MappingRejected(UNSUPPORTED_BY_PROVIDER[provider_market_key])

    target = MARKET_MAP.get((provider_market_key, sport))
    if target is None:
        raise MappingRejected(
            f"marché « {provider_market_key} » non reconnu pour {sport} — rejeté."
        )
    market, period = target

    if market is MarketType.TOTAL_GAMES and not allow_tennis_totals:
        raise MappingRejected(
            "La sémantique de `totals` en tennis (jeux vs sets) n'est pas confirmée "
            "pour ce plan/tournoi — mapping désactivé par défaut."
        )

    mapped: list[MappedOutcome] = []
    for outcome in outcomes:
        name = outcome.get("name")
        if not isinstance(name, str):
            raise MappingRejected(f"issue sans nom exploitable : {outcome!r}")
        code = outcome_code(market=market, name=name, home_team=home_team, away_team=away_team)
        line = None
        if market in (MarketType.TOTAL_GOALS, MarketType.TOTAL_GAMES):
            if "point" not in outcome:
                raise MappingRejected(f"marché over/under sans ligne : {outcome!r}")
            line = parse_line(outcome["point"])
        mapped.append(
            MappedOutcome(
                selection=Selection(
                    market=market,
                    period=period,
                    code=code,
                    label=name,
                    line=line,
                ),
                decimal_odds=parse_price(outcome.get("price")),
            )
        )
    return mapped
