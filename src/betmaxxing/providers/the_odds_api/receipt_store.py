"""The receipt directory as a descriptor: secret, publication, quarantine, intents.

Why this module exists
----------------------
Five independent read-only audits of the activation harness each found real defects
after a green CI. The fifth found them all in one place — the boundary between what
is on disk and what the program is willing to believe — and the shape of the fix is
what this module is.

**A secret is a format, not a file's contents.** v5 created
``signing-key.secret`` and then trusted whatever came back from it. An empty file, a
newline, one character, the word ``secret``, sixty-four non-hexadecimal characters
and a hundred thousand characters were all accepted, all signed with, and all
verified against; a synthetic corpus signed with such a key reached the human-review
gate. One route needed no adversary: a first run interrupted between the exclusive
create and the write left a zero-byte file that every later run read as an empty
key, for ever. So the bytes are validated on the way in *and* on the way out, an
invalid secret fails closed rather than being regenerated — regenerating it would
silently invalidate every receipt already on disk — and creation is atomic.

**A directory is an inode, not a path.** v5 opened each *name* relative to a
directory descriptor with ``O_NOFOLLOW``, which is right, and opened the
*directory* by path with ``O_DIRECTORY`` alone, which is not. ``link``, ``unlink``
and the directory ``fsync`` then went back to ``directory / name``. Three
deterministic probes followed: a receipt directory that was a symbolic link, a
symlinked parent component, and a directory swapped between the listing and the
open. Each one had an outside file read, verified and reported. So
:class:`SecureDirectory` walks every component with ``openat`` semantics, keeps one
descriptor for the whole operation, and every listing, read, publication, link,
unlink, rename and fsync goes through it. On a platform that cannot promise that,
nothing is read at all.

**A durability error is a fact, not a nuisance.** The publication order is written
down below and performed in that order, the progress loop cannot spin, and a failed
``fsync`` is reported rather than suppressed.

**Provenance is a proof, not a type name.** v6 made ``VerifiedReceipt`` a distinct
class and thought that settled it. The sixth audit called ``VerifiedReceipt(payload)``
— a public constructor that checked nothing — on eight receipts whose ``signature``
key had been deleted, and reached the human-review gate; a corpus signed with a
foreign key did the same. So the type is unconstructible from outside now, and there
is no longer any function that mints authority from a payload plus a caller's key:
that function *was* the hole. The only route in is :func:`audit_directory`, which
takes a directory this module has already opened safely and does the reading, the
schema check and the HMAC itself, against the secret of the installation.

The claim is deliberately narrow and testable: **no exported entry point of this
repository produces admitted provenance without a signature check against the
installation's own secret**. Code already executing in this process can reach a
private name or rewrite bytecode; nothing here pretends otherwise.

**An admitted receipt is a frozen value.** v6 copied one level deep, so every
nested dictionary and list stayed shared with the caller's, and ``__getitem__``
handed the live object back: one write through the ordinary Mapping API —
``receipt["freshness"][market] = 300`` — turned a refusal into
``CRITERIA_MET_AWAITING_HUMAN_REVIEW`` while the receipt's own signature stopped
verifying, and nothing re-read the seal. Payloads are frozen recursively on the way
in.

The first attempt at that freeze deserves to stay written down, because it was the
same defect one level lower. The sealed containers were a ``dict`` subclass and a
``list`` subclass overriding every mutator, chosen so that nothing downstream would
have to change vocabulary. Overriding a mutator does not remove it: the base class
method stays reachable through the class object. Measured, all fifteen of
``dict.__setitem__``, ``dict.update``, ``dict.pop``, ``dict.setdefault``,
``dict.clear``, ``dict.__ior__``, ``list.__setitem__``, ``list.append``,
``list.extend``, ``list.insert``, ``list.pop``, ``list.clear``, ``list.__iadd__``,
``list.sort`` and ``list.reverse`` succeeded against a receipt the audit had really
admitted — including the exact write above, which reopened the gate. So
:class:`FrozenMapping` implements :class:`~collections.abc.Mapping` and inherits no
mutable container, sequences become plain tuples, and those fifteen calls raise. The
cost is paid in the open: the structural checks that asked ``isinstance(value, list)``
ask for a non-``str`` :class:`~collections.abc.Sequence`, and re-serialising an
admitted receipt goes through ``to_builtin()`` rather than ``dict()``.

What stays reachable is ``object.__setattr__`` on the single slot. :func:`audit_directory`
therefore records a non-keyed sha256 of every admitted receipt in its result, and
:func:`require_audited` recomputes them before anything reads the batch: a receipt
that changed after the audit admitted it is no longer the evidence that was verified,
and it is not read. Rewriting *both* the payload and its recorded digest still defeats
this. That is a limit, stated as one — not a guarantee.

**A boundary that cannot be read is not an empty boundary.** ``StoreRefused`` used
to collapse into « zero receipts, zero unverifiable » — the same answer a clean,
empty installation gives, so an operator whose receipt directory had become a
symbolic link read « 0 reçu » and moved on. The three cases are distinct values of
:class:`BoundaryState`.

Nothing in this module knows what a receipt *means*. It has no status vocabulary, no
cost model and no criteria: it moves bytes across a boundary and says whether they
crossed it honestly.
"""

from __future__ import annotations

import contextlib
import enum
import hashlib
import hmac
import json as jsonlib
import os
import re
import secrets
import stat as statmodule
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Refusals. Every one of them names what happened, never the value involved.
# ---------------------------------------------------------------------------
class StoreRefused(Exception):
    """The boundary said no. Its message is safe to print."""


class SecretInvalid(StoreRefused):
    """The secret is not sixty-four lowercase hexadecimal characters."""


class SecretMissing(StoreRefused):
    """No secret is configured, and this operation is not allowed to create one."""


class DirectoryUnsafe(StoreRefused):
    """A path component, a name or an object is not what it must be."""


class DirectoryAbsent(DirectoryUnsafe):
    """The directory simply is not there — which is not the same as unsafe.

    A subclass, so every ``except DirectoryUnsafe`` written before this distinction
    existed keeps failing closed. Only the audit, which has to tell an operator with
    no receipts from an operator whose boundary cannot be read, looks for it.
    """


class ContentUndecodable(StoreRefused):
    """The bytes are not UTF-8. A typed refusal, never a bare ``UnicodeDecodeError``.

    A secret file of invalid UTF-8 used to raise out of both secret verbs, and the
    traceback reached the operator instead of a sentence.
    """


class CountInvalid(StoreRefused, ValueError):
    """A count was offered as something that is not a count."""


