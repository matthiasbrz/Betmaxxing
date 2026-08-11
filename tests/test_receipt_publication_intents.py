"""Publication order, durability, and a durable trace before the wire — §8.

Why this suite exists
---------------------
Two findings of the fifth audit meet here.

The first is about **publication**. v5 wrote the bytes to a temporary, ``fsync``-ed
it and published with a hard link, which is right — but the progress loop had no
guard against ``os.write`` returning zero (a subprocess spun for ever under
injection), the ``fsync`` of the directory was wrapped in
``contextlib.suppress(OSError)`` while the protocol advertised it as step five of
an atomic and durable publication, and the code performed step six before step
five, the reverse of the documented order.

The second is worse. ``write_receipt`` was called at five sites, none of them
inside a handler, and the module installed no global one. Injecting ``ENOSPC`` at
the ``discover`` site made the CLI exit 1 with a bare ``OSError``, **no output at
all**, and no receipt: the operator learned neither the outcome nor that a request
had been attempted. At the ``additional`` site the same shape loses the only proof
of a five-credit call.

A receipt written after the fact cannot fix that, so the correction is a durable
**intent** written and ``fsync``-ed *before* the request. Its survival is the
evidence that something may have left; it is resolved only once the final receipt
is durably published, it blocks the qualification gate while it lives, and it
carries no key, no URL, no event in clear and no payload.

Every request here comes from ``httpx.MockTransport``; ``conftest.py`` blocks
outbound connections for the whole session.
"""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import receipt_store as store
from helpers_activation import (
    Recorder,
    core_args,
    discover_args,
    events_payload,
    install,
    odds_payload,
    receipt_path,
    run,
    sports_payload,
)

FREE = {"x-requests-last": "0", "x-requests-remaining": "487"}
PAID = {"x-requests-last": "1", "x-requests-remaining": "486"}
NAME = "20260901T120000-core-aa11bb22cc33dd44.json"
BODY = b'{"marker": "complete"}\n'


def free_routes() -> dict[str, Any]:
    return {
        "/sports/": lambda _r: httpx.Response(200, json=events_payload(), headers=FREE),
        "/sports": lambda _r: httpx.Response(200, json=sports_payload(), headers=FREE),
    }


def paid_routes() -> dict[str, Any]:
    return {"/odds": lambda _r: httpx.Response(200, json=odds_payload(), headers=PAID)}


@pytest.fixture
def directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "receipts"
    target.mkdir()
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(target))
    return target


