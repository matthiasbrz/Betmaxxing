"""Recovery has a perimeter, and every failure has a category — §3.7, §3.8, §3.9.

Why this suite exists
---------------------
Three separate findings of the sixth re-audit, all about what happens when
something goes wrong.

**The recovery command had no perimeter.** ``receipts quarantine --name`` accepted
any regular file of the directory. ``--name aa11bb22cc33dd44.intent`` returned 0
without ``--force`` and took the gate from ``EVIDENCE_CONFLICT`` /
``eligible False`` to ``CRITERIA_MET_AWAITING_HUMAN_REVIEW`` / ``eligible True`` —
a conflict deleted with no receipt anywhere. ``--name signing-key.secret`` also
returned 0, after which eight verified receipts became eight unverifiable ones.
Publication temporaries and unrelated files went the same way. The documentation
called it a command for ``*.json`` receipts; nothing enforced that.

**Hostile input was a denial of service.** One file whose ``signature`` was a
non-ASCII string made ``hmac.compare_digest`` raise, and ``status`` and
``status --json`` died with a raw ``TypeError`` and **zero bytes** on stdout. A
secret file holding invalid UTF-8 raised a bare ``UnicodeDecodeError`` from both
secret verbs. Neither is a refusal an operator can act on.

**The publication net had a hole.** ``_persist_or_report`` caught only
``PersistenceFailed``, while the store raises ``DirectoryUnsafe`` for *any*
``OSError`` at ``open`` — so ``EACCES``, ``EROFS`` and ``ENOSPC`` at the creation
of the receipt's temporary escaped uncaught, printing nothing: precisely the shape
the fifth audit's P2-D3 claimed to have closed.

Plus the two scalars ``evaluate`` never validated, and the secret's own policy.
"""

from __future__ import annotations

import errno
import json
import os
import stat as statmodule
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from betmaxxing.providers.the_odds_api import receipt_store as store
from betmaxxing.providers.the_odds_api.activation import ensure_utc
from helpers_activation import EVENT_ID, Recorder, discover_args, install, run
from helpers_qualification_corpus import threshold_corpus
from helpers_receipt_boundary import audited_corpus, install_secret

LOCAL = "0011223344556677889900aabbccddeeff00112233445566778899aabbccddee"
ATTEMPT = "aa11bb22cc33dd44"


def _routes() -> dict[str, Any]:
    from helpers_activation import event_odds_payload, events_payload, odds_payload, sports_payload

    return {
        f"/events/{EVENT_ID}/odds": event_odds_payload(),
        "/events": events_payload(),
        "/odds": odds_payload(),
        "/sports": sports_payload(),
    }


def _gate() -> dict[str, Any]:
    audit = act.audit_receipts()
    waiting = len(act.unresolved_intents())
    document = qual.evaluate(audit, unresolved_intents=waiting)
    return {
        "eligible": document["eligible_for_human_promotion_review"],
        "state": document["qualification_state"],
        "intents": waiting,
        "verified": len(audit.batch),
        "unverifiable": audit.unverifiable,
    }


def _attempt() -> act.Attempt:
    now = ensure_utc(act._clock())
    return act.Attempt(
        command="additional",
        sport="soccer_probe",
        bookmaker="probebook",
        window=(now, now + timedelta(hours=24)),
        ceiling=5,
        now=now,
        event_id="EV-PROBE-1",
        event_tags=[act.event_tag("EV-PROBE-1", LOCAL)],
        attempt_id=ATTEMPT,
    )