class PersistenceFailed(StoreRefused):
    """Bytes could not be made durable.

    ``published`` says whether the final name exists and is complete;
    ``cleanup_pending`` says whether something remains to be tidied. The two are
    different facts and an operator needs both: the first decides whether the proof
    exists, the second decides whether the directory needs attention.
    """

    def __init__(
        self, message: str, *, published: bool = False, cleanup_pending: bool = False
    ) -> None:
        super().__init__(message)
        self.published = published
        self.cleanup_pending = cleanup_pending


class UnverifiedProvenance(TypeError):
    """Something that was never verified was offered as evidence.

    Also what an attempt to construct a provenance object by hand raises: minting
    authority and asserting it are the same offence.
    """


# ---------------------------------------------------------------------------
# The state of the boundary itself
# ---------------------------------------------------------------------------
class BoundaryState(enum.Enum):
    """Whether the receipt directory could be read, and if not, why not.

    Three values because there are three situations, and v6 published two of them
    identically. ``ABSENT`` is a *fact about the installation* — nothing has run yet.
    ``UNAVAILABLE`` is a *fact about the boundary* — something is there and this
    program refuses to read it. Reporting the second as the first is how a symlinked
    receipt directory looked like a clean slate.
    """

    ABSENT = "ABSENT"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"

    def __str__(self) -> str:
        return self.value


#: Why a boundary is unavailable, as a closed vocabulary. Never a path, never the
#: name of anything an attacker chose: a category an operator can act on.
BOUNDARY_REASONS = (
    "",
    "absent",
    "ambiguous_component",
    "not_a_directory",
    "permission_denied",
    "kernel_support_missing",
    "unreadable",
)


# ---------------------------------------------------------------------------
# The secret: a format, validated in both directions
# ---------------------------------------------------------------------------
#: Thirty-two random bytes, written as sixty-four lowercase hexadecimal characters.
#: One representation, so a file, an environment variable and a test fixture cannot
#: disagree about what a secret is.
SECRET_HEX_LENGTH = 64

#: How many consecutive zero-length writes to absorb before giving up. Bounded, so a
#: stalled descriptor ends in a typed failure instead of an unbounded loop.
MAX_WRITE_STALLS = 3
#: ``fullmatch`` rather than ``match``: in a Python regular expression ``$`` also
#: matches just before a trailing newline, so an anchored ``match`` accepted a
#: sixty-four character secret followed by a line break as a *different* secret
#: from the same characters without one — two spellings of one key, which is two
#: keys as far as an HMAC is concerned.
_SECRET_SHAPE = re.compile(f"[0-9a-f]{{{SECRET_HEX_LENGTH}}}")


def validate_secret_text(text: object) -> str:
    """The secret, or :class:`SecretInvalid`. No stripping, no case folding.

    Deliberately exact. ``strip()`` is what turned ``"\\n"`` into a key and a
    trailing newline into a different key than the same file without one; accepting
    uppercase would mean two spellings of one secret, which is two secrets as far as
    an HMAC is concerned. The message never contains the value, its length, a
    prefix, a suffix or a digest — a refusal must be printable next to a real key.
    """
    if not isinstance(text, str) or not _SECRET_SHAPE.fullmatch(text):
        raise SecretInvalid(
            "Le secret de signature doit être exactement 64 caractères hexadécimaux "
            "minuscules (32 octets). Aucune valeur n'est affichée ni corrigée."
        )
    return text


def new_secret_text() -> str:
    return secrets.token_hex(SECRET_HEX_LENGTH // 2)


# ---------------------------------------------------------------------------
# Signatures. The secret is a parameter, never an ambient lookup.
# ---------------------------------------------------------------------------
def canonical_bytes(payload: Mapping[str, Any], *, signature_field: str) -> bytes:
    """The exact bytes a signature covers.

    Sorted keys and tight separators, so re-serialising a receipt cannot change its
    signature. The signature field itself and every ``_``-prefixed scratch key are
    excluded.
    """
    body = {k: v for k, v in payload.items() if k != signature_field and not k.startswith("_")}
    return jsonlib.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sign(payload: Mapping[str, Any], *, secret: str, signature_field: str) -> str:
    return hmac.new(
        validate_secret_text(secret).encode("utf-8"),
        canonical_bytes(payload, signature_field=signature_field),
        hashlib.sha256,
    ).hexdigest()


#: A signature is sixty-four lowercase hexadecimal characters, exactly. Checked
#: **before** ``compare_digest``, which raises ``TypeError`` on a string holding a
#: non-ASCII character: one receipt file with ``"é" * 64`` under ``signature`` made
#: the whole reporting path die with a traceback and zero bytes of output, for as
#: long as the file stayed on disk.
_SIGNATURE_SHAPE = re.compile("[0-9a-f]{64}")


def verify(payload: Mapping[str, Any], *, secret: str, signature_field: str) -> bool:
    """Constant-time check. A wrong-shaped secret is a refusal, not a mismatch.

    A wrong-shaped *signature* is a plain ``False``: it cannot be the digest of
    anything, so there is nothing to compare, and comparing it is what crashed.
    """
    given = payload.get(signature_field)
    if not isinstance(given, str) or not _SIGNATURE_SHAPE.fullmatch(given):
        return False
    return hmac.compare_digest(given, sign(payload, secret=secret, signature_field=signature_field))


# ---------------------------------------------------------------------------
# Provenance as a type
# ---------------------------------------------------------------------------
#: The one object that authorises the construction of a provenance value. Private,
#: never exported, never accepted as a parameter of anything public. Every
#: constructor below takes it as its **first positional argument**, so the natural
#: spelling — ``VerifiedReceipt(payload)`` — raises instead of minting authority.
_PROVENANCE_TOKEN: Any = object()


def _refuse_minting(what: str) -> UnverifiedProvenance:
    return UnverifiedProvenance(
        f"Un {what} ne se construit pas : il s'obtient en auditant un répertoire de "
        "reçus sûr, dont les fichiers sont signés par le secret de cette installation. "
        "Aucun appelant ne peut frapper une provenance sans vérification."
    )


def _frozen_error(what: str) -> TypeError:
    return TypeError(
        f"Ce {what} appartient à un reçu vérifié : il est scellé et ne se modifie pas."
    )


class FrozenMapping(Mapping[str, Any]):
    """An immutable mapping that **does not inherit from ``dict``**.

    The first attempt at protocol 7 subclassed ``dict`` and ``list`` and overrode every
    mutator, on the reasoning that the repository reads receipts with
    ``isinstance(value, dict)`` and renders them with ``json.dumps``, so keeping the
    nominal types would make the freeze a guarantee rather than a behaviour change.

    That reasoning was wrong, and measurably so: overriding a method on a subclass does
    not remove the base class's. All fifteen of
    ``dict.__setitem__``, ``dict.update``, ``dict.pop``, ``dict.setdefault``,
    ``dict.clear``, ``dict.__ior__``, ``list.__setitem__``, ``list.append``,
    ``list.extend``, ``list.insert``, ``list.pop``, ``list.clear``, ``list.__iadd__``,
    ``list.sort`` and ``list.reverse`` succeeded when called explicitly on the frozen
    object — and ``dict.__setitem__(receipt["freshness"], market, 300)`` is exactly the
    write that moved a corpus to the human-review gate after verification. Nominal
    compatibility with ``dict`` does not outrank the boundary it was protecting.

    So the sealed representation is a wrapper with no mutable base class, and sequences
    become plain tuples. Reading is unchanged — this *is* a
    :class:`~collections.abc.Mapping` — and the two structural checks that asked for a
    ``list`` now ask for a sequence that is not a string, which rejects exactly what
    they rejected before: ``json.loads`` never produces a tuple.
    """

    __slots__ = ("_data",)

    _data: dict[str, Any]

    def __init__(self, token: Any = None, data: Mapping[str, Any] | None = None) -> None:
        if token is not _PROVENANCE_TOKEN or data is None:
            raise _refuse_minting("contenu scellé")
        object.__setattr__(self, "_data", dict(data))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __setitem__(self, key: str, value: Any) -> None:
        # A `Mapping` has no `__setitem__`, so `m[k] = v` would already fail — but with
        # « object does not support item assignment », and `m.__setitem__(k, v)` would
        # fail with `AttributeError`. Spelling it out gives both forms one message that
        # says *why*.
        raise _frozen_error("champ scellé")

    def __delitem__(self, key: str) -> None:
        raise _frozen_error("champ scellé")

    def __setattr__(self, name: str, value: Any) -> None:
        raise _frozen_error("contenu scellé")

    def __delattr__(self, name: str) -> None:
        raise _frozen_error("contenu scellé")

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self._data) == dict(other)
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self) -> int:
        return hash(tuple(sorted((key, repr(value)) for key, value in self._data.items())))

    def __copy__(self) -> FrozenMapping:
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> FrozenMapping:
        return self

    def __reduce__(self) -> Any:
        raise TypeError(
            "Un contenu scellé ne se sérialise pas : il se relit depuis le répertoire "
            "qui l'a admis."
        )

    def __repr__(self) -> str:
        return f"FrozenMapping({self._data!r})"

    def to_builtin(self) -> dict[str, Any]:
        """A plain, mutable copy — for serialisation, never for evidence."""
        return {key: _to_builtin(value) for key, value in self._data.items()}


