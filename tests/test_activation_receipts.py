"""Receipts as evidence: signed, chained by argument, and refused when altered.

Three things were wrong, and they compound.

**`discover` wrote nothing.** The runbook said every successful network step
leaves a receipt; the discovery step did not. So the only proof `core` could have
demanded — that this event was in an approved discovery — did not exist, and
`core` accepted any well-formed `--event-id`.

**`additional` chose its own evidence.** It scanned every JSON file in the
receipt directory for one carrying `status == CORE_LIVE_VERIFIED` and a matching
event hash. It never checked the command, the schema, the sport, the bookmaker,
the age, or whether the file had been edited. Picking a proof on the operator's
behalf, from an unauthenticated file, out of a directory anyone can write to, is
not a precondition — it is a formality.

**Nothing was authenticated.** A plain JSON file with an unsalted SHA of a public
fixture id resists a casual reader and nothing else: the hash is computable from
the provider's own event list, and a stray editor keystroke silently promotes a
failed step into a passing one.

So: an HMAC secret generated locally on first network need, `0600`, in the
gitignored receipt directory, never printed; event ids carried as HMAC rather
than bare SHA; every receipt signed over its canonical JSON and verified with
`hmac.compare_digest` before it is trusted; and the parent receipt supplied
explicitly by path, never discovered.

No network anywhere in this file.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest

from helpers_activation import (
    BOOKMAKER,
    EVENT_ID,
    FAKE_RECEIPT_SECRET,
    OTHER_BOOKMAKER,
    OTHER_EVENT_ID,
    OTHER_SPORT,
    SPORT,
    Recorder,
    additional_args,
    core_args,
    discover_args,
    event_odds_payload,
    events_payload,
    install,
    odds_payload,
    receipt_path,
    receipts_in,
    run,
    sports_payload,
    tamper,
)

FREE_HEADERS = {"x-requests-last": "0", "x-requests-remaining": "480"}
PAID_HEADERS = {"x-requests-last": "1", "x-requests-remaining": "479"}


def free_routes(
    *, sport: str = SPORT, event_id: str = EVENT_ID, hours_ahead: float = 6.0
) -> dict[str, Any]:
    return {
        "/sports/": lambda _r: httpx.Response(
            200,
            json=events_payload(hours_ahead=hours_ahead, event_id=event_id, sport=sport),
            headers=FREE_HEADERS,
        ),
        "/sports": lambda _r: httpx.Response(
            200, json=sports_payload(key=sport), headers=FREE_HEADERS
        ),
    }


def do_discover(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sport: str = SPORT,
    bookmaker: str = BOOKMAKER,
    event_id: str = EVENT_ID,
) -> Any:
    install(monkeypatch, Recorder(free_routes(sport=sport, event_id=event_id)))
    result = run(*discover_args(sport=sport, bookmaker=bookmaker))
    assert result.exit_code == 0, result.stdout
    return result


def do_core(
    monkeypatch: pytest.MonkeyPatch,
    receipts: Path,
    *,
    sport: str = SPORT,
    bookmaker: str = BOOKMAKER,
    event_id: str = EVENT_ID,
) -> Any:
    install(
        monkeypatch,
        Recorder(
            {
                "/odds": lambda _r: httpx.Response(
                    200,
                    json=odds_payload(event_id=event_id, sport=sport, bookmaker=bookmaker),
                    headers=PAID_HEADERS,
                )
            }
        ),
    )
    result = run(
        *core_args(
            discovery_receipt=str(receipt_path(receipts, "discover")),
            sport=sport,
            bookmaker=bookmaker,
            event_id=event_id,
        )
    )
    assert result.exit_code == 0, result.stdout
    return result


# ---------------------------------------------------------------------------
# The local signing secret
# ---------------------------------------------------------------------------
class TestTheSigningSecret:
    def test_it_is_created_on_first_need_and_reused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation

        monkeypatch.delenv("BETMAXXING_ACTIVATION_RECEIPT_SECRET", raising=False)
        first = activation.receipt_secret()
        second = activation.receipt_secret()
        assert first == second
        assert len(first) >= 32

    def test_it_lives_in_the_gitignored_receipt_directory(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation

        monkeypatch.delenv("BETMAXXING_ACTIVATION_RECEIPT_SECRET", raising=False)
        activation.receipt_secret()
        assert (keyed / activation.SECRET_FILENAME).is_file()

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
    def test_it_is_readable_by_its_owner_only(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation

        monkeypatch.delenv("BETMAXXING_ACTIVATION_RECEIPT_SECRET", raising=False)
        activation.receipt_secret()
        mode = stat.S_IMODE((keyed / activation.SECRET_FILENAME).stat().st_mode)
        assert mode == 0o600, f"secret file mode is {oct(mode)}"

    def test_it_never_appears_in_any_receipt(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        do_core(monkeypatch, keyed)
        for path in keyed.glob("*.json"):
            assert FAKE_RECEIPT_SECRET not in path.read_text(encoding="utf-8")

    def test_it_never_appears_in_command_output(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        result = run(*discover_args(extra=("--json",)))
        assert FAKE_RECEIPT_SECRET not in result.output

    def test_the_secret_file_is_not_mistaken_for_a_receipt(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """It must not be named `*.json` and must not be loadable as evidence."""
        from betmaxxing.providers.the_odds_api import activation

        monkeypatch.delenv("BETMAXXING_ACTIVATION_RECEIPT_SECRET", raising=False)
        activation.receipt_secret()
        assert not activation.SECRET_FILENAME.endswith(".json")


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------
class TestSignature:
    def test_every_receipt_carries_one(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        receipts = receipts_in(keyed)
        assert receipts
        for receipt in receipts:
            assert receipt["signature"]
            assert receipt["schema_version"] == 2

    def test_it_verifies_against_the_local_secret(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation

        do_discover(monkeypatch)
        path = receipt_path(keyed, "discover")
        assert activation.verify_receipt(json.loads(path.read_text(encoding="utf-8")))

    def test_a_changed_field_invalidates_it(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation

        do_discover(monkeypatch)
        path = receipt_path(keyed, "discover")
        tamper(path, status="CORE_LIVE_VERIFIED")
        assert not activation.verify_receipt(json.loads(path.read_text(encoding="utf-8")))

    def test_it_is_computed_over_canonical_json(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """Key order and whitespace must not change the signature."""
        from betmaxxing.providers.the_odds_api import activation

        do_discover(monkeypatch)
        payload = json.loads(receipt_path(keyed, "discover").read_text(encoding="utf-8"))
        shuffled = dict(reversed(list(payload.items())))
        assert activation.verify_receipt(shuffled)

    def test_a_receipt_signed_with_another_secret_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation

        do_discover(monkeypatch)
        payload = json.loads(receipt_path(keyed, "discover").read_text(encoding="utf-8"))
        monkeypatch.setenv("BETMAXXING_ACTIVATION_RECEIPT_SECRET", "f" * 64)
        assert not activation.verify_receipt(payload)


class TestTheEventIdentifierIsHmacNotSha:
    def test_it_is_not_the_bare_sha_of_the_public_id(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """An unsalted digest is computable from the provider's own event list."""
        import hashlib

        do_discover(monkeypatch)
        receipt = receipts_in(keyed)[-1]
        bare = hashlib.sha256(EVENT_ID.encode()).hexdigest()[:16]
        assert bare not in json.dumps(receipt)

    def test_it_is_stable_across_processes_on_one_installation(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation

        first = activation.event_tag(EVENT_ID)
        second = activation.event_tag(EVENT_ID)
        assert first == second and first

    def test_it_differs_between_installations(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation

        mine = activation.event_tag(EVENT_ID)
        monkeypatch.setenv("BETMAXXING_ACTIVATION_RECEIPT_SECRET", "a" * 64)
        theirs = activation.event_tag(EVENT_ID)
        assert mine != theirs

    def test_two_events_get_two_tags(self, keyed: Path) -> None:
        from betmaxxing.providers.the_odds_api import activation

        assert activation.event_tag(EVENT_ID) != activation.event_tag(OTHER_EVENT_ID)


# ---------------------------------------------------------------------------
# discover writes evidence
# ---------------------------------------------------------------------------
class TestDiscoverWritesEvidence:
    def test_a_successful_discovery_writes_a_receipt(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        receipt = receipts_in(keyed)[-1]
        assert receipt["command"] == "discover"
        assert receipt["status"] == "DISCOVERY_VERIFIED"

    def test_it_records_the_exact_window_and_an_expiry(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        receipt = receipts_in(keyed)[-1]
        assert receipt["window_from"] == "2026-08-04T12:00:00+00:00"
        assert receipt["window_to"] == "2026-08-05T12:00:00+00:00"
        assert receipt["expires_at"] > receipt["recorded_at"]

    def test_it_records_the_admissible_events_as_tags_only(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        from betmaxxing.providers.the_odds_api import activation

        do_discover(monkeypatch)
        receipt = receipts_in(keyed)[-1]
        assert receipt["event_tags"] == [activation.event_tag(EVENT_ID)]
        blob = json.dumps(receipt)
        assert EVENT_ID not in blob
        for forbidden in ("Olympique", "Rennais"):
            assert forbidden not in blob

    def test_the_terminal_output_still_shows_what_a_human_needs(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """The receipt is sanitised; the screen is how you choose an event."""
        install(monkeypatch, Recorder(free_routes()))
        result = run(*discover_args())
        assert EVENT_ID in result.stdout

    def test_it_prints_the_receipt_path_to_pass_on(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        install(monkeypatch, Recorder(free_routes()))
        result = run(*discover_args())
        assert receipt_path(keyed, "discover").name in result.stdout


# ---------------------------------------------------------------------------
# core demands the discovery receipt
# ---------------------------------------------------------------------------
class TestCoreDemandsADiscoveryReceipt:
    def test_the_argument_is_mandatory(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(
            "core",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            "1",
            "--acknowledge-credits",
            "1",
            "--allow-network",
        )
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_missing_file_is_refused_before_the_network(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=str(keyed / "nope.json")))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_an_event_absent_from_the_discovery_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch, event_id=EVENT_ID)
        recorder = Recorder({"/odds": odds_payload(event_id=OTHER_EVENT_ID)})
        install(monkeypatch, recorder)
        result = run(
            *core_args(
                discovery_receipt=str(receipt_path(keyed, "discover")), event_id=OTHER_EVENT_ID
            )
        )
        assert result.exit_code != 0
        assert recorder.requests == [], "core priced an event no discovery had approved"

    def test_a_tampered_discovery_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        path = receipt_path(keyed, "discover")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["event_tags"] = [*payload["event_tags"], "forged-tag"]
        path.write_text(json.dumps(payload), encoding="utf-8")

        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=str(path)))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_receipt_for_another_sport_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch, sport=OTHER_SPORT)
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=str(receipt_path(keyed, "discover"))))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_receipt_for_another_bookmaker_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch, bookmaker=OTHER_BOOKMAKER)
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=str(receipt_path(keyed, "discover"))))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_an_expired_receipt_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """Yesterday's discovery says nothing about today's fixtures."""
        from betmaxxing.providers.the_odds_api import activation

        do_discover(monkeypatch)
        path = receipt_path(keyed, "discover")
        # Same clock the receipt was written with, advanced past its expiry.
        monkeypatch.setattr(activation, "_clock", lambda: activation.ensure_utc(_far_future()))
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=str(path)))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_core_receipt_cannot_stand_in_for_a_discovery(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        do_core(monkeypatch, keyed)
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=str(receipt_path(keyed, "core"))))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_the_core_receipt_references_its_parent(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        parent = receipts_in(keyed)[-1]
        do_core(monkeypatch, keyed)
        core = [r for r in receipts_in(keyed) if r["command"] == "core"][-1]
        assert core["parent_receipt_id"] == parent["receipt_id"]


def _far_future() -> Any:
    from datetime import timedelta

    from helpers_activation import NOW

    return NOW + timedelta(days=3)


# ---------------------------------------------------------------------------
# additional demands the core receipt
# ---------------------------------------------------------------------------
class TestAdditionalDemandsACoreReceipt:
    def test_the_argument_is_mandatory(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/events/": event_odds_payload()})
        install(monkeypatch, recorder)
        result = run(
            "additional",
            "--sport",
            SPORT,
            "--bookmaker",
            BOOKMAKER,
            "--event-id",
            EVENT_ID,
            "--max-credits",
            "5",
            "--acknowledge-credits",
            "5",
            "--allow-network",
        )
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_it_does_not_scan_the_directory_for_evidence(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """A valid core receipt on disk is not an authorisation to spend five credits."""
        import inspect

        from betmaxxing.providers.the_odds_api import activation

        source = inspect.getsource(activation)
        assert "read_receipts(" not in source, (
            "the harness still walks the receipt directory choosing its own proof"
        )

    def test_a_discovery_receipt_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        recorder = Recorder({"/events/": event_odds_payload()})
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=str(receipt_path(keyed, "discover"))))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_tampered_core_receipt_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        do_core(monkeypatch, keyed)
        path = receipt_path(keyed, "core")
        tamper(path, accounted_credits=0)
        recorder = Recorder({"/events/": event_odds_payload()})
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=str(path)))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_forged_status_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        """The exact attack the unsigned v1 receipt allowed."""
        do_discover(monkeypatch)
        install(monkeypatch, Recorder({"/odds": lambda _r: httpx.Response(200, json=[])}))
        run(*core_args(discovery_receipt=str(receipt_path(keyed, "discover"))))
        failed = [r for r in receipts_in(keyed) if r["command"] == "core"]
        assert failed and failed[-1]["status"] != "CORE_LIVE_VERIFIED"

        path = keyed / failed[-1]["_filename"]
        tamper(path, status="CORE_LIVE_VERIFIED")
        recorder = Recorder({"/events/": event_odds_payload()})
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=str(path)))
        assert result.exit_code != 0
        assert recorder.requests == []

    @pytest.mark.parametrize(
        ("field", "value"),
        [("sport_key", OTHER_SPORT), ("bookmaker", OTHER_BOOKMAKER), ("command", "discover")],
    )
    def test_a_mismatching_field_is_refused(
        self,
        keyed: Path,
        monkeypatch: pytest.MonkeyPatch,
        frozen_clock: None,
        field: str,
        value: str,
    ) -> None:
        do_discover(monkeypatch)
        do_core(monkeypatch, keyed)
        path = receipt_path(keyed, "core")
        tamper(path, **{field: value})
        recorder = Recorder({"/events/": event_odds_payload()})
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=str(path)))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_core_receipt_for_another_event_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        do_core(monkeypatch, keyed)
        recorder = Recorder({"/events/": event_odds_payload(event_id=OTHER_EVENT_ID)})
        install(monkeypatch, recorder)
        result = run(
            *additional_args(core_receipt=str(receipt_path(keyed, "core")), event_id=OTHER_EVENT_ID)
        )
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_a_core_receipt_without_a_mapped_h2h_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        do_core(monkeypatch, keyed)
        path = receipt_path(keyed, "core")
        tamper(path, selections_mapped=0)
        recorder = Recorder({"/events/": event_odds_payload()})
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=str(path)))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_the_happy_chain_is_accepted(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        do_core(monkeypatch, keyed)
        recorder = Recorder(
            {
                "/events/": lambda _r: httpx.Response(
                    200, json=event_odds_payload(), headers={"x-requests-last": "5"}
                )
            }
        )
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=str(receipt_path(keyed, "core"))))
        assert result.exit_code == 0, result.stdout
        assert len(recorder.requests) == 1

    def test_the_additional_receipt_references_its_parent(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        do_core(monkeypatch, keyed)
        core = [r for r in receipts_in(keyed) if r["command"] == "core"][-1]
        recorder = Recorder(
            {
                "/events/": lambda _r: httpx.Response(
                    200, json=event_odds_payload(), headers={"x-requests-last": "5"}
                )
            }
        )
        install(monkeypatch, recorder)
        run(*additional_args(core_receipt=str(receipt_path(keyed, "core"))))
        extra = [r for r in receipts_in(keyed) if r["command"] == "additional"][-1]
        assert extra["parent_receipt_id"] == core["receipt_id"]


# ---------------------------------------------------------------------------
# Path safety and legacy receipts
# ---------------------------------------------------------------------------
class TestOnlyTheAuthorisedDirectoryIsTrusted:
    def test_a_receipt_outside_the_directory_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None, tmp_path: Path
    ) -> None:
        do_discover(monkeypatch)
        outside = tmp_path / "elsewhere.json"
        outside.write_text(receipt_path(keyed, "discover").read_text(encoding="utf-8"))
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=str(outside)))
        assert result.exit_code != 0
        assert recorder.requests == []

    @pytest.mark.skipif(os.name != "posix", reason="symlinks")
    def test_a_symlink_into_the_directory_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None, tmp_path: Path
    ) -> None:
        do_discover(monkeypatch)
        target = tmp_path / "outside.json"
        target.write_text(receipt_path(keyed, "discover").read_text(encoding="utf-8"))
        link = keyed / "linked.json"
        link.symlink_to(target)
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=str(link)))
        assert result.exit_code != 0
        assert recorder.requests == []