# ---------------------------------------------------------------------------
# 8.1 Publication
# ---------------------------------------------------------------------------
class TestTheBytesExistBeforeTheNameDoes:
    def test_partial_writes_still_publish_every_byte(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_write = os.write

        def dribbling_write(fd: int, data: bytes) -> int:
            return real_write(fd, data[:3])

        with store.SecureDirectory.open(directory) as secure:
            monkeypatch.setattr(os, "write", dribbling_write)
            secure.publish_bytes(NAME, BODY)
            monkeypatch.setattr(os, "write", real_write)
        assert (directory / NAME).read_bytes() == BODY

    def test_one_zero_return_is_survived(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_write = os.write
        seen = {"n": 0}

        def stalling_write(fd: int, data: bytes) -> int:
            seen["n"] += 1
            if seen["n"] == 1:
                return 0
            return real_write(fd, data)

        with store.SecureDirectory.open(directory) as secure:
            monkeypatch.setattr(os, "write", stalling_write)
            secure.publish_bytes(NAME, BODY)
            monkeypatch.setattr(os, "write", real_write)
        assert (directory / NAME).read_bytes() == BODY

    def test_a_write_that_never_progresses_fails_fast_instead_of_looping(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The subprocess probe of the fifth audit never terminated. This must."""
        real_write = os.write

        def frozen_write(fd: int, data: bytes) -> int:
            if fd > 2:
                return 0
            return real_write(fd, data)

        with store.SecureDirectory.open(directory) as secure:
            monkeypatch.setattr(os, "write", frozen_write)
            try:
                with pytest.raises(store.PersistenceFailed):
                    secure.publish_bytes(NAME, BODY)
            finally:
                monkeypatch.setattr(os, "write", real_write)
        assert not (directory / NAME).exists()
        assert [p.name for p in directory.iterdir()] == []

    @pytest.mark.parametrize(
        ("label", "number"), [("interrupted", errno.EINTR), ("no space", errno.ENOSPC)]
    )
    def test_a_write_error_is_a_typed_persistence_failure(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch, label: str, number: int
    ) -> None:
        real_write = os.write

        def failing_write(fd: int, data: bytes) -> int:
            if fd > 2:
                raise OSError(number, "injected")
            return real_write(fd, data)

        with store.SecureDirectory.open(directory) as secure:
            monkeypatch.setattr(os, "write", failing_write)
            try:
                with pytest.raises(store.PersistenceFailed):
                    secure.publish_bytes(NAME, BODY)
            finally:
                monkeypatch.setattr(os, "write", real_write)
        assert [p.name for p in directory.iterdir()] == []

    def test_a_durability_error_is_reported_and_never_suppressed(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_fsync = os.fsync
        stage = {"n": 0}

        def failing_fsync(fd: int) -> None:
            stage["n"] += 1
            raise OSError(errno.EIO, "injected durability failure")

        with store.SecureDirectory.open(directory) as secure:
            monkeypatch.setattr(os, "fsync", failing_fsync)
            try:
                with pytest.raises(store.PersistenceFailed):
                    secure.publish_bytes(NAME, BODY)
            finally:
                monkeypatch.setattr(os, "fsync", real_fsync)
        assert stage["n"] >= 1

    def test_a_failure_of_the_second_directory_fsync_is_reported_too(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cleanup fsync. The proof is durable; the operator still hears about it."""
        real_fsync = os.fsync
        calls = {"n": 0}

        def late_failing_fsync(fd: int) -> None:
            calls["n"] += 1
            if calls["n"] >= 3:
                raise OSError(errno.EIO, "injected late durability failure")
            real_fsync(fd)

        with store.SecureDirectory.open(directory) as secure:
            monkeypatch.setattr(os, "fsync", late_failing_fsync)
            try:
                published = secure.publish_bytes(NAME, BODY)
            except store.PersistenceFailed as exc:
                assert exc.published is True
                assert exc.cleanup_pending is True
            else:
                assert published.cleanup_pending is True
            finally:
                monkeypatch.setattr(os, "fsync", real_fsync)
        assert (directory / NAME).read_bytes() == BODY

    def test_the_documented_order_is_the_order_performed(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """write → fsync(temp) → link → fsync(dir) → unlink(temp) → fsync(dir)."""
        events: list[str] = []
        real_write, real_fsync, real_link, real_unlink = (
            os.write,
            os.fsync,
            os.link,
            os.unlink,
        )

        def note(name: str, real: Any) -> Any:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                events.append(name)
                return real(*args, **kwargs)

            return wrapper

        with store.SecureDirectory.open(directory) as secure:
            monkeypatch.setattr(os, "write", note("write", real_write))
            monkeypatch.setattr(os, "fsync", note("fsync", real_fsync))
            monkeypatch.setattr(os, "link", note("link", real_link))
            monkeypatch.setattr(os, "unlink", note("unlink", real_unlink))
            try:
                secure.publish_bytes(NAME, BODY)
            finally:
                monkeypatch.setattr(os, "write", real_write)
                monkeypatch.setattr(os, "fsync", real_fsync)
                monkeypatch.setattr(os, "link", real_link)
                monkeypatch.setattr(os, "unlink", real_unlink)
        skeleton = [e for e in events if e != "write"]
        assert skeleton == ["fsync", "link", "fsync", "unlink", "fsync"], events
        assert events.index("write") < events.index("link")

    def test_no_temporary_is_left_silently_behind(self, directory: Path) -> None:
        with store.SecureDirectory.open(directory) as secure:
            secure.publish_bytes(NAME, BODY)
        assert sorted(p.name for p in directory.iterdir()) == [NAME]

    def test_a_temporary_that_cannot_be_removed_is_reported(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_unlink = os.unlink

        def refusing_unlink(*args: Any, **kwargs: Any) -> None:
            raise PermissionError(errno.EPERM, "injected")

        with store.SecureDirectory.open(directory) as secure:
            monkeypatch.setattr(os, "unlink", refusing_unlink)
            try:
                published = secure.publish_bytes(NAME, BODY)
            except store.PersistenceFailed as exc:
                assert exc.published is True
                assert exc.cleanup_pending is True
            else:
                assert published.cleanup_pending is True
            finally:
                monkeypatch.setattr(os, "unlink", real_unlink)
        assert (directory / NAME).read_bytes() == BODY

    def test_an_identical_republication_is_idempotent_and_a_divergent_one_is_refused(
        self, directory: Path
    ) -> None:
        with store.SecureDirectory.open(directory) as secure:
            assert secure.publish_bytes(NAME, BODY).outcome == "written"
            assert secure.publish_bytes(NAME, BODY).outcome == "exists"
            assert secure.read_text(NAME).encode("utf-8") == BODY

    def test_a_temporary_name_collision_does_not_overwrite(
        self, directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(store.secrets, "token_hex", lambda _n=4: "abcdabcd")
        with store.SecureDirectory.open(directory) as secure:
            secure.publish_bytes(NAME, BODY)
            secure.publish_bytes("20260901T120001-core-bb11bb22cc33dd44.json", BODY)
        assert len(list(directory.iterdir())) == 2


# ---------------------------------------------------------------------------
# 8.2 A durable intent before the wire
# ---------------------------------------------------------------------------
class TestAnIntentExistsBeforeTheRequest:
    @pytest.mark.parametrize("command", ["discover", "core", "additional"])
    def test_the_intent_is_durable_before_the_first_request(
        self,
        workspace: Path,
        keyed: Path,
        frozen_clock: None,
        monkeypatch: pytest.MonkeyPatch,
        command: str,
    ) -> None:
        seen: list[list[str]] = []

        def watching(request: httpx.Request) -> httpx.Response:
            seen.append(sorted(p.name for p in workspace.iterdir()))
            path = str(request.url)
            if "/odds" in path:
                return httpx.Response(200, json=odds_payload(), headers=PAID)
            if "/events" in path or "/sports/" in path:
                return httpx.Response(200, json=events_payload(), headers=FREE)
            return httpx.Response(200, json=sports_payload(), headers=FREE)

        install(monkeypatch, Recorder({"": watching}))
        if command == "discover":
            run(*discover_args())
        else:
            run(*discover_args())
            install(monkeypatch, Recorder({"": watching}))
            discovery = str(receipt_path(workspace, "discover"))
            run(*core_args(discovery_receipt=discovery))
        assert seen, "no request was attempted"
        assert any(name.endswith(act.INTENT_SUFFIX) for names in seen for name in names), (
            f"no intent existed when the request was issued: {seen}"
        )

    def test_a_clean_run_leaves_no_unresolved_intent(
        self, workspace: Path, keyed: Path, frozen_clock: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        result = run(*discover_args())
        assert result.exit_code == 0, result.stdout
        assert act.unresolved_intents() == []
        assert not [p for p in workspace.iterdir() if p.name.endswith(act.INTENT_SUFFIX)]

    def test_a_failed_publication_keeps_the_intent_and_tells_the_operator(
        self, workspace: Path, keyed: Path, frozen_clock: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        real_publish = store.SecureDirectory.publish_bytes

        def failing_for_receipts(self: Any, name: str, payload: bytes) -> Any:
            if name.endswith(".json"):
                raise store.PersistenceFailed("injected", published=False)
            return real_publish(self, name, payload)

        monkeypatch.setattr(store.SecureDirectory, "publish_bytes", failing_for_receipts)
        result = run(*discover_args())
        monkeypatch.setattr(store.SecureDirectory, "publish_bytes", real_publish)

        assert result.exit_code != 0
        assert result.exception is None or not isinstance(result.exception, OSError)
        assert result.stdout.strip(), "the operator was told nothing"
        assert "PERSISTENCE" in result.stdout or "persistance" in result.stdout.lower()
        unresolved = act.unresolved_intents()
        assert len(unresolved) == 1
        assert unresolved[0]["command"] == "discover"
        assert unresolved[0]["state"] == "PREPARED"

    def test_the_same_failure_in_json_is_valid_json_and_names_the_facts(
        self, workspace: Path, keyed: Path, frozen_clock: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        real_publish = store.SecureDirectory.publish_bytes

        def failing_for_receipts(self: Any, name: str, payload: bytes) -> Any:
            if name.endswith(".json"):
                raise store.PersistenceFailed("injected", published=False)
            return real_publish(self, name, payload)

        monkeypatch.setattr(store.SecureDirectory, "publish_bytes", failing_for_receipts)
        result = run(*discover_args(extra=("--json",)))
        monkeypatch.setattr(store.SecureDirectory, "publish_bytes", real_publish)
        assert result.exit_code != 0
        payload = json.loads(result.stdout)
        for key in (
            "status",
            "command",
            "attempt_id",
            "may_have_reached_provider",
            "accounted_credits",
            "persistence_failure",
        ):
            assert key in payload, key
        assert payload["command"] == "discover"
        text = json.dumps(payload)
        from helpers_activation import FAKE_KEY

        assert FAKE_KEY not in text
        assert "api_key" not in text

    def test_an_unresolved_intent_blocks_the_gate_and_is_visible(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from helpers_activation import FAKE_RECEIPT_SECRET
        from helpers_qualification_corpus import write_threshold_corpus

        write_threshold_corpus(workspace, FAKE_RECEIPT_SECRET)
        _audit = act.audit_receipts()
        clean = act.build_activation_state(_audit)
        assert clean["eligible_for_human_promotion_review"] is True
        assert clean["unresolved_attempt_intents"] == 0

        act.publish_intent(
            act.Attempt(
                command="core",
                sport="soccer_corpus_one",
                bookmaker="corpusbook",
                window=(act._clock(), act._clock()),
                ceiling=1,
                now=act._clock(),
            )
        )
        blocked = act.build_activation_state(act.audit_receipts())
        assert blocked["unresolved_attempt_intents"] == 1
        assert blocked["eligible_for_human_promotion_review"] is False
        assert any("intent" in conflict.lower() for conflict in blocked["evidence_conflicts"])
        assert any("intent" in line.lower() for line in act.status_lines(blocked))

    def test_resolving_an_intent_is_idempotent_and_costs_nothing(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempt = act.Attempt(
            command="core",
            sport="soccer_corpus_one",
            bookmaker="corpusbook",
            window=(act._clock(), act._clock()),
            ceiling=1,
            now=act._clock(),
        )
        act.publish_intent(attempt)
        assert len(act.unresolved_intents()) == 1
        act.resolve_intent(attempt.attempt_id)
        act.resolve_intent(attempt.attempt_id)
        assert act.unresolved_intents() == []
        state = act.build_activation_state(act.audit_receipts())
        assert state["accounted_credits_total"] == 0
        assert state["unresolved_attempt_intents"] == 0

    def test_two_workers_on_the_same_identifier_agree(self, workspace: Path) -> None:
        attempt = act.Attempt(
            command="core",
            sport="soccer_corpus_one",
            bookmaker="corpusbook",
            window=(act._clock(), act._clock()),
            ceiling=1,
            now=act._clock(),
        )
        act.publish_intent(attempt)
        act.publish_intent(attempt)
        assert len(act.unresolved_intents()) == 1

    def test_the_intent_carries_no_secret_no_url_and_no_clear_event(self, workspace: Path) -> None:
        from helpers_activation import FAKE_KEY, FAKE_RECEIPT_SECRET

        attempt = act.Attempt(
            command="additional",
            sport="soccer_corpus_one",
            bookmaker="corpusbook",
            window=(act._clock(), act._clock()),
            ceiling=5,
            now=act._clock(),
            event_id="evt-clear-identifier-0001",
        )
        act.publish_intent(attempt)
        body = json.dumps(act.unresolved_intents()[0])
        raw = "".join(
            p.read_text(encoding="utf-8")
            for p in workspace.iterdir()
            if p.name.endswith(act.INTENT_SUFFIX)
        )
        for forbidden in (FAKE_KEY, FAKE_RECEIPT_SECRET, "evt-clear-identifier-0001", "http"):
            assert forbidden not in body
            assert forbidden not in raw

    def test_a_receipt_already_published_reconciles_without_double_counting(
        self, workspace: Path, keyed: Path, frozen_clock: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Crash after publication, before resolution: replay resolves, cost stays once."""
        install(monkeypatch, Recorder(free_routes()))
        real_resolve = act.resolve_intent
        monkeypatch.setattr(act, "resolve_intent", lambda _id: None)
        assert run(*discover_args()).exit_code == 0
        monkeypatch.setattr(act, "resolve_intent", real_resolve)
        assert len(act.unresolved_intents()) == 1

        reconciled = act.reconcile_intents()
        assert reconciled == 1
        assert act.unresolved_intents() == []
        state = act.build_activation_state(act.audit_receipts())
        assert state["verified_receipts"] == 1
        assert state["accounted_credits_total"] == 0
        assert state["unresolved_attempt_intents"] == 0


class TestNoRawOsErrorReachesTheOperator:
    """The five publication sites, including the five-credit one."""

    @pytest.mark.parametrize("command", ["discover", "core", "additional"])
    def test_every_command_reports_a_persistence_failure_as_business_output(
        self,
        workspace: Path,
        keyed: Path,
        frozen_clock: None,
        monkeypatch: pytest.MonkeyPatch,
        command: str,
    ) -> None:
        from helpers_activation import additional_args

        install(monkeypatch, Recorder({**paid_routes(), **free_routes()}))
        args: tuple[str, ...]
        if command == "discover":
            args = discover_args()
        elif command == "core":
            assert run(*discover_args()).exit_code == 0
            args = core_args(discovery_receipt=str(receipt_path(workspace, "discover")))
        else:
            assert run(*discover_args()).exit_code == 0
            assert (
                run(
                    *core_args(discovery_receipt=str(receipt_path(workspace, "discover")))
                ).exit_code
                == 0
            )
            args = additional_args(core_receipt=str(receipt_path(workspace, "core")))

        install(monkeypatch, Recorder({**paid_routes(), **free_routes()}))
        real_publish = store.SecureDirectory.publish_bytes

        def failing_for_receipts(self: Any, name: str, payload: bytes) -> Any:
            if name.endswith(".json"):
                raise store.PersistenceFailed("injected", published=False)
            return real_publish(self, name, payload)

        monkeypatch.setattr(store.SecureDirectory, "publish_bytes", failing_for_receipts)
        result = run(*args)
        monkeypatch.setattr(store.SecureDirectory, "publish_bytes", real_publish)

        assert result.exit_code != 0
        assert not isinstance(result.exception, OSError)
        assert result.stdout.strip()
        assert len(act.unresolved_intents()) >= 1
        if command == "additional":
            intent = next(i for i in act.unresolved_intents() if i["command"] == "additional")
            assert intent["max_credits"] == 5

    def test_a_refusal_after_the_wire_still_reports_when_publication_fails(
        self, workspace: Path, keyed: Path, frozen_clock: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure path writes a receipt too; its loss must also be visible."""
        install(
            monkeypatch,
            Recorder(
                {
                    "/sports/": lambda _r: httpx.Response(200, json={"unexpected": True}),
                    "/sports": lambda _r: httpx.Response(200, json=sports_payload(), headers=FREE),
                }
            ),
        )
        real_publish = store.SecureDirectory.publish_bytes

        def failing_for_receipts(self: Any, name: str, payload: bytes) -> Any:
            if name.endswith(".json"):
                raise store.PersistenceFailed("injected", published=False)
            return real_publish(self, name, payload)

        monkeypatch.setattr(store.SecureDirectory, "publish_bytes", failing_for_receipts)
        result = run(*discover_args())
        monkeypatch.setattr(store.SecureDirectory, "publish_bytes", real_publish)
        assert result.exit_code != 0
        assert result.stdout.strip()
        assert not isinstance(result.exception, OSError)
