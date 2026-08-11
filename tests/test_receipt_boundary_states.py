"""An absent boundary is not an unavailable one — D-077, §3.4 and §3.5.

Why this suite exists
---------------------
Two findings of the sixth re-audit meet here.

``audit_receipts`` ended with ``except StoreRefused: return batch((), 0), 0``. A
receipt directory reached through a symbolic link, or one whose parent had been
substituted, or one the process could not open, therefore reported *exactly* what
an empty installation reports: zero verified, zero unverifiable. The operator read
« 0 reçu » and had no way to tell « you have no evidence » from « your boundary
could not be read at all ».

Meanwhile ``load_parent`` — the gate in front of both paid commands, the one that
runs before the socket — never used the descriptor. It called
``receipt_dir().resolve()``, ``Path(raw_path)``, ``path.is_symlink()``,
``path.resolve()`` and ``resolved.read_text()``: four separate lookups of the same
name, and a ``resolve()`` that follows the very links the store refuses. With the
receipt directory a symbolic link, ``audit_receipts`` reported an empty
installation while ``load_parent`` happily read a parent receipt out of the link
target and authorised a paid call. The safety of one reader proved nothing about
the other, exactly as the protocol warned.

So: three boundary states, distinguishable and published; and one descriptor for
every reader.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from betmaxxing.providers.the_odds_api import receipt_store as store
from betmaxxing.providers.the_odds_api.activation import ensure_utc
from helpers_activation import run
from helpers_qualification_corpus import threshold_corpus
from helpers_receipt_boundary import audited_corpus, install_secret

LOCAL = "0011223344556677889900aabbccddeeff00112233445566778899aabbccddee"


def _boundary(audit: Any) -> str:
    return str(audit.boundary)


def _states() -> Any:
    return getattr(store, "BoundaryState", None) or act.BoundaryState


# ---------------------------------------------------------------------------
# Three states
# ---------------------------------------------------------------------------
class TestTheThreeBoundaryStates:
    def test_a_directory_that_does_not_exist_is_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(tmp_path / "never-created"))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        audit = act.audit_receipts()
        assert _boundary(audit).endswith("ABSENT")
        assert len(audit.batch) == 0
        assert audit.unverifiable == 0
        assert not (tmp_path / "never-created").exists(), "reading must create nothing"

    def test_a_safe_empty_directory_is_available(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "receipts").mkdir()
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(tmp_path / "receipts"))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        audit = act.audit_receipts()
        assert _boundary(audit).endswith("AVAILABLE")
        assert len(audit.batch) == 0
        assert audit.unverifiable == 0

    @pytest.mark.parametrize(
        "shape", ["directory-is-a-link", "parent-is-a-link", "not-a-directory"]
    )
    def test_an_ambiguous_boundary_is_unavailable_and_never_looks_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: str
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        install_secret(target, LOCAL)
        for index, document in enumerate(threshold_corpus(LOCAL)):
            (target / f"20260901T00000{index}-core-c{index}.json").write_text(
                json.dumps(document, indent=2, sort_keys=True), encoding="utf-8"
            )
        if shape == "directory-is-a-link":
            (tmp_path / "linked").symlink_to(target)
            configured = tmp_path / "linked"
        elif shape == "parent-is-a-link":
            (target / "inner").mkdir()
            (tmp_path / "linkparent").symlink_to(target)
            configured = tmp_path / "linkparent" / "inner"
        else:
            (tmp_path / "afile").write_text("not a directory", encoding="utf-8")
            configured = tmp_path / "afile"
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(configured))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        audit = act.audit_receipts()
        assert _boundary(audit).endswith("UNAVAILABLE")
        assert len(audit.batch) == 0
        assert audit.reason
        assert str(tmp_path) not in str(audit.reason), "a reason is a category, not a path"

    def test_the_three_states_are_a_closed_domain(self) -> None:
        values = {member.name for member in _states()}
        assert values == {"ABSENT", "AVAILABLE", "UNAVAILABLE"}


class TestUnavailableBlocksAndIsPublished:
    def _unavailable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        target = tmp_path / "target"
        target.mkdir()
        install_secret(target, LOCAL)
        for index, document in enumerate(threshold_corpus(LOCAL)):
            (target / f"20260901T00000{index}-core-c{index}.json").write_text(
                json.dumps(document, indent=2, sort_keys=True), encoding="utf-8"
            )
        (tmp_path / "linked").symlink_to(target)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(tmp_path / "linked"))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        monkeypatch.setenv("BETMAXXING_MODE", "paper")
        return tmp_path / "linked"

    def test_an_unavailable_boundary_closes_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._unavailable(tmp_path, monkeypatch)
        document = qual.evaluate(act.audit_receipts())
        assert document["eligible_for_human_promotion_review"] is False
        assert document["qualification_state"] in {"EVIDENCE_CONFLICT", "INSUFFICIENT_EVIDENCE"}

    def test_both_renderings_say_the_boundary_is_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._unavailable(tmp_path, monkeypatch)
        as_json = run("status", "--json")
        assert as_json.exit_code == 0, as_json.stdout
        payload = json.loads(as_json.stdout)
        assert payload["receipt_boundary_state"] == "UNAVAILABLE"
        assert payload["receipt_boundary_reason"] in {
            "ambiguous_component",
            "not_a_directory",
            "permission_denied",
            "unreadable",
        }
        assert payload["eligible_for_human_promotion_review"] is False
        plain = run("status")
        assert plain.exit_code == 0, plain.stdout
        assert "FRONTIÈRE INDISPONIBLE" in plain.stdout
        assert "UNAVAILABLE" in plain.stdout

    def test_a_safe_installation_does_not_shout_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        audited_corpus(
            tmp_path / "receipts", threshold_corpus(LOCAL), secret=LOCAL, monkeypatch=monkeypatch
        )
        monkeypatch.setenv("BETMAXXING_MODE", "paper")
        payload = json.loads(run("status", "--json").stdout)
        assert payload["receipt_boundary_state"] == "AVAILABLE"
        assert payload["receipt_boundary_reason"] == ""
        assert "FRONTIÈRE INDISPONIBLE" not in "\n".join(act.status_lines(payload))
        assert payload["eligible_for_human_promotion_review"] is True


# ---------------------------------------------------------------------------
# load_parent
# ---------------------------------------------------------------------------
def _discovery(secret: str, *, sport: str = "soccer_probe", book: str = "probebook") -> dict:
    import hashlib
    import hmac

    now = ensure_utc(act._clock())
    document = {
        "schema_version": act.RECEIPT_SCHEMA_VERSION,
        "receipt_id": "aa11bb22cc33dd44",
        "command": "discover",
        "status": str(act.ActivationStatus.DISCOVERY_VERIFIED),
        "recorded_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=6)).isoformat(),
        "sport_key": sport,
        "bookmaker": book,
        "observed_credits": 0,
        "accounted_credits": 0,
        "estimated_credits": 0,
        "quota_remaining": 400,
        "event_tags": [act.event_tag("EV-PROBE-1", secret)],
        "network_attempted": True,
        "may_have_reached_provider": True,
        "attempts": 1,
    }
    document[act.SIGNATURE_FIELD] = hmac.new(
        secret.encode("utf-8"), act.canonical_bytes(document), hashlib.sha256
    ).hexdigest()
    return document


class TestLoadParentSharesTheDescriptor:
    @pytest.fixture
    def installation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        install_secret(receipts, LOCAL)
        (receipts / "20260901T120000-discover-aa11bb22cc33dd44.json").write_text(
            json.dumps(_discovery(LOCAL), indent=2, sort_keys=True), encoding="utf-8"
        )
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(receipts))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        return receipts

    def _load(self, raw: str, **over: Any) -> Any:
        fields: dict[str, Any] = {
            "signing": LOCAL,
            "command": "discover",
            "status": act.ActivationStatus.DISCOVERY_VERIFIED,
            "sport": "soccer_probe",
            "bookmaker": "probebook",
            "now": ensure_utc(act._clock()),
        }
        fields.update(over)
        return act.load_parent(raw, **fields)

    def test_the_documented_path_and_the_bare_name_both_work(self, installation: Path) -> None:
        name = "20260901T120000-discover-aa11bb22cc33dd44.json"
        assert self._load(str(installation / name))["receipt_id"] == "aa11bb22cc33dd44"
        assert self._load(name)["receipt_id"] == "aa11bb22cc33dd44"

    def test_it_makes_no_security_decision_through_pathlib(self) -> None:
        source = Path(act.__file__).read_text(encoding="utf-8")
        body = source.split("def load_parent(", 1)[1].split("\ndef ", 1)[0]
        # The docstring recounts what the previous version did through `pathlib`; the
        # property under test is about the code, so the prose is removed first.
        body = body.split('"""', 2)[-1]
        for forbidden in (".resolve()", ".is_symlink()", ".is_file()", "Path("):
            assert forbidden not in body, f"load_parent still decides through {forbidden}"
        assert "receipt_directory()" in body, "load_parent must read through the descriptor"

    @pytest.mark.parametrize(
        "raw",
        [
            "../receipts/20260901T120000-discover-aa11bb22cc33dd44.json",
            "sub/20260901T120000-discover-aa11bb22cc33dd44.json",
            "..",
            ".",
            "",
            "/etc/passwd",
        ],
    )
    def test_an_ambiguous_argument_is_refused_before_the_transport(
        self, installation: Path, raw: str
    ) -> None:
        with pytest.raises((act.Refused, store.StoreRefused)):
            self._load(raw)

    def test_a_link_inside_the_directory_is_never_followed(
        self, installation: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps(_discovery(LOCAL)), encoding="utf-8")
        (installation / "linked.json").symlink_to(outside)
        with pytest.raises((act.Refused, store.StoreRefused)):
            self._load("linked.json")

    @pytest.mark.parametrize("shape", ["fifo", "directory"])
    def test_a_non_regular_object_at_the_name_is_refused(
        self, installation: Path, shape: str
    ) -> None:
        name = "20260901T120001-discover-bb22cc33dd44ee55.json"
        if shape == "fifo":
            os.mkfifo(installation / name)
        else:
            (installation / name).mkdir()
        with pytest.raises((act.Refused, store.StoreRefused)):
            self._load(name)

    @pytest.mark.parametrize("shape", ["directory-is-a-link", "parent-is-a-link"])
    def test_an_unsafe_directory_refuses_the_parent_exactly_as_the_audit_does(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: str
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        install_secret(target, LOCAL)
        name = "20260901T120000-discover-aa11bb22cc33dd44.json"
        (target / name).write_text(json.dumps(_discovery(LOCAL)), encoding="utf-8")
        if shape == "directory-is-a-link":
            (tmp_path / "linked").symlink_to(target)
            configured = tmp_path / "linked"
        else:
            (target / "inner").mkdir()
            install_secret(target / "inner", LOCAL)
            (target / "inner" / name).write_text(json.dumps(_discovery(LOCAL)), encoding="utf-8")
            (tmp_path / "linkparent").symlink_to(target)
            configured = tmp_path / "linkparent" / "inner"
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(configured))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        audit = act.audit_receipts()
        assert _boundary(audit).endswith("UNAVAILABLE")
        with pytest.raises((act.Refused, store.StoreRefused)):
            self._load(name)

    def test_a_directory_renamed_after_the_open_reaches_nothing_new(
        self, installation: Path, tmp_path: Path
    ) -> None:
        """The descriptor keeps the inode it opened; the name is irrelevant after that."""
        name = "20260901T120000-discover-aa11bb22cc33dd44.json"
        with act.receipt_directory() as directory:
            moved = tmp_path / "moved"
            installation.rename(moved)
            (tmp_path / "receipts").mkdir()
            (tmp_path / "receipts" / name).write_text("FOREIGN", encoding="utf-8")
            assert name in directory.listdir()
            assert directory.read_text(name) != "FOREIGN"
        moved.rename(installation) if not installation.exists() else None

    def test_a_correctly_signed_receipt_of_the_wrong_scope_is_refused(
        self, installation: Path
    ) -> None:
        name = "20260901T120002-discover-cc33dd44ee55ff66.json"
        (installation / name).write_text(
            json.dumps(_discovery(LOCAL, sport="tennis_probe"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        with pytest.raises(act.Refused):
            self._load(name)

    def test_a_hard_link_to_an_outside_inode_is_accepted_and_documented_as_such(
        self, installation: Path, tmp_path: Path
    ) -> None:
        """The boundary guarantees the name and inode opened here, not the inode's history."""
        outside = tmp_path / "elsewhere.json"
        outside.write_text(
            json.dumps(_discovery(LOCAL), indent=2, sort_keys=True), encoding="utf-8"
        )
        name = "20260901T120003-discover-dd44ee55ff667788.json"
        os.link(outside, installation / name)
        assert self._load(name)["receipt_id"] == "aa11bb22cc33dd44"

    def test_neither_paid_command_reaches_the_transport_on_an_unsafe_boundary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from helpers_activation import Recorder, install

        target = tmp_path / "target"
        target.mkdir()
        install_secret(target, LOCAL)
        name = "20260901T120000-discover-aa11bb22cc33dd44.json"
        (target / name).write_text(json.dumps(_discovery(LOCAL)), encoding="utf-8")
        (tmp_path / "linked").symlink_to(target)
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(tmp_path / "linked"))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        monkeypatch.setenv("BETMAXXING_THE_ODDS_API_KEY", "FAKEKEY0000deadbeef0000FAKEKEY00")
        monkeypatch.setenv("BETMAXXING_MODE", "paper")
        recorder = Recorder({})
        install(monkeypatch, recorder)
        result = run(
            "core",
            "--sport",
            "soccer_probe",
            "--bookmaker",
            "probebook",
            "--event-id",
            "EV-PROBE-1",
            "--discovery-receipt",
            name,
            "--max-credits",
            "1",
            "--acknowledge-credits",
            "1",
            "--allow-network",
        )
        assert result.exit_code != 0
        assert recorder.requests == []
        assert result.stdout.strip()


class TestTheTwoUnverifiableCountersReadOneAudit:
    """The rectificatif's §4: unification is acceptable under three conditions.

    v6 published the same idea twice from two provenances — the D-062 audit counter and
    the qualification counter — and the reason they could disagree was that each counted
    the files itself. Protocol 7 has one audit and both read it. These tests check the
    three conditions the owner set: the same result reaches both renderings, no
    ``**mapping`` assembly can overwrite the field, and the vocabulary agrees.
    """

    def test_both_counters_come_from_the_same_audit_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        audit = audited_corpus(
            tmp_path / "receipts",
            threshold_corpus(LOCAL),
            secret=LOCAL,
            monkeypatch=monkeypatch,
            unreadable=3,
        )
        state = act.build_activation_state(audit)
        assert audit.unverifiable == 3
        assert state["unverifiable_receipts"] == 3
        assert state["qualification_unverifiable_receipts"] == 3
        assert state["unverifiable_receipts"] == state["qualification_unverifiable_receipts"]

    def test_no_mapping_spread_can_overwrite_the_field(self) -> None:
        """The defect this test was originally written to catch, still guarded."""
        source = Path(act.__file__).read_text(encoding="utf-8")
        body = source.split("def build_activation_state(", 1)[1].split("\ndef ", 1)[0]
        assert "**qualification" not in body
        assert "**{" not in body
        returned = body.split("return {", 1)[1]
        # Each key is written exactly once, literally. A spread would let one of them be
        # produced twice with the last write silently winning.
        assert returned.count('"unverifiable_receipts":') == 1
        assert returned.count('"qualification_unverifiable_receipts":') == 1

    def test_both_renderings_publish_the_same_number(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        audited_corpus(
            tmp_path / "receipts",
            threshold_corpus(LOCAL),
            secret=LOCAL,
            monkeypatch=monkeypatch,
            unreadable=2,
        )
        monkeypatch.setenv("BETMAXXING_MODE", "paper")
        payload = json.loads(run("status", "--json").stdout)
        assert payload["unverifiable_receipts"] == 2
        assert payload["qualification_unverifiable_receipts"] == 2
        human = run("status").stdout
        assert "non vérifiables : 2" in human

    def test_the_documents_say_one_audit_rather_than_two_counters(self) -> None:
        root = Path(qual.__file__).parents[4]
        protocol = (root / "docs" / "provider-validation-protocol.md").read_text(encoding="utf-8")
        dictionary = (root / "docs" / "data-dictionary.md").read_text(encoding="utf-8")
        for text in (protocol, dictionary):
            assert "AuditResult" in text or "résultat d'audit" in text