def _freeze(value: Any) -> Any:
    """The same data, with nothing mutable left anywhere inside it.

    Recursive, and built only from objects that have no mutating API at all: a
    :class:`FrozenMapping` wrapper, a ``tuple``, a ``frozenset``, or an immutable
    scalar. ``dict(payload)`` froze the top level and shared every nested container,
    which is how ``receipt["freshness"][market] = 300`` — no private attribute, no
    trick, just the documented Mapping API — moved a corpus from
    ``INSUFFICIENT_EVIDENCE`` to the human-review gate after its signature had been
    checked and while that signature no longer verified. Subclassing ``dict`` and
    ``list`` did not fix it either: the base classes' methods stayed reachable.
    """
    if isinstance(value, FrozenMapping):
        return value
    if isinstance(value, Mapping):
        return FrozenMapping(_PROVENANCE_TOKEN, {key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (str, bytes, bytearray)):
        return value
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, Sequence):
        return tuple(_freeze(item) for item in value)
    return value


def _to_builtin(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_builtin(item) for key, item in value.items()}
    if isinstance(value, (str, bytes, bytearray)):
        return value
    if isinstance(value, frozenset):
        return sorted(_to_builtin(item) for item in value)
    if isinstance(value, Sequence):
        return [_to_builtin(item) for item in value]
    return value


class VerifiedReceipt(Mapping[str, Any]):
    """A receipt this installation read safely, checked and verified.

    A read-only :class:`~collections.abc.Mapping`, so every reader that used to take
    a ``dict`` still works. Two things changed at protocol 7: it cannot be
    constructed (the first argument is a private token), and what it holds is frozen
    all the way down, so nothing handed out through ``__getitem__`` is writable.
    """

    __slots__ = ("_frozen",)

    _frozen: FrozenMapping

    def __init__(self, token: Any = None, payload: Mapping[str, Any] | None = None) -> None:
        if token is not _PROVENANCE_TOKEN or payload is None:
            raise _refuse_minting("reçu vérifié")
        object.__setattr__(self, "_frozen", _freeze(dict(payload)))

    def __getitem__(self, key: str) -> Any:
        return self._frozen[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._frozen)

    def __len__(self) -> int:
        return len(self._frozen)

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("Un reçu vérifié ne se modifie pas.")

    def __copy__(self) -> VerifiedReceipt:
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> VerifiedReceipt:
        # The value is immutable, so a copy of it is itself. Returning a new object
        # would only invite the question of whether the new one is still admitted.
        return self

    def __reduce__(self) -> Any:
        raise TypeError(
            "Un reçu vérifié ne se sérialise pas : une preuve se relit depuis son "
            "répertoire, elle ne voyage pas hors de la frontière qui l'a admise."
        )

    def to_builtin(self) -> dict[str, Any]:
        """A plain, mutable copy of the sealed bytes — for rendering only."""
        return self._frozen.to_builtin()

    def __repr__(self) -> str:
        return f"VerifiedReceipt(receipt_id={self._frozen.get('receipt_id')!r})"


class VerifiedReceiptBatch(Sequence[VerifiedReceipt]):
    """Every receipt this installation could verify, and how many it could not."""

    __slots__ = ("_receipts", "unverifiable")

    _receipts: tuple[VerifiedReceipt, ...]
    unverifiable: int

    def __init__(
        self,
        token: Any = None,
        receipts: Sequence[VerifiedReceipt] | None = None,
        unverifiable: int = 0,
    ) -> None:
        if token is not _PROVENANCE_TOKEN or receipts is None:
            raise _refuse_minting("lot de reçus vérifiés")
        for receipt in receipts:
            if not isinstance(receipt, VerifiedReceipt):
                raise _refuse_minting("lot de reçus vérifiés")
        object.__setattr__(self, "_receipts", tuple(receipts))
        object.__setattr__(self, "unverifiable", _exact_count(unverifiable, "unverifiable"))

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("Un lot de reçus vérifiés ne se modifie pas.")

    def __getitem__(self, index: Any) -> Any:
        return self._receipts[index]

    def __len__(self) -> int:
        return len(self._receipts)