class TestLegacyReceiptsAreRefusedNotPromoted:
    def _v1(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "20260804T120000-core-abcdef01.json"
        path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "command": "core",
                    "status": "CORE_LIVE_VERIFIED",
                    "recorded_at": "2026-08-04T12:00:00+00:00",
                    "sport_key": SPORT,
                    "bookmaker": BOOKMAKER,
                    "event_id_hash": "abcdef0123456789",
                    "max_credits": 1,
                    "observed_credits": 1,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_a_v1_receipt_cannot_authorise_additional(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        recorder = Recorder({"/events/": event_odds_payload()})
        install(monkeypatch, recorder)
        result = run(*additional_args(core_receipt=str(self._v1(keyed))))
        assert result.exit_code != 0
        assert recorder.requests == []

    def test_the_refusal_says_to_rerun_discover(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        install(monkeypatch, Recorder({"/events/": event_odds_payload()}))
        result = run(*additional_args(core_receipt=str(self._v1(keyed))))
        assert "discover" in result.stdout.lower()

    def test_an_unknown_schema_is_refused(
        self, keyed: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: None
    ) -> None:
        do_discover(monkeypatch)
        path = receipt_path(keyed, "discover")
        tamper(path, schema_version=99)
        recorder = Recorder({"/odds": odds_payload()})
        install(monkeypatch, recorder)
        result = run(*core_args(discovery_receipt=str(path)))
        assert result.exit_code != 0
        assert recorder.requests == []
