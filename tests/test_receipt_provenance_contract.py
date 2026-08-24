"""Provenance is the audit's decision, kept intact — D-077, and D-078 for its limits.

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
receipt's own signature stopped verifying. Nothing re-checked the content.

So this suite asks two questions the previous one could not: can a caller mint
authority without the local secret, and can anyone change a receipt after it has
been admitted. Its positive control is the real audit reading real files, because
that is the only route the supported pipeline has.

**What these tests are worth, and what they are not (D-078).** The property under test
is this one, and no larger:

    In the supported application pipeline, only receipts whose HMAC has been verified by
    ``audit_directory`` are passed to evaluation. The provenance object is an internal
    marker and a guard against misuse; it is not a sandbox against arbitrary Python code
    executed in the same process.

So this file tests the public API: constructors, re-exports, subclassing, lookalikes,
mutation through documented calls, and the checksum that catches an accidental change
between the audit and the evaluation. It deliberately does **not** test resistance to
``object.__new__``, ``object.__setattr__``, reflexive reads of private attributes,
monkeypatching, or rewriting content and checksum together: those all presuppose
arbitrary code in this interpreter, which can equally replace ``evaluate`` or read the
secret, and the owner has placed them out of scope rather than pretend a Python-level
control could stop them. Earlier versions of this suite asserted some of them, which
made the guarantee look bigger than it is.
"""

from __future__ import annotations

import copy
import pickle
import re
import unicodedata
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
            store.VerifiedReceiptBatch(tuple(local_audit.batch), 0)

    def test_the_audit_result_type_has_no_public_constructor(self, local_audit: Any) -> None:
        result = getattr(store, "AuditResult", None) or act.AuditResult
        with pytest.raises(store.UnverifiedProvenance):
            result(local_audit.batch, 0, "AVAILABLE", "")

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

    def test_no_module_level_minting_token_exists(self) -> None:
        """D-078 retired it: a module global is one attribute access from `import`.

        v7 guarded the three constructors with ``_PROVENANCE_TOKEN``, and the seventh
        audit reached the human-review gate with eight unsigned receipts in three lines by
        reading that global. The replacement is not a better-hidden token — there is no
        such thing in this language — it is constructors that refuse unconditionally and
        creation confined to private functions of the module.
        """
        for name in dir(store):
            if "TOKEN" in name.upper():
                raise AssertionError(f"receipt_store.{name} is a module-level token again")
        assert not hasattr(store, "_PROVENANCE_TOKEN")

    def test_only_the_audit_path_creates_provenance_in_the_sources(self) -> None:
        """The supported graph mints only after the HMAC check, and nowhere else."""
        source = Path(store.__file__).read_text(encoding="utf-8")
        assert "def _mint_receipt(" in source
        callers = [
            line.strip()
            for line in source.splitlines()
            if "_mint_receipt(" in line and "def _mint_receipt(" not in line
        ]
        assert len(callers) == 1, f"a receipt is minted at {len(callers)} sites: {callers}"
        audit_body = source.split("def audit_directory(", 1)[1].split("\ndef ", 1)[0]
        assert "_mint_receipt(" in audit_body, "the one site must be inside audit_directory"
        assert "verify(payload" in audit_body, "and it must follow the HMAC check"
        for module in (act, qual):
            other = Path(str(module.__file__)).read_text(encoding="utf-8")
            for spelling in ("_mint_receipt(", "_mint_batch(", "_mint_result(", "_sealed("):
                assert spelling not in other, f"{module.__name__} mints provenance itself"


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


