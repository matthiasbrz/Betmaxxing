"""Provenance is a proof, and the proof is a frozen value — D-077, §3.2 and §3.3.

Why this suite exists
---------------------
v6 said « la provenance est un type » and made ``VerifiedReceipt`` that type. The
sixth re-audit called the bluff twice.

``VerifiedReceipt(payload)`` was a public constructor that checked nothing. Eight
receipts with the ``signature`` key *deleted*, wrapped by hand, reached
``CRITERIA_MET_AWAITING_HUMAN_REVIEW`` with ``eligible_for_human_promotion_review``
true — through a batch, through a bare list and through a tuple. So did a corpus
signed with a key the installation does not hold. ``require_verified`` asked
``isinstance``; nothing asked the HMAC.

And the type was frozen one level deep. ``__init__`` did ``dict(payload)``, so
every nested dictionary and list stayed shared with the caller's, and
``__getitem__`` handed the live object back. One write through the ordinary
Mapping API — ``receipt["freshness"][market] = 300`` — turned
``INSUFFICIENT_EVIDENCE`` into ``CRITERIA_MET_AWAITING_HUMAN_REVIEW`` while the
receipt's own signature stopped verifying. Nothing re-read the seal.

So this suite asks two questions the previous one could not: can a caller mint
authority without the local secret, and can anyone change a receipt after it has
been admitted. Its positive control is the real audit reading real files, because
that is now the only way in.

The threat model, stated exactly: this defends the *public Python API of the
repository*. Code that already runs in the process can reach a private attribute
or rewrite bytecode, and no design here prevents that. The claim is narrower and
testable — no documented, exported or re-exported entry point mints provenance
without a signature check against the secret the audit loaded.
"""

from __future__ import annotations

import copy
import pickle
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from betmaxxing.providers.the_odds_api import receipt_store as store
from helpers_qualification_corpus import threshold_corpus
from helpers_receipt_boundary import audited_corpus

LOCAL = "0011223344556677889900aabbccddeeff00112233445566778899aabbccddee"
FOREIGN = "ffeeddccbbaa00998877665544332211ffeeddccbbaa009988776655443322"[:63] + "0"


def _sign(document: dict[str, Any]) -> str:
    import hashlib
    import hmac

    return hmac.new(
        LOCAL.encode("utf-8"), act.canonical_bytes(document), hashlib.sha256
    ).hexdigest()


def _gate(document: Any) -> dict[str, Any]:
    return {
        "state": document["qualification_state"],
        "usable": document["qualification_usable_receipts"],
        "eligible": document["eligible_for_human_promotion_review"],
    }


def _evaluate(audit: Any) -> Any:
    """Evaluate an audit result, whatever arity the module under test wants."""
    return qual.evaluate(audit)


def _state(audit: Any) -> Any:
    return act.build_activation_state(audit)


@pytest.fixture
def local_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    return audited_corpus(
        tmp_path / "receipts", threshold_corpus(LOCAL), secret=LOCAL, monkeypatch=monkeypatch
    )


