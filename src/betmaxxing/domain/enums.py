"""Closed vocabularies shared by every layer.

Market identity is intentionally verbose: a selection is only comparable to a
bookmaker price when sport, market type, period AND line all match exactly.
Approximating between two lines or two periods is forbidden.
"""

from __future__ import annotations

from enum import StrEnum


class Sport(StrEnum):
    FOOTBALL = "football"
    TENNIS = "tennis"


class Period(StrEnum):
    """Portion of the event a market settles on."""

    FULL_TIME = "full_time"
    FIRST_HALF = "first_half"


class MarketType(StrEnum):
    """Supported market families. V1 is pre-match, single bets only."""

    # Football
    MATCH_RESULT_1X2 = "1x2"
    DRAW_NO_BET = "draw_no_bet"
    DOUBLE_CHANCE = "double_chance"
    TOTAL_GOALS = "total_goals"
    # Tennis
    MATCH_WINNER = "match_winner"
    PLAYER_WINS_A_SET = "player_wins_a_set"
    TOTAL_GAMES = "total_games"


#: Markets that require an explicit numeric line (e.g. Over/Under 2.5).
LINE_REQUIRED_MARKETS: frozenset[MarketType] = frozenset(
    {MarketType.TOTAL_GOALS, MarketType.TOTAL_GAMES}
)

#: Markets whose outcomes form a complete, mutually exclusive partition and can
#: therefore be de-vigged as a book. ``double_chance`` is excluded: its three
#: outcomes overlap and sum to 2, so it is de-vigged from the 1X2 book instead.
PARTITION_MARKETS: frozenset[MarketType] = frozenset(
    {
        MarketType.MATCH_RESULT_1X2,
        MarketType.DRAW_NO_BET,
        MarketType.TOTAL_GOALS,
        MarketType.MATCH_WINNER,
        MarketType.TOTAL_GAMES,
    }
)

#: How many selections a complete book must contain, per market type.
EXPECTED_SELECTION_COUNT: dict[MarketType, int] = {
    MarketType.MATCH_RESULT_1X2: 3,
    MarketType.DRAW_NO_BET: 2,
    MarketType.DOUBLE_CHANCE: 3,
    MarketType.TOTAL_GOALS: 2,
    MarketType.MATCH_WINNER: 2,
    MarketType.PLAYER_WINS_A_SET: 2,
    MarketType.TOTAL_GAMES: 2,
}

MARKETS_BY_SPORT: dict[Sport, frozenset[MarketType]] = {
    Sport.FOOTBALL: frozenset(
        {
            MarketType.MATCH_RESULT_1X2,
            MarketType.DRAW_NO_BET,
            MarketType.DOUBLE_CHANCE,
            MarketType.TOTAL_GOALS,
        }
    ),
    Sport.TENNIS: frozenset(
        {
            MarketType.MATCH_WINNER,
            MarketType.PLAYER_WINS_A_SET,
            MarketType.TOTAL_GAMES,
        }
    ),
}


class EventStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PLAY = "in_play"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    WALKOVER = "walkover"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class ScanStatus(StrEnum):
    """Top-level answer of a scan. ``NO_BET`` is a normal, expected outcome.

    ``NO_CANDIDATE`` is an alias of ``NO_BET``: same wire value, clearer name at
    the call site. Fine-grained reasons live in :class:`CollectionStatus`.
    """

    CANDIDATES_FOUND = "CANDIDATES_FOUND"
    NO_BET = "NO_BET"
    NO_CANDIDATE = "NO_BET"  # alias
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class CollectionStatus(StrEnum):
    """Why a scan produced what it produced.

    Reported alongside ``ScanStatus`` so "we collected real data but have no
    model" is never confused with "the provider is down". Both yield zero
    candidates; only one is a fault.
    """

    OK = "OK"
    #: Real data was collected and stored, but no model could price it.
    COLLECTED_NO_MODEL = "COLLECTED_NO_MODEL"
    #: Models ran; nothing cleared the gate. The normal outcome.
    NO_CANDIDATE = "NO_CANDIDATE"
    #: Provider answered correctly, but the configured bookmaker was absent.
    COVERAGE_MISSING = "COVERAGE_MISSING"
    #: Data was returned but is too old to act on.
    DATA_STALE = "DATA_STALE"
    #: The provider failed. This one *is* a fault.
    PROVIDER_ERROR = "PROVIDER_ERROR"