class AuditResult:
    """What one look at the receipt directory established.

    Four facts, carried together because they are only meaningful together: the
    verified receipts, how many files could not be verified, whether the boundary
    could be read at all, and — when it could not — a category saying why. v6
    returned the first two and dropped the others, so an unsafe directory and an
    empty one were indistinguishable downstream.

    Not a tuple: unpacking it into ``batch, unverifiable`` is exactly the mistake
    that lost the boundary state, so it does not unpack.
    """

    __slots__ = ("batch", "boundary", "reason", "seals", "unverifiable")

    batch: VerifiedReceiptBatch
    unverifiable: int
    boundary: BoundaryState
    reason: str
    seals: tuple[str, ...]

    def __init__(
        self,
        token: Any = None,
        batch: VerifiedReceiptBatch | None = None,
        boundary: BoundaryState | None = None,
        reason: str = "",
    ) -> None:
        if token is not _PROVENANCE_TOKEN:
            raise _refuse_minting("résultat d'audit")
        if not isinstance(batch, VerifiedReceiptBatch):
            raise _refuse_minting("résultat d'audit")
        if not isinstance(boundary, BoundaryState) or reason not in BOUNDARY_REASONS:
            raise _refuse_minting("résultat d'audit")
        object.__setattr__(self, "batch", batch)
        object.__setattr__(self, "unverifiable", batch.unverifiable)
        object.__setattr__(self, "boundary", boundary)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "seals", tuple(fingerprint(one) for one in batch))

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("Un résultat d'audit ne se modifie pas.")

    @property
    def readable(self) -> bool:
        """Whether the count of receipts means anything at all."""
        return self.boundary is not BoundaryState.UNAVAILABLE

    def __repr__(self) -> str:
        return (
            f"AuditResult(boundary={self.boundary}, verified={len(self.batch)}, "
            f"unverifiable={self.unverifiable})"
        )


