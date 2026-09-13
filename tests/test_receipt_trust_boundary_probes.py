"""Behavioural probes for the trust-boundary defects, in vocabulary both versions share.

Why this file is separate
-------------------------
The suites beside it exercise the corrected architecture — a strict secret, a stable
directory descriptor, verified provenance, a durable intent — and therefore cannot
even be *collected* against `e43851e`, where those names do not exist. An
``ImportError`` is not evidence of a defect: it is evidence of a rename.

So each defect the fifth audit reproduced also gets a probe here, written only in
the vocabulary `e43851e` already had (``audit_receipts``, ``build_activation_state``,
``evaluate``, ``write_receipt``, ``classify``, the CLI). Each one fails on
`e43851e` **for the property it names**, and passes afterwards. Together they are
the red baseline that matters.

Nothing here opens a socket, reads ``.env``, or touches a real secret or receipt.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import stat as statmodule
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from helpers_activation import (
    FAKE_RECEIPT_SECRET,
    Recorder,
    discover_args,
    events_payload,
    install,
    run,
    sports_payload,
)

FREE = {"x-requests-last": "0", "x-requests-remaining": "487"}
PATH_SENTINEL = "probe_outside_path_c41d"
CONTENT_SENTINEL = "soccer_probe_outside_content_71ab"


def corpus(directory: Path, secret: str = FAKE_RECEIPT_SECRET) -> None:
    from helpers_qualification_corpus import write_threshold_corpus

    write_threshold_corpus(directory, secret)


def one(**over: Any) -> dict[str, Any]:
    from helpers_qualification_corpus import effective_instant, sign_with
    from helpers_qualification_corpus import receipt as build

    drop = over.pop("drop", ())
    document = build(
        command=over.pop("command", "core"),
        status=over.pop("status", "CORE_LIVE_VERIFIED"),
        # Inside the protocol 8 manifest, and after the threshold corpus: a receipt
        # naming another competition is a campaign conflict since v8, and one filed
        # *before* an abort it caused would contradict its own timeline.
        sport=over.pop("sport", "soccer_epl"),
        moment=over.pop("moment", effective_instant() + timedelta(days=9)),
        tag=over.pop("tag", "a1" * 16),
        markets=over.pop("markets", ["h2h"]),
        credits=over.pop("credits", 1),
        secret=FAKE_RECEIPT_SECRET,
        **over,
    )
    for field in drop:
        document.pop(field, None)
    if drop:
        document.pop(act.SIGNATURE_FIELD, None)
        document[act.SIGNATURE_FIELD] = sign_with(document, FAKE_RECEIPT_SECRET)
    return document


def write(directory: Path, documents: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, document in enumerate(documents):
        (directory / f"20260901T12000{index % 10}-probe-{index:016d}.json").write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def state(directory: Path) -> dict[str, Any]:
    return act.build_activation_state(act.audit_receipts())


# ---------------------------------------------------------------------------
# P2-D1 — the evaluator's ambient effects
# ---------------------------------------------------------------------------
class TestTheEvaluatorTouchesNothingAmbient:
    def test_it_reads_no_environment_and_creates_no_secret(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corpus(workspace)
        _audit = act.audit_receipts()
        # From here on the evaluator must be inert.
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        (workspace / act.SECRET_FILENAME).unlink(missing_ok=True)
        reads = {"n": 0}
        real_get = os.environ.get

        def counting_get(key: str, default: Any = None) -> Any:
            if "BETMAXXING" in key:
                reads["n"] += 1
            return real_get(key, default)

        monkeypatch.setattr(os.environ, "get", counting_get)
        qual.evaluate(_audit)
        monkeypatch.setattr(os.environ, "get", real_get)
        assert reads["n"] == 0, "evaluate read the configuration"
        assert not (workspace / act.SECRET_FILENAME).exists(), "evaluate created a secret"

    def test_its_verdict_does_not_change_with_the_ambient_key(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corpus(workspace)
        _audit = act.audit_receipts()
        first = qual.evaluate(_audit)
        monkeypatch.setenv(act.SECRET_VARIABLE, "fedcba9876543210" * 4)
        assert qual.evaluate(_audit) == first


# ---------------------------------------------------------------------------
# P2-D2 — the directory boundary
# ---------------------------------------------------------------------------
class TestNothingOutsideTheDirectoryIsEverRead:
    @pytest.fixture
    def outside(self, tmp_path: Path) -> Path:
        directory = tmp_path / PATH_SENTINEL
        directory.mkdir()
        write(directory, [one(sport=CONTENT_SENTINEL)])
        (directory / act.SECRET_FILENAME).write_text(FAKE_RECEIPT_SECRET, encoding="utf-8")
        return directory

    def test_a_directory_that_is_a_link_yields_nothing(
        self, workspace: Path, outside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = tmp_path / "receipts-link"
        link.symlink_to(outside)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(link))
        _audit = act.audit_receipts()
        verified = _audit.batch
        assert len(verified) == 0
        rendered = json.dumps(act.build_activation_state(_audit), ensure_ascii=False)
        assert CONTENT_SENTINEL not in rendered
        assert PATH_SENTINEL not in rendered

    def test_a_parent_that_is_a_link_yields_nothing(
        self, workspace: Path, outside: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = tmp_path / "holder-link"
        holder.symlink_to(outside.parent)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(holder / outside.name))
        _audit = act.audit_receipts()
        verified = _audit.batch
        assert len(verified) == 0

    def test_a_directory_swapped_after_the_listing_yields_nothing(
        self, workspace: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The window the fifth audit walked through, forced deterministically."""
        write(workspace, [one(sport="soccer_inside")])
        fired = {"n": 0}
        real_glob = Path.glob

        def swapping_glob(self: Path, pattern: str) -> Any:
            names = list(real_glob(self, pattern))
            if fired["n"] == 0 and pattern == "*.json":
                fired["n"] = 1
                keep = self.parent / "kept-aside"
                self.rename(keep)
                self.symlink_to(outside)
            return iter(names)

        monkeypatch.setattr(Path, "glob", swapping_glob)
        _audit = act.audit_receipts()
        verified = _audit.batch
        monkeypatch.setattr(Path, "glob", real_glob)
        for document in verified:
            assert document.get("sport_key") != CONTENT_SENTINEL