# ---------------------------------------------------------------------------
# 3.7 — the quarantine perimeter
# ---------------------------------------------------------------------------
class TestQuarantineIsAReceiptCommandOnly:
    @pytest.fixture
    def installation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        directory = audited_corpus(
            tmp_path / "receipts",
            threshold_corpus(LOCAL),
            secret=LOCAL,
            monkeypatch=monkeypatch,
        ) and (tmp_path / "receipts")
        monkeypatch.setenv("BETMAXXING_MODE", "paper")
        return directory

    @pytest.mark.parametrize("force", [False, True], ids=["without-force", "with-force"])
    def test_the_signing_secret_is_never_movable(self, installation: Path, force: bool) -> None:
        before = _gate()
        args = ["receipts", "quarantine", "--name", act.SECRET_FILENAME]
        if force:
            args.append("--force")
        result = run(*args)
        assert result.exit_code != 0
        assert result.stdout.strip()
        assert (installation / act.SECRET_FILENAME).exists()
        assert _gate() == before

    @pytest.mark.parametrize("force", [False, True], ids=["without-force", "with-force"])
    def test_an_unresolved_intent_is_never_movable(self, installation: Path, force: bool) -> None:
        act.publish_intent(_attempt())
        blocked = _gate()
        assert blocked["eligible"] is False
        assert blocked["intents"] == 1
        args = ["receipts", "quarantine", "--name", f"{ATTEMPT}{act.INTENT_SUFFIX}"]
        if force:
            args.append("--force")
        result = run(*args)
        assert result.exit_code != 0
        assert result.stdout.strip()
        assert (installation / f"{ATTEMPT}{act.INTENT_SUFFIX}").exists()
        assert _gate() == blocked

    @pytest.mark.parametrize("force", [False, True], ids=["without-force", "with-force"])
    def test_a_publication_temporary_is_never_movable(
        self, installation: Path, force: bool
    ) -> None:
        temporary = f".20260901T120000-core-{ATTEMPT}.json.{os.getpid()}.abcd1234.tmp"
        (installation / temporary).write_text("half a receipt", encoding="utf-8")
        args = ["receipts", "quarantine", "--name", temporary]
        if force:
            args.append("--force")
        result = run(*args)
        assert result.exit_code != 0
        assert (installation / temporary).exists()

    @pytest.mark.parametrize("name", ["notes.txt", "README", "signing-key.secret.backup"])
    def test_any_other_file_is_never_movable(self, installation: Path, name: str) -> None:
        (installation / name).write_text("nothing to do with receipts", encoding="utf-8")
        result = run("receipts", "quarantine", "--name", name)
        assert result.exit_code != 0
        assert (installation / name).exists()

    def test_an_incomplete_receipt_is_the_one_nominal_case(self, installation: Path) -> None:
        name = "20260901T120000-core-bb22cc33dd44ee55.json"
        (installation / name).write_text("", encoding="utf-8")
        result = run("receipts", "quarantine", "--name", name)
        assert result.exit_code == 0, result.stdout
        assert not (installation / name).exists()
        assert any(act.QUARANTINE_SUFFIX in p.name for p in installation.iterdir())

    def test_a_complete_signed_receipt_needs_force(self, installation: Path) -> None:
        victim = sorted(p.name for p in installation.glob("*.json"))[0]
        assert run("receipts", "quarantine", "--name", victim).exit_code != 0
        assert (installation / victim).exists()
        assert run("receipts", "quarantine", "--name", victim, "--force").exit_code == 0
        assert not (installation / victim).exists()

    @pytest.mark.parametrize(
        "name",
        ["/etc/passwd", "../receipts/x.json", "sub/x.json", "..", ".", "", "linked.json"],
    )
    def test_no_path_and_no_link_is_ever_accepted(self, installation: Path, name: str) -> None:
        if name == "linked.json":
            (installation / "outside-target.json").write_text("{}", encoding="utf-8")
            (installation / name).symlink_to(installation / "outside-target.json")
        result = run("receipts", "quarantine", "--name", name)
        assert result.exit_code != 0
        assert result.stdout.strip()

    def test_a_collision_still_loses_no_byte(
        self, installation: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        suffixes = iter(["fixed", "fixed", "fixed", "second"])
        monkeypatch.setattr(store.secrets, "token_hex", lambda _n=4: next(suffixes))
        name = "20260901T120000-core-cc33dd44ee55ff66.json"
        (installation / name).write_text("FIRST", encoding="utf-8")
        first = act.quarantine_incomplete_receipt(name)
        (installation / name).write_text("SECOND", encoding="utf-8")
        second = act.quarantine_incomplete_receipt(name)
        assert first != second
        assert (installation / first).read_text(encoding="utf-8") == "FIRST"
        assert (installation / second).read_text(encoding="utf-8") == "SECOND"


# ---------------------------------------------------------------------------
# 3.8 — every failure has a category
# ---------------------------------------------------------------------------
class TestHostileBytesAreARefusalNotACrash:
    @pytest.mark.parametrize(
        ("label", "signature"),
        [
            ("non ascii", "é" * 64),
            ("mixed script", "0" * 63 + "é"),
            ("uppercase", "A" * 64),
            ("too short", "0" * 63),
            ("too long", "0" * 65),
            ("empty", ""),
            ("integer", 1234),
            ("list", ["0" * 64]),
            ("mapping", {"sig": "0" * 64}),
            ("very long", "0" * 100_000),
        ],
    )
    def test_a_malformed_signature_makes_one_receipt_unverifiable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str, signature: Any
    ) -> None:
        corpus = threshold_corpus(LOCAL)
        hostile = dict(corpus[0])
        hostile["receipt_id"] = "ffffffffffffffff"
        hostile[act.SIGNATURE_FIELD] = signature
        audit = audited_corpus(
            tmp_path / "receipts", [*corpus, hostile], secret=LOCAL, monkeypatch=monkeypatch
        )
        assert len(audit.batch) == 8
        assert audit.unverifiable == 1

    def test_the_reporting_path_survives_it_in_both_renderings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corpus = threshold_corpus(LOCAL)
        hostile = dict(corpus[0], receipt_id="ffffffffffffffff")
        hostile[act.SIGNATURE_FIELD] = "é" * 64
        audited_corpus(
            tmp_path / "receipts", [*corpus, hostile], secret=LOCAL, monkeypatch=monkeypatch
        )
        monkeypatch.setenv("BETMAXXING_MODE", "paper")
        for args in (("status",), ("status", "--json")):
            result = run(*args)
            assert result.exit_code == 0, result.stdout
            assert result.stdout.strip()
            assert not isinstance(result.exception, TypeError)

    def test_a_secret_of_invalid_utf8_is_a_sanitised_refusal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "receipts"
        directory.mkdir()
        path = directory / act.SECRET_FILENAME
        path.write_bytes(b"\xff\xfe" + b"a" * 62)
        os.chmod(path, 0o600)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        for verb in (act.load_receipt_secret, act.ensure_receipt_secret):
            with pytest.raises(store.SecretInvalid):
                verb()
        assert path.read_bytes().startswith(b"\xff\xfe")

    def test_a_receipt_of_invalid_utf8_is_counted_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "receipts"
        audited_corpus(directory, threshold_corpus(LOCAL), secret=LOCAL, monkeypatch=monkeypatch)
        (directory / "20260901T129999-core-badbytes.json").write_bytes(b"\xff\xfe{}")
        audit = act.audit_receipts()
        assert len(audit.batch) == 8
        assert audit.unverifiable == 1


