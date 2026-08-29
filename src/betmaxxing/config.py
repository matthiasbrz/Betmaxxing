"""Centralised, versioned configuration.

Every threshold used by the eligibility engine lives here, is documented, and is
stamped into each scan result via :meth:`Settings.fingerprint` so a run can be
reproduced. Thresholds are PROVISIONAL until the pre-registered validation
protocol (docs/validation-protocol.md) has been executed.
"""

from __future__ import annotations

import hashlib
import json
import os
from enum import StrEnum
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The variable the adapter's parser is configured from. Named once, because the
#: activation guard has to read it *without* instantiating :class:`Settings` — see
#: :func:`configured_bookmakers`.
BOOKMAKERS_VARIABLE = "BETMAXXING_BOOKMAKERS"


def split_bookmakers(raw: str) -> list[str]:
    """The bookmaker keys a comma-separated setting names, exactly as written.

    No case folding and no aliasing: ``PINNACLE`` is not ``pinnacle``. The provider's
    keys are lowercase identifiers, and quietly accepting another spelling would make
    a configuration look correct that the parser will not match.
    """
    return [b.strip() for b in raw.split(",") if b.strip()]


def configured_bookmakers() -> list[str]:
    """The configured bookmaker keys, read from their own variable and nothing else.

    Deliberately **not** ``get_settings().bookmaker_list``. ``Settings`` is a pydantic
    settings model, so instantiating it populates every field from the environment —
    including ``the_odds_api_key``. The activation guard runs *before* the provider key
    may be read, and « before » has to mean it: this reads one variable by name, falls
    back to the model's declared default without instantiating it, and touches nothing
    else.
    """
    raw = os.environ.get(BOOKMAKERS_VARIABLE)
    if raw is None:
        raw = str(Settings.model_fields["bookmakers"].default)
    return split_bookmakers(raw)


class RunMode(StrEnum):
    """Execution mode. Only ``demo`` runs without any provider credential."""

    DEMO = "demo"
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE_ANALYSIS = "live_analysis"


class DevigMethod(StrEnum):
    """Method used to strip the bookmaker margin from a complete market."""

    MULTIPLICATIVE = "multiplicative"
    ADDITIVE = "additive"
    POWER = "power"
    SHIN = "shin"


# Bumped by hand whenever a threshold's *meaning* changes, not its value.
CONFIG_SCHEMA_VERSION = "1.0.0"