class UncertaintyStatus(StrEnum):
    """Provenance of an uncertainty statement.

    The distinction that matters: ``SYNTHETIC`` is a made-up number used to
    exercise the interface, ``UNAVAILABLE`` is an honest "we cannot say", and
    only ``VALIDATED`` may gate a real candidate. See D-019.
    """

    #: Deterministic placeholder, demo mode only. Never a basis for a bet.
    SYNTHETIC = "SYNTHETIC"
    #: No defensible method exists yet for this model. `ev_conservative` is null.
    UNAVAILABLE = "UNAVAILABLE"
    #: Produced by a real method that has not passed a coverage study.
    ESTIMATED = "ESTIMATED"
    #: Produced by a method whose coverage was validated by the protocol.
    VALIDATED = "VALIDATED"


class RejectionCode(StrEnum):
    """Why a (event, market, selection) triple did not become a candidate."""

    EV_TOO_LOW = "EV_TOO_LOW"
    CONSERVATIVE_EV_NEGATIVE = "CONSERVATIVE_EV_NEGATIVE"
    ODDS_STALE = "ODDS_STALE"
    MARKET_INCOMPLETE = "MARKET_INCOMPLETE"
    UNCERTAINTY_TOO_HIGH = "UNCERTAINTY_TOO_HIGH"
    LOW_DATA_QUALITY = "LOW_DATA_QUALITY"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    EVENT_MAPPING_AMBIGUOUS = "EVENT_MAPPING_AMBIGUOUS"
    MODEL_NOT_VALIDATED = "MODEL_NOT_VALIDATED"
    OUTSIDE_WINDOW = "OUTSIDE_WINDOW"
    ODDS_OUT_OF_RANGE = "ODDS_OUT_OF_RANGE"
    NO_MODEL_AVAILABLE = "NO_MODEL_AVAILABLE"
    EVENT_NOT_SCHEDULED = "EVENT_NOT_SCHEDULED"
    MISSING_LINE = "MISSING_LINE"
    #: No defensible uncertainty method is available, so no conservative EV can
    #: be computed. Outside demo this blocks publication outright.
    UNCERTAINTY_UNAVAILABLE = "UNCERTAINTY_UNAVAILABLE"
    #: The provider answered, but not for the configured bookmaker.
    BOOKMAKER_COVERAGE_MISSING = "BOOKMAKER_COVERAGE_MISSING"


class ValidationStatus(StrEnum):
    """Lifecycle of a model. Only ``LIVE_ANALYSIS`` may be published live.

    Transitions are governed by docs/validation-protocol.md and the criteria are
    written *before* the final test set is opened.
    """

    BACKTEST_ONLY = "BACKTEST_ONLY"
    PAPER_VALIDATED = "PAPER_VALIDATED"
    LIVE_ANALYSIS = "LIVE_ANALYSIS"


class ProviderKind(StrEnum):
    ODDS = "odds"
    SPORTS_DATA = "sports_data"
    CONTEXT = "context"
    RESULTS = "results"
    NOTIFICATION = "notification"


class ProviderHealth(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


class ChallengeState(StrEnum):
    """State machine of the optional Challenge — Montante module."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    WAITING_FOR_CANDIDATE = "WAITING_FOR_CANDIDATE"
    AWAITING_USER_CONFIRMATION = "AWAITING_USER_CONFIRMATION"
    BET_RECORDED = "BET_RECORDED"
    AWAITING_RESULT = "AWAITING_RESULT"
    TARGET_REACHED = "TARGET_REACHED"
    STOPPED = "STOPPED"
    LOST = "LOST"
    CANCELLED = "CANCELLED"


class BetOutcome(StrEnum):
    """Settlement outcomes, including the bookmaker-specific partial cases."""

    WON = "won"
    LOST = "lost"
    VOID = "void"
    HALF_WON = "half_won"
    HALF_LOST = "half_lost"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"
    PENDING = "pending"
