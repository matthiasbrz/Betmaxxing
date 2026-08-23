"""The suites read a receipt directory of their own, never the working directory.

Why this suite exists
---------------------
``DEFAULT_RECEIPT_DIR`` is ``.activation-receipts`` — a **relative** path. When
``BETMAXXING_ACTIVATION_RECEIPTS`` is unset, ``activation.receipt_dir()`` therefore
resolves it against whatever directory the process happens to be running in. That is
deliberate and stays: an operator running the CLI inside a project wants the receipts
next to the project, and this module has a test that pins exactly that.

The problem was never production. It was that seven test suites inherited the same
resolution without asking for it. ``build_activation_state`` calls
``unresolved_intents()``, and one unresolved intent is an evidence conflict that closes
the qualification gate — so a single stray ``.activation-receipts/<id>.intent`` left in
a checkout turned green suites red. The septies re-audit reproduced it: five tests
across ``test_qualification_v6_contract`` and ``test_provider_qualification``, red with
a foreign intent present, green without. Nothing in the failure output pointed at the
working directory, which is what made it expensive.

The fix is a fixture, ``isolated_receipt_directory``, applied by name to the seven
suites. This module is what keeps it applied, and what proves it does not overreach:
the last two tests here run **without** the fixture and check that the relative default
is still the relative default.

Everything is synthetic. No real secret, receipt or provider payload is read, and no
test here changes the working directory of the session — ``monkeypatch.chdir`` is
per-test and restored on teardown.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from betmaxxing.providers.the_odds_api import activation as act

#: The suites that resolve a receipt directory and must therefore be isolated from the
#: working directory. Two of them were red under a foreign intent; the other five were
#: green by accident of their own fixtures, and are pinned here so they stay that way.
ISOLATED_SUITES = (
    "test_qualification_v6_contract",
    "test_provider_qualification",
    "test_qualification_v5_contract",
    "test_qualification_v4_contract",
    "test_qualification_v2_contract",
    "test_activation_receipts",
    "test_activation_characterisation",
)

#: The two the re-audit actually caught, and the five tests that failed in them.
SUITES_THE_REAUDIT_CAUGHT = ("test_qualification_v6_contract", "test_provider_qualification")

VARIABLE = "BETMAXXING_ACTIVATION_RECEIPTS"

#: The value the restoration probe's child process starts from, and the value it must be
#: back to once the child has finished. A single constant feeds both the environment
#: handed to pytest and the assertion generated inside the child: two separate literals
#: could drift apart silently and leave the probe green while measuring nothing.
SENTINEL_BEFORE = "/sentinel/before"

REPOSITORY = Path(act.__file__).resolve().parents[4]


def plain_environment(**extra: str) -> dict[str, str]:
    """The parent's environment, with colour forced off in the child.

    The battery runs one pass under ``FORCE_COLOR=1``, and a subprocess inheriting it
    prints ``\\x1b[31m1 failed\\x1b[0m, \\x1b[32m1 passed\\x1b[0m`` — where the literal
    ``1 failed, 1 passed`` no longer occurs. Reading a child's summary is a behavioural
    assertion, so the child is pinned to plain text rather than the assertions being
    loosened to tolerate escapes.
    """
    environment = {**os.environ, **extra}
    environment.pop("FORCE_COLOR", None)
    environment["NO_COLOR"] = "1"
    return environment


def plant_foreign_intent(directory: Path) -> Path:
    """One unresolved intent, of the shape that closes the gate. Synthetic throughout."""
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / "dd44ee55ff6600a1.intent"
    path.write_text(
        json.dumps(
            {
                "attempt_id": "dd44ee55ff6600a1",
                "command": "core",
                "sport": "soccer_probe",
                "bookmaker": "probebook",
                "max_credits": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    return path


# ---------------------------------------------------------------------------
# The fixture does what it says
# ---------------------------------------------------------------------------
class TestTheFixtureIsolates:
    def test_the_variable_points_at_the_fixture_directory(
        self, isolated_receipt_directory: Path
    ) -> None:
        assert os.environ[VARIABLE] == str(isolated_receipt_directory)
        assert act.receipt_dir() == isolated_receipt_directory

    def test_the_directory_is_absent_until_something_creates_it(
        self, isolated_receipt_directory: Path
    ) -> None:
        """A clean installation, which is the state several suites assert on."""
        assert not isolated_receipt_directory.exists()

    def test_a_foreign_intent_in_the_working_directory_is_invisible(
        self, isolated_receipt_directory: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point, stated as one assertion.

        Red on 66d03bf: without the fixture the intent below is found, the gate closes,
        and every test that reads a qualification verdict in the module fails.
        """
        elsewhere = tmp_path / "cwd"
        elsewhere.mkdir()
        planted = plant_foreign_intent(elsewhere / act.DEFAULT_RECEIPT_DIR)
        monkeypatch.chdir(elsewhere)

        assert planted.exists(), "the probe must really have planted one"
        assert act.unresolved_intents() == []

    def test_two_different_working_directories_give_the_same_answer(
        self, isolated_receipt_directory: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answers = []
        for name in ("first", "second"):
            where = tmp_path / name
            where.mkdir()
            plant_foreign_intent(where / act.DEFAULT_RECEIPT_DIR)
            monkeypatch.chdir(where)
            answers.append((act.receipt_dir(), act.unresolved_intents()))
        assert answers[0] == answers[1]
        assert answers[0] == (isolated_receipt_directory, [])

    def test_each_test_receives_a_distinct_directory(
        self, isolated_receipt_directory: Path, request: pytest.FixtureRequest
    ) -> None:
        """Function-scoped: the path carries this test's name, so no two can collide."""
        seen = getattr(request.config, "_isolation_paths", None)
        if seen is None:
            seen = set()
            request.config._isolation_paths = seen  # type: ignore[attr-defined]
        assert str(isolated_receipt_directory) not in seen
        seen.add(str(isolated_receipt_directory))

    def test_a_second_test_also_receives_a_distinct_directory(
        self, isolated_receipt_directory: Path, request: pytest.FixtureRequest
    ) -> None:
        """The companion of the test above; together they prove distinctness."""
        seen = getattr(request.config, "_isolation_paths", None)
        if seen is None:
            seen = set()
            request.config._isolation_paths = seen  # type: ignore[attr-defined]
        assert str(isolated_receipt_directory) not in seen
        seen.add(str(isolated_receipt_directory))


# ---------------------------------------------------------------------------
# The environment goes back exactly as it was
# ---------------------------------------------------------------------------
class TestTheEnvironmentIsRestored:
    """`monkeypatch` restores on teardown, including after a failure. Proven, not assumed."""

    @staticmethod
    def _run(body: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
        """Run a throwaway module against the *real* fixture, outside the repository.

        Conftest discovery follows the test file's own ancestry, so a module in
        ``tmp_path`` would never see ``tests/conftest.py``. The local conftest below
        re-exports the genuine fixture rather than redefining it — redefining it would
        make this class test a copy, which proves nothing about the one in use.

        The starting value is placed in the child's environment *before* pytest starts.
        Setting it inside the child with an ``autouse`` fixture would look equivalent and
        is not: that fixture re-establishes the value at the setup of every test, the
        one checking it came back included, so the check would pass whether or not the
        fixture under test restores anything — and its own ``monkeypatch`` teardown would
        overwrite the leak besides, erasing the very evidence being sought. Only a value
        pre-set in the environment lets the second test observe the first test's teardown.
        """
        (tmp_path / "conftest.py").write_text(
            # Loaded by path under a distinct module name: the local file is itself
            # called `conftest`, so a plain `from conftest import ...` would import
            # itself. This binds the genuine fixture object, not a copy of it.
            "import importlib.util, sys\n"
            f"sys.path.insert(0, {str(REPOSITORY / 'tests')!r})\n"
            f"_spec = importlib.util.spec_from_file_location("
            f"'repository_conftest', {str(REPOSITORY / 'tests' / 'conftest.py')!r})\n"
            "_module = importlib.util.module_from_spec(_spec)\n"
            "_spec.loader.exec_module(_module)\n"
            "isolated_receipt_directory = _module.isolated_receipt_directory\n",
            encoding="utf-8",
        )
        module = tmp_path / "test_restoration_probe.py"
        module.write_text(body, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "pytest", str(module), "-q", "-p", "no:cacheprovider"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=plain_environment(
                PYTHONPATH=str(REPOSITORY / "src"), **{VARIABLE: SENTINEL_BEFORE}
            ),
            check=False,
        )

    #: The first test takes the real fixture and checks the variable moved off the
    #: sentinel; the second takes no fixture touching the variable at all, so it reads
    #: whatever the first test's teardown left behind. Both the name and the sentinel are
    #: interpolated from this module's constants — the child cannot disagree with the
    #: environment it was handed.
    PROBE = """
import os

VARIABLE = {variable!r}
BEFORE = {before!r}


def test_{outcome}(isolated_receipt_directory):
    assert os.environ[VARIABLE] != BEFORE
    {tail}


def test_zz_the_variable_came_back():
    assert os.environ[VARIABLE] == BEFORE
"""

    @classmethod
    def _probe(cls, *, outcome: str, tail: str) -> str:
        return cls.PROBE.format(
            variable=VARIABLE, before=SENTINEL_BEFORE, outcome=outcome, tail=tail
        )

    def test_the_previous_value_returns_after_a_passing_test(self, tmp_path: Path) -> None:
        done = self._run(self._probe(outcome="passes", tail="assert True"), tmp_path)
        assert "2 passed" in done.stdout, done.stdout + done.stderr

    def test_the_previous_value_returns_after_a_failing_test(self, tmp_path: Path) -> None:
        done = self._run(
            self._probe(outcome="fails", tail='raise AssertionError("deliberate")'),
            tmp_path,
        )
        assert "1 failed, 1 passed" in done.stdout, done.stdout + done.stderr


# ---------------------------------------------------------------------------
# Every suite that needs the fixture declares it
# ---------------------------------------------------------------------------
class TestTheSuitesDeclareTheFixture:
    @pytest.mark.parametrize("suite", ISOLATED_SUITES)
    def test_the_suite_applies_the_isolation_fixture(self, suite: str) -> None:
        """Structural, and therefore cheap: removing a marker fails here immediately."""
        text = (REPOSITORY / "tests" / f"{suite}.py").read_text(encoding="utf-8")
        assert "pytestmark" in text, suite
        assert "isolated_receipt_directory" in text, suite

    def test_the_fixture_is_not_autouse(self) -> None:
        """Opting in is the design: a blanket fixture could not be tested from outside."""
        text = (REPOSITORY / "tests" / "conftest.py").read_text(encoding="utf-8")
        block = text.split("def isolated_receipt_directory", 1)[0]
        declaration = block.rsplit("@pytest.fixture", 1)[1]
        assert "autouse" not in declaration


# ---------------------------------------------------------------------------
# Under a foreign intent, the suites stay green
# ---------------------------------------------------------------------------
@pytest.mark.slow
class TestTheSuitesSurviveAForeignIntent:
    """The end-to-end statement, run the only way it can honestly be run.

    A subprocess with its own working directory, containing the very
    ``.activation-receipts`` that made these suites red. In-process assertions cannot
    show this: the suites must actually execute against a polluted cwd.
    """

    @staticmethod
    def _shadow(cwd: Path) -> Path:
        """A working directory that looks like the repository, minus its receipts.

        Some of these suites read other paths relative to the working directory —
        ``docs/provider-validation-protocol.md`` among them. Running them from a bare
        temporary directory would fail on *that* dependency and tell us nothing about
        the one under test, so every top-level entry is symlinked through and only
        ``.activation-receipts`` is replaced by the hostile one.
        """
        shadow = cwd / "shadow"
        shadow.mkdir()
        for entry in REPOSITORY.iterdir():
            if entry.name == act.DEFAULT_RECEIPT_DIR:
                continue
            (shadow / entry.name).symlink_to(entry)
        plant_foreign_intent(shadow / act.DEFAULT_RECEIPT_DIR)
        return shadow

    def _run_suites(self, names: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
        shadow = self._shadow(cwd)
        targets = [str(REPOSITORY / "tests" / f"{name}.py") for name in names]
        environment = plain_environment(PYTHONPATH=str(REPOSITORY / "src"))
        environment.pop(VARIABLE, None)
        return subprocess.run(
            [sys.executable, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider", "--tb=line"],
            capture_output=True,
            text=True,
            cwd=str(shadow),
            env=environment,
            check=False,
        )

    def test_the_two_suites_the_reaudit_caught_stay_green(self, tmp_path: Path) -> None:
        done = self._run_suites(SUITES_THE_REAUDIT_CAUGHT, tmp_path)
        assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]
        assert "failed" not in done.stdout, done.stdout[-4000:]

    def test_all_seven_suites_stay_green(self, tmp_path: Path) -> None:
        done = self._run_suites(ISOLATED_SUITES, tmp_path)
        assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]
        assert "failed" not in done.stdout, done.stdout[-4000:]

    def test_the_suites_leave_no_receipt_directory_in_the_repository(self, tmp_path: Path) -> None:
        before = (REPOSITORY / act.DEFAULT_RECEIPT_DIR).exists()
        self._run_suites(SUITES_THE_REAUDIT_CAUGHT, tmp_path)
        assert (REPOSITORY / act.DEFAULT_RECEIPT_DIR).exists() is before


# ---------------------------------------------------------------------------
# And the relative default is still the relative default
# ---------------------------------------------------------------------------
class TestTheDefaultIsUnchanged:
    """No fixture is applied in this class — that is the point of it.

    If ``isolated_receipt_directory`` were ``autouse``, these two tests would silently
    stop testing anything, which is precisely why it is not.
    """

    def test_the_default_is_still_relative(self) -> None:
        assert act.DEFAULT_RECEIPT_DIR == ".activation-receipts"
        assert not Path(act.DEFAULT_RECEIPT_DIR).is_absolute()

    def test_an_unset_variable_resolves_against_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production behaviour, pinned: no variable means « next to where you are »."""
        monkeypatch.delenv(VARIABLE, raising=False)
        monkeypatch.chdir(tmp_path)
        resolved = act.receipt_dir()
        assert resolved == Path(act.DEFAULT_RECEIPT_DIR)
        assert resolved.resolve() == (tmp_path / act.DEFAULT_RECEIPT_DIR).resolve()

    def test_an_unset_variable_really_reads_that_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not just the path — the intent planted there is genuinely found."""
        monkeypatch.delenv(VARIABLE, raising=False)
        monkeypatch.chdir(tmp_path)
        plant_foreign_intent(tmp_path / act.DEFAULT_RECEIPT_DIR)
        found = act.unresolved_intents()
        assert [entry.get("attempt_id") for entry in found] == ["dd44ee55ff6600a1"]

    def test_an_explicit_variable_still_wins_over_the_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        elsewhere = tmp_path / "explicit"
        monkeypatch.setenv(VARIABLE, str(elsewhere))
        monkeypatch.chdir(tmp_path)
        assert act.receipt_dir() == elsewhere