class TestOnlyTheAuditMintsAuthority:
    def test_the_audit_of_signed_files_is_the_positive_control(self, local_audit: Any) -> None:
        assert len(local_audit.batch) == 8
        assert local_audit.unverifiable == 0
        assert _gate(_evaluate(local_audit)) == {
            "state": "CRITERIA_MET_AWAITING_HUMAN_REVIEW",
            "usable": 8,
            "eligible": True,
        }

    def test_the_provenance_type_has_no_public_constructor(self) -> None:
        unsigned = {k: v for k, v in threshold_corpus(LOCAL)[0].items() if k != act.SIGNATURE_FIELD}
        with pytest.raises(store.UnverifiedProvenance):
            store.VerifiedReceipt(unsigned)

    def test_the_type_refuses_even_a_correctly_signed_payload(self) -> None:
        """Being signed is not the point: the audit decides, not the caller."""
        with pytest.raises(store.UnverifiedProvenance):
            store.VerifiedReceipt(threshold_corpus(LOCAL)[0])

    def test_the_batch_type_has_no_public_constructor(self, local_audit: Any) -> None:
        with pytest.raises(store.UnverifiedProvenance):
            store.VerifiedReceiptBatch(tuple(local_audit.batch), 0)  # type: ignore[arg-type]

    def test_the_audit_result_type_has_no_public_constructor(self, local_audit: Any) -> None:
        result = getattr(store, "AuditResult", None) or act.AuditResult
        with pytest.raises(store.UnverifiedProvenance):
            result(local_audit.batch, 0, "AVAILABLE", "")  # type: ignore[arg-type]

    def test_no_public_factory_takes_an_arbitrary_key(self) -> None:
        """`trust(payload, secret=…)` was exactly such a factory."""
        for name in ("trust", "trusted", "mint", "as_verified", "verified_receipt"):
            assert not hasattr(store, name), f"receipt_store.{name} mints with a caller's key"
            assert not hasattr(act, name), f"activation.{name} mints with a caller's key"

    def test_no_alias_reexports_a_usable_constructor(self) -> None:
        for module in (act, qual):
            for name in ("VerifiedReceipt", "VerifiedReceiptBatch"):
                alias = getattr(module, name, None)
                if alias is None:
                    continue
                with pytest.raises(store.UnverifiedProvenance):
                    alias({})

    @pytest.mark.parametrize("shape", ["list", "tuple", "raw-dicts"])
    def test_neither_evaluator_accepts_a_hand_built_sequence(self, shape: str) -> None:
        corpus = threshold_corpus(LOCAL)
        payload: Any = (
            corpus if shape == "raw-dicts" else (list(corpus) if shape == "list" else tuple(corpus))
        )
        with pytest.raises((store.UnverifiedProvenance, TypeError)):
            qual.evaluate(payload)
        with pytest.raises((store.UnverifiedProvenance, TypeError)):
            act.build_activation_state(payload)

    def test_a_forged_corpus_of_eight_never_reaches_the_gate(self) -> None:
        """The exact probe of the duodecies report, as a permanent test."""
        forged = [
            {k: v for k, v in document.items() if k != act.SIGNATURE_FIELD}
            for document in threshold_corpus(LOCAL)
        ]
        with pytest.raises((store.UnverifiedProvenance, TypeError)):
            qual.evaluate(forged)  # type: ignore[arg-type]

    def test_a_corpus_signed_with_a_foreign_key_is_unverifiable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        audit = audited_corpus(
            tmp_path / "receipts",
            threshold_corpus(FOREIGN),
            secret=LOCAL,
            monkeypatch=monkeypatch,
        )
        assert len(audit.batch) == 0
        assert audit.unverifiable == 8
        assert _gate(_evaluate(audit))["eligible"] is False

    def test_the_audit_is_the_only_construction_site_in_the_sources(self) -> None:
        source = Path(store.__file__).read_text(encoding="utf-8")
        assert "_PROVENANCE" in source or "_MINT" in source, (
            "the module must carry an explicit, private minting token"
        )


