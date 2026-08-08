"""Configuration hygiene and secret handling.

Acceptance criterion: no secret and no fictitious data may ever appear as real
data, and thresholds must be versioned and reproducible.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from betmaxxing.config import CONFIG_SCHEMA_VERSION, RunMode, Settings
from betmaxxing.security import secret_hygiene

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A value that is shaped exactly like a real provider key and is not one. Every
#: test below asserts on the *verdict* and on the absence of this string from the
#: output, never on the string being echoed back.
SYNTHETIC_CREDENTIAL = "0123456789abcdef0123456789abcdef"


class TestFingerprint:
    def test_is_stable_for_identical_configuration(self) -> None:
        assert (
            Settings(mode=RunMode.DEMO).fingerprint() == Settings(mode=RunMode.DEMO).fingerprint()
        )

    def test_changes_when_a_threshold_changes(self) -> None:
        base = Settings(mode=RunMode.DEMO, min_ev=0.03)
        changed = Settings(mode=RunMode.DEMO, min_ev=0.05)
        assert base.fingerprint() != changed.fingerprint()

    def test_is_unaffected_by_non_decision_settings(self) -> None:
        """A different log level must not invalidate a run's reproducibility."""
        base = Settings(mode=RunMode.DEMO, log_level="INFO")
        noisy = Settings(mode=RunMode.DEMO, log_level="DEBUG")
        assert base.fingerprint() == noisy.fingerprint()

    def test_covers_every_published_threshold(self) -> None:
        thresholds = Settings(mode=RunMode.DEMO).eligibility_thresholds()
        for key in (
            "min_ev",
            "min_conservative_ev",
            "max_prob_half_width",
            "max_odds_age_seconds",
            "min_data_quality",
            "min_odds",
            "max_odds",
            "devig_method",
            "window_hours",
        ):
            assert key in thresholds

    def test_schema_version_is_reported(self) -> None:
        assert re.match(r"^\d+\.\d+\.\d+$", CONFIG_SCHEMA_VERSION)


class TestRedaction:
    def test_secret_bearing_fields_are_masked(self) -> None:
        settings = Settings(
            mode=RunMode.DEMO,
            odds_api_key="SECRET_KEY_VALUE",
            telegram_bot_token="SECRET_TOKEN_VALUE",
            smtp_password="SECRET_PASSWORD_VALUE",
        )
        redacted = settings.redacted()
        assert redacted["odds_api_key"] == "***set***"
        assert redacted["telegram_bot_token"] == "***set***"
        assert redacted["smtp_password"] == "***set***"
        blob = str(redacted)
        for secret in ("SECRET_KEY_VALUE", "SECRET_TOKEN_VALUE", "SECRET_PASSWORD_VALUE"):
            assert secret not in blob

    def test_unset_secrets_stay_empty_not_masked(self) -> None:
        redacted = Settings(mode=RunMode.DEMO).redacted()
        assert redacted["odds_api_key"] == ""

    def test_non_secret_fields_are_preserved(self) -> None:
        redacted = Settings(mode=RunMode.DEMO, min_ev=0.07).redacted()
        assert redacted["min_ev"] == 0.07


class TestValidation:
    def test_max_odds_must_exceed_min_odds(self) -> None:
        with pytest.raises(ValueError):
            Settings(mode=RunMode.DEMO, min_odds=3.0, max_odds=2.0)

    def test_negative_window_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            Settings(mode=RunMode.DEMO, window_hours=-1)

    def test_kelly_fraction_is_bounded(self) -> None:
        with pytest.raises(ValueError):
            Settings(mode=RunMode.DEMO, kelly_fraction=1.5)

    def test_stake_cap_is_bounded(self) -> None:
        with pytest.raises(ValueError):
            Settings(mode=RunMode.DEMO, max_stake_pct_of_bankroll=0.9)

    def test_settings_are_immutable(self) -> None:
        settings = Settings(mode=RunMode.DEMO)
        with pytest.raises(ValueError):
            settings.min_ev = 0.5  # type: ignore[misc]