class TestEveryPublicationFailureIsReported:
    @pytest.fixture
    def ready(
        self, workspace: Path, keyed: None, frozen_clock: None, monkeypatch: pytest.MonkeyPatch
    ) -> Path:
        install(monkeypatch, Recorder(_routes()))
        return workspace

    def _outcome(self, workspace: Path, result: Any) -> dict[str, Any]:
        files = sorted(p.name for p in workspace.iterdir()) if workspace.exists() else []
        return {
            "exit": result.exit_code,
            "empty": not result.stdout.strip(),
            "escaped": type(result.exception).__name__ if result.exception else None,
            "intents": len([n for n in files if n.endswith(act.INTENT_SUFFIX)]),
            "receipts": len([n for n in files if n.endswith(".json")]),
        }

    @pytest.mark.parametrize(
        "code",
        [errno.EACCES, errno.EROFS, errno.ENOSPC, errno.EPERM],
        ids=["EACCES", "EROFS", "ENOSPC", "EPERM"],
    )
    def test_an_open_failure_on_the_receipt_temporary_is_reported(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch, code: int
    ) -> None:
        real = os.open

        def guarded(path: Any, flags: int, *rest: Any, **kwargs: Any) -> Any:
            if isinstance(path, str) and ".json." in path and path.endswith(".tmp"):
                raise OSError(code, os.strerror(code))
            return real(path, flags, *rest, **kwargs)

        monkeypatch.setattr(os, "open", guarded)
        result = run(*discover_args(extra=("--json",)))
        monkeypatch.setattr(os, "open", real)
        outcome = self._outcome(ready, result)
        assert outcome["exit"] != 0
        assert outcome["empty"] is False
        assert outcome["escaped"] in {"SystemExit", None}
        assert outcome["intents"] == 1, "the trace of a possible request must survive"
        payload = json.loads(result.stdout)
        assert payload["persistence_failure"]
        assert payload["attempt_id"]

    @pytest.mark.parametrize(
        "code", [errno.ENOSPC, errno.EINTR, errno.EIO], ids=["ENOSPC", "EINTR", "EIO"]
    )
    def test_a_write_failure_is_reported(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch, code: int
    ) -> None:
        real = os.write
        seen = {"n": 0}

        def guarded(fd: int, data: bytes) -> int:
            seen["n"] += 1
            if seen["n"] > 1:
                raise OSError(code, os.strerror(code))
            return real(fd, data)

        monkeypatch.setattr(os, "write", guarded)
        result = run(*discover_args(extra=("--json",)))
        monkeypatch.setattr(os, "write", real)
        outcome = self._outcome(ready, result)
        assert outcome["exit"] != 0
        assert outcome["empty"] is False
        assert outcome["intents"] == 1

    def test_no_progress_for_ever_ends_in_a_typed_failure(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = os.write
        seen = {"n": 0}

        def guarded(fd: int, data: bytes) -> int:
            seen["n"] += 1
            if seen["n"] > 1:
                return 0
            return real(fd, data)

        monkeypatch.setattr(os, "write", guarded)
        result = run(*discover_args(extra=("--json",)))
        monkeypatch.setattr(os, "write", real)
        assert result.exit_code != 0
        assert result.stdout.strip()

    def test_an_fsync_failure_is_reported(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = os.fsync
        seen = {"n": 0}

        def guarded(fd: int) -> None:
            seen["n"] += 1
            if seen["n"] > 3:
                raise OSError(errno.EIO, "io error")
            return real(fd)

        monkeypatch.setattr(os, "fsync", guarded)
        result = run(*discover_args(extra=("--json",)))
        monkeypatch.setattr(os, "fsync", real)
        outcome = self._outcome(ready, result)
        assert outcome["exit"] != 0
        assert outcome["empty"] is False

    def test_an_unsafe_directory_at_publication_is_reported(
        self, ready: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Not `PersistenceFailed`: `write_receipt` can raise the whole store family."""
        real = act.write_receipt

        def exploding(document: Any) -> Any:
            raise store.DirectoryUnsafe("frontière indisponible (probe)")

        monkeypatch.setattr(act, "write_receipt", exploding)
        result = run(*discover_args(extra=("--json",)))
        monkeypatch.setattr(act, "write_receipt", real)
        assert result.exit_code != 0
        assert result.stdout.strip()
        assert not isinstance(result.exception, store.StoreRefused)
        payload = json.loads(result.stdout)
        assert payload["persistence_failure"]
        assert len([p for p in ready.iterdir() if p.name.endswith(act.INTENT_SUFFIX)]) == 1

    def test_a_divergent_collision_is_a_business_refusal(
        self, workspace: Path, keyed: None, frozen_clock: None
    ) -> None:
        document = {
            "schema_version": act.RECEIPT_SCHEMA_VERSION,
            "receipt_id": ATTEMPT,
            "command": "discover",
            "status": "DISCOVERY_VERIFIED",
            "recorded_at": "2026-08-04T12:00:00+00:00",
            "sport_key": "soccer_probe",
        }
        act.write_receipt(dict(document))
        with pytest.raises(act.Refused) as caught:
            act.write_receipt(dict(document, sport_key="tennis_probe"))
        assert str(caught.value)
        assert not isinstance(caught.value, store.PersistenceFailed)


# ---------------------------------------------------------------------------
# 3.9 — the secret's policy and the two scalars
# ---------------------------------------------------------------------------
class TestTheSecretPolicy:
    def test_a_variable_that_is_present_but_empty_is_invalid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "receipts"
        install_secret(directory, LOCAL)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
        monkeypatch.setenv(act.SECRET_VARIABLE, "")
        for verb in (act.load_receipt_secret, act.ensure_receipt_secret):
            with pytest.raises(store.SecretInvalid):
                verb()

    def test_only_a_truly_absent_variable_falls_back_to_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "receipts"
        install_secret(directory, LOCAL)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        assert act.load_receipt_secret() == LOCAL

    @pytest.mark.parametrize("mode", [0o640, 0o644, 0o666, 0o604, 0o660])
    def test_a_secret_readable_by_anyone_else_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
    ) -> None:
        directory = tmp_path / "receipts"
        path = install_secret(directory, LOCAL)
        os.chmod(path, mode)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        with pytest.raises(store.SecretInvalid):
            act.load_receipt_secret()
        assert statmodule.S_IMODE(path.stat().st_mode) == mode, "a refusal repairs nothing"

    @pytest.mark.parametrize("mode", [0o600, 0o400])
    def test_a_private_secret_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
    ) -> None:
        directory = tmp_path / "receipts"
        path = install_secret(directory, LOCAL)
        os.chmod(path, mode)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        assert act.load_receipt_secret() == LOCAL

    def test_a_platform_without_posix_ownership_skips_the_check_and_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other side of the branch, tested rather than excluded from coverage.

        On a platform with no ownership or permission bits there is nothing to compare,
        so the check is skipped — and a secret that would be refused here is accepted
        there. That is a documented limit of the platform, not of the policy, and it is
        reachable from a test because the detection is a function.
        """
        directory = tmp_path / "receipts"
        path = install_secret(directory, LOCAL)
        os.chmod(path, 0o666)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        with pytest.raises(store.SecretInvalid):
            act.load_receipt_secret()
        monkeypatch.setattr(store, "posix_ownership_available", lambda: False)
        assert act.load_receipt_secret() == LOCAL
        assert statmodule.S_IMODE(path.stat().st_mode) == 0o666, "nothing is repaired"

    def test_the_platform_probe_answers_true_here(self) -> None:
        assert store.posix_ownership_available() is True

    def test_the_created_secret_is_private_and_the_directory_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "made" / "by" / "the" / "store"
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        created = act.ensure_receipt_secret()
        assert store._SECRET_SHAPE.fullmatch(created)
        assert statmodule.S_IMODE((directory / act.SECRET_FILENAME).stat().st_mode) == 0o600
        assert statmodule.S_IMODE(directory.stat().st_mode) == 0o700


class TestTheTwoScalarsAreExactCounts:
    @pytest.fixture
    def audit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
        return audited_corpus(
            tmp_path / "receipts", threshold_corpus(LOCAL), secret=LOCAL, monkeypatch=monkeypatch
        )

    @pytest.mark.parametrize(
        "value",
        [True, False, -1, -5, 2.5, "3", "many", None, [1, 2], {"a": 1}],
        ids=[
            "true",
            "false",
            "minus-one",
            "minus-five",
            "float",
            "digit-string",
            "word",
            "none",
            "list",
            "mapping",
        ],
    )
    def test_unresolved_intents_refuses_anything_that_is_not_a_count(
        self, audit: Any, value: Any
    ) -> None:
        with pytest.raises((TypeError, ValueError, qual.QualificationInputInvalid)):
            qual.evaluate(audit, unresolved_intents=value)

    @pytest.mark.parametrize("value", [0, 1, 7], ids=["zero", "one", "seven"])
    def test_a_real_count_is_accepted_and_a_positive_one_blocks(
        self, audit: Any, value: int
    ) -> None:
        document = qual.evaluate(audit, unresolved_intents=value)
        assert document["eligible_for_human_promotion_review"] is (value == 0)

    def test_none_never_means_zero(self, audit: Any) -> None:
        with pytest.raises((TypeError, ValueError, qual.QualificationInputInvalid)):
            qual.evaluate(audit, unresolved_intents=None)  # type: ignore[arg-type]

    def test_the_unverifiable_count_comes_from_the_audit_and_stays_a_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        audit = audited_corpus(
            tmp_path / "receipts",
            threshold_corpus(LOCAL),
            secret=LOCAL,
            monkeypatch=monkeypatch,
            unreadable=3,
        )
        assert audit.unverifiable == 3
        document = qual.evaluate(audit)
        assert document["qualification_unverifiable_receipts"] == 3
        assert isinstance(document["qualification_unverifiable_receipts"], int)
        assert document["qualification_unverifiable_receipts"] >= 0
