"""`receipts reconcile`: the operator's only way out of the crash window.

Why this suite exists
---------------------
An intent is written and ``fsync``-ed *before* the request, and removed once its
receipt is durably published. Between those two moments the process can die, and
then the intent survives while the receipt exists — a state that blocks the
human-review gate for ever, because an unresolved intent is an evidence conflict.

``reconcile_intents()`` was written for exactly that window, is documented in §3.2
of the protocol as *the* accounting resolution, and was tested — but no CLI command
called it. So the documented recovery was not runnable, which is the same defect the
tredecies register recorded as closed for the quarantine one level down: « v5
documentait une sortie de secours sans la rendre exécutable ». An operator's only
remaining options were to edit Python or to delete the intent by hand, and deleting
an intent by hand is precisely what reopens the gate without evidence.

This suite drives the command, not the function. Everything is synthetic: the secret
is a fixed test value, the directory is a fresh ``tmp_path``, and no receipt, key or
payload of a real installation is ever read. No socket is opened — a test asserts it.
"""

from __future__ import annotations

import errno
import json
import os
import re
import socket
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from betmaxxing.providers.the_odds_api import receipt_store as store
from betmaxxing.providers.the_odds_api.activation import ensure_utc
from helpers_receipt_boundary import install_secret

runner = CliRunner()

LOCAL = "0011223344556677889900aabbccddeeff00112233445566778899aabbccddee"
FOREIGN = "ffeeddccbbaa00998877665544332211ffeeddccbbaa00998877665544332200"
ATTEMPT = "aa11bb22cc33dd44"

#: Strings a hostile intent or receipt could carry. None may reach any rendering.
SENTINELS = (
    "QQRECONCILECOMMAND01",
    "QQRECONCILESPORT02",
    "QQRECONCILEBOOK03",
    "QQRECONCILESTATE04",
)

ANSI = re.compile(r"\x1b\[")


# ---------------------------------------------------------------------------
# Fixtures — the same synthetic boundary the intent contract uses
# ---------------------------------------------------------------------------
@pytest.fixture
def receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "receipts"
    directory.mkdir()
    install_secret(directory, LOCAL)
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
    monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
    monkeypatch.setenv("BETMAXXING_MODE", "paper")
    return directory


def attempt(**over: Any) -> act.Attempt:
    now = ensure_utc(act._clock())
    fields: dict[str, Any] = {
        "command": "core",
        "sport": "soccer_probe",
        "bookmaker": "probebook",
        "window": (now, now + timedelta(hours=24)),
        "ceiling": 1,
        "now": now,
        "event_id": "EV-PROBE-1",
        "event_tags": [act.event_tag("EV-PROBE-1", LOCAL)],
        "attempt_id": ATTEMPT,
    }
    fields.update(over)
    return act.Attempt(**fields)


def receipt_of(**over: Any) -> dict[str, Any]:
    """A signed, current, well-formed `core` receipt for :data:`ATTEMPT`."""
    now = max(
        ensure_utc(act._clock()),
        ensure_utc(datetime.fromisoformat(qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC)),
    )
    document: dict[str, Any] = {
        "schema_version": act.RECEIPT_SCHEMA_VERSION,
        "qualification_protocol_version": qual.PROVIDER_VALIDATION_PROTOCOL_VERSION,
        "provider_adapter_evidence_version": qual.PROVIDER_ADAPTER_EVIDENCE_VERSION,
        "receipt_id": ATTEMPT,
        "command": "core",
        "status": "CORE_LIVE_VERIFIED",
        "recorded_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=6)).isoformat(),
        "sport_key": "soccer_probe",
        "bookmaker": "probebook",
        "event_tag": act.event_tag("EV-PROBE-1", LOCAL),
        "network_attempted": True,
        "may_have_reached_provider": True,
        "attempts": 1,
        "estimated_credits": 1,
        "observed_credits": 1,
        "accounted_credits": 1,
        "markets_requested": ["h2h"],
        "market_states": {"h2h": "OBSERVED_MAPPED"},
        "markets_mapped": ["h2h"],
        "markets_observed": ["h2h"],
        "markets_rejected": [],
        "markets_absent": [],
        "markets_not_evaluated": [],
        "selections_mapped": 3,
        "freshness": {"h2h": 300},
        "mapping_rejections": [],
        "quota_remaining": 400,
        "bookmaker_state": str(act.BookmakerState.OBSERVED),
    }
    document.update(over)
    signature = over.pop("__signature__", None)
    secret = over.pop("__secret__", LOCAL)
    document.pop("__signature__", None)
    document.pop("__secret__", None)
    if signature is None:
        document[act.SIGNATURE_FIELD] = act.sign_receipt(document, secret)
    elif signature is not False:
        document[act.SIGNATURE_FIELD] = signature
    return document