class TestSafeDefaults:
    def test_default_mode_is_demo(self) -> None:
        assert Settings().mode is RunMode.DEMO

    def test_staking_is_off_by_default(self) -> None:
        assert Settings().staking_enabled is False
        assert Settings().bankroll == 0.0

    def test_notifications_are_off_by_default(self) -> None:
        assert Settings().notifications_enabled is False

    def test_scheduler_is_off_by_default(self) -> None:
        assert Settings().scheduler_enabled is False

    def test_llm_is_off_by_default(self) -> None:
        assert Settings().llm_enabled is False

    def test_winamax_defaults_to_manual_import(self) -> None:
        # No authorized programmatic feed is claimed.
        assert Settings().winamax_mode == "manual"

    def test_paper_and_live_modes_require_real_providers(self) -> None:
        assert Settings(mode=RunMode.PAPER).requires_real_providers
        assert Settings(mode=RunMode.LIVE_ANALYSIS).requires_real_providers
        assert not Settings(mode=RunMode.DEMO).requires_real_providers


class TestParsedLists:
    def test_scan_times_are_parsed(self) -> None:
        assert Settings(scan_times="08:00, 12:00 ,18:00").scan_time_list == [
            "08:00",
            "12:00",
            "18:00",
        ]

    def test_milestones_are_parsed_as_floats(self) -> None:
        assert Settings(milestones_hours_before="24,12,0.25").milestone_hours == [
            24.0,
            12.0,
            0.25,
        ]

    def test_notification_channels_are_parsed(self) -> None:
        assert Settings(notification_channels="telegram,email").notification_channel_list == [
            "telegram",
            "email",
        ]


class TestRepositoryHygiene:
    def test_env_example_exists_and_has_no_values_for_secrets(self) -> None:
        """The template names the secret variables and gives none of them a value.

        This assertion used to interpolate the offending line into its own
        message. When a key was actually committed the guard fired correctly and
        printed the key into the CI log, which turned a caught mistake into a
        second copy of it. The verdict now names the variable and the line
        number, and the value stays where it is.
        """
        path = REPO_ROOT / ".env.example"
        content = path.read_text(encoding="utf-8")
        named = [
            match.group("name")
            for line in content.splitlines()
            if (match := secret_hygiene.ASSIGNMENT.match(line)) is not None
        ]
        assert named, "the example file should list the secret variables"
        findings = secret_hygiene.scan_text(content, path=".env.example")
        assert findings == [], "; ".join(str(finding) for finding in findings)

    def test_gitignore_excludes_env_and_databases(self) -> None:
        content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert ".env" in content
        assert "*.db" in content

    def test_no_source_file_contains_an_obvious_hardcoded_secret(self) -> None:
        pattern = re.compile(
            r"""(api_key|token|password|secret)\s*=\s*["'][A-Za-z0-9_\-]{16,}["']""",
            re.IGNORECASE,
        )
        offenders: list[str] = []
        for path in (REPO_ROOT / "src").rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
        assert offenders == []


class TestTheSecretGuardAcceptsAnEmptyValue:
    """An empty assignment is the whole point of the template and must pass."""

    @pytest.mark.parametrize(
        "line",
        [
            "BETMAXXING_THE_ODDS_API_KEY=",
            "BETMAXXING_THE_ODDS_API_KEY=   ",
            'BETMAXXING_THE_ODDS_API_KEY=""',
            "BETMAXXING_THE_ODDS_API_KEY=''",
            "export BETMAXXING_THE_ODDS_API_KEY=",
            "  BETMAXXING_THE_ODDS_API_KEY =  ",
        ],
    )
    def test_an_empty_assignment_is_accepted_in_an_environment_file(self, line: str) -> None:
        assert secret_hygiene.scan_text(line, path=".env.example") == []

    def test_naming_the_variable_is_not_itself_a_violation(self) -> None:
        template = "\n".join(f"{name}=" for name in secret_hygiene.SECRET_VARIABLES)
        assert secret_hygiene.scan_text(template, path=".env.example") == []


