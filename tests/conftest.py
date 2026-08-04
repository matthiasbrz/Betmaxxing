"""Shared fixtures.

Two invariants the whole suite depends on:

* no test ever performs network I/O or sends a notification — the settings
  fixture forces ``notifications_enabled=False`` and demo providers never touch
  the network;
* each test gets its own SQLite file, so ordering cannot leak state.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from betmaxxing.config import RunMode, Settings, reset_settings_cache
from betmaxxing.storage.db import create_all, reset_engine

#: A fixed instant used wherever a test needs a deterministic "now".
FIXED_NOW = datetime(2026, 8, 4, 9, 0, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def settings(tmp_path: Path) -> Iterator[Settings]:
    """Demo-mode settings backed by a per-test SQLite file."""
    reset_engine()
    reset_settings_cache()
    yield Settings(
        mode=RunMode.DEMO,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        notifications_enabled=False,
        staking_enabled=False,
    )
    reset_engine()
    reset_settings_cache()


@pytest.fixture
def db_settings(settings: Settings) -> Settings:
    create_all(settings)
    return settings


@pytest.fixture
def env_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Settings installed in the environment, for code paths calling get_settings()."""
    reset_engine()
    reset_settings_cache()
    monkeypatch.setenv("BETMAXXING_MODE", "demo")
    monkeypatch.setenv("BETMAXXING_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("BETMAXXING_NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("BETMAXXING_STAKING_ENABLED", "false")
    from betmaxxing.config import get_settings

    yield get_settings()
    reset_engine()
    reset_settings_cache()