def publish(directory: Path, document: dict[str, Any], name: str | None = None) -> Path:
    """Write a receipt the way the audit will find it: a regular, durable file."""
    stem = name or f"20260901T000000-core-{document.get('receipt_id', 'x')}.json"
    path = directory / stem
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    return path


def pending() -> int:
    return len(act.unresolved_intents())


def reconcile(*extra: str) -> Any:
    return runner.invoke(act.app, ["receipts", "reconcile", *extra])


def payload_of(result: Any) -> dict[str, Any]:
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# The command exists, and it is the operator's route
# ---------------------------------------------------------------------------
class TestTheCommandIsReachable:
    """Red on 269f339: `reconcile_intents()` existed, no command called it."""

    def test_receipts_reconcile_is_a_command(self, receipts: Path) -> None:
        result = runner.invoke(act.app, ["receipts", "--help"])
        assert result.exit_code == 0, result.stdout
        assert "reconcile" in result.stdout

    def test_it_runs_on_an_empty_installation(self, receipts: Path) -> None:
        result = reconcile()
        assert result.exit_code == 0, result.stdout
        assert result.stdout.strip() != ""

    def test_it_has_a_json_variant(self, receipts: Path) -> None:
        result = reconcile("--json")
        assert result.exit_code == 0, result.stdout
        payload_of(result)  # valid JSON or this raises

    @pytest.mark.parametrize(
        "field",
        [
            "boundary_state",
            "verified_receipts_considered",
            "resolved_intents",
            "remaining_intents",
            "qualification_state",
            "eligible_for_human_promotion_review",
        ],
    )
    def test_the_json_publishes_the_required_field(self, receipts: Path, field: str) -> None:
        assert field in payload_of(reconcile("--json"))

    def test_the_human_rendering_names_the_same_facts(self, receipts: Path) -> None:
        text = reconcile().stdout
        for needle in ("Frontière", "Intents résolus", "Intents restants"):
            assert needle in text, text

    @pytest.mark.parametrize("flag", [(), ("--json",)])
    def test_neither_rendering_emits_ansi(self, receipts: Path, flag: tuple[str, ...]) -> None:
        assert not ANSI.search(reconcile(*flag).stdout)