# ---------------------------------------------------------------------------
# P2-D3 — a publication failure must be a business outcome
# ---------------------------------------------------------------------------
class TestAPublicationFailureIsReported:
    def test_the_cli_says_something_and_raises_no_raw_oserror(
        self, workspace: Path, keyed: Path, frozen_clock: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(
            monkeypatch,
            Recorder(
                {
                    "/sports/": lambda _r: httpx.Response(200, json=events_payload(), headers=FREE),
                    "/sports": lambda _r: httpx.Response(200, json=sports_payload(), headers=FREE),
                }
            ),
        )
        real_write = os.write

        def failing_write(fd: int, data: bytes) -> int:
            if fd > 2 and statmodule.S_ISREG(os.fstat(fd).st_mode):
                raise OSError(errno.ENOSPC, "injected")
            return real_write(fd, data)

        monkeypatch.setattr(os, "write", failing_write)
        result = run(*discover_args())
        monkeypatch.setattr(os, "write", real_write)

        assert result.exit_code != 0
        assert not isinstance(result.exception, OSError), (
            f"a raw {type(result.exception).__name__} reached the operator"
        )
        assert result.stdout.strip(), "the operator was told nothing at all"

    def test_a_directory_fsync_failure_is_not_swallowed(
        self, workspace: Path, frozen_clock: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        document = one()
        real_fsync = os.fsync

        def failing_dir_fsync(fd: int) -> None:
            if statmodule.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(errno.EIO, "injected durability failure")
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", failing_dir_fsync)
        try:
            with pytest.raises(Exception) as caught:
                act.write_receipt(dict(document))
            assert not isinstance(caught.value, AssertionError)
        finally:
            monkeypatch.setattr(os, "fsync", real_fsync)

    def test_a_write_that_never_progresses_terminates(self, tmp_path: Path) -> None:
        """A subprocess, a short timeout, and only this child is ever killed."""
        script = tmp_path / "child.py"
        script.write_text(
            "import os, sys, json\n"
            f"os.environ['BETMAXXING_ACTIVATION_RECEIPTS'] = {str(tmp_path / 'r')!r}\n"
            f"os.environ['BETMAXXING_ACTIVATION_RECEIPT_SECRET'] = {FAKE_RECEIPT_SECRET!r}\n"
            "os.environ['BETMAXXING_MODE'] = 'paper'\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from betmaxxing.providers.the_odds_api import activation as act\n"
            "from helpers_qualification_corpus import threshold_corpus\n"
            "document = threshold_corpus(os.environ['BETMAXXING_ACTIVATION_RECEIPT_SECRET'])[0]\n"
            "real = os.write\n"
            "def frozen(fd, data):\n"
            "    import stat\n"
            "    if fd > 2 and stat.S_ISREG(os.fstat(fd).st_mode):\n"
            "        return 0\n"
            "    return real(fd, data)\n"
            "os.write = frozen\n"
            "try:\n"
            "    act.write_receipt(dict(document))\n"
            "except BaseException as exc:\n"
            "    os.write = real\n"
            "    print('raised', type(exc).__name__)\n"
            "else:\n"
            "    os.write = real\n"
            "    print('returned')\n",
            encoding="utf-8",
        )
        env = dict(os.environ)
        source_root = str(Path(act.__file__).parents[3])
        tests_root = str(Path(__file__).parent)
        env["PYTHONPATH"] = os.pathsep.join([source_root, tests_root])
        proc = subprocess.Popen(
            [sys.executable, str(script), tests_root],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )
        try:
            out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise AssertionError("the publication loop never terminated") from None
        assert out.strip().startswith("raised"), f"{out!r} {err[-400:]!r}"


# ---------------------------------------------------------------------------
# P2-D4 — the couples the producer really writes
# ---------------------------------------------------------------------------
class TestTheContractKnowsWhatDiscoverWrites:
    @pytest.mark.parametrize("status", ["COST_UNVERIFIED", "COST_MISMATCH"])
    def test_a_free_call_with_an_unusable_credit_header_is_not_an_unknown_pair(
        self, workspace: Path, status: str
    ) -> None:
        document = one(
            command="discover",
            status=status,
            markets=[],
            credits=0,
            markets_requested=[],
            market_states={},
            markets_mapped=[],
            markets_observed=[],
            selections_mapped=0,
            freshness={},
            observed_credits=None if status == "COST_UNVERIFIED" else 3,
            accounted_credits=0,
            estimated_credits=0,
            bookmaker_state="NOT_RETURNED",
            events_returned=1,
            events_in_window=1,
            events_admissible=1,
            event_tags=["a" * 32],
            event_tag="",
        )
        assert qual.classify(document) != "unknown_command_status_pair"

    def test_an_honest_discover_cost_receipt_does_not_conflict_a_corpus(
        self, workspace: Path
    ) -> None:
        corpus(workspace)
        write(
            workspace,
            [
                one(
                    tag="f1" * 16,
                    command="discover",
                    status="COST_UNVERIFIED",
                    markets=[],
                    credits=0,
                    markets_requested=[],
                    market_states={},
                    markets_mapped=[],
                    markets_observed=[],
                    selections_mapped=0,
                    freshness={},
                    observed_credits=None,
                    accounted_credits=0,
                    estimated_credits=0,
                    bookmaker_state="NOT_RETURNED",
                    events_returned=1,
                    events_in_window=1,
                    events_admissible=1,
                    event_tags=["a" * 32],
                    event_tag="",
                )
            ],
        )
        document = state(workspace)
        assert document["qualification_unknown_pair_receipts"] == 0
        # The pair is honest, the receipt costs nothing and it spoils no threshold — that
        # is the claim. What this corpus does contradict is the campaign's four
        # pre-registered discoveries, a ceiling frozen in 03C-2F bis: since quater the
        # shared corpus is the register in full, so this receipt is a *fifth* discovery
        # whatever it says about its own cost.
        assert all(entry["passed"] for entry in document["criteria_results"])
        assert document["campaign_invocation_counts"]["discover"] == 5
        assert any(
            "invocations discover" in conflict for conflict in document["evidence_conflicts"]
        ), document["evidence_conflicts"]


# ---------------------------------------------------------------------------
# P2-D5 — the command domain
# ---------------------------------------------------------------------------
class TestOnlyDiscoverReportsADiscovery:
    @pytest.mark.parametrize(
        ("label", "over"),
        [
            ("plan", {"command": "plan", "status": "PLAN_ONLY"}),
            ("absent", {"drop": ("command",)}),
            ("empty", {"command": ""}),
            ("unknown", {"command": "sync"}),
            ("integer", {"command": 7}),
            ("None", {"command": None}),
            ("list", {"command": ["core"]}),
            ("Core", {"command": "Core"}),
            ("padded", {"command": " core "}),
        ],
    )
    def test_no_other_command_claims_a_discovery(
        self, workspace: Path, label: str, over: dict[str, Any]
    ) -> None:
        write(workspace, [one(**over)])
        assert state(workspace)["execution_state"] != "DISCOVERY_ATTEMPTED", label

    @pytest.mark.parametrize("command", ["Core", " core ", "CORE"])
    def test_a_lookalike_paid_command_never_hides_from_the_census(
        self, workspace: Path, command: str
    ) -> None:
        write(workspace, [one(command=command)])
        document = state(workspace)
        assert document["execution_state"] != "CORE_ATTEMPTED"
        assert document["execution_state"] != "DISCOVERY_ATTEMPTED"
        assert document["accounted_credits_total"] == 0


# ---------------------------------------------------------------------------
# P3-8 / P3-9 — the labels and the rejected receipts
# ---------------------------------------------------------------------------
class TestTheLabelsSayOnlyWhatIsEstablished:
    def test_no_bucket_claims_a_reach_that_is_not_established(self) -> None:
        for over in (
            {"may_have_reached_provider": "yes"},
            {"drop": ("may_have_reached_provider",)},
        ):
            category = qual.cost_category(one(**over))
            assert "provider_reached" not in category, category

    def test_a_rejected_receipt_feeds_no_semantic_counter(self, workspace: Path) -> None:
        write(workspace, [one(selections_mapped="3", accounted_credits=9)])
        document = state(workspace)
        assert all(count == 0 for count in document["paid_call_cost_census"].values())
        assert document["connectivity_and_cost_proof"] == "NOT_EXERCISED"
        # No positive claim from a rejected receipt — and no negative one either: saying
        # "nothing was attempted" is itself an affirmation the receipt cannot support.
        assert document["execution_state"] != "CORE_ATTEMPTED"
        assert document["execution_state"] != "NO_NETWORK_ATTEMPTED"
        assert document["paid_activation_state"] == "PAID_ATTEMPT_STATE_UNESTABLISHED"
        assert document["accounted_credits_total"] == 0
        assert document["rejected_receipt_credits_not_counted"] == 9


# ---------------------------------------------------------------------------
# P3-4 — the quarantine's bounds
# ---------------------------------------------------------------------------
class TestQuarantineStaysInsideTheDirectory:
    def test_an_outside_path_is_never_renamed(self, workspace: Path, tmp_path: Path) -> None:
        victim = tmp_path / "outside-victim.json"
        victim.write_text("OUTSIDE", encoding="utf-8")
        with pytest.raises(Exception) as caught:
            act.quarantine_incomplete_receipt(str(victim))
        assert not isinstance(caught.value, AssertionError)
        assert victim.exists(), "a file outside the receipt directory was moved"

    def test_a_collision_never_replaces_the_earlier_bytes(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import secrets as secrets_module

        monkeypatch.setattr(secrets_module, "token_hex", lambda _n=4: "collide")
        monkeypatch.setattr(act.secrets, "token_hex", lambda _n=4: "collide")
        workspace.mkdir(parents=True, exist_ok=True)
        name = "20260901T120000-core-aa11bb22cc33dd44.json"
        (workspace / name).write_text("FIRST", encoding="utf-8")
        act.quarantine_incomplete_receipt(name)
        (workspace / name).write_text("SECOND", encoding="utf-8")
        with contextlib.suppress(Exception):
            # A bounded refusal is an acceptable answer; losing the first bytes is not.
            act.quarantine_incomplete_receipt(name)
        bodies = sorted(
            path.read_text(encoding="utf-8")
            for path in workspace.iterdir()
            if act.QUARANTINE_SUFFIX in path.name
        )
        assert "FIRST" in bodies, "the first quarantined receipt's bytes were destroyed"
