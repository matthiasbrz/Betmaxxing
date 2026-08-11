"""An intent is a cautious blocker, never a positive proof — D-077, §3.6.

Why this suite exists
---------------------
v6 introduced the intent journal to close the worst failure mode of v5: five
credits committed, the receipt unpublishable, and no trace at all that anything
had gone out. The file is written and ``fsync``-ed before the socket, which is
right. What the sixth re-audit found is how easily it goes away again.

``reconcile_intents`` built its set of published identifiers from
``_read_receipt_payloads`` — which parses JSON and verifies **nothing**. A
two-key file was enough:

    {"receipt_id": "aa11bb22cc33dd44"}

``reconcile_intents()`` returned 1, the intent was gone, zero receipts were
verified, and the gate moved from ``EVIDENCE_CONFLICT`` back to
``INSUFFICIENT_EVIDENCE``. Thirteen forged shapes were tried — unsigned, foreign
key, unknown schema, unknown command, wrong sport, wrong bookmaker, wrong tag,
wrong cost, historical protocol — and **all thirteen** resolved. No material scope
was ever compared.

Three smaller holes came with it. ``_IDENTIFIER`` used ``re.match`` with ``$``,
so ``"aaaaaaaa\\n"`` was a legal identifier — the very defect the module documents
having fixed for the secret's own pattern. Republishing the same ``attempt_id``
with a different command, sport, bookmaker, ceiling or tag was accepted in
silence, the file keeping the first scope. And an existing *empty* file at the
intent's name counted as a successful publication, so the trace meant to survive a
crash was zero bytes long.

Finally, the untrusted body was echoed: ``unresolved_attempt_intent_details``
published the file verbatim and the human rendering repeated its ``command`` and
``max_credits``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from betmaxxing.providers.the_odds_api import receipt_store as store
from betmaxxing.providers.the_odds_api.activation import ensure_utc
from helpers_receipt_boundary import install_secret

LOCAL = "0011223344556677889900aabbccddeeff00112233445566778899aabbccddee"
FOREIGN = "ffeeddccbbaa00998877665544332211ffeeddccbbaa0099887766554433220"
ATTEMPT = "aa11bb22cc33dd44"
SENTINELS = (
    "QQINTENTCOMMAND01",
    "QQINTENTSPORT02",
    "QQINTENTBOOK03",
    "QQINTENTTAG04",
    "QQINTENTCEILING05",
    "QQINTENTNOTE06",
    "QQINTENTVERSION07",
    "QQINTENTSTATE08",
    "QQINTENTINSTANT09",
    "QQINTENTEXTRA10",
)


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
    import hashlib
    import hmac

    # Dated at or after the effective instant so the same receipts also read as current
    # evidence for the gate assertions below. Reconciliation itself does not require it:
    # it requires the same *lineage* (schema, protocol, adapter-evidence version), which
    # is what refuses a receipt produced under an earlier protocol.
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
        "bookmaker_state": "OBSERVED",
        "quota_remaining": 400,
    }
    secret = over.pop("_secret", LOCAL)
    unsigned = over.pop("_unsigned", False)
    document.update(over)
    if not unsigned:
        document[act.SIGNATURE_FIELD] = hmac.new(
            str(secret).encode("utf-8"), act.canonical_bytes(document), hashlib.sha256
        ).hexdigest()
    return document


def publish(directory: Path, document: dict[str, Any], name: str = "evidence") -> None:
    (directory / f"20260901T120000-core-{name}.json").write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def pending() -> int:
    return len(act.unresolved_intents())


# ---------------------------------------------------------------------------
# 3.6 — identity
# ---------------------------------------------------------------------------
class TestTheIdentifierIsAnExactMatch:
    @pytest.mark.parametrize(
        ("label", "value", "accepted"),
        [
            ("7 hex", "a" * 7, False),
            ("8 hex", "a" * 8, True),
            ("16 hex", "a" * 16, True),
            ("64 hex", "a" * 64, True),
            ("65 hex", "a" * 65, False),
            ("uppercase", "A" * 16, False),
            ("trailing newline", "a" * 16 + "\n", False),
            ("leading newline", "\n" + "a" * 16, False),
            ("trailing space", "a" * 16 + " ", False),
            ("tab", "a" * 8 + "\t", False),
            ("ansi", "\x1b[31m" + "a" * 16, False),
            ("separator", "aa/bb" + "a" * 11, False),
            ("nul", "a" * 15 + "\x00", False),
            ("unicode", "é" * 16, False),
            ("very large", "a" * 100_000, False),
            ("empty", "", False),
        ],
    )
    def test_only_lowercase_hexadecimal_of_the_right_length_is_a_name(
        self, receipts: Path, label: str, value: str, accepted: bool
    ) -> None:
        if accepted:
            act.publish_intent(attempt(attempt_id=value))
            assert f"{value}{act.INTENT_SUFFIX}" in os.listdir(receipts)
        else:
            with pytest.raises((store.StoreRefused, act.Refused)):
                act.publish_intent(attempt(attempt_id=value))
            assert not [n for n in os.listdir(receipts) if n.endswith(act.INTENT_SUFFIX)]

    def test_the_pattern_is_anchored_on_both_ends(self) -> None:
        assert store._IDENTIFIER.fullmatch("a" * 16)
        assert not store._IDENTIFIER.fullmatch("a" * 16 + "\n")


class TestTheBodyHasAPositiveContract:
    def test_a_published_intent_carries_exactly_the_declared_fields(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        body = json.loads((receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").read_text(encoding="utf-8"))
        assert set(body) == {
            "intent_version",
            "attempt_id",
            "command",
            "sport_key",
            "bookmaker",
            "event_tag",
            "max_credits",
            "state",
            "prepared_at",
        }
        assert body["intent_version"] == store.INTENT_VERSION
        assert body["attempt_id"] == ATTEMPT
        assert body["command"] == "core"
        assert body["state"] == "PREPARED"
        assert isinstance(body["max_credits"], int)

    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param({"intent_version": 999}, id="unknown-version"),
            pytest.param({"intent_version": "1"}, id="version-mistyped"),
            pytest.param({"command": "banana"}, id="command-outside-domain"),
            pytest.param({"command": 7}, id="command-mistyped"),
            pytest.param({"max_credits": "5"}, id="ceiling-mistyped"),
            pytest.param({"max_credits": -1}, id="ceiling-negative"),
            pytest.param({"max_credits": 10**9}, id="ceiling-out-of-range"),
            pytest.param({"state": "DONE"}, id="state-outside-domain"),
            pytest.param({"sport_key": 7}, id="sport-mistyped"),
            pytest.param({"prepared_at": "not-an-instant"}, id="instant-unparseable"),
            pytest.param({"attempt_id": "bb22cc33dd44ee55"}, id="body-disagrees-with-name"),
            pytest.param({"surprise": "extra"}, id="unknown-field"),
            pytest.param({"command": None}, id="field-absent"),
        ],
    )
    def test_a_body_outside_the_contract_is_invalid_and_still_blocks(
        self, receipts: Path, mutate: dict[str, Any]
    ) -> None:
        body = {
            "intent_version": store.INTENT_VERSION,
            "attempt_id": ATTEMPT,
            "command": "core",
            "sport_key": "soccer_probe",
            "bookmaker": "probebook",
            "event_tag": act.event_tag("EV-PROBE-1", LOCAL),
            "max_credits": 1,
            "state": "PREPARED",
            "prepared_at": ensure_utc(act._clock()).isoformat(),
        }
        for key, value in mutate.items():
            if value is None:
                body.pop(key, None)
            else:
                body[key] = value
        (receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").write_text(
            json.dumps(body, indent=2), encoding="utf-8"
        )
        listed = act.unresolved_intents()
        assert len(listed) == 1
        assert listed[0].get("state") == "UNREADABLE_OR_INVALID"
        assert qual.evaluate(act.audit_receipts())["eligible_for_human_promotion_review"] is False

    def test_an_unreadable_intent_blocks_without_being_parsed(self, receipts: Path) -> None:
        (receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").write_bytes(b"\xff\xfe not json \x00")
        listed = act.unresolved_intents()
        assert len(listed) == 1
        assert listed[0].get("state") == "UNREADABLE_OR_INVALID"


class TestNothingHostileIsEverEchoed:
    def test_ten_sentinels_in_an_intent_reach_no_output(self, receipts: Path) -> None:
        (receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").write_text(
            json.dumps(
                {
                    "intent_version": SENTINELS[6],
                    "attempt_id": ATTEMPT,
                    "command": SENTINELS[0],
                    "sport_key": SENTINELS[1],
                    "bookmaker": SENTINELS[2],
                    "event_tag": SENTINELS[3],
                    "max_credits": SENTINELS[4],
                    "state": SENTINELS[7],
                    "prepared_at": SENTINELS[8],
                    "note": "\x1b[31m" + SENTINELS[5] + "\n" + SENTINELS[9],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        from helpers_activation import run

        plain = run("status")
        as_json = run("status", "--json")
        assert plain.exit_code == 0, plain.stdout
        assert as_json.exit_code == 0, as_json.stdout
        rendered = plain.stdout + as_json.stdout
        leaked = [s for s in SENTINELS if s in rendered]
        assert leaked == [], leaked
        assert "\x1b[" not in rendered
        assert json.loads(as_json.stdout)["eligible_for_human_promotion_review"] is False

    def test_the_state_document_names_the_category_not_the_content(self, receipts: Path) -> None:
        (receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").write_text(
            json.dumps({"attempt_id": ATTEMPT, "command": SENTINELS[0]}), encoding="utf-8"
        )
        state = act.build_activation_state(act.audit_receipts())
        rendered = json.dumps(state, default=str) + "\n".join(
            str(line) for line in act.status_lines(state)
        )
        assert SENTINELS[0] not in rendered
        assert "UNREADABLE_OR_INVALID" in rendered
        assert str(state["unresolved_attempt_intents"]) == "1"


# ---------------------------------------------------------------------------
# 3.6 — idempotence and collision
# ---------------------------------------------------------------------------
class TestPublicationIsIdempotentOnlyOnIdenticalBytes:
    def test_the_same_intent_twice_leaves_one_identical_file(self, receipts: Path) -> None:
        # One attempt, published twice: that is the replay production performs, and the
        # bytes must be identical because `prepared_at` belongs to the attempt.
        one = attempt()
        act.publish_intent(one)
        first = (receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").read_bytes()
        act.publish_intent(one)
        assert (receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").read_bytes() == first
        assert pending() == 1

    @pytest.mark.parametrize(
        "over",
        [
            pytest.param({"command": "additional"}, id="command"),
            pytest.param({"sport": "tennis_probe"}, id="sport"),
            pytest.param({"bookmaker": "otherbook"}, id="bookmaker"),
            pytest.param({"ceiling": 5}, id="ceiling"),
            pytest.param({"event_tags": [act.event_tag("EV-OTHER", LOCAL)]}, id="event-tag"),
        ],
    )
    def test_a_divergent_scope_under_the_same_identifier_is_refused(
        self, receipts: Path, over: dict[str, Any]
    ) -> None:
        act.publish_intent(attempt())
        kept = (receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").read_bytes()
        with pytest.raises((act.Refused, store.StoreRefused)):
            act.publish_intent(attempt(**over))
        assert (receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").read_bytes() == kept

    @pytest.mark.parametrize("shape", ["empty", "truncated", "symlink", "directory"])
    def test_a_suspect_target_is_never_a_successful_publication(
        self, receipts: Path, tmp_path: Path, shape: str
    ) -> None:
        name = receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}"
        if shape == "empty":
            name.write_text("", encoding="utf-8")
        elif shape == "truncated":
            name.write_text('{"attempt_id": "aa11bb2', encoding="utf-8")
        elif shape == "symlink":
            (tmp_path / "outside.intent").write_text("{}", encoding="utf-8")
            name.symlink_to(tmp_path / "outside.intent")
        else:
            name.mkdir()
        with pytest.raises((act.Refused, store.StoreRefused)):
            act.publish_intent(attempt())

    def test_a_forced_collision_between_two_commands_stops_the_second(
        self, receipts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(act.secrets, "token_hex", lambda _n=8: ATTEMPT)
        act.publish_intent(attempt(command="core", ceiling=1))
        with pytest.raises((act.Refused, store.StoreRefused)):
            act.publish_intent(attempt(command="additional", ceiling=5))
        body = json.loads((receipts / f"{ATTEMPT}{act.INTENT_SUFFIX}").read_text(encoding="utf-8"))
        assert body["command"] == "core"
        assert body["max_credits"] == 1


# ---------------------------------------------------------------------------
# 3.6 — reconciliation
# ---------------------------------------------------------------------------
FORGERIES: list[tuple[str, dict[str, Any]]] = [
    ("json only, no signature", {"_unsigned": True}),
    ("signature of another key", {"_secret": FOREIGN}),
    ("unknown schema", {"schema_version": 999}),
    ("unknown command and status", {"command": "banana", "status": "NOPE"}),
    ("historical protocol", {"qualification_protocol_version": 2}),
    ("different sport", {"sport_key": "tennis_probe"}),
    ("different bookmaker", {"bookmaker": "otherbook"}),
    ("different event tag", {"event_tag": "0" * 24}),
    ("different command", {"command": "additional", "status": "ADDITIONAL_LIVE_VERIFIED"}),
    ("cost above the ceiling", {"accounted_credits": 99, "observed_credits": 99}),
    ("malformed markets", {"market_states": "not a mapping"}),
    ("contradictory attempt", {"network_attempted": False, "attempts": 1}),
    ("bare identifier only", {}),
]


class TestReconciliationNeedsARealReceipt:
    @pytest.mark.parametrize(("label", "over"), FORGERIES, ids=[f[0] for f in FORGERIES])
    def test_no_forgery_resolves_an_intent(
        self, receipts: Path, label: str, over: dict[str, Any]
    ) -> None:
        act.publish_intent(attempt())
        assert pending() == 1
        if label == "bare identifier only":
            publish(receipts, {"receipt_id": ATTEMPT})
        else:
            publish(receipts, receipt_of(**over))
        assert act.reconcile_intents() == 0, label
        assert pending() == 1, label
        assert qual.evaluate(act.audit_receipts())["eligible_for_human_promotion_review"] is False

    def test_the_exact_receipt_resolves_it_once_and_only_once(self, receipts: Path) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        assert act.reconcile_intents() == 1
        assert pending() == 0
        assert act.reconcile_intents() == 0

    def test_accounting_and_admissibility_are_two_different_questions(self, receipts: Path) -> None:
        """A receipt of the right lineage, recorded too early, resolves and qualifies nothing.

        The rectificatif's §3, as a test. *Accounting* asks whether a durable verified
        receipt records this attempt's outcome — same lineage, no instant. *Admissibility*
        asks whether it supports a pre-registered criterion — and there the effective
        instant applies, so a receipt recorded before it stays historical.

        Both facts are published, and neither is inferred from the other: the unresolved
        intent count falls to zero while the historical non-qualifying count rises.
        """
        act.publish_intent(attempt())
        early = datetime.fromisoformat(qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC) - timedelta(
            hours=1
        )
        historical = receipt_of(
            recorded_at=early.isoformat(), expires_at=(early + timedelta(hours=6)).isoformat()
        )
        publish(receipts, historical)

        before = qual.evaluate(act.audit_receipts(), unresolved_intents=pending())
        assert before["eligible_for_human_promotion_review"] is False
        assert pending() == 1

        assert act.reconcile_intents() == 1, "the same lineage resolves the accounting"
        assert pending() == 0

        after = qual.evaluate(act.audit_receipts(), unresolved_intents=pending())
        assert after["qualification_historical_nonqualifying_receipts"] == 1
        assert after["qualification_usable_receipts"] == 0
        assert after["qualification_reasons"]["before_effective_instant"] == 1
        assert after["eligible_for_human_promotion_review"] is False

    def test_reconciliation_reads_through_the_audit_not_the_raw_parser(self) -> None:
        source = Path(act.__file__).read_text(encoding="utf-8")
        body = source.split("def reconcile_intents(", 1)[1].split("\ndef ", 1)[0]
        assert "_read_receipt_payloads" not in body

    def test_a_crash_between_publication_and_resolution_is_recoverable(
        self, receipts: Path
    ) -> None:
        act.publish_intent(attempt())
        publish(receipts, receipt_of())  # the receipt is durable, the intent was never removed
        assert pending() == 1
        assert qual.evaluate(act.audit_receipts())["eligible_for_human_promotion_review"] is False
        assert act.reconcile_intents() == 1
        assert pending() == 0

    def test_two_concurrent_reconciliations_resolve_it_once(self, receipts: Path) -> None:
        import subprocess
        import sys

        act.publish_intent(attempt())
        publish(receipts, receipt_of())
        script = (
            "import os,sys;"
            "os.environ['BETMAXXING_ACTIVATION_RECEIPTS']=sys.argv[1];"
            "os.environ.pop('BETMAXXING_ACTIVATION_RECEIPT_SECRET',None);"
            "from betmaxxing.providers.the_odds_api import activation as a;"
            "print(a.reconcile_intents())"
        )
        env = {k: v for k, v in os.environ.items() if k != act.SECRET_VARIABLE}
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(receipts)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            for _ in range(2)
        ]
        totals = []
        for proc in procs:
            out, err = proc.communicate()
            assert proc.returncode == 0, err
            totals.append(int(out.strip()))
        assert sum(totals) == 1
        assert pending() == 0

    def test_an_unavailable_boundary_never_hides_a_pending_intent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        install_secret(target, LOCAL)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(target))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        act.publish_intent(attempt())
        (tmp_path / "linked").symlink_to(target)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(tmp_path / "linked"))
        audit = act.audit_receipts()
        assert str(audit.boundary).endswith("UNAVAILABLE")
        assert qual.evaluate(audit)["eligible_for_human_promotion_review"] is False
        assert (target / f"{ATTEMPT}{act.INTENT_SUFFIX}").exists()