class TestTheSecretGuardRefusesAPopulatedValue:
    """A synthetic value is refused, and never reproduced in the verdict."""

    @pytest.mark.parametrize(
        "line",
        [
            "BETMAXXING_THE_ODDS_API_KEY=VALUE",
            'BETMAXXING_THE_ODDS_API_KEY="VALUE"',
            "BETMAXXING_THE_ODDS_API_KEY='VALUE'",
            "  BETMAXXING_THE_ODDS_API_KEY=VALUE",
            "export BETMAXXING_THE_ODDS_API_KEY=VALUE",
            "  export  BETMAXXING_THE_ODDS_API_KEY = VALUE  ",
            'export BETMAXXING_THE_ODDS_API_KEY = "VALUE"',
            "betmaxxing_the_odds_api_key=VALUE",
        ],
    )
    def test_quotes_spaces_export_and_case_do_not_bypass_the_check(self, line: str) -> None:
        """Every syntactic dressing an env file allows still counts as a value."""
        findings = secret_hygiene.scan_text(
            line.replace("VALUE", SYNTHETIC_CREDENTIAL), path=".env.example"
        )
        assert len(findings) == 1
        assert findings[0].variable == "BETMAXXING_THE_ODDS_API_KEY"
        assert findings[0].line == 1

    def test_every_known_secret_variable_is_covered(self) -> None:
        for name in secret_hygiene.SECRET_VARIABLES:
            findings = secret_hygiene.scan_text(
                f"{name}={SYNTHETIC_CREDENTIAL}", path=".env.example"
            )
            assert len(findings) == 1, name
            assert findings[0].variable == name.upper()


