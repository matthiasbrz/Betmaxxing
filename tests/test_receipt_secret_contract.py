"""The signing secret is a strict format with an atomic life cycle — D-076, §5.

Why this suite exists
---------------------
The fifth independent read-only audit reproduced one P1 on `e43851e`: nothing
validated the secret. A file holding an empty string, a newline, one character,
the word ``secret`` or sixty-four non-hexadecimal characters was accepted, signed
with, and verified against — and a synthetic corpus signed with such a key reached
``CRITERIA_MET_AWAITING_HUMAN_REVIEW``. One route needed no adversary at all: a
first run interrupted between the exclusive create and the write left a zero-byte
file that every later run accepted as an empty key, for ever.

Two properties are therefore tested here, and they are different properties:

* **format** — a secret is exactly sixty-four lowercase hexadecimal characters, in
  a file or in the environment, with no ``strip()`` that would turn an invalid
  file into a key, and an invalid existing secret fails **closed** rather than
  being silently regenerated (which would invalidate every receipt already on
  disk);
* **life cycle** — creation is atomic, so no crash and no race can leave a name
  that exists but is empty or partial, and a read-only verification never creates
  anything.

Nothing here reads a real secret, a real receipt or ``.env``. Every value is
synthetic, every directory is a throwaway ``tmp_path``, and no test asserts on a
secret's value, length, prefix or digest.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from betmaxxing.providers.the_odds_api import activation as act
from betmaxxing.providers.the_odds_api import qualification as qual

VALID = "0123456789abcdef" * 4
OTHER_VALID = "fedcba9876543210" * 4

#: Every shape that is not a secret. The point of the table is that each one used
#: to be accepted and to sign a corpus that opened the gate.
INVALID_SECRETS: list[tuple[str, str]] = [
    ("empty", ""),
    ("spaces", "    "),
    ("newline only", "\n"),
    ("one character", "a"),
    ("sixty-three hex", "0" * 63),
    ("sixty-five hex", "0" * 65),
    ("sixty-four with one non-hex", "0" * 63 + "z"),
    ("sixty-four uppercase hex", "A" * 64),
    ("sixty-four hex plus newline", VALID + "\n"),
    ("leading space", " " + VALID[1:]),
    ("very long", "a" * 100_000),
    ("the word secret", "secret"),
]


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway receipt directory with no secret configured anywhere."""
    directory = tmp_path / "receipts"
    directory.mkdir()
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
    monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
    return directory


