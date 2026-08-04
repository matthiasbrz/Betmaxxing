"""Configuration hygiene and secret handling.

Acceptance criterion: no secret and no fictitious data may ever appear as real
data, and thresholds must be versioned and reproducible.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from betmaxxing.config import CONFIG_SCHEMA_VERSION, RunMode, Settings

REPO_ROOT = Path(__file__).resolve().parents[1]


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
        content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        secret_lines = [
            line
            for line in content.splitlines()
            if re.match(r"^[A-Z_]*(API_KEY|TOKEN|PASSWORD|SECRET)=", line)
        ]
        assert secret_lines, "the example file should list the secret variables"
        for line in secret_lines:
            assert line.split("=", 1)[1] == "", f"{line} must not carry a value"

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
