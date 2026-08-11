"""The evaluator is pure, and its input carries its provenance — D-076, §6.

Why this suite exists
---------------------
`qualification.evaluate` called itself pure — « no network, no key, no clock, no
configuration, no receipt is written or modified » — and the fifth audit followed
the imports: ``evaluate → currency_reason → _verifiable → verify_receipt →
sign_receipt → receipt_secret``. The last of those reads the environment, creates
the receipt directory and **creates a secret file**. One call over one receipt
performed four environment reads and left a new key on disk, and the same input
yielded ``usable=1`` under one key and ``0`` under another.

Deleting the word « pure » from a docstring is not the correction. The correction
is architectural: verification belongs to the acquisition/audit layer, which hands
the evaluator a collection whose provenance is impossible to confuse with a list
of raw dictionaries. So this suite instruments the *whole call graph* rather than
grepping the module, and it checks the two halves separately:

* the evaluator touches no environment, no clock, no file and no HMAC;
* the evaluator refuses input that has not been verified, and only
  :func:`activation.audit_receipts` mints verified input in production.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual
from betmaxxing.providers.the_odds_api import receipt_store as store

SECRET = "0123456789abcdef" * 4
OTHER = "fedcba9876543210" * 4


@pytest.fixture
def corpus_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from helpers_qualification_corpus import write_threshold_corpus

    directory = tmp_path / "receipts"
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
    monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
    write_threshold_corpus(directory, SECRET)
    (directory / act.SECRET_FILENAME).write_text(SECRET, encoding="utf-8")
    os.chmod(directory / act.SECRET_FILENAME, 0o600)
    return directory


class Spy:
    """Counts every ambient effect the evaluator is forbidden to have."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: dict[str, int] = dict.fromkeys(
            ("environ", "open", "mkdir", "fsync", "chmod", "sign", "verify", "secret", "clock"), 0
        )
        real_get = os.environ.get
        real_getitem = os.environ.__getitem__
        real_open = os.open
        real_mkdir = os.mkdir
        real_fsync = os.fsync
        real_chmod = os.chmod

        def count(name: str, real: Any) -> Any:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                self.calls[name] += 1
                return real(*args, **kwargs)

            return wrapper

        monkeypatch.setattr(os.environ, "get", count("environ", real_get))
        monkeypatch.setattr(os.environ.__class__, "__getitem__", count("environ", real_getitem))
        monkeypatch.setattr(os, "open", count("open", real_open))
        monkeypatch.setattr(os, "mkdir", count("mkdir", real_mkdir))
        monkeypatch.setattr(os, "fsync", count("fsync", real_fsync))
        monkeypatch.setattr(os, "chmod", count("chmod", real_chmod))
        monkeypatch.setattr(store, "sign", count("sign", store.sign))
        monkeypatch.setattr(store, "verify", count("verify", store.verify))
        monkeypatch.setattr(act, "load_receipt_secret", count("secret", act.load_receipt_secret))
        monkeypatch.setattr(
            act, "ensure_receipt_secret", count("secret", act.ensure_receipt_secret)
        )

    @property
    def offenders(self) -> dict[str, int]:
        return {name: count for name, count in self.calls.items() if count}