class TestTheVerdictNeverReproducesTheValue:
    """A guard whose own output must be redacted has just moved the leak."""

    def test_the_finding_carries_no_part_of_the_value(self) -> None:
        finding = secret_hygiene.scan_text(
            f"BETMAXXING_THE_ODDS_API_KEY={SYNTHETIC_CREDENTIAL}", path=".env.example"
        )[0]
        rendered = str(finding)
        assert SYNTHETIC_CREDENTIAL not in rendered
        # Not even a fragment: no window of the value survives anywhere.
        for size in (8, 12, 16):
            for start in range(0, len(SYNTHETIC_CREDENTIAL) - size + 1):
                assert SYNTHETIC_CREDENTIAL[start : start + size] not in rendered
        assert repr(finding).count(SYNTHETIC_CREDENTIAL) == 0

    def test_the_command_line_output_carries_no_part_of_the_value(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / ".env.example"
        target.write_text(f"BETMAXXING_THE_ODDS_API_KEY={SYNTHETIC_CREDENTIAL}\n", encoding="utf-8")
        assert secret_hygiene.main([str(target)]) == 1
        captured = capsys.readouterr()
        assert SYNTHETIC_CREDENTIAL not in captured.out + captured.err
        assert "BETMAXXING_THE_ODDS_API_KEY" in captured.out

    def test_the_module_is_runnable_as_a_subprocess_without_leaking(self, tmp_path: Path) -> None:
        """The pre-commit hook and CI both invoke it this way, not as an import."""
        target = tmp_path / ".env.example"
        target.write_text(f"BETMAXXING_THE_ODDS_API_KEY={SYNTHETIC_CREDENTIAL}\n", encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                "-W",
                "error",
                "-m",
                "betmaxxing.security.secret_hygiene",
                str(target),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 1
        assert SYNTHETIC_CREDENTIAL not in completed.stdout + completed.stderr
        assert "BETMAXXING_THE_ODDS_API_KEY" in completed.stdout


class TestTheGuardDistinguishesProseFromCredentials:
    """Documentation must keep showing the shape of a setting, or nobody reads it."""

    @pytest.mark.parametrize(
        "line",
        [
            "BETMAXXING_THE_ODDS_API_KEY=<your-key>",
            "BETMAXXING_THE_ODDS_API_KEY=…",
            "BETMAXXING_THE_ODDS_API_KEY=votre-cle",
            "BETMAXXING_THE_ODDS_API_KEY=$THE_ODDS_API_KEY",
            "BETMAXXING_THE_ODDS_API_KEY=xxxxxxxx-remplacer",
        ],
    )
    def test_a_placeholder_in_prose_is_allowed(self, line: str) -> None:
        assert secret_hygiene.scan_text(line, path="docs/deployment.md") == []

    @pytest.mark.parametrize(
        "line",
        [
            "BETMAXXING_THE_ODDS_API_KEY=VALUE",
            'BETMAXXING_THE_ODDS_API_KEY="VALUE"',
            "export BETMAXXING_THE_ODDS_API_KEY=VALUE",
        ],
    )
    def test_a_credential_shaped_value_is_refused_even_in_prose(self, line: str) -> None:
        findings = secret_hygiene.scan_text(
            line.replace("VALUE", SYNTHETIC_CREDENTIAL), path="docs/deployment.md"
        )
        assert len(findings) == 1
        assert findings[0].reason == secret_hygiene.LOOKS_LIKE_A_CREDENTIAL

    def test_a_placeholder_is_still_refused_inside_an_environment_file(self) -> None:
        """`.env.example` is copied verbatim, so even a placeholder is a value there."""
        findings = secret_hygiene.scan_text(
            "BETMAXXING_THE_ODDS_API_KEY=<your-key>", path=".env.example"
        )
        assert len(findings) == 1
        assert findings[0].reason == secret_hygiene.IN_ENVIRONMENT_FILE

    def test_a_comment_about_an_assignment_is_not_an_assignment(self) -> None:
        prose = (
            "# Put your key in `.env`, for example:\n"
            f"#     export BETMAXXING_THE_ODDS_API_KEY='{SYNTHETIC_CREDENTIAL}'\n"
        )
        assert secret_hygiene.scan_text(prose, path=".env.example") == []

    @pytest.mark.parametrize("name", [".env", ".env.example", ".env.local", "deploy/.env.ci"])
    def test_every_environment_file_variant_is_treated_strictly(self, name: str) -> None:
        assert secret_hygiene.is_environment_file(name)

    @pytest.mark.parametrize("name", ["README.md", "docs/deployment.md", "src/a.py"])
    def test_other_files_are_not_treated_as_environment_files(self, name: str) -> None:
        assert not secret_hygiene.is_environment_file(name)


class TestTheGuardCoversTheRealRepository:
    """The check that would have stopped the incident, run on this very tree."""

    def test_no_tracked_file_carries_a_populated_secret(self) -> None:
        findings = secret_hygiene.scan_paths(
            REPO_ROOT / name for name in secret_hygiene.tracked_files(REPO_ROOT)
        )
        assert findings == [], "; ".join(str(finding) for finding in findings)

    def test_the_variable_list_matches_the_template(self) -> None:
        """A new secret setting must be added to SECRET_VARIABLES, not just to the file."""
        content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        declared = {
            match.group(1)
            for line in content.splitlines()
            if (match := re.match(r"^([A-Z_]*(?:API_KEY|TOKEN|PASSWORD|SECRET))=", line))
        }
        known = {name.upper() for name in secret_hygiene.SECRET_VARIABLES}
        assert declared <= known, f"not covered by the guard: {sorted(declared - known)}"

    def test_env_is_not_tracked(self) -> None:
        assert ".env" not in secret_hygiene.tracked_files(REPO_ROOT)
