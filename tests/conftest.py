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
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from betmaxxing.config import RunMode, Settings, reset_settings_cache
from betmaxxing.storage.db import create_all, get_engine, reset_engine

#: A fixed instant used wherever a test needs a deterministic "now".
FIXED_NOW = datetime(2026, 8, 4, 9, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Outbound network guard
# ---------------------------------------------------------------------------
#: Hosts a test may legitimately reach: the loopback interface, for the local
#: PostgreSQL cluster. AF_UNIX is allowed unconditionally — a domain socket is a
#: file on this machine and cannot leave it.
_ALLOWED_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0"})

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class OutboundNetworkBlocked(RuntimeError):
    """A test tried to open a socket to something that is not this machine."""


def _permitted(self: socket.socket, address: object) -> bool:
    if getattr(self, "family", None) == getattr(socket, "AF_UNIX", None):
        return True
    if isinstance(address, str | bytes):
        return True
    if isinstance(address, tuple) and address:
        return str(address[0]) in _ALLOWED_HOSTS
    return False


def _guarded_connect(self: socket.socket, address: object) -> object:
    if not _permitted(self, address):
        raise OutboundNetworkBlocked(
            f"refus de connexion sortante vers {address!r}. La suite ne joint jamais "
            "un fournisseur : utilisez httpx.MockTransport. Seuls AF_UNIX et la "
            "boucle locale (PostgreSQL de test) sont autorisés."
        )
    return _real_connect(self, address)  # type: ignore[arg-type]


def _guarded_connect_ex(self: socket.socket, address: object) -> object:
    if not _permitted(self, address):
        raise OutboundNetworkBlocked(f"refus de connexion sortante vers {address!r}.")
    return _real_connect_ex(self, address)  # type: ignore[arg-type]


@pytest.fixture(autouse=True, scope="session")
def _no_outbound_network() -> Iterator[None]:
    """Make "no test calls a provider" a property of the runner, not a habit.

    Every provider test already injects a fake transport. That is a convention,
    and a convention is one forgotten fixture away from a real, billed request
    to ``api.the-odds-api.com`` from someone's laptop — with a real key in the
    environment, during the very tranche that is preparing a *controlled*
    activation. This makes the failure mode impossible instead of unlikely.

    Subprocesses (the Alembic harness) are unaffected: they do not inherit a
    monkeypatched method, and they only ever touch SQLite files.
    """
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign, assignment]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign, assignment]
    try:
        yield
    finally:
        socket.socket.connect = _real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _real_connect_ex  # type: ignore[method-assign]


#: Set by CI (and by a developer running a local cluster) to a SQLAlchemy URL.
#: Unset means the PostgreSQL suites skip — they never silently pass.
POSTGRES_URL_VARIABLE = "BETMAXXING_TEST_POSTGRES_URL"

#: Settings read the ambient environment, so a real key exported in the operator's
#: shell silently becomes the value under test. Cleared for every test.
_AMBIENT_SECRETS = (
    "BETMAXXING_THE_ODDS_API_KEY",
    "BETMAXXING_ODDS_API_KEY",
    "BETMAXXING_SPORTSDATA_API_KEY",
    "BETMAXXING_ACTIVATION_RECEIPT_SECRET",
    "BETMAXXING_TELEGRAM_BOT_TOKEN",
    "BETMAXXING_SMTP_PASSWORD",
    "BETMAXXING_API_TOKEN",
)


