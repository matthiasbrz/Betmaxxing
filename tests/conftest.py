"""Shared fixtures.

Three invariants the whole suite depends on:

* no test ever performs network I/O to a sports provider or sends a
  notification — the settings fixture forces ``notifications_enabled=False`` and
  demo providers never touch the network;
* each test gets its own SQLite file, so ordering cannot leak state;
* the PostgreSQL fixtures talk to a **local, ephemeral** database containing only
  test rows. That is a database connection, not a provider call.

Why a real PostgreSQL matters here
----------------------------------
``FOR UPDATE SKIP LOCKED``, ``UPDATE`` re-evaluating its ``WHERE`` clause after a
row lock, and ``READ COMMITTED`` snapshot behaviour have no SQLite equivalent.
A test that compiles the SQL, or mocks the driver, proves that we *wrote* the
statement — not that the engine gives us the guarantee we claim. Concurrency
claims about PostgreSQL are only made where a PostgreSQL test backs them.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from betmaxxing.config import RunMode, Settings, reset_settings_cache
from betmaxxing.storage.db import create_all, get_engine, reset_engine

#: A fixed instant used wherever a test needs a deterministic "now".
FIXED_NOW = datetime(2026, 8, 4, 9, 0, 0, tzinfo=UTC)

#: Set by CI (and by a developer running a local cluster) to a SQLAlchemy URL.
#: Unset means the PostgreSQL suites skip — they never silently pass.
POSTGRES_URL_VARIABLE = "BETMAXXING_TEST_POSTGRES_URL"


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
        challenge_enabled=True,
    )
    reset_engine()
    reset_settings_cache()


@pytest.fixture
def db_settings(settings: Settings) -> Settings:
    create_all(settings)
    return settings


@pytest.fixture
def postgres_url() -> str:
    url = os.environ.get(POSTGRES_URL_VARIABLE, "").strip()
    if not url:
        pytest.skip(
            f"{POSTGRES_URL_VARIABLE} is not set — the PostgreSQL concurrency suite "
            "needs a real cluster and must never be silently skipped in CI."
        )
    return url


@pytest.fixture
def pg_settings(postgres_url: str, request: pytest.FixtureRequest) -> Iterator[Settings]:
    """A pristine PostgreSQL schema for one test.

    ``DROP SCHEMA public CASCADE`` rather than a per-test database: creating a
    database per test serialises on the template and is an order of magnitude
    slower, and a dropped schema is just as isolated.
    """
    reset_engine()
    reset_settings_cache()
    settings = Settings(
        mode=RunMode.DEMO,
        database_url=postgres_url,
        notifications_enabled=False,
        staking_enabled=False,
        challenge_enabled=True,
        provider_budget_per_day=getattr(request, "param", 0) or 0,
    )
    engine = get_engine(settings)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
    create_all(settings)
    yield settings
    reset_engine()
    reset_settings_cache()


@pytest.fixture
def env_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Settings installed in the environment, for code paths calling get_settings()."""
    reset_engine()
    reset_settings_cache()
    monkeypatch.setenv("BETMAXXING_MODE", "demo")
    monkeypatch.setenv("BETMAXXING_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("BETMAXXING_NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("BETMAXXING_STAKING_ENABLED", "false")
    monkeypatch.setenv("BETMAXXING_CHALLENGE_ENABLED", "true")
    from betmaxxing.config import get_settings

    yield get_settings()
    reset_engine()
    reset_settings_cache()