def _exact_count(value: object, field: str) -> int:
    """An exact, non-negative Python integer, or a refusal naming the field.

    ``bool`` is excluded deliberately: ``True`` is an ``int`` in Python and
    ``unresolved_intents=True`` used to mean « one unresolved intent », while
    ``False`` and ``None`` both quietly meant zero — so « I do not know how many »
    read as « there are none », which is the wrong direction for a blocker.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CountInvalid(
            f"{field} est un compte : un entier Python exact et positif ou nul. "
            "Ni booléen, ni flottant, ni chaîne, ni None."
        )
    if value < 0:
        raise CountInvalid(f"{field} est un compte : il ne peut pas être négatif.")
    return value


def fingerprint(payload: Mapping[str, Any]) -> str:
    """A non-keyed digest of the sealed content, for detecting tampering after minting.

    Deliberately **not** an HMAC: no secret is involved, so computing one here keeps the
    evaluator pure — no environment, no file, no key, no clock. It is not a signature and
    proves nothing about origin; its only job is to notice that the bytes admitted by the
    audit are not the bytes being read now.

    Why it exists: ``__slots__`` leaves exactly one attribute name on a verified receipt,
    and ``object.__setattr__`` can replace it. That primitive cannot be taken away from
    code running in this process — but a one-line substitution can be made to fail, and
    that is worth doing. Someone who also replaces the recorded digests defeats this, and
    that limit is written down rather than argued away.
    """
    body = jsonlib.dumps(
        _to_builtin(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def require_audited(result: object) -> tuple[VerifiedReceipt, ...]:
    """The receipts of a real audit, unchanged since it admitted them, or a refusal.

    Only an :class:`AuditResult` is accepted. Lists, tuples and bare batches are not:
    each of them was a way of assembling evidence by hand, and one of them —
    ``[VerifiedReceipt(payload) for payload in forged]`` — reached the gate.

    Each receipt is then checked against the fingerprint recorded when it was minted, so
    a payload swapped in afterwards — by any means, including ``object.__setattr__`` on
    the single remaining slot — is refused instead of read.
    """
    if not isinstance(result, AuditResult):
        raise UnverifiedProvenance(
            "Une évaluation prend le résultat d'un audit du répertoire de reçus, pas "
            "une liste, un tuple ni un lot assemblé à la main."
        )
    receipts = tuple(result.batch)
    seals = result.seals
    if len(seals) != len(receipts):
        raise UnverifiedProvenance(
            "Le lot audité et ses empreintes ne correspondent plus : le résultat d'audit "
            "a été altéré après sa production."
        )
    for receipt, seal in zip(receipts, seals, strict=True):
        if fingerprint(receipt) != seal:
            raise UnverifiedProvenance(
                "Un reçu a changé depuis que l'audit l'a admis : il n'est plus la preuve "
                "qui a été vérifiée, et il n'est pas lu."
            )
    return receipts


# ---------------------------------------------------------------------------
# The directory
# ---------------------------------------------------------------------------
#: Every kernel facility the boundary depends on. Missing any one of them means the
#: guarantee cannot be given, and a guarantee that cannot be given is not downgraded
#: silently: the directory is not read at all.
_NEEDED_DIR_FD = ("open", "link", "unlink", "rename", "stat", "mkdir")


def _require_kernel_support() -> int:
    flags = getattr(os, "O_NOFOLLOW", 0)
    if not flags:
        raise DirectoryUnsafe(
            "Cette plateforme n'offre pas O_NOFOLLOW : le répertoire de reçus ne peut "
            "pas être ouvert sans risque de suivre un lien, donc il n'est pas lu."
        )
    supported = {function.__name__ for function in getattr(os, "supports_dir_fd", set())}
    missing = [name for name in _NEEDED_DIR_FD if name not in supported]
    if missing:
        raise DirectoryUnsafe(
            "Cette plateforme n'offre pas les opérations relatives à un descripteur de "
            "répertoire dont la frontière dépend ; le répertoire de reçus n'est pas lu."
        )
    return flags


def boundary_reason_of(exc: OSError) -> str:
    """One of :data:`BOUNDARY_REASONS` for an ``errno``. Never a path, never a name."""
    import errno as errnomodule

    code = getattr(exc, "errno", None)
    if code in {errnomodule.ELOOP, errnomodule.EMLINK}:
        return "ambiguous_component"
    if code == errnomodule.ENOTDIR:
        return "not_a_directory"
    if code in {errnomodule.EACCES, errnomodule.EPERM}:
        return "permission_denied"
    if code == errnomodule.ENOENT:
        return "absent"
    return "unreadable"


def _check_name(name: object) -> str:
    """One plain name of one directory. Never a path, never a traversal."""
    if not isinstance(name, str) or not name or name in {".", ".."}:
        raise DirectoryUnsafe("Un nom de fichier de reçu est une chaîne simple, non vide.")
    if "/" in name or "\\" in name or "\0" in name:
        raise DirectoryUnsafe(
            "Un nom de fichier de reçu ne contient pas de séparateur de chemin : "
            "l'opération reste dans le répertoire autorisé."
        )
    return name


@dataclass(frozen=True)
class Published:
    """What a publication actually achieved."""

    outcome: str
    cleanup_pending: bool = False


class SecureDirectory:
    """One directory, opened component by component, held open by descriptor.

    The whole operation — listing, reading, publishing, linking, unlinking, renaming
    and syncing — runs against this descriptor. No sensitive step ever returns to a
    path, because a path is re-resolved on every use and that is exactly the window
    three probes of the fifth audit walked through.
    """

    __slots__ = ("fd", "label")

    def __init__(self, fd: int, label: str) -> None:
        self.fd = fd
        self.label = label

    # -- construction -------------------------------------------------------
    @classmethod
    @contextmanager
    def open(cls, path: Path | str, *, create: bool = False) -> Iterator[SecureDirectory]:
        no_follow = _require_kernel_support()
        target = Path(path)
        if not target.parts:
            raise DirectoryUnsafe("Le répertoire de reçus n'est pas nommé.")
        flags = os.O_RDONLY | os.O_DIRECTORY | no_follow | getattr(os, "O_CLOEXEC", 0)
        parts = list(target.parts)
        if target.is_absolute():
            # The root itself is the one component nobody can substitute.
            current = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
            parts = parts[1:]
        else:
            current = os.open(".", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
        try:
            for component in parts:
                _check_name(component)
                current = cls._descend(current, component, flags=flags, create=create)
            info = os.fstat(current)
            if not statmodule.S_ISDIR(info.st_mode):
                raise DirectoryUnsafe("Le répertoire de reçus n'est pas un répertoire régulier.")
            directory = cls(current, str(target))
        except BaseException:
            os.close(current)
            raise
        try:
            yield directory
        finally:
            os.close(directory.fd)

    @staticmethod
    def _descend(parent: int, component: str, *, flags: int, create: bool) -> int:
        """Open one component below ``parent``, creating it only if asked to.

        The caller owns ``parent`` on every error path — closing it here as well is a
        double close, and a double close on a descriptor number the kernel has already
        reused is worse than a leak.
        """
        try:
            child = os.open(component, flags, dir_fd=parent)
        except FileNotFoundError:
            if not create:
                raise DirectoryAbsent(
                    "Le répertoire de reçus n'existe pas ; rien n'est lu et rien n'est créé."
                ) from None
            try:
                os.mkdir(component, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            except OSError as exc:
                raise DirectoryUnsafe(
                    "Le répertoire de reçus ne peut pas être créé sous un composant sûr."
                ) from exc
            try:
                child = os.open(component, flags, dir_fd=parent)
            except OSError as exc:
                raise DirectoryUnsafe(
                    "Le composant du répertoire de reçus vient de changer de nature."
                ) from exc
        except OSError as exc:
            # ELOOP for a link under O_NOFOLLOW, ENOTDIR for a file, and every other
            # answer that is not "a real directory of this parent". The category is
            # carried on the exception so the audit can publish it without ever
            # publishing the path an attacker may have chosen.
            unsafe = DirectoryUnsafe(
                "Un composant du chemin du répertoire de reçus est un lien, un fichier "
                "ou un objet ambigu. Aucun renvoi n'est suivi, donc rien n'est lu."
            )
            unsafe.reason = boundary_reason_of(exc)  # type: ignore[attr-defined]
            raise unsafe from exc
        os.close(parent)
        return child

    # -- reading ------------------------------------------------------------
    def listdir(self) -> list[str]:
        return sorted(os.listdir(self.fd))

    def names_ending(self, suffix: str) -> list[str]:
        return [name for name in self.listdir() if name.endswith(suffix)]

    def open_file(self, name: str, *, flags: int, mode: int = 0o600) -> int:
        _check_name(name)
        try:
            return os.open(
                name,
                flags | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
                mode,
                dir_fd=self.fd,
            )
        except FileExistsError:
            raise
        except OSError as exc:
            raise DirectoryUnsafe(
                f"{name} n'est pas un fichier régulier accessible du répertoire de reçus."
            ) from exc

    def read_text(self, name: str) -> str:
        """The text of a regular file of *this* directory, read from the descriptor.

        A link, a dangling link, a directory, a device and a FIFO all fail here
        rather than being read; ``O_NONBLOCK`` means a FIFO cannot even make the
        program wait. The bytes returned are the bytes of the object ``fstat``
        described — there is no second lookup for something else to occupy.
        """
        handle = self.open_file(name, flags=os.O_RDONLY)
        try:
            info = os.fstat(handle)
            if not statmodule.S_ISREG(info.st_mode):
                raise DirectoryUnsafe(
                    f"{name} n'est pas un fichier régulier ; son contenu n'est pas lu."
                )
            chunks: list[bytes] = []
            while chunk := os.read(handle, 65536):
                chunks.append(chunk)
        finally:
            os.close(handle)
        try:
            return b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError as exc:
            # A typed refusal, not a bare `UnicodeDecodeError`: the secret verbs and
            # the audit both read through here, and both used to hand the operator a
            # traceback for a file of arbitrary bytes.
            raise ContentUndecodable(
                f"{name} n'est pas du texte UTF-8 ; son contenu n'est pas interprété."
            ) from exc

    def stat(self, name: str) -> os.stat_result:
        _check_name(name)
        try:
            return os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except OSError as exc:
            raise DirectoryUnsafe(f"{name} n'est pas lisible dans le répertoire de reçus.") from exc

    def exists(self, name: str) -> bool:
        """Whether the name is taken. Only ``ENOENT`` counts as « no ».

        Every other ``errno`` used to answer « absent » here, and ``ensure_secret``
        acts on that answer by *creating* — so a permission or I/O error on the
        secret's name read as « there is no secret yet », which is the one conclusion
        that must never be reached by accident.
        """
        _check_name(name)
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise DirectoryUnsafe(
                f"L'existence de {name} n'a pas pu être établie dans le répertoire de "
                "reçus ; aucune conclusion n'est tirée et rien n'est créé."
            ) from exc
        return True

    # -- writing ------------------------------------------------------------
    def fsync(self) -> None:
        """Make the directory's own entries durable. Failures are reported."""
        try:
            os.fsync(self.fd)
        except OSError as exc:
            raise PersistenceFailed(
                "Le répertoire de reçus n'a pas pu être synchronisé : la publication "
                "n'est pas garantie durable.",
                published=True,
                cleanup_pending=True,
            ) from exc

    def unlink(self, name: str) -> None:
        _check_name(name)
        os.unlink(name, dir_fd=self.fd)

    def rename(self, source: str, destination: str) -> None:
        """Move a name without ever replacing another.

        ``os.rename`` replaces its target silently, which is how a forced quarantine
        collision destroyed the bytes it was supposed to preserve. A hard link
        followed by an unlink refuses instead, and keeps the inode.
        """
        _check_name(source)
        _check_name(destination)
        os.link(source, destination, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
        os.unlink(source, dir_fd=self.fd)

    def publish_bytes(self, name: str, payload: bytes) -> Published:
        """Write ``payload`` and publish it under ``name``, in this exact order.

        1. write every byte to a fresh temporary of this directory;
        2. ``fsync`` the temporary;
        3. publish under the final name with a hard link, which **fails** rather
           than replacing when the name is taken;
        4. ``fsync`` the directory, so the new entry survives;
        5. remove the temporary;
        6. ``fsync`` the directory again, so its removal survives too.

        ``O_CREAT | O_EXCL`` on the final name is atomic about *existence* and says
        nothing about content: v4 published an empty name and filled it afterwards,
        so an interruption in between left a receipt that was not one — and then
        refused the real receipt for ever under "already exists with different signed
        content", which was false.

        No step is suppressed. A failed ``fsync`` used to be swallowed while the
        protocol advertised durability; here it raises, and says whether the proof
        was published before it failed.
        """
        _check_name(name)
        temporary = f".{name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        try:
            handle = self.open_file(
                temporary, flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode=0o600
            )
        except DirectoryUnsafe as exc:
            # `open_file` turns every `OSError` into `DirectoryUnsafe`, so `EACCES`,
            # `EROFS`, `EPERM` and `ENOSPC` at the creation of the temporary left this
            # function through a door the five publication sites did not watch: the
            # `discover` step exited on an uncaught store exception with *nothing* on
            # stdout, which is the very failure v6 said it had closed. Failing to
            # create a temporary is a durability failure, and it is reported as one.
            raise PersistenceFailed(
                "Le temporaire de publication n'a pas pu être créé dans le répertoire "
                "de reçus ; rien n'est publié.",
                published=False,
            ) from exc
        try:
            written = 0
            stalls = 0
            while written < len(payload):
                progress = os.write(handle, payload[written:])
                if progress < 0:  # pragma: no cover - os.write raises instead
                    raise PersistenceFailed("L'écriture du reçu a échoué.")
                if progress == 0:
                    # A regular file never does this. If it ever did, an unguarded
                    # `written += os.write(...)` would spin for ever — a probe of the
                    # fifth audit ran one for six seconds and had to be killed. A few
                    # retries absorb a transient stall; past that it is an error, and
                    # the publication stops rather than hanging.
                    stalls += 1
                    if stalls > MAX_WRITE_STALLS:
                        raise PersistenceFailed(
                            "L'écriture du reçu n'avance plus après "
                            f"{MAX_WRITE_STALLS} tentatives ; la publication est abandonnée."
                        )
                    continue
                stalls = 0
                written += progress
            os.fsync(handle)
        except PersistenceFailed:
            os.close(handle)
            with contextlib.suppress(OSError):
                self.unlink(temporary)
            raise
        except OSError as exc:
            os.close(handle)
            with contextlib.suppress(OSError):
                self.unlink(temporary)
            raise PersistenceFailed(
                f"Les octets du reçu n'ont pas pu être écrits durablement ({exc.errno})."
            ) from exc
        except BaseException:
            os.close(handle)
            with contextlib.suppress(OSError):
                self.unlink(temporary)
            raise
        os.close(handle)

        outcome = "written"
        try:
            os.link(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
        except FileExistsError:
            outcome = "exists"
        except OSError as exc:
            with contextlib.suppress(OSError):
                self.unlink(temporary)
            raise PersistenceFailed(
                f"Le reçu n'a pas pu être publié sous son nom final ({exc.errno})."
            ) from exc

        cleanup_pending = False
        try:
            self.fsync()
        except PersistenceFailed as exc:
            exc.published = outcome == "written"
            with contextlib.suppress(OSError):
                self.unlink(temporary)
            raise
        try:
            self.unlink(temporary)
        except OSError as exc:
            raise PersistenceFailed(
                "Le temporaire du reçu n'a pas pu être supprimé ; la preuve est publiée "
                f"et un fichier temporaire reste à retirer ({exc.errno}).",
                published=outcome == "written",
                cleanup_pending=True,
            ) from exc
        try:
            self.fsync()
        except PersistenceFailed as exc:
            exc.published = outcome == "written"
            exc.cleanup_pending = True
            raise
        return Published(outcome=outcome, cleanup_pending=cleanup_pending)


# ---------------------------------------------------------------------------
# The secret's life cycle, on top of the directory
# ---------------------------------------------------------------------------
#: The one variable that configures a signing secret for this installation. It lives
#: here, next to the file it competes with, because « the environment when it is set,
#: otherwise the file » is one policy and must have one implementation.
SECRET_ENVIRONMENT_VARIABLE = "BETMAXXING_ACTIVATION_RECEIPT_SECRET"


def posix_ownership_available() -> bool:
    """Whether this platform exposes the ownership and permission bits the check needs."""
    return hasattr(os, "getuid")


def _check_secret_privacy(directory: SecureDirectory, name: str) -> None:
    """Refuse a secret anyone else can read. POSIX only, and said as such.

    Not defence against a local adversary who is already root — it is the boundary
    saying what it can see: a key group- or world-readable is not private, and using
    it while claiming the receipts it signs are trustworthy would be a promise this
    program cannot keep. On a platform without POSIX ownership and permission bits,
    this check is skipped and the limit is documented rather than implied away.
    """
    info = directory.stat(name)
    if not statmodule.S_ISREG(info.st_mode):
        raise SecretInvalid(
            "Le secret de signature n'est pas un fichier régulier du répertoire de "
            "reçus ; rien n'est lu et rien n'est remplacé."
        )
    if not posix_ownership_available():
        # A platform without POSIX ownership and permission bits cannot answer the
        # question, so the check is skipped rather than guessed at. Extracted into a
        # function on purpose: a branch excluded from the coverage measurement is a
        # branch nobody has to think about, and this one is a documented limit.
        return
    if info.st_uid != os.getuid():
        raise SecretInvalid(
            "Le secret de signature appartient à un autre compte ; il n'est pas lu. "
            "Aucune valeur n'est affichée."
        )
    if statmodule.S_IMODE(info.st_mode) & 0o077:
        raise SecretInvalid(
            "Le secret de signature accorde un droit au groupe ou à tous ; il n'est "
            "pas lu. Attendu 0600. Aucune valeur n'est affichée et rien n'est corrigé."
        )


def load_secret(directory: SecureDirectory, name: str) -> str:
    """The stored secret, validated. Never created, never repaired."""
    if not directory.exists(name):
        raise SecretMissing(
            "Aucun secret de signature n'est configuré dans le répertoire de reçus."
        )
    _check_secret_privacy(directory, name)
    try:
        text = directory.read_text(name)
    except ContentUndecodable as exc:
        raise SecretInvalid(
            "Le secret de signature n'est pas du texte UTF-8 : ce n'est pas un secret. "
            "Aucune valeur n'est affichée ni corrigée."
        ) from exc
    return validate_secret_text(text)


def injected_secret() -> str | None:
    """The configured secret, or ``None`` when the variable is genuinely absent.

    The one place the environment half of the policy lives. The variable is
    *configuration*, not an argument: no caller chooses a key per call, which is what
    made a hand-minted provenance possible. Present but empty is **invalid**, not
    absent — v6 treated ``""`` as « unset » and went on to read the file, while
    ``"   "`` was refused, so two spellings of « nothing » had two different meanings
    and neither was written down.
    """
    configured = os.environ.get(SECRET_ENVIRONMENT_VARIABLE)
    if configured is None:
        return None
    return validate_secret_text(configured)


def installation_secret(directory: SecureDirectory, name: str) -> str:
    """This installation's secret: the variable when it is set, otherwise the file."""
    configured = injected_secret()
    if configured is not None:
        return configured
    return load_secret(directory, name)


def ensure_secret(directory: SecureDirectory, name: str) -> str:
    """The stored secret, or a new one published atomically.

    An existing secret is validated and returned as it is. An existing *invalid*
    secret is a refusal, deliberately: rewriting it would make every receipt already
    signed with it unverifiable, and silently turning an operator's evidence into
    noise is worse than stopping.
    """
    if directory.exists(name):
        return load_secret(directory, name)
    candidate = new_secret_text()
    try:
        published = directory.publish_bytes(name, candidate.encode("utf-8"))
    except PersistenceFailed:
        raise
    if published.outcome == "exists":
        # Another process won the race. Its value is the one that counts, and both
        # sides end up agreeing on a complete, valid secret.
        return load_secret(directory, name)
    return candidate


# ---------------------------------------------------------------------------
# Attempt intents: the trace that survives a failed publication
# ---------------------------------------------------------------------------
#: Deliberately not ``*.json``: an intent is not a receipt and must never be listed
#: as one, in the audit or anywhere else.
INTENT_SUFFIX = ".intent"
INTENT_VERSION = 1
#: ``fullmatch``, and no ``$``. With ``re.match`` and ``$``, ``"aaaaaaaa\n"`` was a
#: legal identifier — the identical defect this module documents having fixed for
#: :data:`_SECRET_SHAPE`, left in place one screen further down.
_IDENTIFIER = re.compile("[0-9a-f]{8,64}")

#: What an intent may say, and nothing else. A closed set both ways: a missing field
#: and an extra one are equally invalid, because an intent whose shape is negotiable
#: is an intent whose meaning is negotiable.
INTENT_FIELDS = (
    "intent_version",
    "attempt_id",
    "command",
    "sport_key",
    "bookmaker",
    "event_tag",
    "max_credits",
    "state",
    "prepared_at",
)
INTENT_COMMANDS = ("plan", "discover", "core", "additional")
INTENT_STATES = ("PREPARED",)
#: No step of this protocol may commit more than the whole campaign's ceiling.
INTENT_MAX_CREDITS = 16
#: The single label every invalid or unreadable intent is reported under. It replaces
#: the body: the previous version published the file verbatim under
#: ``unresolved_attempt_intent_details``, so a hostile ``command`` and a hostile
#: ``max_credits`` were echoed into the operator's JSON and terminal.
INTENT_INVALID_STATE = "UNREADABLE_OR_INVALID"


class IntentInvalid(StoreRefused):
    """The intent about to be published is not the intent this contract allows."""


def _intent_name(attempt_id: object) -> str:
    if not isinstance(attempt_id, str) or not _IDENTIFIER.fullmatch(attempt_id):
        raise DirectoryUnsafe(
            "Un identifiant de tentative est exactement 8 à 64 caractères hexadécimaux "
            "minuscules, sans espace, sans saut de ligne et sans séparateur."
        )
    return f"{attempt_id}{INTENT_SUFFIX}"


def valid_intent(payload: object, *, attempt_id: str | None = None) -> dict[str, Any] | None:
    """The intent, if it satisfies the contract exactly. Otherwise ``None``.

    Positive and closed: every field present, no field extra, every type and bound
    checked, and — when the name is known — the body's own identifier equal to it. A
    body that disagrees with its filename is two claims about one attempt, and the
    protocol has no rule for choosing between them.
    """
    if not isinstance(payload, Mapping) or set(payload) != set(INTENT_FIELDS):
        return None
    if payload.get("intent_version") != INTENT_VERSION or isinstance(
        payload.get("intent_version"), bool
    ):
        return None
    identifier = payload.get("attempt_id")
    if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
        return None
    if attempt_id is not None and identifier != attempt_id:
        return None
    if payload.get("command") not in INTENT_COMMANDS:
        return None
    if payload.get("state") not in INTENT_STATES:
        return None
    for field in ("sport_key", "bookmaker", "event_tag", "prepared_at"):
        value = payload.get(field)
        if not isinstance(value, str) or "\n" in value or "\x1b" in value or "\x00" in value:
            return None
    ceiling = payload.get("max_credits")
    if isinstance(ceiling, bool) or not isinstance(ceiling, int):
        return None
    if ceiling < 0 or ceiling > INTENT_MAX_CREDITS:
        return None
    try:
        moment = datetime.fromisoformat(str(payload["prepared_at"]))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return dict(payload)


def _intent_bytes(intent: Mapping[str, Any]) -> bytes:
    return (
        jsonlib.dumps(dict(intent), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def publish_intent(directory: SecureDirectory, intent: Mapping[str, Any]) -> str:
    """Record, durably, that a request is about to be issued.

    Called before the socket, ``fsync``-ed before the socket. If the final receipt
    cannot be published afterwards, this file is the only thing left saying that
    something may have gone out and may have been billed — the failure mode that
    made a five-credit call disappear from the record entirely.

    Idempotent **on identical bytes only**. v6 relied on ``publish_bytes`` answering
    ``"exists"``, which says nothing about content: republishing the same
    ``attempt_id`` with a different command, sport, bookmaker, ceiling or tag was
    accepted in silence while the file kept the first scope, and an existing *empty*
    file at the name counted as a successful publication — so the trace meant to
    survive a crash was zero bytes long.
    """
    checked = valid_intent(intent)
    if checked is None:
        raise IntentInvalid(
            "L'intent à publier ne respecte pas son contrat : version, identifiant, "
            "commande, portée, plafond, état et instant sont exigés et bornés. Aucune "
            "valeur n'est reprise dans ce message."
        )
    name = _intent_name(checked["attempt_id"])
    body = _intent_bytes(checked)
    published = directory.publish_bytes(name, body)
    if published.outcome != "exists":
        return name
    try:
        existing = directory.read_text(name).encode("utf-8")
    except StoreRefused as exc:
        raise IntentInvalid(
            "Un objet occupe déjà le nom de cet intent et n'est pas un fichier régulier "
            "lisible du répertoire de reçus. Aucune requête n'est émise."
        ) from exc
    if existing != body:
        raise IntentInvalid(
            "Un intent de même identifiant et de contenu différent existe déjà : deux "
            "tentatives ne partagent pas une identité. Aucune requête n'est émise et "
            "l'intent existant est conservé intact."
        )
    return name


def resolve_intent(directory: SecureDirectory, attempt_id: str) -> bool:
    """Forget an intent whose receipt is durably published. Idempotent."""
    name = _intent_name(attempt_id)
    if not directory.exists(name):
        return False
    directory.unlink(name)
    directory.fsync()
    return True


def unresolved_intents(directory: SecureDirectory) -> list[dict[str, Any]]:
    """Every intent still on disk, sanitised.

    A valid intent is returned as it was written — every value in it was produced by
    this program and checked on the way in. An invalid or unreadable one is reduced to
    its **local name** and :data:`INTENT_INVALID_STATE`: it still blocks, and nothing
    an attacker wrote reaches a report. The local name is the file's own, already
    constrained to hexadecimal by the listing filter below.
    """
    out: list[dict[str, Any]] = []
    for name in sorted(directory.names_ending(INTENT_SUFFIX)):
        stem = name[: -len(INTENT_SUFFIX)]
        safe_stem = stem if _IDENTIFIER.fullmatch(stem) else "(nom illisible)"
        try:
            payload = jsonlib.loads(directory.read_text(name))
        except (StoreRefused, OSError, ValueError):
            out.append({"attempt_id": safe_stem, "state": INTENT_INVALID_STATE})
            continue
        checked = valid_intent(payload, attempt_id=stem if safe_stem == stem else None)
        if checked is None:
            out.append({"attempt_id": safe_stem, "state": INTENT_INVALID_STATE})
        else:
            out.append(checked)
    return out


# ---------------------------------------------------------------------------
# The audit: the only place provenance is minted
# ---------------------------------------------------------------------------
def audit_directory(
    directory: SecureDirectory,
    *,
    secret_name: str,
    signature_field: str,
    accepted_schema_versions: frozenset[int],
    schema_field: str = "schema_version",
) -> AuditResult:
    """Read, check and verify one already-safely-opened directory.

    This is the whole trust boundary in one function, and the only one that can
    produce an :class:`AuditResult`. Note what it does **not** take: a payload, a
    list of receipts, or a secret. A caller cannot choose the evidence and cannot
    choose the key — to obtain admitted provenance it must own a directory this
    module opened component by component, and put correctly signed files in it. That
    is production's path, and it is now also the only path a test has.

    A missing secret and an invalid one both yield « everything unverifiable »: an
    installation with receipts and no usable key reports them as unreadable rather
    than inventing a key that would make them valid.
    """
    try:
        secret = installation_secret(directory, secret_name)
    except (SecretMissing, SecretInvalid):
        payloads, unreadable = _parse_receipts(directory)
        total = len(payloads) + unreadable
        return _mint_result(_mint_batch((), total), BoundaryState.AVAILABLE)

    payloads, unverifiable = _parse_receipts(directory)
    verified: list[VerifiedReceipt] = []
    for payload in payloads:
        version = payload.get(schema_field)
        if isinstance(version, bool) or not isinstance(version, int):
            unverifiable += 1
            continue
        if version not in accepted_schema_versions:
            unverifiable += 1
            continue
        if not verify(payload, secret=secret, signature_field=signature_field):
            unverifiable += 1
            continue
        verified.append(VerifiedReceipt(_PROVENANCE_TOKEN, payload))
    return _mint_result(_mint_batch(tuple(verified), unverifiable), BoundaryState.AVAILABLE)


def audit_unreadable(reason: str) -> AuditResult:
    """The answer when the boundary itself could not be read.

    Empty, and **labelled**. v6 returned the same empty answer a clean installation
    returns, so a receipt directory that had become a symbolic link reported « 0 reçu,
    0 invérifiable » — and the paid commands went on reading it through another door.
    """
    if reason not in BOUNDARY_REASONS or reason in {"", "absent"}:
        reason = "unreadable"
    return _mint_result(_mint_batch((), 0), BoundaryState.UNAVAILABLE, reason)


def audit_absent() -> AuditResult:
    """The answer when there is simply no receipt directory yet."""
    return _mint_result(_mint_batch((), 0), BoundaryState.ABSENT, "absent")


def _parse_receipts(directory: SecureDirectory) -> tuple[list[dict[str, Any]], int]:
    """Every ``*.json`` of the directory that parses, and how many did not.

    The second number matters as much as the first: a link, a dangling link, a
    directory named ``*.json``, a device, a file of arbitrary bytes and a truncated
    file must be **counted** and never read. Dropping them silently would let an
    operator remove the evidence of a problem by making it unreadable.
    """
    out: list[dict[str, Any]] = []
    unreadable = 0
    for name in directory.names_ending(".json"):
        try:
            payload = jsonlib.loads(directory.read_text(name))
        except (StoreRefused, OSError, ValueError):
            unreadable += 1
            continue
        if not isinstance(payload, dict):
            unreadable += 1
            continue
        out.append(payload)
    return out, unreadable


def _mint_batch(receipts: Sequence[VerifiedReceipt], unverifiable: int) -> VerifiedReceiptBatch:
    return VerifiedReceiptBatch(_PROVENANCE_TOKEN, receipts, unverifiable)


def _mint_result(
    batch: VerifiedReceiptBatch, boundary: BoundaryState, reason: str = ""
) -> AuditResult:
    return AuditResult(_PROVENANCE_TOKEN, batch, boundary, reason)
