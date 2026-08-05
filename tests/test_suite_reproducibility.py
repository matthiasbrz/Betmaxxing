"""The suite must be the same suite however it is invoked.

CI runs the ``pytest`` console script. Developers usually run ``python -m
pytest``. The two are *not* equivalent: ``python -m pytest`` prepends the current
directory to ``sys.path``, so a test module importing another test module by
package path happens to work. The console script does not, and collection dies.

That is not a cosmetic difference — it means CI was executing a different (and
in fact empty) suite from the one that was reported as green.

The static guard below is the real fix's contract: shared factories live in
``tests/conftest.py`` (or an explicitly importable helper), never in a sibling
test module.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent

#: Collection of the whole suite twice is slow but bounded; it is the only way
#: to prove the two invocations agree.
COLLECT_ARGS = ["--collect-only", "-q", "-p", "no:cacheprovider"]


def _collect(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=_clean_env(),
    )


def _clean_env() -> dict[str, str]:
    import os

    # Drop anything that could make the two runs differ for reasons unrelated to
    # the invocation itself.
    return {k: v for k, v in os.environ.items() if not k.startswith("BETMAXXING_")}


def _collected(output: str) -> dict[str, int]:
    """Parse ``--collect-only -q``: one ``path: count`` line per test module."""
    collected: dict[str, int] = {}
    for line in output.splitlines():
        path, separator, count = line.rpartition(": ")
        if separator and count.strip().isdigit() and path.endswith(".py"):
            collected[path.strip()] = int(count)
    return collected


def _test_modules() -> list[Path]:
    return sorted(TESTS_DIR.glob("test_*.py"))


class TestNoTestModuleImportsAnother:
    """A test module importing a sibling is what broke the console script."""

    @pytest.mark.parametrize("module", _test_modules(), ids=lambda p: p.name)
    def test_module_does_not_import_a_sibling_test_module(self, module: Path) -> None:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tests":
                offenders.append(f"from {node.module} import ...")
            if isinstance(node, ast.Import):
                offenders.extend(
                    f"import {alias.name}"
                    for alias in node.names
                    if alias.name.split(".")[0] == "tests"
                )
        assert not offenders, (
            f"{module.name} imports another test module ({'; '.join(offenders)}). "
            "Move the shared helper into tests/conftest.py — the `pytest` console "
            "script cannot resolve the `tests` package."
        )


@pytest.fixture(scope="module")
def module_collect() -> subprocess.CompletedProcess[str]:
    return _collect([sys.executable, "-m", "pytest", *COLLECT_ARGS])


@pytest.fixture(scope="module")
def script_collect() -> subprocess.CompletedProcess[str]:
    executable = shutil.which("pytest")
    if executable is None:  # pragma: no cover - dev environments always have it
        pytest.skip("the pytest console script is not installed")
    return _collect([executable, *COLLECT_ARGS])


@pytest.mark.slow
class TestBothInvocationsCollectTheSameSuite:
    """Runs the collector in a subprocess; recursion is impossible because
    ``--collect-only`` never executes a test body."""

    def test_the_console_script_collects_without_error(
        self, script_collect: subprocess.CompletedProcess[str]
    ) -> None:
        assert script_collect.returncode == 0, (
            "`pytest` (the command CI runs) failed during collection:\n"
            f"{script_collect.stdout}\n{script_collect.stderr}"
        )

    def test_python_m_pytest_collects_without_error(
        self, module_collect: subprocess.CompletedProcess[str]
    ) -> None:
        assert module_collect.returncode == 0, module_collect.stdout

    def test_both_invocations_collect_the_same_modules(
        self,
        script_collect: subprocess.CompletedProcess[str],
        module_collect: subprocess.CompletedProcess[str],
    ) -> None:
        script_modules = _collected(script_collect.stdout)
        module_modules = _collected(module_collect.stdout)
        assert script_modules, "the console script collected nothing"
        assert script_modules == module_modules

    def test_both_invocations_collect_the_same_number_of_tests(
        self,
        script_collect: subprocess.CompletedProcess[str],
        module_collect: subprocess.CompletedProcess[str],
    ) -> None:
        script_total = sum(_collected(script_collect.stdout).values())
        module_total = sum(_collected(module_collect.stdout).values())
        assert script_total > 0
        assert script_total == module_total