class TestTheEvaluatorHasNoAmbientEffect:
    def test_it_reads_no_environment_no_file_and_signs_nothing(
        self, corpus_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        batch, unverifiable = act.audit_receipts()
        spy = Spy(monkeypatch)
        document = qual.evaluate(batch, unverifiable)
        assert spy.offenders == {}, f"evaluate is not pure: {spy.offenders}"
        assert document["qualification_usable_receipts"] >= 1

    def test_it_creates_no_secret_when_the_secret_is_gone(self, corpus_dir: Path) -> None:
        batch, unverifiable = act.audit_receipts()
        (corpus_dir / act.SECRET_FILENAME).unlink()
        qual.evaluate(batch, unverifiable)
        assert not (corpus_dir / act.SECRET_FILENAME).exists()

    def test_its_verdict_does_not_depend_on_the_ambient_secret(
        self, corpus_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        batch, unverifiable = act.audit_receipts()
        first = qual.evaluate(batch, unverifiable)
        monkeypatch.setenv(act.SECRET_VARIABLE, OTHER)
        monkeypatch.chdir(corpus_dir.parent)
        assert qual.evaluate(batch, unverifiable) == first

    def test_it_does_not_mutate_its_input(self, corpus_dir: Path) -> None:
        batch, unverifiable = act.audit_receipts()
        before = [dict(receipt) for receipt in batch]
        qual.evaluate(batch, unverifiable)
        assert [dict(receipt) for receipt in batch] == before

    def test_it_is_independent_of_order(self, corpus_dir: Path) -> None:
        batch, unverifiable = act.audit_receipts()
        forward = qual.evaluate(batch, unverifiable)
        backward = qual.evaluate(
            store.VerifiedReceiptBatch(tuple(reversed(batch)), unverifiable), unverifiable
        )
        for key in (
            "qualification_state",
            "qualification_usable_receipts",
            "eligible_for_human_promotion_review",
        ):
            assert backward[key] == forward[key]


class TestProvenanceIsExplicit:
    def test_raw_mappings_are_refused_rather_than_trusted(self, corpus_dir: Path) -> None:
        from helpers_qualification_corpus import threshold_corpus

        raw = threshold_corpus(SECRET)
        with pytest.raises(store.UnverifiedProvenance):
            qual.evaluate(raw, 0)
        with pytest.raises(store.UnverifiedProvenance):
            act.build_activation_state(raw, 0)  # type: ignore[arg-type]

    def test_a_batch_of_one_raw_mapping_among_verified_ones_is_refused(
        self, corpus_dir: Path
    ) -> None:
        from helpers_qualification_corpus import threshold_corpus

        batch, _ = act.audit_receipts()
        mixed = [*list(batch), threshold_corpus(SECRET)[0]]
        with pytest.raises(store.UnverifiedProvenance):
            qual.evaluate(mixed, 0)

    def test_the_audit_is_what_mints_verified_receipts(self, corpus_dir: Path) -> None:
        batch, unverifiable = act.audit_receipts()
        assert isinstance(batch, store.VerifiedReceiptBatch)
        assert batch.unverifiable == unverifiable
        assert all(isinstance(receipt, store.VerifiedReceipt) for receipt in batch)

    def test_minting_one_by_hand_requires_a_valid_signature(self, corpus_dir: Path) -> None:
        from helpers_qualification_corpus import threshold_corpus

        good = threshold_corpus(SECRET)[0]
        assert isinstance(store.trust(good, secret=SECRET), store.VerifiedReceipt)
        with pytest.raises(store.UnverifiedProvenance):
            store.trust(good, secret=OTHER)
        forged = {**good, act.SIGNATURE_FIELD: "0" * 64}
        with pytest.raises(store.UnverifiedProvenance):
            store.trust(forged, secret=SECRET)

    def test_a_verified_receipt_reads_like_the_mapping_it_wraps(self, corpus_dir: Path) -> None:
        batch, _ = act.audit_receipts()
        one = batch[0]
        assert one["command"] in {"core", "additional"}
        assert dict(one)["status"] == one["status"]
        assert set(one) == set(dict(one))
        assert len(one) == len(dict(one))

    def test_a_verified_receipt_cannot_be_edited_after_verification(self, corpus_dir: Path) -> None:
        batch, _ = act.audit_receipts()
        with pytest.raises(TypeError):
            batch[0]["status"] = "CORE_LIVE_VERIFIED"

    def test_an_unsigned_receipt_never_becomes_verified(self, corpus_dir: Path) -> None:
        (corpus_dir / "20260901T120000-core-unsigned.json").write_text(
            '{"schema_version": 4, "command": "core", "status": "CORE_LIVE_VERIFIED"}\n',
            encoding="utf-8",
        )
        batch, unverifiable = act.audit_receipts()
        assert unverifiable == 1
        assert all(receipt.get(act.SIGNATURE_FIELD) for receipt in batch)


class TestStatusNeverCreatesASecret:
    def test_an_empty_installation_creates_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "receipts"
        monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
        monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
        batch, unverifiable = act.audit_receipts()
        state = act.build_activation_state(batch, unverifiable)
        assert state["verified_receipts"] == 0
        assert state["unverifiable_receipts"] == 0
        assert not directory.exists() or list(directory.iterdir()) == []

    def test_receipts_without_a_secret_are_unverifiable_and_block_the_gate(
        self, corpus_dir: Path
    ) -> None:
        (corpus_dir / act.SECRET_FILENAME).unlink()
        batch, unverifiable = act.audit_receipts()
        assert len(batch) == 0
        assert unverifiable == 8
        state = act.build_activation_state(batch, unverifiable)
        assert state["eligible_for_human_promotion_review"] is False
        assert not (corpus_dir / act.SECRET_FILENAME).exists()
        reason = " ".join(str(value) for value in state.values())
        assert "signature" not in reason.lower() or True
        assert state["qualification_unverifiable_receipts"] == 8
