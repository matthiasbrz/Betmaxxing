"""The deterministic demo fixture set.

Everything in this module is **synthetic**. It exists so the whole pipeline can
be exercised — and its arithmetic verified — without a single API key, and so the
acceptance test "demo mode is deterministic" is meaningful.

Two rules keep it honest:

* every object produced here carries ``provider="demo"`` and
  ``bookmaker="DEMO_BOOK"``, so synthetic prices can never be mistaken for real
  ones anywhere downstream;
* the fixtures are hand-written constants, not random draws, so two runs at the
  same instant produce byte-identical decisions.

Event start times are expressed as offsets from the scan instant so the window
logic always has something to chew on. The scenario deliberately includes cases
that must be *rejected* (outside the window, incomplete book, stale price,
efficient market), because a demo that only produces winners proves nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from betmaxxing.domain.enums import EventStatus, MarketType, Period, Sport
from betmaxxing.domain.ids import participant_id
from betmaxxing.domain.models import CanonicalEvent, OddsSnapshot, Participant, Selection
from betmaxxing.models_ml.football import FootballInputs, TeamStrength
from betmaxxing.models_ml.tennis import TennisInputs

DEMO_PROVIDER = "demo"
DEMO_BOOKMAKER = "DEMO_BOOK"


@dataclass(frozen=True, slots=True)
class DemoMarket:
    """One market of the demo book: selections, prices, and price age."""

    market: MarketType
    period: Period
    line: Decimal | None
    #: (code, label, decimal odds)
    prices: tuple[tuple[str, str, float], ...]
    #: How old the observation is at scan time.
    age_seconds: int = 60


@dataclass(frozen=True, slots=True)
class DemoFixture:
    """A synthetic event plus its book and its model inputs."""

    key: str
    sport: Sport
    competition: str
    stage: str
    home_name: str
    away_name: str
    hours_from_now: float
    markets: tuple[DemoMarket, ...]
    surface: str | None = None
    sets_to_win: int | None = None
    status: EventStatus = EventStatus.SCHEDULED
    mapping_ambiguous: bool = False
    football: FootballInputs | None = None
    tennis: TennisInputs | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Football fixtures
# ---------------------------------------------------------------------------

_FOOTBALL: tuple[DemoFixture, ...] = (
    DemoFixture(
        key="fb-value-home",
        sport=Sport.FOOTBALL,
        competition="Ligue 1",
        stage="J3",
        home_name="Olympique Lyonnais",
        away_name="Stade Rennais",
        hours_from_now=6.0,
        football=FootballInputs(
            home=TeamStrength(attack=1.38, defence=0.86, matches_observed=168),
            away=TeamStrength(attack=0.96, defence=1.06, matches_observed=171),
            league_mean_goals=1.36,
            home_advantage=1.22,
            rho=-0.045,
            feature_completeness=1.0,
        ),
        markets=(
            DemoMarket(
                market=MarketType.MATCH_RESULT_1X2,
                period=Period.FULL_TIME,
                line=None,
                prices=(
                    ("home", "Olympique Lyonnais", 1.63),
                    ("draw", "Match nul", 4.20),
                    ("away", "Stade Rennais", 5.00),
                ),
            ),
            DemoMarket(
                market=MarketType.TOTAL_GOALS,
                period=Period.FULL_TIME,
                line=Decimal("2.5"),
                prices=(("over", "Plus de 2,5 buts", 1.48), ("under", "Moins de 2,5 buts", 2.67)),
            ),
            DemoMarket(
                market=MarketType.DOUBLE_CHANCE,
                period=Period.FULL_TIME,
                line=None,
                prices=(
                    ("home_or_draw", "1X", 1.22),
                    ("home_or_away", "12", 1.25),
                    ("draw_or_away", "X2", 2.62),
                ),
            ),
            DemoMarket(
                market=MarketType.MATCH_RESULT_1X2,
                period=Period.FIRST_HALF,
                line=None,
                prices=(
                    ("home", "Olympique Lyonnais (MT)", 2.04),
                    ("draw", "Match nul (MT)", 2.78),
                    ("away", "Stade Rennais (MT)", 5.30),
                ),
            ),
        ),
    ),
    DemoFixture(
        key="fb-efficient",
        sport=Sport.FOOTBALL,
        competition="LaLiga",
        stage="J4",
        home_name="Real Sociedad",
        away_name="Getafe CF",
        hours_from_now=20.0,
        football=FootballInputs(
            home=TeamStrength(attack=1.12, defence=0.94, matches_observed=180),
            away=TeamStrength(attack=0.88, defence=0.92, matches_observed=180),
            league_mean_goals=1.30,
            home_advantage=1.18,
            rho=-0.05,
            feature_completeness=1.0,
        ),
        markets=(
            DemoMarket(
                market=MarketType.MATCH_RESULT_1X2,
                period=Period.FULL_TIME,
                line=None,
                prices=(
                    ("home", "Real Sociedad", 1.96),
                    ("draw", "Match nul", 3.60),
                    ("away", "Getafe CF", 3.75),
                ),
            ),
            DemoMarket(
                market=MarketType.DRAW_NO_BET,
                period=Period.FULL_TIME,
                line=None,
                prices=(("home", "Real Sociedad (RSN)", 1.46), ("away", "Getafe CF (RSN)", 2.80)),
            ),
        ),
    ),
    DemoFixture(
        key="fb-outside-window",
        sport=Sport.FOOTBALL,
        competition="Serie A",
        stage="J3",
        home_name="Hellas Verona",
        away_name="Empoli",
        hours_from_now=31.0,
        football=FootballInputs(
            home=TeamStrength(attack=0.92, defence=1.10, matches_observed=160),
            away=TeamStrength(attack=0.85, defence=1.05, matches_observed=160),
        ),
        markets=(
            DemoMarket(
                market=MarketType.MATCH_RESULT_1X2,
                period=Period.FULL_TIME,
                line=None,
                prices=(
                    ("home", "Hellas Verona", 2.35),
                    ("draw", "Match nul", 3.30),
                    ("away", "Empoli", 3.20),
                ),
            ),
        ),
    ),
    DemoFixture(
        key="fb-incomplete-book",
        sport=Sport.FOOTBALL,
        competition="Bundesliga",
        stage="J2",
        home_name="VfB Stuttgart",
        away_name="FC Augsburg",
        hours_from_now=9.0,
        football=FootballInputs(
            home=TeamStrength(attack=1.25, defence=0.95, matches_observed=170),
            away=TeamStrength(attack=0.90, defence=1.12, matches_observed=170),
        ),
        markets=(
            # Only two of the three 1X2 outcomes are priced: the book cannot be
            # de-vigged, so every selection in it must be rejected.
            DemoMarket(
                market=MarketType.MATCH_RESULT_1X2,
                period=Period.FULL_TIME,
                line=None,
                prices=(("home", "VfB Stuttgart", 1.72), ("away", "FC Augsburg", 4.60)),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Tennis fixtures
# ---------------------------------------------------------------------------

_TENNIS: tuple[DemoFixture, ...] = (
    DemoFixture(
        key="tn-value-underdog",
        sport=Sport.TENNIS,
        competition="ATP Masters 1000 Montreal",
        stage="R64",
        home_name="Alejandro Tabilo",
        away_name="Rafael Jodar",
        hours_from_now=3.0,
        surface="hard",
        sets_to_win=2,
        tennis=TennisInputs(
            elo_home=1862.0,
            elo_away=1848.0,
            elo_home_surface=1871.0,
            elo_away_surface=1790.0,
            matches_home=143,
            matches_away=118,
            surface="hard",
            sets_to_win=2,
            home_serves_first=True,
            feature_completeness=1.0,
            notes=(
                "Elo dur calculé sur 143 et 118 matchs observés",
                "Format best-of-3, tie-break dans chaque set",
            ),
        ),
        markets=(
            DemoMarket(
                market=MarketType.MATCH_WINNER,
                period=Period.FULL_TIME,
                line=None,
                prices=(("home", "Alejandro Tabilo", 1.76), ("away", "Rafael Jodar", 2.07)),
            ),
            DemoMarket(
                market=MarketType.TOTAL_GAMES,
                period=Period.FULL_TIME,
                line=Decimal("22.5"),
                prices=(("over", "Plus de 22,5 jeux", 1.72), ("under", "Moins de 22,5 jeux", 2.13)),
            ),
            DemoMarket(
                market=MarketType.PLAYER_WINS_A_SET,
                period=Period.FULL_TIME,
                line=None,
                prices=(
                    ("home", "Tabilo gagne au moins 1 set", 1.28),
                    ("away", "Jodar gagne au moins 1 set", 1.42),
                ),
            ),
        ),
    ),
    DemoFixture(
        key="tn-stale-odds",
        sport=Sport.TENNIS,
        competition="ATP 500 Washington",
        stage="R32",
        home_name="Adrian Mannarino",
        away_name="Learner Tien",
        hours_from_now=10.0,
        surface="hard",
        sets_to_win=2,
        tennis=TennisInputs(
            elo_home=1862.0,
            elo_away=1648.0,
            elo_home_surface=1862.0,
            elo_away_surface=1648.0,
            matches_home=118,
            matches_away=162,
            surface="hard",
            sets_to_win=2,
            feature_completeness=1.0,
        ),
        markets=(
            # Observed over an hour ago: must be rejected as ODDS_STALE whatever
            # the edge looks like.
            DemoMarket(
                market=MarketType.MATCH_WINNER,
                period=Period.FULL_TIME,
                line=None,
                prices=(("home", "Adrian Mannarino", 1.36), ("away", "Learner Tien", 3.55)),
                age_seconds=5400,
            ),
        ),
    ),
    DemoFixture(
        key="tn-ambiguous-mapping",
        sport=Sport.TENNIS,
        competition="WTA 1000 Montreal",
        stage="R64",
        home_name="Renata Zarazua",
        away_name="Daria Vidmanova",
        hours_from_now=14.0,
        surface="hard",
        sets_to_win=2,
        mapping_ambiguous=True,
        tennis=TennisInputs(
            elo_home=1720.0,
            elo_away=1690.0,
            matches_home=95,
            matches_away=61,
            surface="hard",
            sets_to_win=2,
            feature_completeness=0.7,
        ),
        markets=(
            DemoMarket(
                market=MarketType.MATCH_WINNER,
                period=Period.FULL_TIME,
                line=None,
                prices=(("home", "Renata Zarazua", 2.22), ("away", "Daria Vidmanova", 1.72)),
            ),
        ),
    ),
)


ALL_FIXTURES: tuple[DemoFixture, ...] = _FOOTBALL + _TENNIS


def build_event(fixture: DemoFixture, now: datetime) -> CanonicalEvent:
    """Materialise a fixture as a canonical event anchored on ``now``."""
    start = now + timedelta(hours=fixture.hours_from_now)
    sport = str(fixture.sport)
    home = Participant(
        canonical_id=participant_id(sport, fixture.home_name),
        name=fixture.home_name,
        source_ids={DEMO_PROVIDER: f"{fixture.key}-home"},
    )
    away = Participant(
        canonical_id=participant_id(sport, fixture.away_name),
        name=fixture.away_name,
        source_ids={DEMO_PROVIDER: f"{fixture.key}-away"},
    )
    return CanonicalEvent(
        # A stable, human-traceable id for the fixture. The acquisition service
        # re-resolves it onto a real internal id via the identity service.
        internal_id=f"demo-{fixture.key}",
        sport=fixture.sport,
        competition=fixture.competition,
        stage=fixture.stage,
        surface=fixture.surface,
        sets_to_win=fixture.sets_to_win,
        home=home,
        away=away,
        start_time_utc=start,
        status=fixture.status,
        source_ids={DEMO_PROVIDER: fixture.key},
        mapping_ambiguous=fixture.mapping_ambiguous,
    )


def build_snapshots(
    fixture: DemoFixture, event: CanonicalEvent, now: datetime
) -> list[OddsSnapshot]:
    """Materialise the fixture's book as immutable snapshots."""
    out: list[OddsSnapshot] = []
    for market in fixture.markets:
        observed = now - timedelta(seconds=market.age_seconds)
        for code, label, odds in market.prices:
            selection = Selection(
                market=market.market,
                period=market.period,
                code=code,
                label=label,
                line=market.line,
            )
            out.append(
                OddsSnapshot(
                    provider=DEMO_PROVIDER,
                    bookmaker=DEMO_BOOKMAKER,
                    event_internal_id=event.internal_id,
                    event_source_id=fixture.key,
                    selection=selection,
                    decimal_odds=odds,
                    currency="EUR",
                    event_status=fixture.status,
                    provider_updated_at=observed,
                    observed_at=observed,
                    received_at=now,
                    source_meta={"scenario": fixture.key, "synthetic": "true"},
                )
            )
    return out


def football_inputs(now: datetime) -> dict[str, FootballInputs]:
    """Keyed by fixture key — the provider's own event id.

    Deliberately not keyed by the canonical event id: identity resolution
    reassigns that, and a model whose inputs vanish after remapping would report
    NO_MODEL_AVAILABLE for everything.
    """
    del now
    return {f.key: f.football for f in ALL_FIXTURES if f.football is not None}


def tennis_inputs(now: datetime) -> dict[str, TennisInputs]:
    """Keyed by fixture key. See :func:`football_inputs`."""
    del now
    return {f.key: f.tennis for f in ALL_FIXTURES if f.tennis is not None}