class TestTheAdmittedReceiptIsAFrozenValue:
    def test_the_source_dictionary_can_no_longer_reach_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corpus = threshold_corpus(LOCAL)
        audit = audited_corpus(tmp_path / "receipts", corpus, secret=LOCAL, monkeypatch=monkeypatch)
        before = _gate(_evaluate(audit))
        corpus[0]["market_states"]["h2h"] = "FABRICATED"
        corpus[0]["freshness"]["h2h"] = 10**9
        corpus[0]["markets_mapped"].append("invented")
        assert audit.batch[0]["market_states"]["h2h"] == "OBSERVED_MAPPED"
        assert _gate(_evaluate(audit)) == before

    @pytest.mark.parametrize("key", ["market_states", "freshness"])
    def test_a_nested_mapping_handed_out_is_not_writable(self, local_audit: Any, key: str) -> None:
        nested = local_audit.batch[0][key]
        with pytest.raises(TypeError):
            nested["h2h"] = "TAMPERED"
        with pytest.raises((TypeError, AttributeError)):
            nested.clear()

    @pytest.mark.parametrize(
        "key", ["markets_requested", "markets_mapped", "markets_observed", "markets_rejected"]
    )
    def test_a_nested_sequence_handed_out_is_not_writable(self, local_audit: Any, key: str) -> None:
        nested = local_audit.batch[0][key]
        with pytest.raises((TypeError, AttributeError)):
            nested.append("invented")

    @pytest.mark.parametrize(
        "key", ["signature", "receipt_id", "status", "event_tag", "accounted_credits"]
    )
    def test_no_scalar_can_be_replaced_after_verification(self, local_audit: Any, key: str) -> None:
        with pytest.raises(TypeError):
            local_audit.batch[0][key] = "REWRITTEN"

    def test_no_reachable_attribute_replaces_the_payload(self, local_audit: Any) -> None:
        receipt = local_audit.batch[0]
        original = dict(receipt)
        for name in ("_payload", "_frozen", "_receipt", "payload"):
            holder = getattr(receipt, name, None)
            if holder is None:
                continue
            with pytest.raises((TypeError, AttributeError)):
                holder["status"] = "REWRITTEN"
        assert dict(receipt) == original

    def test_the_stale_corpus_cannot_be_freshened_after_the_fact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The P1 of the sixth re-audit, reduced to one test."""
        stale = []
        for document in threshold_corpus(LOCAL):
            copy_of = dict(document)
            copy_of["freshness"] = dict.fromkeys(
                document["freshness"], qual.PROTOCOL_MAX_ODDS_AGE_SECONDS + 600
            )
            copy_of[act.SIGNATURE_FIELD] = _sign(copy_of)
            stale.append(copy_of)
        audit = audited_corpus(tmp_path / "receipts", stale, secret=LOCAL, monkeypatch=monkeypatch)
        assert _gate(_evaluate(audit))["eligible"] is False
        for receipt in audit.batch:
            with pytest.raises((TypeError, AttributeError)):
                receipt["freshness"]["h2h"] = 300
        assert _gate(_evaluate(audit))["eligible"] is False
        assert _state(audit)["eligible_for_human_promotion_review"] is False

    def test_copies_keep_the_same_bytes_and_share_nothing_mutable(self, local_audit: Any) -> None:
        receipt = local_audit.batch[0]
        for clone in (copy.copy(receipt), copy.deepcopy(receipt)):
            assert dict(clone) == dict(receipt)
            with pytest.raises((TypeError, AttributeError)):
                clone["market_states"]["h2h"] = "VIA_COPY"

    def test_pickle_round_trips_without_creating_authority(self, local_audit: Any) -> None:
        receipt = local_audit.batch[0]
        try:
            payload = pickle.dumps(receipt)
        except (TypeError, pickle.PicklingError):
            return  # refusing to pickle is an acceptable answer
        restored = pickle.loads(payload)
        assert dict(restored) == dict(receipt)
        with pytest.raises((TypeError, AttributeError)):
            restored["status"] = "REWRITTEN"

    def test_a_receipt_still_reads_like_the_mapping_it_replaces(self, local_audit: Any) -> None:
        receipt = local_audit.batch[0]
        assert receipt["command"] in {"core", "additional"}
        assert set(receipt) == set(dict(receipt))
        assert len(receipt) == len(dict(receipt))
        assert receipt.get("nothing-here") is None
        assert list(receipt["markets_requested"]) == ["h2h"] or receipt["command"] == "additional"


class TestNoBaseClassCallCanBypassTheSeal:
    """The rectificatif's blocking check — and the reason the first design failed.

    Protocol 7's first attempt froze payloads into ``dict`` and ``list`` *subclasses*
    with every mutator overridden, so that ``isinstance(value, dict)`` kept working
    across the repository. Overriding a method on a subclass does not remove the base
    class's: all fifteen of the calls below succeeded when addressed to the base class
    explicitly, and ``dict.__setitem__(receipt["freshness"], market, 300)`` is precisely
    the write that moves a stale corpus to the human-review gate.

    The sealed representation therefore inherits from nothing mutable: a
    :class:`~receipt_store.FrozenMapping` wrapper and plain tuples. These tests assert
    both halves — the nested objects are not instances of the mutable builtins at all,
    and every base-class call fails.
    """

    @pytest.fixture
    def stale(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
        corpus = []
        for document in threshold_corpus(LOCAL):
            copy_of = dict(document)
            copy_of["freshness"] = dict.fromkeys(
                document["freshness"], qual.PROTOCOL_MAX_ODDS_AGE_SECONDS + 600
            )
            copy_of[act.SIGNATURE_FIELD] = _sign(copy_of)
            corpus.append(copy_of)
        return audited_corpus(tmp_path / "receipts", corpus, secret=LOCAL, monkeypatch=monkeypatch)

    def test_the_sealed_containers_are_not_mutable_builtins(self, stale: Any) -> None:
        receipt = stale.batch[0]
        assert not isinstance(receipt["freshness"], dict)
        assert not isinstance(receipt["markets_requested"], list)
        assert isinstance(receipt["freshness"], store.FrozenMapping)
        assert isinstance(receipt["markets_requested"], tuple)

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(lambda m: dict.__setitem__(m, "h2h", 300), id="dict.__setitem__"),
            pytest.param(lambda m: dict.__delitem__(m, "h2h"), id="dict.__delitem__"),
            pytest.param(lambda m: dict.update(m, {"h2h": 300}), id="dict.update"),
            pytest.param(lambda m: dict.pop(m, "h2h"), id="dict.pop"),
            pytest.param(lambda m: dict.popitem(m), id="dict.popitem"),
            pytest.param(lambda m: dict.setdefault(m, "invented", 1), id="dict.setdefault"),
            pytest.param(lambda m: dict.clear(m), id="dict.clear"),
            pytest.param(lambda m: dict.__ior__(m, {"h2h": 300}), id="dict.__ior__"),
        ],
    )
    def test_no_dict_base_call_reaches_a_sealed_mapping(self, stale: Any, call: Any) -> None:
        nested = stale.batch[0]["freshness"]
        before = dict(nested)
        with pytest.raises(TypeError):
            call(nested)
        assert dict(nested) == before

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(lambda s: list.__setitem__(s, 0, "z"), id="list.__setitem__"),
            pytest.param(lambda s: list.__delitem__(s, 0), id="list.__delitem__"),
            pytest.param(lambda s: list.append(s, "z"), id="list.append"),
            pytest.param(lambda s: list.extend(s, ["z"]), id="list.extend"),
            pytest.param(lambda s: list.insert(s, 0, "z"), id="list.insert"),
            pytest.param(lambda s: list.remove(s, "h2h"), id="list.remove"),
            pytest.param(lambda s: list.pop(s), id="list.pop"),
            pytest.param(lambda s: list.clear(s), id="list.clear"),
            pytest.param(lambda s: list.sort(s), id="list.sort"),
            pytest.param(lambda s: list.reverse(s), id="list.reverse"),
            pytest.param(lambda s: list.__iadd__(s, ["z"]), id="list.__iadd__"),
            pytest.param(lambda s: list.__imul__(s, 2), id="list.__imul__"),
        ],
    )
    def test_no_list_base_call_reaches_a_sealed_sequence(self, stale: Any, call: Any) -> None:
        nested = stale.batch[0]["markets_requested"]
        before = tuple(nested)
        with pytest.raises(TypeError):
            call(nested)
        assert tuple(nested) == before

    def test_a_deeply_nested_mapping_is_sealed_too(self, stale: Any) -> None:
        receipt = stale.batch[0]
        states = receipt["market_states"]
        with pytest.raises(TypeError):
            dict.__setitem__(states, "h2h", "FABRICATED")
        with pytest.raises(TypeError):
            states["h2h"] = "FABRICATED"

    @pytest.mark.parametrize("attribute", ["_payload", "_data", "payload", "_frozen"])
    def test_no_ordinary_assignment_reaches_an_internal_attribute(
        self, stale: Any, attribute: str
    ) -> None:
        receipt = stale.batch[0]
        before = dict(receipt)
        with pytest.raises((AttributeError, TypeError)):
            setattr(receipt, attribute, {"status": "REWRITTEN"})
        assert dict(receipt) == before

    def test_only_one_attribute_name_exists_at_all(self, stale: Any) -> None:
        """`__slots__` is why: there is no dictionary to add a name to."""
        receipt = stale.batch[0]
        assert type(receipt).__slots__ == ("_frozen",)
        assert not hasattr(receipt, "__dict__")
        with pytest.raises(AttributeError):
            object.__setattr__(receipt, "_payload", {})

    def test_a_payload_swapped_through_object_setattr_is_refused_not_read(
        self, stale: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one primitive Python cannot take away — met with a recorded fingerprint.

        `object.__setattr__` bypasses `__setattr__` by definition, so the single slot a
        verified receipt owns can be replaced by code running in this process. What the
        audit records at mint time is a non-keyed digest of the sealed content, re-checked
        at the door of every semantic read: the substitution is detected and refused
        rather than evaluated. Someone who replaces the recorded digests too defeats this,
        and that limit is stated in the module and in D-077 rather than argued away.
        """
        qualifying = audited_corpus(
            tmp_path / "fresh", threshold_corpus(LOCAL), secret=LOCAL, monkeypatch=monkeypatch
        )
        assert _gate(_evaluate(qualifying))["eligible"] is True
        fresh_payload = qualifying.batch[0].to_builtin()

        receipt = stale.batch[0]
        object.__setattr__(receipt, "_frozen", store._freeze(fresh_payload))
        assert receipt["freshness"]["h2h"] == 300, "the swap did happen"
        with pytest.raises(store.UnverifiedProvenance):
            _evaluate(stale)
        with pytest.raises(store.UnverifiedProvenance):
            _state(stale)

    def test_the_stale_corpus_survives_every_attempt_at_once(self, stale: Any) -> None:
        before = _gate(_evaluate(stale))
        assert before == {
            "state": "INSUFFICIENT_EVIDENCE",
            "usable": 8,
            "eligible": False,
        }
        attempts = (
            lambda m, s: dict.__setitem__(m, "h2h", 300),
            lambda m, s: dict.update(m, {"h2h": 300}),
            lambda m, s: dict.clear(m),
            lambda m, s: list.append(s, "z"),
            lambda m, s: list.clear(s),
            lambda m, s: m.__setitem__("h2h", 300),
            lambda m, s: copy.deepcopy(m).__setitem__("h2h", 300),
        )
        for receipt in stale.batch:
            freshness = receipt["freshness"]
            markets = receipt["markets_requested"]
            for attempt in attempts:
                with pytest.raises(TypeError):
                    attempt(freshness, markets)
            # The sealed sequence is a plain tuple, so it has no mutating API to override
            # in the first place — which is exactly why the previous design failed.
            for name in ("__setitem__", "append", "extend", "clear", "sort", "reverse"):
                assert not hasattr(markets, name), name
        assert _gate(_evaluate(stale)) == before
        assert _state(stale)["eligible_for_human_promotion_review"] is False

    def test_a_sealed_mapping_cannot_be_pickled_into_a_writable_one(self, stale: Any) -> None:
        nested = stale.batch[0]["freshness"]
        try:
            payload = pickle.dumps(nested)
        except (TypeError, pickle.PicklingError):
            return
        restored = pickle.loads(payload)
        with pytest.raises(TypeError):
            restored["h2h"] = 300

    def test_copies_of_a_sealed_mapping_are_still_sealed(self, stale: Any) -> None:
        nested = stale.batch[0]["freshness"]
        for clone in (copy.copy(nested), copy.deepcopy(nested)):
            assert dict(clone) == dict(nested)
            with pytest.raises(TypeError):
                clone["h2h"] = 300
            with pytest.raises(TypeError):
                dict.__setitem__(clone, "h2h", 300)

    def test_the_repr_of_each_sealed_object_is_readable_and_says_nothing_new(
        self, stale: Any
    ) -> None:
        receipt = stale.batch[0]
        assert repr(receipt).startswith("VerifiedReceipt(receipt_id=")
        assert repr(receipt["freshness"]).startswith("FrozenMapping(")
        assert repr(stale).startswith("AuditResult(")
        assert "AVAILABLE" in repr(stale)
        assert LOCAL not in repr(receipt) + repr(receipt["freshness"]) + repr(stale)

    def test_to_builtin_gives_a_detached_mutable_copy(self, stale: Any) -> None:
        receipt = stale.batch[0]
        plain = receipt.to_builtin()
        assert isinstance(plain, dict)
        assert isinstance(plain["freshness"], dict)
        assert isinstance(plain["markets_requested"], list)
        plain["freshness"]["h2h"] = 300
        assert receipt["freshness"]["h2h"] != 300, "the copy must be detached"
        import json as jsonlib

        jsonlib.dumps(plain)  # a builtin copy is what serialisation is for
