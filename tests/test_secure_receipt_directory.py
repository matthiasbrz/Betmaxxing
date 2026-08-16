"""The receipt directory is a descriptor, not a path — D-076, §7.

Why this suite exists
---------------------
v5 protected the *name* of a receipt: it opened it relative to a directory
descriptor with ``O_NOFOLLOW``. The fifth audit showed the directory itself was
not protected. ``_open_in_directory`` opened the directory **by path** with
``O_DIRECTORY`` alone — no ``O_NOFOLLOW`` — and ``link``, ``unlink`` and the
directory ``fsync`` went back to ``directory / name`` afterwards. Three probes
followed from that: a receipt directory that was a symbolic link to somewhere
else, a symlinked *parent* component, and a directory swapped between ``glob()``
and the open. In all three the content of an outside file was read, verified, and
reported — sentinel and all.

So the boundary tested here is not "the final name is not a link". It is: one
directory descriptor, opened component by component without following anything,
kept for the whole operation, and used for every listing, read, publication, link,
unlink, rename and fsync. Every probe below uses a deterministic barrier in the
window it targets rather than a sequential ``is_symlink()`` check, because that is
the only kind of evidence the previous version's guarantee failed to survive.

Sentinels are synthetic and distinct in path and in content, so a reflection is
recognisable in either place.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import receipt_store as store

SECRET = "0123456789abcdef" * 4
#: Two sentinels: one in the outside *path*, one in the outside *content*.
PATH_SENTINEL = "outside_path_sentinel_9f3c"
CONTENT_SENTINEL = "soccer_outside_content_sentinel_5b71"


def open_fds() -> set[str]:
    return set(os.listdir("/proc/self/fd"))


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory the harness must never reach, holding a properly signed receipt."""
    from helpers_qualification_corpus import effective_instant
    from helpers_qualification_corpus import receipt as make_receipt

    directory = tmp_path / PATH_SENTINEL
    directory.mkdir()
    document = make_receipt(
        command="core",
        status="CORE_LIVE_VERIFIED",
        sport=CONTENT_SENTINEL,
        moment=effective_instant().replace(microsecond=0),
        tag="f0" * 16,
        markets=["h2h"],
        credits=1,
        secret=SECRET,
    )
    (directory / "20260901T120000-core-outside0000000.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (directory / act.SECRET_FILENAME).write_text(SECRET, encoding="utf-8")
    return directory


@pytest.fixture
def inside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "receipts"
    directory.mkdir()
    (directory / act.SECRET_FILENAME).write_text(SECRET, encoding="utf-8")
    os.chmod(directory / act.SECRET_FILENAME, 0o600)
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
    monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
    return directory


def no_reflection(*rendered: object) -> None:
    """Nothing read from outside is echoed back.

    ``receipt_directory`` is exempt for the path sentinel, and only for it: that field
    is the operator's own configured value, printed so they can see which directory was
    consulted. Everything else — and every appearance of the *content* sentinel, which
    could only come from a file the boundary was supposed to refuse — is a reflection.
    """
    for item in rendered:
        text = str(item)
        assert CONTENT_SENTINEL not in text
        for line in text.splitlines():
            if "receipt_directory" in line or "Répertoire" in line:
                continue
            assert PATH_SENTINEL not in line


def only_the_configured_path(state: dict[str, Any]) -> None:
    """The path sentinel appears in the configured directory and nowhere else."""
    for key, value in state.items():
        if key == "receipt_directory":
            continue
        assert PATH_SENTINEL not in json.dumps(value, ensure_ascii=False, default=str), key
        assert CONTENT_SENTINEL not in json.dumps(value, ensure_ascii=False, default=str), key


# ---------------------------------------------------------------------------
# The three shapes reproduced by the fifth audit
# ---------------------------------------------------------------------------
class TestTheDirectoryItselfIsNeverFollowed:
    def test_a_receipt_directory_that_is_a_link_is_refused(
        self, tmp_path: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = tmp_path / "receipts-link"
        link.symlink_to(outside)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(link))
        _audit = act.audit_receipts()
        batch = _audit.batch
        assert len(batch) == 0, "outside content was read through a directory link"
        state = act.build_activation_state(_audit)
        only_the_configured_path(state)
        assert state["bookmaker_coverage_observations"] == []

    def test_a_parent_component_that_is_a_link_is_refused(
        self, tmp_path: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        parent_link = tmp_path / "parent-link"
        parent_link.symlink_to(outside.parent)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(parent_link / outside.name))
        _audit = act.audit_receipts()
        batch = _audit.batch
        assert len(batch) == 0
        only_the_configured_path(act.build_activation_state(_audit))

    def test_a_broken_link_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = tmp_path / "dangling"
        link.symlink_to(tmp_path / "nowhere-at-all")
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(link))
        _audit = act.audit_receipts()
        batch = _audit.batch
        assert len(batch) == 0

    def test_an_internal_link_to_a_sibling_directory_is_refused(
        self, tmp_path: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "root"
        root.mkdir()
        (root / "real").mkdir()
        (root / "receipts").symlink_to(root / "real")
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(root / "receipts"))
        with pytest.raises(store.DirectoryUnsafe), store.SecureDirectory.open(act.receipt_dir()):
            pass

    def test_a_dot_dot_component_is_refused(
        self, inside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(inside / ".." / inside.name))
        with pytest.raises(store.DirectoryUnsafe), store.SecureDirectory.open(act.receipt_dir()):
            pass

    def test_a_regular_file_where_the_directory_should_be_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "not-a-directory"
        target.write_text("x", encoding="utf-8")
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(target))
        with pytest.raises(store.DirectoryUnsafe), store.SecureDirectory.open(act.receipt_dir()):
            pass


