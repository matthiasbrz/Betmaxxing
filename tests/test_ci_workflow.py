"""Static checks on the CI workflow itself.

A guard that cannot observe what it claims to observe is worse than no guard:
it produces a green tick, or a red one, for reasons unrelated to the property it
names. Two steps in `ci.yml` were in that state, and neither could have been
caught by running the test suite — the defect lives in the shell around it.

Both were invisible for the same structural reason: the step that runs the
suite failed first, so every step after it was `skipped`, and a skipped step
reports nothing at all. They surfaced only when the suite finally passed.

These tests read the workflow as text. That is deliberate: parsing it as YAML
and inspecting `jobs.quality.steps[*].run` would assert on the same strings with
more machinery, and the properties at stake are lexical.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def step_body(name: str) -> str:
    """Return the `run:` block of the named step, comments excluded.

    Comments are stripped so a rule can be *described* in a comment without the
    description satisfying the rule — which is exactly how the smoke-test guard
    came to match its own explanatory prose.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index(f"- name: {name}")
    following = text.find("\n      - name: ", start + 1)
    block = text[start : following if following != -1 else len(text)]
    return "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))


class TestTheWorkflowExists:
    def test_the_ci_workflow_is_tracked(self) -> None:
        assert WORKFLOW.is_file()


class TestThePostgresGuardCanSeeItsEvidence:
    """It greps pytest's summary counts, so it must not suppress them."""

    NAME = "The PostgreSQL concurrency suite actually ran"

    def test_it_does_not_pass_quiet_to_pytest(self) -> None:
        """`-q` prints progress dots and no counts, so both greps go blind."""
        body = step_body(self.NAME)
        assert re.search(r"^\s*pytest\b.*\s-q\b", body, re.MULTILINE) is None, (
            "-q suppresses the summary line this step greps for"
        )

    def test_the_skip_grep_is_not_anchored_to_the_line_start(self) -> None:
        """pytest writes `N skipped, M deselected …`, never at column zero."""
        body = step_body(self.NAME)
        assert "^[0-9]+ skipped" not in body, (
            "an anchored skip pattern matches no pytest summary, passing or skipped"
        )
        assert re.search(r"grep\s+-qE\s+\"\[0-9\]\+ skipped\"", body) is not None

    def test_it_still_fails_when_the_suite_is_skipped(self) -> None:
        """The point of the step: a skipped suite must be an error, not silence."""
        body = step_body(self.NAME)
        assert "skipped" in body
        assert "exit 1" in body

    def test_it_still_requires_passing_tests(self) -> None:
        assert re.search(r"grep\s+-qE\s+\"\[0-9\]\+ passed\"", step_body(self.NAME)) is not None

    def test_pytest_failure_is_not_swallowed_by_the_pipe(self) -> None:
        """`tee` exits 0, so without pipefail only the greps decide the step."""
        body = step_body(self.NAME)
        assert "| tee" in body
        assert "set -o pipefail" in body

    def test_warnings_stay_fatal_and_the_marker_stays(self) -> None:
        body = step_body(self.NAME)
        assert "-W error" in body
        assert "-m postgres" in body


class TestTheCollectionComparisonCanFail:
    """It compared `tail -1` of two collections: two empty strings, always equal."""

    NAME = "The two pytest invocations collect the same suite"

    def test_it_does_not_compare_the_last_line_of_the_output(self) -> None:
        assert "tail -1" not in step_body(self.NAME), (
            "`--collect-only -q` ends with a blank line, so tail -1 compares nothing"
        )

    def test_it_compares_a_non_zero_count(self) -> None:
        body = step_body(self.NAME)
        assert 'test "$script_count" -gt 0' in body, "an empty collection must fail too"
        assert 'test "$script_count" = "$module_count"' in body

    def test_it_still_exercises_both_invocations(self) -> None:
        body = step_body(self.NAME)
        assert "count pytest" in body
        assert "count python -m pytest" in body


class TestTheGuardsThatMustNotBeRelaxed:
    """Cheap insurance that a future green was not bought by loosening these."""

    @pytest.mark.parametrize(
        "fragment",
        [
            "ruff check .",
            "ruff format --check .",
            "mypy",
            "pytest -W error --cov=betmaxxing",
            "alembic check",
            "python -m betmaxxing.security.secret_hygiene",
        ],
    )
    def test_the_workflow_still_runs(self, fragment: str) -> None:
        assert fragment in WORKFLOW.read_text(encoding="utf-8")

    def test_the_credit_consuming_smoke_test_is_not_invoked(self) -> None:
        """The same rule the workflow enforces on itself, checked from here too."""
        text = WORKFLOW.read_text(encoding="utf-8")
        invocations = re.findall(
            r"^[^#\n]*(?:python|bash|sh|\./)[^#\n]*smoke_the_odds_api", text, re.MULTILINE
        )
        assert invocations == []
