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
import tempfile
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


#: Inside the protocol 8 manifest. These were a scope of their own until v8, when
#: a receipt naming another competition or another bookmaker became a campaign
#: conflict — which would have made every corpus here assert the wrong thing.
_SPORT = "soccer_epl"
_BOOKMAKER = "pinnacle"


def attempt(**over: Any) -> act.Attempt:
    now = ensure_utc(act._clock())
    fields: dict[str, Any] = {
        "command": "core",
        "sport": _SPORT,
        "bookmaker": _BOOKMAKER,
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
        "sport_key": _SPORT,
        "bookmaker": _BOOKMAKER,
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
            ("a later protocol", {"qualification_protocol_version": 9}),
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
        assert document["resolved_intents"] is None
        assert document["remaining_intents"] is None
        assert document["intent_counts_state"] == act.INTENT_COUNTS_UNESTABLISHED

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
        assert document["resolved_intents"] is None
        assert document["remaining_intents"] is None
        assert document["intent_counts_state"] == act.INTENT_COUNTS_UNESTABLISHED

    def test_an_available_directory_reports_available(self, receipts: Path) -> None:
        assert payload_of(reconcile("--json"))["boundary_state"] == "AVAILABLE"

    def test_a_missing_secret_fails_closed(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        (receipts / act.SECRET_FILENAME).unlink()
        result = reconcile("--json")
        assert result.exit_code != 0, result.stdout
        document = payload_of(result)
        assert document["resolved_intents"] is None
        assert document["remaining_intents"] is None
        assert document["intent_counts_state"] == act.INTENT_COUNTS_UNESTABLISHED
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
        document = payload_of(result)
        assert document["resolved_intents"] is None
        assert document["remaining_intents"] is None
        assert document["intent_counts_state"] == act.INTENT_COUNTS_UNESTABLISHED
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
        document = payload_of(result)
        on_disk = (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()

        # Whatever failed, the report is confronted with the directory rather than
        # trusted: the defect this replaces was a refusal publishing its initialised
        # zeros as though it had counted.
        if call == "read":
            # The fault lands before the inventory, so nothing is established. Not
            # zero — nothing.
            assert on_disk
            assert document["resolved_intents"] is None
            assert document["remaining_intents"] is None
            assert document["intent_counts_state"] == act.INTENT_COUNTS_UNESTABLISHED
            assert document["intent_resolution_durability"] == act.DURABILITY_NOT_ATTEMPTED
        elif call == "unlink":
            # Nothing was removed and the inventory still answers, so both counts are
            # real and they agree with the directory.
            assert on_disk
            assert document["resolved_intents"] == 0
            assert document["remaining_intents"] == 1
            assert document["intent_counts_state"] == act.INTENT_COUNTS_ESTABLISHED
            assert document["intent_resolution_durability"] == act.DURABILITY_NOT_ATTEMPTED
        else:
            # `unlink` succeeded and the `fsync` after it did not. The entry *is* gone,
            # so the report says so, and marks the durability of that removal — not the
            # removal itself — as the thing that is not established.
            assert not on_disk
            assert document["resolved_intents"] == 1
            assert document["remaining_intents"] == 0
            assert document["intent_counts_state"] == act.INTENT_COUNTS_ESTABLISHED
            assert document["intent_resolution_durability"] == act.DURABILITY_UNCERTAIN

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


# ---------------------------------------------------------------------------
# §quater — every published count is confronted with the directory
# ---------------------------------------------------------------------------
REFUSED_STEMS = (
    "bb22cc33dd44ee55",  # a symlink the boundary declines to follow
    "cc33dd44ee55ff66",  # a FIFO, which must not be opened and must not hang
    "dd44ee55ff6600a1",  # bytes that are not UTF-8
    "ee55ff6600a1b2c3",  # truncated JSON
    "ff6600a1b2c3d4e5",  # well-formed JSON carrying hostile strings
)


def rendered(value: Any) -> str:
    """The human token for a JSON value: a number, or the words for its absence."""
    return act.UNESTABLISHED_COUNT if value is None else str(value)


def plant_refused_intents(receipts: Path, tmp_path: Path) -> None:
    """Five intents no receipt can resolve, each unreadable in a different way."""
    outside = tmp_path / "planted.intent"
    outside.write_text("{}", encoding="utf-8")
    (receipts / f"{REFUSED_STEMS[0]}{store.INTENT_SUFFIX}").symlink_to(outside)
    os.mkfifo(receipts / f"{REFUSED_STEMS[1]}{store.INTENT_SUFFIX}")
    (receipts / f"{REFUSED_STEMS[2]}{store.INTENT_SUFFIX}").write_bytes(b"\xff\xfe\x00\x01")
    (receipts / f"{REFUSED_STEMS[3]}{store.INTENT_SUFFIX}").write_text("{ trunc", encoding="utf-8")
    (receipts / f"{REFUSED_STEMS[4]}{store.INTENT_SUFFIX}").write_text(
        json.dumps({"attempt_id": SENTINELS[0], "command": SENTINELS[1], "sport": SENTINELS[2]}),
        encoding="utf-8",
    )


class TestNoCountIsPublishedBeforeItIsTaken:
    """Red on 69c69b2: the refusal paths published their initialised zeros.

    ``reconcile_intents_report`` built a document holding ``resolved_intents = 0`` and
    ``remaining_intents = 0`` and every ``except`` branch raised with it, so a command
    that never opened the directory still printed « Intents restants : 0 » — from a
    directory it had not read, while an intent sat in it. That is the same category of
    statement D-077 gave ``BoundaryState.UNAVAILABLE`` its own value to avoid, one
    level up: a count nobody took, wearing the appearance of a measurement.

    Every test here compares what the report says with what the directory holds.
    """

    # -- counts that were never taken ---------------------------------------
    def test_a_missing_secret_publishes_no_count_at_all(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        (receipts / act.SECRET_FILENAME).unlink()
        result = reconcile("--json")
        document = payload_of(result)
        assert result.exit_code != 0, result.stdout
        # The intent is physically there; the old report said « 0 restant » anyway.
        assert (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()
        assert document["resolved_intents"] is None
        assert document["remaining_intents"] is None
        assert document["intent_counts_state"] == act.INTENT_COUNTS_UNESTABLISHED
        assert document["intent_resolution_durability"] == act.DURABILITY_NOT_ATTEMPTED

    def test_a_read_fault_before_the_inventory_establishes_nothing(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        real_os_read = os.read
        state = {"armed": True}

        def faulty_os_read(fd: int, length: int) -> bytes:
            if state["armed"]:
                state["armed"] = False
                raise OSError(errno.EIO, os.strerror(errno.EIO))
            return real_os_read(fd, length)

        monkeypatch.setattr(os, "read", faulty_os_read)
        result = reconcile("--json")
        document = payload_of(result)
        assert result.exit_code != 0, result.stdout
        assert (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()
        assert document["resolved_intents"] is None
        assert document["remaining_intents"] is None
        assert document["intent_counts_state"] == act.INTENT_COUNTS_UNESTABLISHED

    @pytest.mark.parametrize("flag", [(), ("--json",)])
    def test_an_absent_boundary_invents_nothing_and_creates_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: tuple[str, ...]
    ) -> None:
        target = tmp_path / "nowhere"
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(target))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        result = reconcile(*flag)
        assert result.exit_code != 0, result.stdout
        assert not target.exists()
        if flag:
            document = payload_of(result)
            assert document["resolved_intents"] is None
            assert document["remaining_intents"] is None
            assert document["intent_counts_state"] == act.INTENT_COUNTS_UNESTABLISHED
        else:
            assert f"Intents restants     : {act.UNESTABLISHED_COUNT}" in result.stdout

    @pytest.mark.parametrize(
        "field", ["resolved_intents", "remaining_intents", "verified_receipts_considered"]
    )
    def test_no_refusal_path_ever_publishes_an_unmeasured_zero(
        self, receipts: Path, field: str
    ) -> None:
        """Zero is a measurement. A refusal before the inventory has not made one."""
        act.publish_intent(attempt())
        (receipts / act.SECRET_FILENAME).unlink()
        assert payload_of(reconcile("--json"))[field] != 0

    # -- a count taken is a count published ---------------------------------
    def test_a_success_without_intents_publishes_real_zeros(self, receipts: Path) -> None:
        result = reconcile("--json")
        document = payload_of(result)
        assert result.exit_code == 0, result.stdout
        assert document["resolved_intents"] == 0
        assert document["remaining_intents"] == 0
        assert document["intent_counts_state"] == act.INTENT_COUNTS_ESTABLISHED
        assert document["intent_resolution_durability"] == act.DURABILITY_DURABLE
        assert list(receipts.glob(f"*{store.INTENT_SUFFIX}")) == []

    def test_a_recovery_publishes_counts_that_match_the_directory(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        document = payload_of(reconcile("--json"))
        assert document["resolved_intents"] == 1
        assert document["remaining_intents"] == 0
        assert document["intent_counts_state"] == act.INTENT_COUNTS_ESTABLISHED
        assert document["intent_resolution_durability"] == act.DURABILITY_DURABLE
        assert not (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()
        assert len(list(receipts.glob(f"*{store.INTENT_SUFFIX}"))) == 0

    def test_mixed_refused_intents_are_counted_exactly(
        self, receipts: Path, tmp_path: Path
    ) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        plant_refused_intents(receipts, tmp_path)
        result = reconcile("--json")
        document = payload_of(result)
        assert result.exit_code == 0, result.stdout
        assert document["resolved_intents"] == 1
        assert document["remaining_intents"] == 5
        assert document["intent_counts_state"] == act.INTENT_COUNTS_ESTABLISHED
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert document["eligible_for_human_promotion_review"] is False
        # The five that could not be resolved are all still there, and the one that
        # could is gone: the two counts are the directory, not an estimate of it.
        assert not (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()
        for stem in REFUSED_STEMS:
            path = receipts / f"{stem}{store.INTENT_SUFFIX}"
            assert path.exists() or path.is_symlink(), stem

    def test_no_hostile_string_reaches_either_rendering(
        self, receipts: Path, tmp_path: Path
    ) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        plant_refused_intents(receipts, tmp_path)
        for flag in ((), ("--json",)):
            text = reconcile(*flag).stdout
            for sentinel in SENTINELS:
                assert sentinel not in text, (flag, sentinel)

    # -- the partial result --------------------------------------------------
    def test_a_failed_final_inventory_is_partial_not_established(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The resolutions are known, the remaining count is not. Publish exactly that."""
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        real = store.unresolved_intents
        calls = {"n": 0}

        def failing(directory: Any) -> Any:
            calls["n"] += 1
            if calls["n"] > 1:
                raise OSError(errno.EIO, os.strerror(errno.EIO))
            return real(directory)

        monkeypatch.setattr(store, "unresolved_intents", failing)
        result = reconcile("--json")
        document = payload_of(result)
        assert result.exit_code != 0, result.stdout
        assert document["resolved_intents"] == 1
        assert document["remaining_intents"] is None
        assert document["intent_counts_state"] == act.INTENT_COUNTS_PARTIAL
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert document["eligible_for_human_promotion_review"] is False
        assert not (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()

    # -- durability, which is not the same question as the counts ------------
    def test_an_fsync_fault_counts_the_removal_and_doubts_only_its_durability(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())

        def faulty_fsync(fd: int) -> None:
            raise OSError(errno.EIO, os.strerror(errno.EIO))

        monkeypatch.setattr(os, "fsync", faulty_fsync)
        result = reconcile("--json")
        document = payload_of(result)
        assert result.exit_code != 0, result.stdout
        # The entry is gone. Saying « 0 résolu » here was the contradiction.
        assert not (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()
        assert document["resolved_intents"] == 1
        assert document["remaining_intents"] == 0
        assert document["intent_resolution_durability"] == act.DURABILITY_UNCERTAIN
        assert document["intent_counts_state"] == act.INTENT_COUNTS_ESTABLISHED
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert document["eligible_for_human_promotion_review"] is False

    def test_the_human_rendering_of_an_fsync_fault_says_what_happened(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())

        def faulty_fsync(fd: int) -> None:
            raise OSError(errno.EIO, os.strerror(errno.EIO))

        monkeypatch.setattr(os, "fsync", faulty_fsync)
        text = reconcile().stdout
        assert "Intents résolus      : 1" in text
        assert act.DURABILITY_UNCERTAIN in text
        assert "durabilité n'est pas établie" in text
        # And it must not simultaneously claim a remaining intent blocks the gate.
        assert "Un intent restant bloque la porte" not in text
        assert not ANSI.search(text)

    def test_a_replay_after_an_fsync_fault_settles_the_state(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second pass establishes the directory durably, resolving nothing new."""
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        real_fsync = os.fsync
        broken = {"on": True}

        def faulty_fsync(fd: int) -> None:
            if broken["on"]:
                raise OSError(errno.EIO, os.strerror(errno.EIO))
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", faulty_fsync)
        first = payload_of(reconcile("--json"))
        assert first["resolved_intents"] == 1
        assert first["intent_resolution_durability"] == act.DURABILITY_UNCERTAIN

        broken["on"] = False
        result = reconcile("--json")
        second = payload_of(result)
        assert result.exit_code == 0, result.stdout
        assert second["resolved_intents"] == 0
        assert second["remaining_intents"] == 0
        assert second["intent_counts_state"] == act.INTENT_COUNTS_ESTABLISHED
        # Nothing new was removed, and the directory is nonetheless established as
        # durable — that is what makes the replay a recovery and not a shrug.
        assert second["intent_resolution_durability"] == act.DURABILITY_DURABLE
        assert second["qualification_state"] == "INSUFFICIENT_EVIDENCE"

    def test_a_replay_is_idempotent_in_every_published_field(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        reconcile("--json")
        first = payload_of(reconcile("--json"))
        second = payload_of(reconcile("--json"))
        assert first == second

    # -- the two renderings say the same thing -------------------------------
    @staticmethod
    def _plant(
        scenario: str, receipts: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Put the directory back into the scenario's starting state. Repeatable.

        The parity tests below run the command twice, and one of these scenarios is a
        *recovery*: the first run removes the intent. Re-planting between the two runs
        is what makes the comparison a comparison of renderings rather than of two
        different directories.
        """
        # Only when it is not already there: re-publishing an intent whose bytes differ
        # is refused on purpose — two attempts do not share an identity.
        wanted = scenario in {"recovered", "blocked", "no_secret"}
        if wanted and not (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists():
            act.publish_intent(attempt())
        if scenario == "recovered":
            publish(receipts, receipt_of())
        elif scenario == "no_secret":
            (receipts / act.SECRET_FILENAME).unlink(missing_ok=True)
        elif scenario == "absent_boundary":
            monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(tmp_path / "nowhere"))

    @pytest.mark.parametrize(
        "scenario", ["empty", "recovered", "blocked", "no_secret", "absent_boundary"]
    )
    def test_the_human_rendering_and_the_json_agree(
        self,
        receipts: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        scenario: str,
    ) -> None:
        self._plant(scenario, receipts, tmp_path, monkeypatch)
        document = payload_of(reconcile("--json"))
        self._plant(scenario, receipts, tmp_path, monkeypatch)
        text = reconcile().stdout
        assert f"Intents résolus      : {rendered(document['resolved_intents'])}" in text
        assert f"Intents restants     : {rendered(document['remaining_intents'])}" in text
        assert f"Comptage des intents : {document['intent_counts_state']}" in text
        assert f"Durabilité           : {document['intent_resolution_durability']}" in text
        assert document["qualification_state"] in text
        assert not ANSI.search(text)

    @pytest.mark.parametrize(
        "scenario", ["empty", "recovered", "blocked", "no_secret", "absent_boundary"]
    )
    def test_no_rendering_contradicts_its_own_counts(
        self,
        receipts: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        scenario: str,
    ) -> None:
        """The closing sentence is chosen by the state, so it cannot fight the numbers."""
        self._plant(scenario, receipts, tmp_path, monkeypatch)
        remaining = payload_of(reconcile("--json"))["remaining_intents"]
        self._plant(scenario, receipts, tmp_path, monkeypatch)
        text = reconcile().stdout
        blocks = "Un intent restant bloque la porte" in text
        assert blocks is (remaining is not None and remaining > 0), text
        if remaining is None:
            assert "n'est pas établi" in text
        assert "Aucune suppression manuelle n'est autorisée." in text

    def test_the_two_vocabularies_are_closed_sets(self, receipts: Path) -> None:
        """No third spelling of « I did not look » can appear without a test failing."""
        assert {
            act.INTENT_COUNTS_ESTABLISHED,
            act.INTENT_COUNTS_PARTIAL,
            act.INTENT_COUNTS_UNESTABLISHED,
        } == {"ESTABLISHED", "PARTIAL", "UNESTABLISHED"}
        assert {
            act.DURABILITY_NOT_ATTEMPTED,
            act.DURABILITY_DURABLE,
            act.DURABILITY_UNCERTAIN,
        } == {"NOT_ATTEMPTED", "DURABLE", "UNCERTAIN"}
        document = payload_of(reconcile("--json"))
        assert document["intent_counts_state"] in {"ESTABLISHED", "PARTIAL", "UNESTABLISHED"}
        assert document["intent_resolution_durability"] in {
            "NOT_ATTEMPTED",
            "DURABLE",
            "UNCERTAIN",
        }

    def test_the_store_reports_removal_and_durability_apart(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The unit underneath: an unlink that happened is reported as having happened."""
        act.publish_intent(attempt())
        real_fsync = os.fsync

        def faulty_fsync(fd: int) -> None:
            raise OSError(errno.EIO, os.strerror(errno.EIO))

        with act.receipt_directory() as directory:
            monkeypatch.setattr(os, "fsync", faulty_fsync)
            outcome = store.resolve_intent_reporting(directory, ATTEMPT)
            monkeypatch.setattr(os, "fsync", real_fsync)
        assert outcome.removed is True
        assert outcome.durable is False
        assert not (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()

        with act.receipt_directory() as directory:
            again = store.resolve_intent_reporting(directory, ATTEMPT)
        assert again.removed is False
        assert again.durable is True


# ---------------------------------------------------------------------------
# §quater — the documents publish the counting rule as well
# ---------------------------------------------------------------------------
class TestTheDocumentsPublishTheTruthRule:
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
        assert "D-080" in self._read(relative)

    @pytest.mark.parametrize(
        "relative",
        ["docs/provider-validation-protocol.md", "docs/provider-activation.md"],
    )
    def test_both_documents_publish_the_two_vocabularies(self, relative: str) -> None:
        text = self._read(relative)
        for value in ("ESTABLISHED", "PARTIAL", "UNESTABLISHED"):
            assert value in text, (relative, value)
        for value in ("NOT_ATTEMPTED", "DURABLE", "UNCERTAIN"):
            assert value in text, (relative, value)

    @pytest.mark.parametrize(
        "relative",
        ["docs/provider-validation-protocol.md", "docs/provider-activation.md"],
    )
    def test_both_documents_say_a_missing_count_is_not_zero(self, relative: str) -> None:
        text = self._read(relative)
        assert act.UNESTABLISHED_COUNT in text
        assert "entiers ou `null`" in text

    def test_the_protocol_forbids_substituting_zero_for_a_measurement(self) -> None:
        text = self._read("docs/provider-validation-protocol.md")
        assert "Remplacer une absence de mesure par zéro est interdit" in text
        assert "zéro est une mesure" in text

    def test_the_protocol_states_the_three_situations(self) -> None:
        text = self._read("docs/provider-validation-protocol.md")
        assert "refus avant toute mesure" in text
        assert "résultat partiel" in text
        assert "succès complet" in text

    def test_the_protocol_states_the_fsync_rule(self) -> None:
        text = self._read("docs/provider-validation-protocol.md")
        assert "la suppression a eu lieu dans l'espace de noms courant" in text
        assert "resolved_intents = 0` et `remaining_intents = 0`" in text

    def test_the_protocol_states_that_a_clean_run_synchronises_anyway(self) -> None:
        text = self._read("docs/provider-validation-protocol.md")
        assert "synchronise le répertoire même lorsqu'elle ne retire rien" in text

    def test_the_runbook_tells_the_operator_what_to_do_about_uncertain(self) -> None:
        text = self._read("docs/provider-activation.md")
        assert "UNCERTAIN" in text
        assert "Relancez la commande" in text
        assert "surtout pas toucher au répertoire à la main" in text

    def test_the_register_records_what_the_decision_leaves_alone(self) -> None:
        text = self._read("docs/decisions.md")
        assert "6 / 10 / 16" in text
        assert "CRITERIA_MET_AWAITING_HUMAN_REVIEW" in text
        assert "2026-08-11T14:20:00+00:00" in text

    def test_the_runbook_publishes_every_field_the_command_emits(self, receipts: Path) -> None:
        """The list in the runbook is checked against what the command actually prints."""
        text = self._read("docs/provider-activation.md")
        for field in payload_of(reconcile("--json")):
            assert field in text, field


# ---------------------------------------------------------------------------
# §sexies — the behaviours a mutation would otherwise carry away silently
# ---------------------------------------------------------------------------
#: Exactly what a successful `receipts reconcile --json` publishes. A refusal adds
#: `status` and `detail`, and nothing else. The runbook carries the same list between
#: two stable markers, and the guards below compare the two sets **in both directions**.
PUBLISHED_FIELDS = frozenset(
    {
        "boundary_state",
        "boundary_reason",
        "verified_receipts_considered",
        "unverifiable_receipts",
        "resolved_intents",
        "remaining_intents",
        "intent_counts_state",
        "intent_resolution_durability",
        "qualification_state",
        "eligible_for_human_promotion_review",
    }
)

REFUSAL_EXTRA_FIELDS = frozenset({"status", "detail"})

RUNBOOK_FIELD_MARKERS = (
    "<!-- champs-publiés-reconcile:début -->",
    "<!-- champs-publiés-reconcile:fin -->",
)


def documented_fields(root: Path) -> set[str]:
    """The field list the runbook declares, read from between its two markers."""
    text = (root / "docs/provider-activation.md").read_text(encoding="utf-8")
    opening, closing = RUNBOOK_FIELD_MARKERS
    assert opening in text and closing in text, "les balises de la liste ont disparu"
    block = text.split(opening, 1)[1].split(closing, 1)[0]
    return {line.strip() for line in block.splitlines() if line.strip() and "```" not in line}


class TestTheEstablishingSyncIsGuarded:
    """Red if the establishing ``fsync`` is dropped — and nothing else in this file is.

    D-080 requires a completed run to synchronise the directory *even when it removes
    nothing*, so that a replay after a durability fault establishes the current state
    instead of shrugging. The code did that, and deleting the single ``directory.fsync()``
    left all 123 tests of this file green while changing the observable answer from
    ``exit 1 · UNCERTAIN`` to ``exit 0 · DURABLE`` — a report claiming a durability it
    never established, which is the exact fault D-080 forbids. This class is the guard.
    """

    @staticmethod
    def _break_fsync(monkeypatch: pytest.MonkeyPatch) -> None:
        def faulty_fsync(fd: int) -> None:
            raise OSError(errno.EIO, os.strerror(errno.EIO))

        monkeypatch.setattr(os, "fsync", faulty_fsync)

    def test_a_failed_establishing_sync_is_uncertain_without_any_removal(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No intent, so the only ``fsync`` of the whole run is the establishing one."""
        assert list(receipts.glob(f"*{store.INTENT_SUFFIX}")) == []
        self._break_fsync(monkeypatch)
        result = reconcile("--json")
        document = payload_of(result)
        assert result.exit_code != 0, result.stdout
        assert document["resolved_intents"] == 0
        assert document["remaining_intents"] == 0
        assert document["intent_counts_state"] == act.INTENT_COUNTS_ESTABLISHED
        assert document["intent_resolution_durability"] == act.DURABILITY_UNCERTAIN
        assert document["qualification_state"] == "EVIDENCE_CONFLICT"
        assert document["eligible_for_human_promotion_review"] is False
        # Nothing was removed and nothing was created: only the sync failed.
        assert list(receipts.glob(f"*{store.INTENT_SUFFIX}")) == []

    def test_the_human_rendering_says_the_state_could_not_be_made_durable(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And it must not borrow the sentence written for an observed removal."""
        self._break_fsync(monkeypatch)
        text = reconcile().stdout
        assert f"Durabilité           : {act.DURABILITY_UNCERTAIN}" in text
        assert "L'état courant n'a pas pu être rendu durable" in text
        assert "La suppression a été observée" not in text
        assert "Un intent restant bloque la porte" not in text
        assert not ANSI.search(text)

    def test_the_two_forms_of_uncertain_differ_only_by_the_resolution_count(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both forms are `UNCERTAIN`; `resolved_intents` is what separates them."""
        # A toggle rather than `monkeypatch.undo()`: undoing would also revert the
        # fixture's own environment setup, and `publish_intent` needs a working `fsync`.
        broken = {"on": True}
        real_fsync = os.fsync

        def faulty_fsync(fd: int) -> None:
            if broken["on"]:
                raise OSError(errno.EIO, os.strerror(errno.EIO))
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", faulty_fsync)
        without = payload_of(reconcile("--json"))

        broken["on"] = False
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        broken["on"] = True
        with_removal = payload_of(reconcile("--json"))

        assert without["intent_resolution_durability"] == act.DURABILITY_UNCERTAIN
        assert with_removal["intent_resolution_durability"] == act.DURABILITY_UNCERTAIN
        assert without["resolved_intents"] == 0
        assert with_removal["resolved_intents"] == 1
        # And the one that removed something really did remove it.
        assert not (receipts / f"{ATTEMPT}{store.INTENT_SUFFIX}").exists()

    def test_a_clean_run_that_removes_nothing_still_reports_durable(self, receipts: Path) -> None:
        """The other half of the same rule: the sync happens, so the state is settled."""
        document = payload_of(reconcile("--json"))
        assert document["resolved_intents"] == 0
        assert document["intent_resolution_durability"] == act.DURABILITY_DURABLE


class TestThePublishedFieldsAreExactlyTheDocumentedOnes:
    """A bidirectional guard: emitted set == documented set, no field on either side alone.

    The previous guard ran one way — every emitted field had to appear in the runbook —
    so a field could be dropped from the report and the runbook would keep advertising
    it, unguarded. ``boundary_reason`` was in exactly that position: asserted nowhere.
    """

    ROOT = Path(act.__file__).resolve().parents[4]

    def test_a_successful_run_emits_exactly_the_normative_set(self, receipts: Path) -> None:
        assert set(payload_of(reconcile("--json"))) == set(PUBLISHED_FIELDS)

    def test_a_refusal_emits_the_normative_set_plus_status_and_detail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(tmp_path / "nowhere"))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        result = reconcile("--json")
        assert result.exit_code != 0, result.stdout
        assert set(payload_of(result)) == set(PUBLISHED_FIELDS | REFUSAL_EXTRA_FIELDS)

    def test_the_runbook_declares_exactly_the_normative_set(self) -> None:
        assert documented_fields(self.ROOT) == set(PUBLISHED_FIELDS)

    def test_every_emitted_field_is_documented(self, receipts: Path) -> None:
        assert set(payload_of(reconcile("--json"))) <= documented_fields(self.ROOT)

    def test_every_documented_field_is_emitted(self, receipts: Path) -> None:
        """The direction that was missing. Dropping `boundary_reason` fails here."""
        assert documented_fields(self.ROOT) <= set(payload_of(reconcile("--json")))

    @pytest.mark.parametrize("field", sorted(PUBLISHED_FIELDS))
    def test_each_field_is_published_by_both_renderings(self, receipts: Path, field: str) -> None:
        document = payload_of(reconcile("--json"))
        assert field in document
        # Every field's *value* reaches the human rendering too, under its own label or
        # inside one — `boundary_reason` is the empty string on a healthy boundary, so
        # only the non-empty values are checked for presence.
        value = document[field]
        if isinstance(value, str) and value:
            assert value in reconcile().stdout, field


class TestTheThrowawayDirectoryIsThrownAway:
    """`helpers_receipt_boundary.audited` used to leak one directory per call.

    Each leak held a synthetic signing key and a synthetic corpus; the quinquies
    re-audit counted 143 182 of them, about 2.2 GB, accumulated by the five qualification
    suites over the life of the runner. The fix is a `finally`; these tests are what
    keeps it there.
    """

    @staticmethod
    def _corpus() -> list[dict[str, Any]]:
        return [receipt_of()]

    def test_the_directory_is_removed_after_a_successful_audit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tempfile

        from helpers_receipt_boundary import audited

        seen: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*a: Any, **k: Any) -> str:
            made = real_mkdtemp(*a, **k)
            seen.append(Path(made))
            return made

        monkeypatch.setattr(tempfile, "mkdtemp", spy)
        result = audited(self._corpus(), secret=LOCAL)
        assert seen, "aucun répertoire jetable n'a été créé"
        assert not seen[-1].exists(), seen[-1]
        # The result survives its directory: everything was read before the removal.
        assert len(result.batch) == 1

    def test_the_directory_is_removed_when_the_audit_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tempfile

        from helpers_receipt_boundary import audited

        seen: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*a: Any, **k: Any) -> str:
            made = real_mkdtemp(*a, **k)
            seen.append(Path(made))
            return made

        monkeypatch.setattr(tempfile, "mkdtemp", spy)

        def boom() -> Any:
            raise RuntimeError("audit refusé")

        monkeypatch.setattr(act, "audit_receipts", boom)
        with pytest.raises(RuntimeError):
            audited(self._corpus(), secret=LOCAL)
        assert seen, "aucun répertoire jetable n'a été créé"
        assert not seen[-1].exists(), seen[-1]

    def test_the_directory_is_removed_when_writing_the_corpus_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The `finally` must cover the write, not only the audit."""
        import tempfile

        import helpers_receipt_boundary as helper

        seen: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*a: Any, **k: Any) -> str:
            made = real_mkdtemp(*a, **k)
            seen.append(Path(made))
            return made

        monkeypatch.setattr(tempfile, "mkdtemp", spy)

        def boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("écriture impossible")

        monkeypatch.setattr(helper, "write_receipt_files", boom)
        with pytest.raises(RuntimeError):
            helper.audited(self._corpus(), secret=LOCAL)
        assert seen, "aucun répertoire jetable n'a été créé"
        assert not seen[-1].exists(), seen[-1]

    def test_a_series_of_calls_leaves_nothing_behind(self) -> None:
        """Measured the way the re-audit measured it: count, bytes, keys."""
        from helpers_receipt_boundary import audited

        temporary = Path(tempfile.gettempdir())

        def leaked() -> list[Path]:
            return sorted(temporary.glob("audited-*"))

        before = set(leaked())
        for _ in range(8):
            audited(self._corpus(), secret=LOCAL)
        after = [path for path in leaked() if path not in before]
        assert after == [], after
        assert sum(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) for p in after) == 0
        assert [p for p in after if (p / act.SECRET_FILENAME).exists()] == []

    def test_the_environment_variable_is_restored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cleanup must not disturb what the caller had configured."""
        from helpers_receipt_boundary import audited

        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, "/nowhere/at/all")
        audited(self._corpus(), secret=LOCAL)
        assert os.environ[act.RECEIPT_DIR_VARIABLE] == "/nowhere/at/all"

    def test_no_path_outside_the_created_directory_is_removed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A neighbour of the throwaway directory must survive it."""
        import tempfile

        from helpers_receipt_boundary import audited

        neighbour = tmp_path / "neighbour"
        neighbour.mkdir()
        (neighbour / "keep.txt").write_text("keep", encoding="utf-8")
        real_mkdtemp = tempfile.mkdtemp
        seen: list[Path] = []

        def spy(*a: Any, **k: Any) -> str:
            made = real_mkdtemp(*a, **k)
            seen.append(Path(made))
            return made

        monkeypatch.setattr(tempfile, "mkdtemp", spy)
        audited(self._corpus(), secret=LOCAL)
        assert not seen[-1].exists()
        assert (neighbour / "keep.txt").read_text(encoding="utf-8") == "keep"


class TestTheDocumentsPublishBothFormsOfUncertain:
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
        assert "D-081" in self._read(relative)

    @pytest.mark.parametrize(
        "relative",
        ["docs/provider-validation-protocol.md", "docs/provider-activation.md"],
    )
    def test_both_documents_publish_the_two_forms(self, relative: str) -> None:
        text = self._read(relative)
        assert "avec suppression" in text
        assert "sans aucune suppression" in text
        assert "resolved_intents" in text

    @pytest.mark.parametrize(
        "relative",
        ["docs/provider-validation-protocol.md", "docs/provider-activation.md"],
    )
    def test_both_documents_say_a_new_run_is_needed(self, relative: str) -> None:
        assert "une nouvelle exécution est nécessaire" in self._read(relative)

    def test_the_protocol_states_the_form_without_any_unlink(self) -> None:
        text = self._read("docs/provider-validation-protocol.md")
        assert "rien n'a été retiré" in text
        assert "fsync` destiné à établir durablement l'état courant qui a échoué" in text

    def test_the_runbook_no_longer_defines_uncertain_by_the_unlink_alone(self) -> None:
        """The exact sentence the quinquies re-audit falsified must be gone."""
        text = self._read("docs/provider-activation.md")
        assert "Elle signifie que l'`unlink` d'un intent a réussi" not in text

    def test_the_register_records_the_harness_leak_and_its_size(self) -> None:
        text = self._read("docs/decisions.md")
        assert "143 182" in text
        assert "helpers_receipt_boundary" in text