# ---------------------------------------------------------------------------
# §4 — the mandatory recovery case
# ---------------------------------------------------------------------------
class TestTheCrashWindowIsRecoverable:
    """intent fsync-ed → receipt durable → crash before resolution → reconcile."""

    def test_exactly_one_intent_is_resolved(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        assert pending() == 1
        before = qual.evaluate(act.audit_receipts(), unresolved_intents=pending())
        assert before["eligible_for_human_promotion_review"] is False
        assert before["qualification_state"] == "EVIDENCE_CONFLICT"

        document = payload_of(reconcile("--json"))
        assert document["resolved_intents"] == 1
        assert document["remaining_intents"] == 0
        assert document["boundary_state"] == "AVAILABLE"
        assert document["verified_receipts_considered"] == 1

    def test_the_receipt_survives_and_stays_verified(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        reconcile("--json")
        audit = act.audit_receipts()
        assert len(audit.batch) == 1
        assert audit.unverifiable == 0
        assert audit.batch[0]["receipt_id"] == ATTEMPT

    def test_no_credit_is_added_or_changed(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        before = [dict(r) for r in act.audit_receipts().batch]
        reconcile("--json")
        after = [dict(r) for r in act.audit_receipts().batch]
        assert before == after
        for receipt in after:
            assert receipt["estimated_credits"] == 1
            assert receipt["observed_credits"] == 1
            assert receipt["accounted_credits"] == 1

    def test_the_second_reconciliation_resolves_nothing(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        assert payload_of(reconcile("--json"))["resolved_intents"] == 1
        again = payload_of(reconcile("--json"))
        assert again["resolved_intents"] == 0
        assert again["remaining_intents"] == 0

    def test_the_artificial_conflict_is_gone_afterwards(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        document = payload_of(reconcile("--json"))
        assert document["qualification_state"] != "EVIDENCE_CONFLICT"
        recomputed = qual.evaluate(act.audit_receipts(), unresolved_intents=pending())
        assert recomputed["qualification_state"] == document["qualification_state"]
        assert recomputed["evidence_conflicts"] == []

    def test_one_verified_receipt_does_not_qualify_anything(self, receipts: Path) -> None:
        """Recovery is accounting, not evidence: the gate stays shut on one event."""
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        document = payload_of(reconcile("--json"))
        assert document["eligible_for_human_promotion_review"] is False
        assert document["qualification_state"] == "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# §4 — no forgery resolves an intent
# ---------------------------------------------------------------------------
class TestNoForgeryResolvesAnIntent:
    """Each case leaves the intent exactly where it was."""

    def _run(self, receipts: Path, document: dict[str, Any] | None, **kw: Any) -> dict[str, Any]:
        act.publish_intent(attempt())
        if document is not None:
            publish(receipts, document, **kw)
        assert pending() == 1
        result = reconcile("--json")
        assert result.exit_code == 0, result.stdout
        return payload_of(result)

    def test_an_unsigned_receipt_resolves_nothing(self, receipts: Path) -> None:
        unsigned = receipt_of()
        unsigned.pop(act.SIGNATURE_FIELD)
        assert self._run(receipts, unsigned)["resolved_intents"] == 0
        assert pending() == 1

    def test_a_foreign_key_resolves_nothing(self, receipts: Path) -> None:
        document = receipt_of()
        document.pop(act.SIGNATURE_FIELD)
        document[act.SIGNATURE_FIELD] = act.sign_receipt(document, FOREIGN)
        assert self._run(receipts, document)["resolved_intents"] == 0
        assert pending() == 1

    @pytest.mark.parametrize(
        ("label", "over"),
        [
            ("another sport", {"sport_key": "tennis_elsewhere"}),
            ("another bookmaker", {"bookmaker": "otherbook"}),
            ("another command", {"command": "additional"}),
            ("another event tag", {"event_tag": "9" * 32}),
            ("a cost above the ceiling", {"accounted_credits": 5}),
        ],
    )
    def test_a_different_material_scope_resolves_nothing(
        self, receipts: Path, label: str, over: dict[str, Any]
    ) -> None:
        assert self._run(receipts, receipt_of(**over))["resolved_intents"] == 0, label
        assert pending() == 1, label

    @pytest.mark.parametrize(
        ("label", "over"),
        [
            ("an earlier protocol", {"qualification_protocol_version": 6}),
            ("a later protocol", {"qualification_protocol_version": 8}),
            ("an earlier schema", {"schema_version": 3}),
            ("another adapter evidence version", {"provider_adapter_evidence_version": 0}),
        ],
    )
    def test_an_incompatible_lineage_resolves_nothing(
        self, receipts: Path, label: str, over: dict[str, Any]
    ) -> None:
        assert self._run(receipts, receipt_of(**over))["resolved_intents"] == 0, label
        assert pending() == 1, label

    @pytest.mark.parametrize(
        ("label", "over"),
        [
            ("an unknown status", {"status": "SOMETHING_ELSE"}),
            ("an unknown command", {"command": "sync"}),
            ("a non-persistable couple", {"command": "discover", "status": "CORE_LIVE_VERIFIED"}),
        ],
    )
    def test_an_unknown_couple_resolves_nothing(
        self, receipts: Path, label: str, over: dict[str, Any]
    ) -> None:
        assert self._run(receipts, receipt_of(**over))["resolved_intents"] == 0, label
        assert pending() == 1, label

    def test_an_identifier_only_match_resolves_nothing(self, receipts: Path) -> None:
        """The v6 defect, as a permanent test: two keys used to be enough."""
        assert self._run(receipts, {"receipt_id": ATTEMPT})["resolved_intents"] == 0
        assert pending() == 1

    def test_an_empty_receipt_resolves_nothing(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        (receipts / "20260901T000000-core-empty.json").write_text("", encoding="utf-8")
        assert payload_of(reconcile("--json"))["resolved_intents"] == 0
        assert pending() == 1

    def test_an_unreadable_receipt_resolves_nothing(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        (receipts / "20260901T000000-core-broken.json").write_text("{ trunc", encoding="utf-8")
        assert payload_of(reconcile("--json"))["resolved_intents"] == 0
        assert pending() == 1

    def test_no_receipt_at_all_resolves_nothing(self, receipts: Path) -> None:
        assert self._run(receipts, None)["resolved_intents"] == 0
        assert pending() == 1

    def test_a_symlinked_receipt_resolves_nothing(self, receipts: Path, tmp_path: Path) -> None:
        act.publish_intent(attempt())
        outside = tmp_path / "planted.json"
        outside.write_text(json.dumps(receipt_of(), indent=2, sort_keys=True), encoding="utf-8")
        (receipts / "20260901T000000-core-link.json").symlink_to(outside)
        assert payload_of(reconcile("--json"))["resolved_intents"] == 0
        assert pending() == 1


# ---------------------------------------------------------------------------
# §5 — the boundary, the secret, and failing closed
# ---------------------------------------------------------------------------
class TestTheBoundaryAndTheSecret:
    def test_an_absent_directory_is_reported_and_resolves_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(tmp_path / "nowhere"))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        result = reconcile("--json")
        assert result.exit_code != 0, result.stdout
        document = payload_of(result)
        assert document["boundary_state"] == "ABSENT"
        assert document["resolved_intents"] == 0

    def test_the_absent_directory_is_not_created_by_looking(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "nowhere"
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(target))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        reconcile("--json")
        assert not target.exists()

    def test_a_symlinked_directory_is_unavailable_and_blocks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = tmp_path / "real"
        real.mkdir()
        install_secret(real, LOCAL)
        link = tmp_path / "link"
        link.symlink_to(real)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(link))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        result = reconcile("--json")
        assert result.exit_code != 0, result.stdout
        document = payload_of(result)
        assert document["boundary_state"] == "UNAVAILABLE"
        assert document["resolved_intents"] == 0

    def test_an_available_directory_reports_available(self, receipts: Path) -> None:
        assert payload_of(reconcile("--json"))["boundary_state"] == "AVAILABLE"

    def test_a_missing_secret_fails_closed(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        (receipts / act.SECRET_FILENAME).unlink()
        result = reconcile("--json")
        assert result.exit_code != 0, result.stdout
        assert payload_of(result)["resolved_intents"] == 0
        assert pending() == 1

    @pytest.mark.parametrize("bad", ["", "\n", "secret", "z" * 64, LOCAL.upper(), LOCAL[:63]])
    def test_an_invalid_secret_fails_closed(self, receipts: Path, bad: str) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        path = receipts / act.SECRET_FILENAME
        path.write_text(bad, encoding="utf-8")
        os.chmod(path, 0o600)
        result = reconcile("--json")
        assert result.exit_code != 0, result.stdout
        assert payload_of(result)["resolved_intents"] == 0
        assert pending() == 1

    @pytest.mark.skipif(os.geteuid() == 0, reason="uid 0 bypasses POSIX permissions")
    @pytest.mark.parametrize("mode", [0o640, 0o644, 0o666, 0o604])
    def test_a_world_or_group_readable_secret_fails_closed(self, receipts: Path, mode: int) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        os.chmod(receipts / act.SECRET_FILENAME, mode)
        result = reconcile("--json")
        assert result.exit_code != 0, result.stdout
        assert pending() == 1

    def test_no_secret_is_ever_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A recovery path must not bring a key into existence just by looking."""
        directory = tmp_path / "receipts"
        directory.mkdir()
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        reconcile("--json")
        assert not (directory / act.SECRET_FILENAME).exists()
        assert sorted(p.name for p in directory.iterdir()) == []

    def test_a_symlinked_intent_is_not_followed(self, receipts: Path, tmp_path: Path) -> None:
        publish(receipts, receipt_of())
        outside = tmp_path / "planted.intent"
        outside.write_text("{}", encoding="utf-8")
        (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").symlink_to(outside)
        result = reconcile("--json")
        assert result.exit_code == 0, result.stdout
        assert payload_of(result)["resolved_intents"] == 0


# ---------------------------------------------------------------------------
# §5 — storage faults become typed business errors
# ---------------------------------------------------------------------------
class TestStorageFaultsFailClosed:
    @pytest.mark.parametrize(
        ("call", "code"),
        [
            ("unlink", errno.EACCES),
            ("unlink", errno.EROFS),
            ("unlink", errno.EIO),
            ("fsync", errno.EIO),
            ("fsync", errno.ENOSPC),
            ("read", errno.EIO),
            ("read", errno.ENOSPC),
            ("read", errno.EACCES),
        ],
    )
    def test_a_storage_fault_is_typed_and_leaves_the_intent(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch, call: str, code: int
    ) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())

        if call == "unlink":
            real = os.unlink

            def faulty(path: Any, *a: Any, **k: Any) -> Any:
                if str(path).endswith(store.INTENT_SUFFIX):
                    raise OSError(code, os.strerror(code))
                return real(path, *a, **k)

            monkeypatch.setattr(os, "unlink", faulty)
        elif call == "fsync":

            def faulty_fsync(fd: int) -> None:
                raise OSError(code, os.strerror(code))

            monkeypatch.setattr(os, "fsync", faulty_fsync)
        else:
            # At the `os.read` level, where the boundary genuinely lets an OSError
            # through: `read_text` wraps a refused *object* but not a failing *disk*.
            real_os_read = os.read
            state = {"armed": True}

            def faulty_os_read(fd: int, length: int) -> bytes:
                if state["armed"]:
                    state["armed"] = False
                    raise OSError(code, os.strerror(code))
                return real_os_read(fd, length)

            monkeypatch.setattr(os, "read", faulty_os_read)

        result = reconcile("--json")
        assert result.exit_code != 0, result.stdout
        assert result.stdout.strip() != ""
        assert not ANSI.search(result.stdout)
        if call != "fsync":
            # `resolve_intent` unlinks and *then* fsyncs, so an fsync fault leaves the
            # entry already removed and merely not durably so. Asserting the file still
            # exists there would be asserting the wrong thing; what matters, and is
            # asserted for every case, is that the failure is typed and reported.
            assert (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()

    @pytest.mark.parametrize("code", [errno.EACCES, errno.EPERM])
    def test_an_intent_the_boundary_refuses_keeps_blocking_without_aborting(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch, code: int
    ) -> None:
        """A refused *object* is not a failing *disk*, and the two differ on purpose.

        ``open_file`` turns an ``EACCES`` at open into :class:`DirectoryUnsafe`, so the
        intent is an object the boundary declines to follow. It must keep blocking the
        gate — reduced to a category, never echoed — while the reconciliation of the
        other intents continues. Aborting here would let one unreadable file deny the
        recovery of every other attempt.
        """
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        real_open_file = store.SecureDirectory.open_file

        def refuse(self: Any, name: str, *, flags: int, mode: int = 0o600) -> int:
            if name.endswith(store.INTENT_SUFFIX):
                raise store.DirectoryUnsafe(f"{name} n'est pas lisible sûrement.")
            return real_open_file(self, name, flags=flags, mode=mode)

        monkeypatch.setattr(store.SecureDirectory, "open_file", refuse)
        result = reconcile("--json")
        assert result.exit_code == 0, result.stdout
        document = payload_of(result)
        assert document["resolved_intents"] == 0
        assert document["remaining_intents"] == 1
        assert (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()

    def test_a_directory_substituted_mid_operation_is_still_read_through_the_descriptor(
        self, receipts: Path, tmp_path: Path
    ) -> None:
        """The descriptor is opened once; renaming the path cannot redirect it."""
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        elsewhere = tmp_path / "swapped"
        os.rename(receipts, elsewhere)
        hostile = tmp_path / "receipts"
        hostile.mkdir()
        install_secret(hostile, FOREIGN)
        result = reconcile("--json")
        # Whatever it reports, it must not have resolved an intent out of the
        # substituted directory, and the real intent must survive there.
        assert payload_of(result)["resolved_intents"] == 0
        assert (elsewhere / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()


# ---------------------------------------------------------------------------
# §5 — concurrency, isolation, and no leakage
# ---------------------------------------------------------------------------
class TestConcurrencyAndIsolation:
    def test_two_concurrent_reconciliations_resolve_it_once(self, receipts: Path) -> None:
        import subprocess
        import sys

        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        script = (
            "from typer.testing import CliRunner;"
            "from betmaxxing.providers.the_odds_api import activation as act;"
            "r=CliRunner().invoke(act.app,['receipts','reconcile','--json']);"
            "import json,sys;"
            "sys.stdout.write(str(json.loads(r.stdout)['resolved_intents']))"
        )
        env = {**os.environ, act.RECEIPT_DIR_VARIABLE: str(receipts)}
        env.pop(act.SECRET_VARIABLE, None)
        runs = [
            subprocess.run(
                [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=False
            )
            for _ in range(2)
        ]
        totals = [int(run.stdout.strip() or 0) for run in runs if run.returncode == 0]
        assert sum(totals) == 1, [r.stdout + r.stderr for r in runs]
        assert pending() == 0

    def test_the_command_opens_no_socket(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*a: Any, **k: Any) -> Any:
            raise AssertionError("reconcile must not touch the network")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)
        monkeypatch.setattr(socket, "getaddrinfo", refuse)
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        assert reconcile("--json").exit_code == 0

    def test_the_command_reads_no_provider_key(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("THE_ODDS_API_KEY", "QQPROVIDERKEYSENTINEL")
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        result = reconcile("--json")
        assert "QQPROVIDERKEYSENTINEL" not in result.stdout

    def test_no_secret_value_reaches_either_rendering(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        for flag in ((), ("--json",)):
            text = reconcile(*flag).stdout
            assert LOCAL not in text
            assert act.SECRET_FILENAME not in text

    def test_no_hostile_intent_content_reaches_either_rendering(self, receipts: Path) -> None:
        publish(receipts, receipt_of())
        (receipts / f"{'b' * 16}{store.INTENT_SUFFIX}").write_text(
            json.dumps(
                {
                    "intent_version": 1,
                    "attempt_id": SENTINELS[0],
                    "command": SENTINELS[0],
                    "state": SENTINELS[3],
                    "sport_key": SENTINELS[1],
                    "bookmaker": SENTINELS[2],
                    "event_tag": "a" * 32,
                    "prepared_at": "2026-09-01T10:00:00+00:00",
                    "max_credits": 1,
                }
            ),
            encoding="utf-8",
        )
        for flag in ((), ("--json",)):
            text = reconcile(*flag).stdout
            for sentinel in SENTINELS:
                assert sentinel not in text, (flag, sentinel, text)

    def test_no_receipt_path_is_published(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        for flag in ((), ("--json",)):
            assert str(receipts) not in reconcile(*flag).stdout


# ---------------------------------------------------------------------------
# The invariant the whole command exists to preserve
# ---------------------------------------------------------------------------
class TestNoIntentIsRemovedWithoutEvidence:
    def test_the_quarantine_still_refuses_an_intent(self, receipts: Path) -> None:
        """The other door stays shut: recovery is reconciliation, not deletion."""
        act.publish_intent(attempt())
        name = f"{ATTEMPT}{store.INTENT_SUFFIX}"
        for extra in ([], ["--force"]):
            result = runner.invoke(
                act.app, ["receipts", "quarantine", "--name", name, *extra, "--json"]
            )
            assert result.exit_code != 0, result.stdout
        assert (receipts / name).exists()

    def test_the_command_never_unlinks_an_unmatched_intent(self, receipts: Path) -> None:
        """Two intents, one receipt: exactly the matching one goes."""
        act.publish_intent(attempt())
        other = "cc33dd44ee55ff66"
        act.publish_intent(attempt(attempt_id=other, event_id="EV-PROBE-2", event_tags=[]))
        publish(receipts, receipt_of())
        assert pending() == 2
        document = payload_of(reconcile("--json"))
        assert document["resolved_intents"] == 1
        assert document["remaining_intents"] == 1
        assert not (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()
        assert (receipts / f"{other}{store.INTENT_SUFFIX}").exists()

    def test_the_secret_file_is_never_touched(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        path = receipts / act.SECRET_FILENAME
        before = (path.read_text(encoding="utf-8"), stat.S_IMODE(path.stat().st_mode))
        reconcile("--json")
        after = (path.read_text(encoding="utf-8"), stat.S_IMODE(path.stat().st_mode))
        assert before == after


# ---------------------------------------------------------------------------
# §6 — the documents say what the code does
# ---------------------------------------------------------------------------
class TestTheDocumentsPublishTheBudgetAndTheRecovery:
    ROOT = Path(act.__file__).resolve().parents[4]

    def _read(self, relative: str) -> str:
        return " ".join((self.ROOT / relative).read_text(encoding="utf-8").split())

    @pytest.mark.parametrize(
        "relative",
        [
            "docs/provider-validation-protocol.md",
            "docs/provider-activation.md",
            "docs/decisions.md",
        ],
    )
    def test_every_document_names_the_decision(self, relative: str) -> None:
        assert "D-079" in self._read(relative)

    @pytest.mark.parametrize(
        "relative",
        ["docs/provider-validation-protocol.md", "docs/provider-activation.md"],
    )
    def test_the_recovery_command_is_published(self, relative: str) -> None:
        text = self._read(relative)
        assert "receipts reconcile" in text
        assert "sans en créer un" in text or "sans être créé" in text

    def test_the_protocol_separates_the_two_tranches(self) -> None:
        text = self._read("docs/provider-validation-protocol.md")
        assert "Tranche 1" in text and "Tranche 2" in text
        for number in ("6", "10", "16"):
            assert number in text
        assert "3 sur 8" in text

    def test_the_protocol_warns_that_plan_six_is_one_event(self) -> None:
        text = self._read("docs/provider-validation-protocol.md")
        assert "plan --max-credits 6" in text
        assert "un seul événement" in text

    def test_the_protocol_refuses_satisfaction_by_repetition(self) -> None:
        text = self._read("docs/provider-validation-protocol.md")
        assert "ne se satisfont pas par répétition" in text
        assert "qualification_exact_duplicate_copies" in text

    def test_the_documents_forbid_manual_intent_deletion(self) -> None:
        for relative in ("docs/provider-validation-protocol.md", "docs/provider-activation.md"):
            text = self._read(relative)
            assert "interdite" in text or "interdit" in text
            assert "--force" in text

    def test_no_document_promises_a_qualification_from_one_tranche(self) -> None:
        text = self._read("docs/provider-validation-protocol.md")
        assert "Aucun résultat intermédiaire n'est une qualification" in text
        assert "CRITERIA_MET_AWAITING_HUMAN_REVIEW" in text

    def test_the_derived_budget_still_matches_the_documented_total(self) -> None:
        """The split is a schedule, not a discount: the contractual total stays 16."""
        budget = qual.campaign_budget()
        assert budget["contractual_credits"] == 16
        assert budget["cli_invocations"] == 12
        assert qual.STEP_CEILINGS["core"] * 6 == 6
        assert qual.STEP_CEILINGS["additional"] * 2 == 10
