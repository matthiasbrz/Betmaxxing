"""Quarantine: bounded to one directory, never replacing, and reachable — §12.

Why this suite exists
---------------------
v5 introduced ``quarantine_incomplete_receipt`` as *the* documented way out of the
one situation the previous version could not recover from: a zero-byte file left
by an interruption, blocking its own receipt id for ever. The fifth audit found
three things wrong with it.

It was bounded to nothing. It derived its directory from the argument, so any path
the process could rename was renamed — including a file outside the receipt
directory, and including a foreign file when a parent component was substituted
between the check and the ``os.rename``.

It replaced. ``os.rename`` overwrites its target, so a forced name collision
destroyed the bytes of the file quarantined first — against the protocol's own
« sans perdre un octet ».

And it was unreachable. The refusal message told the operator to use
``quarantine_incomplete_receipt``, which no command exposed: the documented
recovery could only be performed by importing the module in a Python shell.

So the function here takes a **basename** of the already-opened secure directory,
never a path; it retries on collision instead of overwriting; and a real command
performs it.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import receipt_store as store
from helpers_activation import run

NAME = "20260901T120000-core-aa11bb22cc33dd44.json"


def _plain(text: str) -> str:
    """The text without styling.

    Typer renders its help through rich, and under ``FORCE_COLOR`` the option names come
    back wrapped in escape sequences. The property under test is that the option is
    documented, not how it is painted.
    """
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


INCOMPLETE = ""


@pytest.fixture
def directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "receipts"
    target.mkdir()
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(target))
    monkeypatch.setenv("BETMAXXING_MODE", "paper")
    return target


class TestItOperatesOnABasenameOfTheAuthorisedDirectory:
    def test_an_incomplete_receipt_is_moved_aside_with_its_bytes(self, directory: Path) -> None:
        (directory / NAME).write_text(INCOMPLETE, encoding="utf-8")
        quarantined = act.quarantine_incomplete_receipt(NAME)
        assert not (directory / NAME).exists()
        assert (directory / quarantined).exists()
        assert (directory / quarantined).stat().st_size == 0
        assert not quarantined.endswith(".json")
        assert act.QUARANTINE_SUFFIX in quarantined

    def test_a_partial_receipt_keeps_every_byte(self, directory: Path) -> None:
        body = '{"schema_version": 4, "command": "co'
        (directory / NAME).write_text(body, encoding="utf-8")
        quarantined = act.quarantine_incomplete_receipt(NAME)
        assert (directory / quarantined).read_text(encoding="utf-8") == body

    def test_a_path_is_refused_where_a_name_is_expected(self, directory: Path) -> None:
        (directory / NAME).write_text(INCOMPLETE, encoding="utf-8")
        for candidate in (
            str(directory / NAME),
            f"../{directory.name}/{NAME}",
            f"sub/{NAME}",
            "..",
            ".",
            "",
        ):
            with pytest.raises(store.DirectoryUnsafe):
                act.quarantine_incomplete_receipt(candidate)
        assert (directory / NAME).exists()

    def test_an_outside_file_is_never_moved(self, directory: Path, tmp_path: Path) -> None:
        victim = tmp_path / "outside.json"
        victim.write_text("OUTSIDE", encoding="utf-8")
        with pytest.raises(store.DirectoryUnsafe):
            act.quarantine_incomplete_receipt(str(victim))
        assert victim.read_text(encoding="utf-8") == "OUTSIDE"

    def test_a_link_is_never_followed_or_moved(self, directory: Path, tmp_path: Path) -> None:
        target = tmp_path / "outside-target.json"
        target.write_text("OUTSIDE", encoding="utf-8")
        (directory / NAME).symlink_to(target)
        with pytest.raises(store.DirectoryUnsafe):
            act.quarantine_incomplete_receipt(NAME)
        assert target.exists()
        assert (directory / NAME).is_symlink()

    def test_a_broken_link_is_refused(self, directory: Path, tmp_path: Path) -> None:
        (directory / NAME).symlink_to(tmp_path / "nowhere")
        with pytest.raises(store.DirectoryUnsafe):
            act.quarantine_incomplete_receipt(NAME)

    def test_a_parent_substituted_after_the_check_moves_nothing_outside(
        self, directory: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        foreign = outside / NAME
        foreign.write_text("FOREIGN", encoding="utf-8")
        (directory / NAME).write_text(INCOMPLETE, encoding="utf-8")
        # The whole directory is replaced by a link to `outside` once it is open.
        with store.SecureDirectory.open(directory) as secure:
            kept = directory.parent / "kept"
            directory.rename(kept)
            directory.symlink_to(outside)
            act.quarantine_in(secure, NAME)
        assert foreign.read_text(encoding="utf-8") == "FOREIGN"
        assert not (kept / NAME).exists()
        assert any(act.QUARANTINE_SUFFIX in p.name for p in kept.iterdir())

    def test_a_complete_signed_receipt_is_not_quarantined_by_accident(
        self, directory: Path
    ) -> None:
        from helpers_activation import FAKE_RECEIPT_SECRET
        from helpers_qualification_corpus import threshold_corpus

        document = threshold_corpus(FAKE_RECEIPT_SECRET)[0]
        (directory / NAME).write_text(json.dumps(document, indent=2), encoding="utf-8")
        with pytest.raises(act.Refused):
            act.quarantine_incomplete_receipt(NAME)
        assert (directory / NAME).exists()
        assert act.quarantine_incomplete_receipt(NAME, force=True)
        assert not (directory / NAME).exists()


class TestItNeverReplaces:
    def test_a_destination_collision_retries_instead_of_overwriting(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fifth audit forced the suffix and lost the first file's bytes."""
        suffixes = iter(["fixed", "fixed", "fixed", "second"])
        monkeypatch.setattr(store.secrets, "token_hex", lambda _n=4: next(suffixes))
        (directory / NAME).write_text("FIRST", encoding="utf-8")
        first = act.quarantine_incomplete_receipt(NAME)
        (directory / NAME).write_text("SECOND", encoding="utf-8")
        second = act.quarantine_incomplete_receipt(NAME)
        assert first != second
        assert (directory / first).read_text(encoding="utf-8") == "FIRST"
        assert (directory / second).read_text(encoding="utf-8") == "SECOND"

    def test_a_hundred_collisions_stop_bounded_and_lose_nothing(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(store.secrets, "token_hex", lambda _n=4: "always")
        (directory / NAME).write_text("KEEP", encoding="utf-8")
        kept = act.quarantine_incomplete_receipt(NAME)
        for index in range(100):
            (directory / NAME).write_text(f"body-{index}", encoding="utf-8")
            try:
                act.quarantine_incomplete_receipt(NAME)
            except store.PersistenceFailed:
                break
        else:  # pragma: no cover - a bounded retry must give up at some point
            raise AssertionError("the retry is not bounded")
        assert (directory / kept).read_text(encoding="utf-8") == "KEEP"
        assert (directory / NAME).exists(), "the source is left in place when it cannot move"

    def test_the_source_name_is_free_again_and_the_receipt_republishes(
        self, workspace: Path, frozen_clock: None
    ) -> None:
        from helpers_activation import FAKE_RECEIPT_SECRET
        from helpers_qualification_corpus import threshold_corpus

        document = threshold_corpus(FAKE_RECEIPT_SECRET)[0]
        path = act.write_receipt(dict(document))
        name = path.name
        path.write_text("", encoding="utf-8")  # an interruption, after the fact
        with pytest.raises(act.Refused):
            act.write_receipt(dict(document))
        act.quarantine_incomplete_receipt(name)
        again = act.write_receipt(dict(document))
        assert again.name == name
        batch, unverifiable = act.audit_receipts()
        assert len(batch) == 1
        assert unverifiable == 0

    def test_an_interruption_after_the_quarantine_link_keeps_both_readable(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (directory / NAME).write_text("BYTES", encoding="utf-8")
        real_unlink = os.unlink

        def failing_unlink(*args: Any, **kwargs: Any) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(os, "unlink", failing_unlink)
        with pytest.raises(KeyboardInterrupt):
            act.quarantine_incomplete_receipt(NAME)
        monkeypatch.setattr(os, "unlink", real_unlink)
        bodies = {p.read_text(encoding="utf-8") for p in directory.iterdir()}
        assert bodies == {"BYTES"}

    def test_nothing_else_in_the_directory_is_touched(self, directory: Path) -> None:
        neighbour = "20260901T120001-core-bb11bb22cc33dd44.json"
        (directory / NAME).write_text("", encoding="utf-8")
        (directory / neighbour).write_text("NEIGHBOUR", encoding="utf-8")
        act.quarantine_incomplete_receipt(NAME)
        assert (directory / neighbour).read_text(encoding="utf-8") == "NEIGHBOUR"


class TestTheOperatorCanActuallyRunIt:
    def test_the_command_exists_and_is_documented(self, directory: Path) -> None:
        listing = run("--help")
        assert "receipts" in _plain(listing.stdout)
        helped = run("receipts", "quarantine", "--help")
        assert helped.exit_code == 0, helped.stdout
        assert "--name" in _plain(helped.stdout)

    def test_it_quarantines_an_incomplete_receipt_end_to_end(self, workspace: Path) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / NAME).write_text("", encoding="utf-8")
        result = run("receipts", "quarantine", "--name", NAME)
        assert result.exit_code == 0, result.stdout
        assert NAME in result.stdout
        assert not (workspace / NAME).exists()
        assert any(act.QUARANTINE_SUFFIX in p.name for p in workspace.iterdir())

    def test_it_refuses_a_path_and_says_so(self, workspace: Path) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / NAME).write_text("", encoding="utf-8")
        result = run("receipts", "quarantine", "--name", str(workspace / NAME))
        assert result.exit_code != 0
        assert result.stdout.strip()
        assert (workspace / NAME).exists()

    def test_it_reports_a_missing_name_without_a_traceback(self, workspace: Path) -> None:
        result = run(
            "receipts", "quarantine", "--name", "20260901T120000-core-ffffffffffffffff.json"
        )
        assert result.exit_code != 0
        assert not isinstance(result.exception, OSError)
        assert result.stdout.strip()

    def test_the_refusal_message_of_write_receipt_names_the_command(
        self, workspace: Path, frozen_clock: None
    ) -> None:
        from helpers_activation import FAKE_RECEIPT_SECRET
        from helpers_qualification_corpus import threshold_corpus

        document = threshold_corpus(FAKE_RECEIPT_SECRET)[0]
        path = act.write_receipt(dict(document))
        path.write_text("", encoding="utf-8")
        with pytest.raises(act.Refused) as caught:
            act.write_receipt(dict(document))
        assert "receipts quarantine" in str(caught.value)