@pytest.fixture(autouse=True)
def _no_ambient_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the operator's real credentials out of the suite entirely.

    ``Settings`` is a pydantic settings model, so any field not passed explicitly
    is filled from the environment. A developer with a real key exported — which
    is precisely the state during a controlled activation — therefore ran a
    different suite from CI: assertions comparing a synthetic key to
    ``resolved_the_odds_api_key`` failed, and pytest printed the *real* key into
    the diff of expected versus actual. That is a live credential in a terminal,
    a scrollback buffer and any captured log, produced by the test suite itself.

    Clearing these makes the suite depend only on what a test passes, so it
    behaves identically on a laptop with credentials and on a runner without
    them. Tests that need a key pass an explicit synthetic one; the activation
    harness has its own fixtures for the receipt secret.

    ``BETMAXXING_TEST_POSTGRES_URL`` is deliberately untouched: it is a local
    database address, not a credential, and the PostgreSQL suites must keep
    skipping loudly when it is absent rather than being silently neutered here.
    """
    for name in _AMBIENT_SECRETS:
        monkeypatch.delenv(name, raising=False)


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


# ---------------------------------------------------------------------------
# Activation harness
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_receipt_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the receipt directory at a clean per-test path, never at the cwd.

    ``DEFAULT_RECEIPT_DIR`` is ``.activation-receipts``, a **relative** path, so
    ``activation.receipt_dir()`` resolves it against the process's working directory
    whenever ``BETMAXXING_ACTIVATION_RECEIPTS`` is unset. That is the intended
    behaviour for an operator running the CLI inside a project, and this fixture does
    not change it — production keeps the relative default, and the test that pins that
    default deliberately declines this fixture.

    What it changes is the suites. ``build_activation_state`` calls
    ``unresolved_intents()``, and a single unresolved intent closes the qualification
    gate; so one stray ``.activation-receipts/<id>.intent`` left in a checkout — by a
    manual CLI run, a demo, an interrupted probe — silently turned green suites red,
    with the failure surfacing far from its cause. The septies re-audit reproduced
    exactly that: five tests across two suites, red with a foreign intent present and
    green without it.

    Deliberately **not** ``autouse``. A blanket fixture would also neuter the test
    that verifies the relative default, and a guard nobody can opt out of is a guard
    nobody can test. Suites opt in with ``pytest.mark.usefixtures``.

    Function-scoped, so every test gets its own directory and no ordering can leak
    state. The path is *not* created: an absent directory is what a clean installation
    looks like, and several suites assert on that boundary state. ``monkeypatch``
    restores the previous value exactly, including after a failure — teardown runs
    either way.
    """
    directory = tmp_path / "isolated-activation-receipts"
    monkeypatch.setenv("BETMAXXING_ACTIVATION_RECEIPTS", str(directory))
    return directory


#: These three live here rather than in a test module because four suites need
#: them, and pytest only discovers fixtures from conftest. The payloads and
#: argument builders they go with are in ``tests/helpers_activation.py``.
@pytest.fixture
def workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_settings: Settings,
    isolated_receipt_directory: Path,
) -> Path:
    """A throwaway receipt directory and a database, with no key configured.

    Depends on :func:`isolated_receipt_directory` so that the ordering is fixed
    rather than incidental: isolation runs first, this fixture then overrides the
    variable with its own path. A module applying both therefore gets ``workspace``'s
    directory deterministically, instead of whichever fixture pytest happened to
    instantiate last.
    """
    from helpers_activation import BOOKMAKER, FAKE_RECEIPT_SECRET

    monkeypatch.setenv("BETMAXXING_MODE", "paper")
    # The harness parses a paid response with the adapter's own parser, and that parser
    # keeps only the bookmakers `settings.bookmaker_list` names — not the one passed on
    # the command line. The two agreed by accident while `--bookmaker` and the shipped
    # default were both `winamax_fr`; under the protocol 8 manifest they do not, and a
    # mismatch turns a perfectly good response into `SCHEMA_MISMATCH`. Stated here so
    # the suites configure what an operator must also configure — see the runbook.
    monkeypatch.setenv("BETMAXXING_BOOKMAKERS", BOOKMAKER)
    monkeypatch.setenv("BETMAXXING_DATABASE_URL", db_settings.database_url)
    monkeypatch.setenv("BETMAXXING_NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("BETMAXXING_ACTIVATION_RECEIPTS", str(tmp_path / "receipts"))
    # Deterministic signing secret: no test depends on real randomness, and none
    # writes a secret into a directory a developer might later inspect by hand.
    monkeypatch.setenv("BETMAXXING_ACTIVATION_RECEIPT_SECRET", FAKE_RECEIPT_SECRET)
    monkeypatch.delenv("BETMAXXING_THE_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("BETMAXXING_ODDS_API_KEY", raising=False)
    reset_settings_cache()
    return tmp_path / "receipts"


@pytest.fixture
def keyed(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from helpers_activation import FAKE_KEY

    monkeypatch.setenv("BETMAXXING_THE_ODDS_API_KEY", FAKE_KEY)
    reset_settings_cache()
    return workspace


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from betmaxxing.providers.the_odds_api import activation
    from helpers_activation import NOW

    monkeypatch.setattr(activation, "_clock", lambda: NOW)


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