class TestNoPublicMutatorReachesASealedContainer:
    """Every mutating call the public API offers, refused — and nothing more claimed.

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

    **Scope, per D-078.** These are ordinary public calls on public builtins, which is why
    they are tested. What is *not* tested here, because the owner has put it outside the
    threat model: ``object.__new__``, ``object.__setattr__``,
    ``object.__getattribute__`` on the private dictionary, monkeypatching, and rewriting
    content together with its checksum. Those reach the data, and the class name no longer
    pretends otherwise — it used to be « NoBaseClassCallCanBypassTheSeal », which read as a
    security boundary rather than a guard against misuse.
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


class TestTheSupportedPropertyAndItsBoundaries:
    """D-078 as executable statements: what is claimed, and where it stops."""

    def test_a_raw_mapping_is_refused_by_the_evaluator(self) -> None:
        """The narrowest form of the sixth audit's P1: one unsigned dict."""
        unsigned = {k: v for k, v in threshold_corpus(LOCAL)[0].items() if k != act.SIGNATURE_FIELD}
        for candidate in (unsigned, [unsigned], (unsigned,), {}, None, 0):
            with pytest.raises((store.UnverifiedProvenance, TypeError)):
                qual.evaluate(candidate)  # type: ignore[arg-type]

    def test_no_public_or_reexported_name_constructs_a_provenance(self) -> None:
        payload = threshold_corpus(LOCAL)[0]
        for module in (store, act, qual):
            for name in dir(module):
                if name.startswith("_"):
                    continue
                candidate = getattr(module, name)
                if not isinstance(candidate, type):
                    continue
                if candidate not in (
                    store.VerifiedReceipt,
                    store.VerifiedReceiptBatch,
                    store.AuditResult,
                    store.FrozenMapping,
                ):
                    continue
                with pytest.raises((store.UnverifiedProvenance, TypeError)):
                    candidate(payload)

    @pytest.mark.parametrize(
        "name", ["VerifiedReceipt", "VerifiedReceiptBatch", "AuditResult", "FrozenMapping"]
    )
    def test_the_provenance_types_refuse_subclassing(self, name: str) -> None:
        parent = getattr(store, name)
        with pytest.raises(TypeError):
            type(f"Fake{name}", (parent,), {})

    def test_a_lookalike_is_not_accepted_by_the_evaluator(self, local_audit: Any) -> None:
        """Exact type identity, not `isinstance`: a subclass would have satisfied that."""

        class Lookalike:
            """Duck-types AuditResult without being one."""

            batch = local_audit.batch
            unverifiable = 0
            boundary = store.BoundaryState.AVAILABLE
            reason = ""
            checksums = local_audit.checksums
            readable = True

        with pytest.raises(store.UnverifiedProvenance):
            qual.evaluate(Lookalike())  # type: ignore[arg-type]
        with pytest.raises(store.UnverifiedProvenance):
            store.require_audited(Lookalike())

    def test_an_absent_receipt_directory_admits_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(tmp_path / "never"))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        audit = act.audit_receipts()
        assert len(audit.batch) == 0
        assert audit.boundary is store.BoundaryState.ABSENT
        assert _gate(_evaluate(audit))["eligible"] is False

    @pytest.mark.parametrize("flavour", ["unsigned", "foreign-key", "mangled-signature"])
    def test_a_receipt_the_hmac_refuses_stays_unverifiable(
        self, flavour: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corpus = []
        for document in threshold_corpus(LOCAL):
            candidate = dict(document)
            if flavour == "unsigned":
                candidate.pop(act.SIGNATURE_FIELD, None)
            elif flavour == "foreign-key":
                candidate[act.SIGNATURE_FIELD] = "b" * 64
            else:
                candidate[act.SIGNATURE_FIELD] = "not a signature"
            corpus.append(candidate)
        audit = audited_corpus(tmp_path / "receipts", corpus, secret=LOCAL, monkeypatch=monkeypatch)
        assert len(audit.batch) == 0
        assert audit.unverifiable == len(corpus)
        assert _gate(_evaluate(audit))["eligible"] is False

    def test_the_checksum_is_an_integrity_control_and_says_so(self) -> None:
        first = {"receipt_id": "aa11bb22", "status": "CORE_LIVE_VERIFIED"}
        second = {"receipt_id": "aa11bb22", "status": "COVERAGE_MISSING"}
        assert store.content_checksum(first) == store.content_checksum(dict(first))
        assert store.content_checksum(first) != store.content_checksum(second)
        # Order must not matter: it is the content that is checked, not the layout.
        assert store.content_checksum(first) == store.content_checksum(
            {"status": "CORE_LIVE_VERIFIED", "receipt_id": "aa11bb22"}
        )
        signature = str(store.content_checksum.__doc__)
        assert "not a signature" in signature
        assert "authenticates nothing" in signature
        assert not hasattr(store, "fingerprint"), "the misleading name is retired"

    def test_a_result_whose_counts_disagree_with_its_checksums_is_refused(
        self, local_audit: Any
    ) -> None:
        """`require_audited` compares lengths before reading anything."""
        assert len(local_audit.checksums) == len(local_audit.batch)
        assert store.require_audited(local_audit) == tuple(local_audit.batch)

    def test_the_audit_result_publishes_checksums_not_seals(self, local_audit: Any) -> None:
        assert hasattr(local_audit, "checksums")
        assert not hasattr(local_audit, "seals"), "the misleading name is retired"
        assert "checksums" in type(local_audit).__slots__


class TestTheDocumentsPublishOneThreatModel:
    """D-078 must read the same in the code, the protocol, the runbook and the decision."""

    ROOT = Path(store.__file__).resolve().parents[4]

    @pytest.mark.parametrize(
        "relative",
        [
            "docs/decisions.md",
            "docs/provider-validation-protocol.md",
            "docs/provider-activation.md",
            "docs/data-dictionary.md",
            "docs/roadmap.md",
        ],
    )
    def test_every_document_names_the_decision(self, relative: str) -> None:
        text = (self.ROOT / relative).read_text(encoding="utf-8")
        assert "D-078" in text, f"{relative} does not name the threat-model decision"

    @pytest.mark.parametrize(
        "relative",
        [
            "docs/decisions.md",
            "docs/provider-validation-protocol.md",
            "docs/provider-activation.md",
        ],
    )
    def test_the_in_scope_and_out_of_scope_lists_are_published(self, relative: str) -> None:
        text = (self.ROOT / relative).read_text(encoding="utf-8")
        assert "object.__setattr__" in text, "the out-of-scope primitives must be named"
        assert "hors périmètre" in text or "hors du périmètre" in text

    def test_the_module_states_the_property_and_disclaims_the_absolutes(self) -> None:
        """The words may appear — but only in the sentence that refuses them.

        A substring ban would be the wrong test: the honest way to retire « non-forgeable »
        is to name it and say it is not claimed, which is what the module does. So the
        assertion is on the disclaimer and on the supported property.
        """
        source = Path(store.__file__).read_text(encoding="utf-8")
        docstring = source.split('"""', 2)[1]
        assert "are **not** used here as guarantees" in docstring
        assert "only receipts whose HMAC has been verified by" in docstring
        assert "not a sandbox against arbitrary Python code" in docstring
        assert "Out of scope:" in docstring
        assert "In scope:" in docstring

    #: Every absolute D-078 retires, in both languages, as the sexdecies re-audit found
    #: them. Written normalised: lower case, no Markdown emphasis, hyphens folded to
    #: spaces. Test the normaliser below before adding to this list.
    RETIRED_ABSOLUTES = (
        "unconstructible",
        "non constructible",
        "non forgeable",
        "unforgeable",
        "cannot be constructed",
        "cannot be forged",
        "cannot be fabricated",
        "impossible to construct",
        "impossible to forge",
        "impossible to fabricate",
        "impossible a construire",
        "impossible a forger",
        "impossible a fabriquer",
        "ne peut pas etre construit",
        "ne peuvent pas etre construits",
        "aucun objet mutable",
        "preuve cryptographique portee par le type",
    )

    #: The artefacts whose *active* prose must not claim an absolute. The two modules and
    #: the roadmap are here because the sexdecies re-audit found the claim alive in all
    #: three; the normative documents are here because they are what an operator reads.
    ACTIVE_PROSE = (
        "src/betmaxxing/providers/the_odds_api/receipt_store.py",
        "src/betmaxxing/providers/the_odds_api/qualification.py",
        "docs/roadmap.md",
        "docs/provider-validation-protocol.md",
        "docs/provider-activation.md",
        "docs/data-dictionary.md",
        "docs/decisions.md",
    )

    @staticmethod
    def normalise(text: str) -> str:
        """Fold the ways the same claim can be spelled, so the guard cannot be dodged.

        Case, Markdown emphasis (``**``, ``*``, ``_``), backticks, RST double backticks,
        hyphens and non-breaking spaces all disappear; accents are stripped so that
        « impossible à fabriquer » and « impossible a fabriquer » are one string. Without
        this the sexdecies occurrences slip through: ``is now **unconstructible**`` puts
        emphasis markers *inside* the phrase, which a plain substring ban never sees.
        """
        folded = unicodedata.normalize("NFKD", text.lower())
        folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
        for noise in ("**", "``", "`", "*", "_"):
            folded = folded.replace(noise, "")
        # Every Unicode dash, not just ASCII: NFKD folds a non-breaking hyphen to
        # U+2010, which a plain "[-\u2013\u2014]" class silently misses.
        folded = re.sub(r"[\u2010-\u2015\u2212-]+", " ", folded)
        return re.sub(r"[\s\u00a0\u202f]+", " ", folded)

    @staticmethod
    def active_prose_only(text: str) -> str:
        """Drop what is quoted, so a retired word may still be *named* as retired.

        Two exemptions, and both are narrow. A phrase inside French guillemets is a
        **mention**, not a claim — « non-forgeable » is how D-078 names the term it
        withdraws. And a line that marks itself historical (« retiré », « supersédé »,
        « historique », « ancienne formulation », or the English equivalents) is a
        record of what was said, not a statement that it holds. Everything else is an
        assertion and is checked.
        """
        without_quotations = re.sub(r"«[^»]*»", " ", text)
        kept = []
        for line in without_quotations.splitlines():
            marks = TestTheDocumentsPublishOneThreatModel.normalise(line)
            if any(
                marker in marks
                for marker in (
                    "retire",
                    "retiree",
                    "retirees",
                    "superced",
                    "supersed",
                    "historique",
                    "ancienne formulation",
                    "no longer used",
                    "not used here as guarantees",
                    "retired",
                    "superseded",
                )
            ):
                continue
            kept.append(line)
        return "\n".join(kept)

    def test_the_normaliser_sees_through_emphasis_and_spelling(self) -> None:
        """The guard is only worth its normaliser, so the normaliser is tested first."""
        normalise = self.normalise
        assert "unconstructible" in normalise("provenance is now **unconstructible**, and")
        assert "non constructible" in normalise("provenance **non-constructible** et gelée")
        assert "non constructible" in normalise("provenance NON\u2011CONSTRUCTIBLE")
        assert "cannot be constructed" in normalise("An ``AuditResult`` cannot be constructed")
        assert "impossible a fabriquer" in normalise("« impossible à fabriquer »".strip("« »"))

    def test_the_normaliser_keeps_a_named_retirement_out_of_scope(self) -> None:
        """A word may be spoken in order to be withdrawn — that must stay legal."""
        active = self.active_prose_only(
            "So the words « non-forgeable », « unconstructible » are **not** used here.\n"
            "Vocabulaire retiré. « non constructible » n'est plus employé.\n"
        )
        assert self.normalise(active).strip() in ("", "so the words , are not used here.")

    @pytest.mark.parametrize("relative", ACTIVE_PROSE)
    def test_no_active_prose_claims_an_absolute(self, relative: str) -> None:
        """D-078 retired these words; the sexdecies re-audit found three still asserted.

        Two were in ``qualification.py`` — the module docstring said provenance « is now
        **unconstructible** » and ``evaluate`` said an ``AuditResult`` « cannot be
        constructed » — and one was in ``docs/roadmap.md``, inside the very sentence that
        announces D-078. All three are assertions, not citations, so all three are caught
        here.
        """
        text = (self.ROOT / relative).read_text(encoding="utf-8")
        haystack = self.normalise(self.active_prose_only(text))
        claimed = [phrase for phrase in self.RETIRED_ABSOLUTES if phrase in haystack]
        assert claimed == [], (
            f"{relative} asserts {claimed!r}; D-078 retired these. State the supported "
            "property instead: the objects handed to evaluation come from the HMAC audit, "
            "and the marker guards against ordinary misuse, not arbitrary Python."
        )

    @pytest.mark.parametrize(
        "relative",
        [
            "src/betmaxxing/providers/the_odds_api/receipt_store.py",
            "src/betmaxxing/providers/the_odds_api/qualification.py",
        ],
    )
    def test_both_modules_state_the_supported_property(self, relative: str) -> None:
        """Removing a claim is half the job; the module must say what *does* hold."""
        text = self.normalise((self.ROOT / relative).read_text(encoding="utf-8"))
        assert "hmac" in text, f"{relative} does not name the boundary that carries origin"
        assert "d 078" in text, f"{relative} does not name the decision that bounds it"

    def test_the_protocol_keeps_its_versions_and_its_instant(self) -> None:
        """The threat model of D-078 is unchanged by the campaign boundary of D-082."""
        assert qual.PROVIDER_VALIDATION_PROTOCOL_VERSION == 8
        assert qual.PROVIDER_ADAPTER_EVIDENCE_VERSION == 1
        assert qual.QUALIFYING_SCHEMA_VERSION == 4
        assert qual.QUALIFICATION_EVIDENCE_NOT_BEFORE_UTC == "2026-08-25T00:00:00+00:00"