def _write_secret(directory: Path, body: str) -> Path:
    path = directory / act.SECRET_FILENAME
    path.write_text(body, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


# ---------------------------------------------------------------------------
# The defect, in the vocabulary of the version that shipped it
# ---------------------------------------------------------------------------
class TestTheOldSecretWasNeverValidated:
    """Behavioural, not import-shaped: these run against `e43851e` and fail there."""

    @pytest.mark.parametrize(
        ("label", "body"), INVALID_SECRETS, ids=[c[0] for c in INVALID_SECRETS]
    )
    def test_an_invalid_secret_file_never_signs_anything(
        self, store: Path, label: str, body: str
    ) -> None:
        _write_secret(store, body)
        with pytest.raises(Exception) as caught:
            act.sign_receipt({"a": 1}, act.load_receipt_secret())
        assert not isinstance(caught.value, AssertionError)
        # And the refusal says nothing about the value it refused. Only checked for
        # bodies long enough to be recognisable: a one-character body cannot be told
        # apart from ordinary prose, so asserting on it would test nothing.
        needle = body.strip()
        if len(needle) >= 8:
            assert needle not in str(caught.value)

    @pytest.mark.parametrize(
        ("label", "body"), INVALID_SECRETS, ids=[c[0] for c in INVALID_SECRETS]
    )
    def test_an_invalid_secret_file_is_never_repaired(
        self, store: Path, label: str, body: str
    ) -> None:
        path = _write_secret(store, body)
        before = path.read_bytes()
        with pytest.raises(Exception):  # noqa: B017 - the type differs between versions
            act.ensure_receipt_secret()
        assert path.read_bytes() == before, "an invalid secret must fail closed, not be rewritten"

    def test_a_zero_byte_secret_left_by_an_interrupted_run_is_refused(self, store: Path) -> None:
        (store / act.SECRET_FILENAME).touch()
        with pytest.raises(Exception):  # noqa: B017 - the type differs between versions
            act.load_receipt_secret()
        with pytest.raises(Exception):  # noqa: B017 - the type differs between versions
            act.ensure_receipt_secret()

    @pytest.mark.parametrize(
        ("label", "body"), INVALID_SECRETS, ids=[c[0] for c in INVALID_SECRETS]
    )
    def test_an_invalid_injected_secret_is_refused(
        self, store: Path, monkeypatch: pytest.MonkeyPatch, label: str, body: str
    ) -> None:
        monkeypatch.setenv(act.SECRET_VARIABLE, body)
        with pytest.raises(Exception):  # noqa: B017 - the type differs between versions
            act.load_receipt_secret()

    def test_an_invalid_file_is_refused_even_when_the_environment_is_valid(
        self, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The environment wins, but it may not launder a broken file into silence."""
        _write_secret(store, "")
        monkeypatch.setenv(act.SECRET_VARIABLE, VALID)
        assert act.load_receipt_secret() == VALID
        # the file is still there, untouched, and still invalid
        assert (store / act.SECRET_FILENAME).read_text(encoding="utf-8") == ""

    def test_a_valid_secret_is_accepted_from_the_file_and_from_the_environment(
        self, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_secret(store, VALID)
        assert act.load_receipt_secret() == VALID
        monkeypatch.setenv(act.SECRET_VARIABLE, OTHER_VALID)
        assert act.load_receipt_secret() == OTHER_VALID


class TestTheValidatorItself:
    def test_it_accepts_exactly_sixty_four_lowercase_hex(self) -> None:
        assert act.validate_secret_text(VALID) == VALID

    @pytest.mark.parametrize(
        ("label", "body"), INVALID_SECRETS, ids=[c[0] for c in INVALID_SECRETS]
    )
    def test_it_refuses_everything_else(self, label: str, body: str) -> None:
        with pytest.raises(act.SecretInvalid):
            act.validate_secret_text(body)

    def test_the_refusal_never_reflects_the_value(self) -> None:
        needle = "cafebabe" * 8
        try:
            act.validate_secret_text(needle + "extra")
        except act.SecretInvalid as exc:
            assert needle not in str(exc)
            assert "cafe" not in str(exc)
        else:  # pragma: no cover - the call above must raise
            raise AssertionError("an over-long secret must be refused")

    def test_a_generated_secret_satisfies_the_validator(self) -> None:
        for _ in range(16):
            assert act.validate_secret_text(act.new_secret_text())

    def test_the_shared_test_secret_satisfies_the_validator(self) -> None:
        from helpers_activation import FAKE_RECEIPT_SECRET

        assert act.validate_secret_text(FAKE_RECEIPT_SECRET) == FAKE_RECEIPT_SECRET


# ---------------------------------------------------------------------------
# Creation: atomic, concurrent, crash-tolerant
# ---------------------------------------------------------------------------
class TestCreationIsAtomic:
    def test_ensure_creates_a_valid_secret_at_0600(self, store: Path) -> None:
        value = act.ensure_receipt_secret()
        assert act.validate_secret_text(value) == value
        path = store / act.SECRET_FILENAME
        info = path.stat()
        assert info.st_mode & 0o777 == 0o600
        assert info.st_size == 64
        assert path.read_text(encoding="utf-8") == value

    def test_ensure_is_idempotent_and_never_rotates_a_valid_secret(self, store: Path) -> None:
        first = act.ensure_receipt_secret()
        assert act.ensure_receipt_secret() == first
        assert act.load_receipt_secret() == first

    def test_load_never_creates_a_missing_secret(self, store: Path) -> None:
        with pytest.raises(act.SecretMissing):
            act.load_receipt_secret()
        assert list(store.iterdir()) == []

    def test_no_temporary_survives_a_successful_creation(self, store: Path) -> None:
        act.ensure_receipt_secret()
        assert sorted(p.name for p in store.iterdir()) == [act.SECRET_FILENAME]

    def test_a_crash_between_the_write_and_the_publication_leaves_no_secret(
        self, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The name may not exist until the bytes do."""
        real_link = os.link

        def failing_link(*args: Any, **kwargs: Any) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(os, "link", failing_link)
        with pytest.raises(KeyboardInterrupt):
            act.ensure_receipt_secret()
        monkeypatch.setattr(os, "link", real_link)
        assert not (store / act.SECRET_FILENAME).exists()
        # the interrupted attempt leaves nothing that a later run would read as a key
        assert [p.name for p in store.iterdir() if not p.name.startswith(".")] == []

    def test_a_crash_after_publication_before_cleanup_keeps_a_complete_secret(
        self, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_unlink = os.unlink

        def failing_unlink(*args: Any, **kwargs: Any) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(os, "unlink", failing_unlink)
        with pytest.raises(KeyboardInterrupt):
            act.ensure_receipt_secret()
        monkeypatch.setattr(os, "unlink", real_unlink)
        published = act.load_receipt_secret()
        assert act.validate_secret_text(published) == published

    def test_a_reader_during_creation_never_sees_a_partial_secret(self, store: Path) -> None:
        """Whatever a concurrent reader sees, it is either absent or complete."""
        seen: list[str] = []
        real_publish = act.receipt_store.SecureDirectory.publish_bytes

        def watching_publish(self: Any, name: str, payload: bytes) -> Any:
            outcome = real_publish(self, name, payload)
            try:
                seen.append(act.load_receipt_secret())
            except Exception as exc:
                seen.append(type(exc).__name__)
            return outcome

        act.receipt_store.SecureDirectory.publish_bytes = watching_publish  # type: ignore[method-assign]
        try:
            value = act.ensure_receipt_secret()
        finally:
            act.receipt_store.SecureDirectory.publish_bytes = real_publish  # type: ignore[method-assign]
        assert seen == [value]


class TestConcurrentCreators:
    """Deterministic barriers, real processes, and one agreed key at the end."""

    @staticmethod
    def _child_source() -> str:
        return (
            "import os, sys, json\n"
            "os.environ['BETMAXXING_ACTIVATION_RECEIPTS'] = sys.argv[1]\n"
            "os.environ.pop('BETMAXXING_ACTIVATION_RECEIPT_SECRET', None)\n"
            "barrier = sys.argv[2]\n"
            "from betmaxxing.providers.the_odds_api import activation as act\n"
            "open(os.path.join(barrier, str(os.getpid())), 'w').close()\n"
            "while len(os.listdir(barrier)) < int(sys.argv[3]):\n"
            "    pass\n"
            "try:\n"
            "    print(json.dumps({'ok': act.ensure_receipt_secret()}))\n"
            "except BaseException as exc:\n"
            "    print(json.dumps({'error': type(exc).__name__}))\n"
        )

    def _race(self, tmp_path: Path, workers: int) -> list[dict[str, str]]:
        directory = tmp_path / f"receipts-{workers}"
        directory.mkdir()
        barrier = tmp_path / f"barrier-{workers}"
        barrier.mkdir()
        script = tmp_path / "child.py"
        script.write_text(self._child_source(), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(Path(act.__file__).parents[4]), env.get("PYTHONPATH", "")]
        )
        procs = [
            subprocess.Popen(
                [sys.executable, str(script), str(directory), str(barrier), str(workers)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
            )
            for _ in range(workers)
        ]
        out = []
        for proc in procs:
            stdout, _ = proc.communicate(timeout=120)
            out.append(json.loads(stdout.strip().splitlines()[-1]))
        published = (directory / act.SECRET_FILENAME).read_text(encoding="utf-8")
        assert act.validate_secret_text(published) == published
        for result in out:
            assert result.get("ok") == published, result
        assert sorted(p.name for p in directory.iterdir()) == [act.SECRET_FILENAME]
        return out

    @pytest.mark.parametrize("workers", [2, 16])
    def test_every_racing_creator_ends_with_the_same_complete_secret(
        self, tmp_path: Path, workers: int
    ) -> None:
        assert len(self._race(tmp_path, workers)) == workers


class TestTheSecretIsNeverReadThroughASubstitution:
    def test_a_link_to_an_outside_secret_is_refused(self, store: Path, tmp_path: Path) -> None:
        planted = tmp_path / "outside.secret"
        planted.write_text(OTHER_VALID, encoding="utf-8")
        os.symlink(planted, store / act.SECRET_FILENAME)
        with pytest.raises(Exception) as caught:
            act.load_receipt_secret()
        assert OTHER_VALID not in str(caught.value)

    def test_a_broken_link_is_refused(self, store: Path, tmp_path: Path) -> None:
        os.symlink(tmp_path / "nowhere", store / act.SECRET_FILENAME)
        with pytest.raises(Exception):  # noqa: B017 - the type differs between versions
            act.load_receipt_secret()

    def test_a_directory_named_like_the_secret_is_refused(self, store: Path) -> None:
        (store / act.SECRET_FILENAME).mkdir()
        with pytest.raises(Exception):  # noqa: B017 - the type differs between versions
            act.load_receipt_secret()

    def test_a_fifo_named_like_the_secret_is_refused_without_blocking(self, store: Path) -> None:
        os.mkfifo(store / act.SECRET_FILENAME)
        with pytest.raises(Exception):  # noqa: B017 - the type differs between versions
            act.load_receipt_secret()


# ---------------------------------------------------------------------------
# The known-key corpus: the P1 itself
# ---------------------------------------------------------------------------
class TestAKnownOrTrivialKeyCannotOpenTheGate:
    """A full threshold corpus signed with an invalid key must never qualify."""

    @staticmethod
    def _corpus(directory: Path, secret: str) -> None:
        from helpers_qualification_corpus import write_threshold_corpus

        write_threshold_corpus(directory, secret)

    @pytest.mark.parametrize(
        ("label", "body"),
        [case for case in INVALID_SECRETS if case[0] != "sixty-four hex plus newline"],
        ids=[c[0] for c in INVALID_SECRETS if c[0] != "sixty-four hex plus newline"],
    )
    def test_a_corpus_signed_with_an_invalid_key_never_qualifies(
        self, store: Path, label: str, body: str
    ) -> None:
        # The corpus is signed with the literal bytes an attacker would use.
        self._corpus(store, body)
        _write_secret(store, body)
        _audit = act.audit_receipts()
        batch, unverifiable = _audit.batch, _audit.unverifiable
        assert len(batch) == 0, "no receipt may be verified under an invalid key"
        assert unverifiable >= 1
        state = act.build_activation_state(_audit)
        assert state["eligible_for_human_promotion_review"] is False
        assert state["qualification_state"] != str(
            qual.QualificationState.CRITERIA_MET_AWAITING_HUMAN_REVIEW
        )
        assert state["adapter_state"] == "IMPLEMENTED_UNVERIFIED"

    def test_the_same_corpus_under_a_valid_key_is_read_as_evidence(self, store: Path) -> None:
        """The control: the refusal above is about the key, not about the corpus."""
        self._corpus(store, VALID)
        _write_secret(store, VALID)
        _audit = act.audit_receipts()
        batch, unverifiable = _audit.batch, _audit.unverifiable
        assert len(batch) >= 1
        assert unverifiable == 0

    def test_a_receipt_signed_with_another_valid_key_is_unverifiable(self, store: Path) -> None:
        self._corpus(store, OTHER_VALID)
        _write_secret(store, VALID)
        _audit = act.audit_receipts()
        batch, unverifiable = _audit.batch, _audit.unverifiable
        assert len(batch) == 0
        assert unverifiable >= 1