class Settings(BaseSettings):
    """Application settings, loaded from environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="BETMAXXING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # -- runtime ------------------------------------------------------------
    mode: RunMode = RunMode.DEMO
    display_timezone: str = "Europe/Paris"
    log_level: str = "INFO"
    demo_seed: int = 20260804

    # -- storage ------------------------------------------------------------
    database_url: str = "sqlite+pysqlite:///./betmaxxing.db"

    # -- scan window --------------------------------------------------------
    window_hours: float = Field(
        default=24.0,
        gt=0,
        description="Events starting in ]now, now + window_hours] are in scope.",
    )

    # -- eligibility thresholds (PROVISIONAL) -------------------------------
    min_ev: float = Field(
        default=0.03,
        description="Minimum central expected value, as a fraction (0.03 == +3%).",
    )
    min_conservative_ev: float = Field(
        default=0.0,
        description="Minimum EV recomputed at the lower bound of the probability interval.",
    )
    max_prob_half_width: float = Field(
        default=0.08,
        gt=0,
        description="Maximum half-width of the model probability interval.",
    )
    max_odds_age_seconds: int = Field(
        default=900, gt=0, description="An odds snapshot older than this is stale."
    )
    min_data_quality: float = Field(
        default=0.60, ge=0, le=1, description="Minimum composite data-quality score."
    )
    min_odds: float = Field(default=1.20, gt=1.0)
    max_odds: float = Field(default=8.0, gt=1.0)
    devig_method: DevigMethod = DevigMethod.SHIN
    prob_interval_z: float = Field(
        default=1.6448536269514722,
        gt=0,
        description="z-score for the probability interval (1.6449 == 90% two-sided).",
    )

    # -- staking ------------------------------------------------------------
    staking_enabled: bool = False
    bankroll: float = Field(default=0.0, ge=0)
    currency: str = "EUR"
    unit_pct_of_bankroll: float = Field(default=0.01, gt=0, le=0.1)
    kelly_fraction: float = Field(default=0.25, gt=0, le=1.0)
    max_stake_pct_of_bankroll: float = Field(default=0.01, gt=0, le=0.1)
    max_daily_exposure_pct: float = Field(default=0.05, gt=0, le=0.5)

    # -- challenge (opt-in, simulation only) --------------------------------
    challenge_enabled: bool = Field(
        default=False,
        description="Challenge — Montante. Off by default; mutating endpoints 404 when off.",
    )

    # -- providers ----------------------------------------------------------
    winamax_mode: str = "manual"
    odds_provider: str = "demo"
    #: Deprecated generic key. Prefer BETMAXXING_THE_ODDS_API_KEY.
    odds_api_key: str = ""
    odds_api_base_url: str = ""
    the_odds_api_key: str = ""
    the_odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    #: Comma-separated bookmaker keys, e.g. "winamax_fr".
    bookmakers: str = "winamax_fr"
    the_odds_api_regions: str = "eu,fr"
    the_odds_api_sport_keys: str = (
        "soccer_france_ligue_one,soccer_epl,soccer_spain_la_liga,tennis_atp_aus_open_singles"
    )
    #: Credit budgets. A request estimated above these is refused before it runs.
    provider_budget_per_scan: int = 50
    provider_budget_per_day: int = 450
    sportsdata_provider: str = "demo"
    sportsdata_api_key: str = ""
    provider_timeout_seconds: float = 10.0
    provider_max_retries: int = 3

    # -- notifications ------------------------------------------------------
    notifications_enabled: bool = False
    notification_channels: str = "console"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""
    quiet_hours_start: int = Field(default=23, ge=0, le=23)
    quiet_hours_end: int = Field(default=8, ge=0, le=23)

    # -- scheduler ----------------------------------------------------------
    scheduler_enabled: bool = False
    scan_times: str = "08:00,12:00,18:00"
    milestones_hours_before: str = "24,12,6,2,1,0.25"

    # -- llm ----------------------------------------------------------------
    llm_enabled: bool = False
    llm_provider: str = ""

    # -- api ----------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_token: str = ""
    cors_origins: str = "http://localhost:5173"

    @field_validator("max_odds")
    @classmethod
    def _max_above_min(cls, v: float, info: Any) -> float:
        min_odds = info.data.get("min_odds")
        if min_odds is not None and v <= min_odds:
            raise ValueError("max_odds must be greater than min_odds")
        return v

    # -- derived helpers ----------------------------------------------------
    @property
    def notification_channel_list(self) -> list[str]:
        return [c.strip() for c in self.notification_channels.split(",") if c.strip()]

    @property
    def scan_time_list(self) -> list[str]:
        return [t.strip() for t in self.scan_times.split(",") if t.strip()]

    @property
    def milestone_hours(self) -> list[float]:
        return [float(h.strip()) for h in self.milestones_hours_before.split(",") if h.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def bookmaker_list(self) -> list[str]:
        return split_bookmakers(self.bookmakers)

    @property
    def the_odds_api_sport_key_list(self) -> list[str]:
        return [k.strip() for k in self.the_odds_api_sport_keys.split(",") if k.strip()]

    @property
    def resolved_the_odds_api_key(self) -> str:
        """The Odds API key, honouring the deprecated generic variable.

        Returns the value only; callers must never log it. The deprecation is
        surfaced by :meth:`deprecation_warnings`, which names the variable but
        never its content.
        """
        return self.the_odds_api_key or self.odds_api_key

    def deprecation_warnings(self) -> list[str]:
        out: list[str] = []
        if not self.the_odds_api_key and self.odds_api_key:
            out.append(
                "BETMAXXING_ODDS_API_KEY est déprécié — utilisez "
                "BETMAXXING_THE_ODDS_API_KEY. La valeur actuelle est reprise "
                "temporairement."
            )
        return out

    @property
    def requires_real_providers(self) -> bool:
        """True for every mode that must refuse to run on synthetic data."""
        return self.mode in (RunMode.PAPER, RunMode.LIVE_ANALYSIS)

    def eligibility_thresholds(self) -> dict[str, Any]:
        """The exact threshold set applied to a scan, for audit and reproduction."""
        return {
            "min_ev": self.min_ev,
            "min_conservative_ev": self.min_conservative_ev,
            "max_prob_half_width": self.max_prob_half_width,
            "max_odds_age_seconds": self.max_odds_age_seconds,
            "min_data_quality": self.min_data_quality,
            "min_odds": self.min_odds,
            "max_odds": self.max_odds,
            "devig_method": str(self.devig_method),
            "prob_interval_z": self.prob_interval_z,
            "window_hours": self.window_hours,
        }

    def fingerprint(self) -> str:
        """Stable hash of the decision-relevant configuration."""
        payload = {"schema": CONFIG_SCHEMA_VERSION, **self.eligibility_thresholds()}
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def redacted(self) -> dict[str, Any]:
        """Full settings dump with every secret-bearing field masked."""
        secret_suffixes = ("_key", "_token", "_password", "_secret")
        out: dict[str, Any] = {}
        for name, value in self.model_dump().items():
            if name.endswith(secret_suffixes):
                out[name] = "***set***" if value else ""
            else:
                out[name] = value
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()


def reset_settings_cache() -> None:
    """Test hook — drops the cached singleton."""
    get_settings.cache_clear()