class TestOneDescriptorForTheWholeOperation:
    def test_the_directory_is_opened_once_and_never_re_resolved(self, inside: Path) -> None:
        """A rename during the operation cannot redirect a single byte."""
        with store.SecureDirectory.open(inside) as directory:
            moved = inside.parent / "renamed-away"
            inside.rename(moved)
            try:
                directory.publish_bytes("20260901T120000-core-aa00000000000000.json", b"{}\n")
                assert directory.listdir()
                assert sorted(p.name for p in moved.iterdir())
            finally:
                moved.rename(inside)

    def test_a_swap_between_listing_and_reading_yields_no_outside_content(
        self, inside: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fired = {"n": 0}
        real_listdir = store.SecureDirectory.listdir

        def swapping_listdir(self: Any) -> list[str]:
            names = real_listdir(self)
            if fired["n"] == 0:
                fired["n"] = 1
                # The whole directory is replaced by a link to the outside one.
                keep = inside.parent / "kept"
                inside.rename(keep)
                (inside).symlink_to(outside)
            return names

        monkeypatch.setattr(store.SecureDirectory, "listdir", swapping_listdir)
        _audit = act.audit_receipts()
        batch = _audit.batch
        assert fired["n"] == 1
        assert len(batch) == 0

    def test_publication_after_a_swap_never_lands_outside(
        self, inside: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = sorted(p.name for p in outside.iterdir())
        with store.SecureDirectory.open(inside) as directory:
            keep = inside.parent / "kept2"
            inside.rename(keep)
            inside.symlink_to(outside)
            directory.publish_bytes("20260901T120001-core-bb00000000000000.json", b'{"a": 1}\n')
        assert sorted(p.name for p in outside.iterdir()) == before
        assert (keep / "20260901T120001-core-bb00000000000000.json").exists()

    def test_unlink_and_rename_after_a_swap_never_touch_outside(
        self, inside: Path, outside: Path
    ) -> None:
        victim = "20260901T120002-core-cc00000000000000.json"
        (inside / victim).write_text("{}\n", encoding="utf-8")
        outside_names = sorted(p.name for p in outside.iterdir())
        with store.SecureDirectory.open(inside) as directory:
            keep = inside.parent / "kept3"
            inside.rename(keep)
            inside.symlink_to(outside)
            directory.rename(victim, victim + ".incomplete-x")
            directory.unlink(victim + ".incomplete-x")
            directory.fsync()
        assert sorted(p.name for p in outside.iterdir()) == outside_names

    def test_a_name_listed_from_one_inode_is_read_from_that_open(
        self, inside: Path, outside: Path
    ) -> None:
        """The bytes returned are the bytes of the object ``fstat`` described."""
        name = "20260901T120003-core-dd00000000000000.json"
        (inside / name).write_text('{"marker": "inside"}\n', encoding="utf-8")
        with store.SecureDirectory.open(inside) as directory:
            (inside / name).unlink()
            (inside / name).symlink_to(outside / "20260901T120000-core-outside0000000.json")
            with pytest.raises(store.DirectoryUnsafe):
                directory.read_text(name)

    def test_every_descriptor_is_closed_on_success_and_on_failure(
        self, inside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = open_fds()
        with store.SecureDirectory.open(inside) as directory:
            directory.listdir()
        assert open_fds() == baseline
        bad = tmp_path / "link-for-fd-check"
        bad.symlink_to(inside)
        with pytest.raises(store.DirectoryUnsafe), store.SecureDirectory.open(bad):
            pass
        assert open_fds() == baseline
        with pytest.raises(RuntimeError), store.SecureDirectory.open(inside):
            raise RuntimeError("boom")
        assert open_fds() == baseline

    def test_names_with_separators_are_refused(self, inside: Path) -> None:
        with store.SecureDirectory.open(inside) as directory:
            for name in ("../escape.json", "a/b.json", "", ".", "..", "/absolute.json"):
                with pytest.raises(store.DirectoryUnsafe):
                    directory.read_text(name)
                with pytest.raises(store.DirectoryUnsafe):
                    directory.publish_bytes(name, b"{}")


class TestFailClosedWithoutTheKernelGuarantees:
    def test_no_o_nofollow_means_the_directory_is_not_read(
        self, inside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
        with pytest.raises(store.DirectoryUnsafe), store.SecureDirectory.open(inside):
            pass
        _audit = act.audit_receipts()
        batch = _audit.batch
        assert len(batch) == 0

    def test_no_dir_fd_support_means_the_directory_is_not_read(
        self, inside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "supports_dir_fd", set())
        with pytest.raises(store.DirectoryUnsafe), store.SecureDirectory.open(inside):
            pass


class TestTheOutsideIsNeverReflected:
    def test_no_sentinel_reaches_the_status_document_in_any_shape(
        self, tmp_path: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for variant in ("link", "parent"):
            if variant == "link":
                target = tmp_path / f"receipts-{variant}"
                target.symlink_to(outside)
            else:
                holder = tmp_path / f"holder-{variant}"
                holder.symlink_to(outside.parent)
                target = holder / outside.name
            monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(target))
            _audit = act.audit_receipts()
            state = act.build_activation_state(_audit)
            only_the_configured_path(state)
            no_reflection("\n".join(act.status_lines(state)))
