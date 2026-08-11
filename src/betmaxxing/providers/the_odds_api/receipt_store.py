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

**Provenance is a type.** The evaluator upstairs called itself pure while its call
graph reached the HMAC and, through it, the environment and a file it created.
Verification belongs here; what leaves this module is a
:class:`VerifiedReceipt`, and a plain dictionary can no longer pass for one.

Nothing in this module knows what a receipt *means*. It has no status vocabulary, no
cost model and no criteria: it moves bytes across a boundary and says whether they
crossed it honestly.
"""

from __future__ import annotations

import contextlib
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
    """Something that was never verified was offered as evidence."""


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


def verify(payload: Mapping[str, Any], *, secret: str, signature_field: str) -> bool:
    """Constant-time check. A wrong-shaped secret is a refusal, not a mismatch."""
    given = payload.get(signature_field)
    if not isinstance(given, str) or not given:
        return False
    return hmac.compare_digest(given, sign(payload, secret=secret, signature_field=signature_field))


# ---------------------------------------------------------------------------
# Provenance as a type
# ---------------------------------------------------------------------------
class VerifiedReceipt(Mapping[str, Any]):
    """A receipt whose signature and schema were checked before it got here.

    A read-only :class:`~collections.abc.Mapping`, so every reader that used to take
    a ``dict`` still works — and cannot edit what it was handed. Being a distinct
    type is the point: the evaluator can require provenance instead of assuming it,
    and a plain dictionary read straight off the disk no longer passes for evidence.
    """

    __slots__ = ("_payload",)

    _payload: dict[str, Any]

    def __init__(self, payload: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_payload", dict(payload))

    def __getitem__(self, key: str) -> Any:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"VerifiedReceipt(receipt_id={self._payload.get('receipt_id')!r})"


def trust(
    payload: Mapping[str, Any], *, secret: str, signature_field: str = "signature"
) -> VerifiedReceipt:
    """Verify one payload and wrap it. The only honest way to mint provenance."""
    if not verify(payload, secret=secret, signature_field=signature_field):
        raise UnverifiedProvenance(
            "Ce reçu n'est pas signé par le secret local : il n'entre pas dans la preuve."
        )
    return VerifiedReceipt(payload)


class VerifiedReceiptBatch(Sequence[VerifiedReceipt]):
    """Every receipt this installation could verify, and how many it could not."""

    __slots__ = ("_receipts", "unverifiable")

    _receipts: tuple[VerifiedReceipt, ...]
    unverifiable: int

    def __init__(self, receipts: Sequence[VerifiedReceipt], unverifiable: int) -> None:
        for receipt in receipts:
            if not isinstance(receipt, VerifiedReceipt):
                raise UnverifiedProvenance(
                    "Un lot de reçus vérifiés ne contient que des reçus vérifiés."
                )
        object.__setattr__(self, "_receipts", tuple(receipts))
        object.__setattr__(self, "unverifiable", int(unverifiable))

    def __getitem__(self, index: Any) -> Any:
        return self._receipts[index]

    def __len__(self) -> int:
        return len(self._receipts)


def require_verified(receipts: object) -> tuple[VerifiedReceipt, ...]:
    """The receipts, if their provenance is beyond doubt. Otherwise a refusal.

    Passing raw mappings used to work, which is why nothing noticed that the
    evaluator was verifying them itself — inside a function documented as pure.
    """
    if isinstance(receipts, VerifiedReceiptBatch):
        return tuple(receipts)
    if isinstance(receipts, (str, bytes, Mapping)) or not isinstance(receipts, Sequence):
        raise UnverifiedProvenance(
            "Une évaluation prend un lot de reçus vérifiés, pas une valeur brute."
        )
    out = []
    for receipt in receipts:
        if not isinstance(receipt, VerifiedReceipt):
            raise UnverifiedProvenance(
                "Un reçu non vérifié a été proposé comme preuve. La vérification de "
                "signature appartient à l'audit, pas à l'évaluateur."
            )
        out.append(receipt)
    return tuple(out)


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
                raise DirectoryUnsafe(
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
            # answer that is not "a real directory of this parent".
            raise DirectoryUnsafe(
                "Un composant du chemin du répertoire de reçus est un lien, un fichier "
                "ou un objet ambigu. Aucun renvoi n'est suivi, donc rien n'est lu."
            ) from exc
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
        return b"".join(chunks).decode("utf-8")

    def stat(self, name: str) -> os.stat_result:
        _check_name(name)
        try:
            return os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except OSError as exc:
            raise DirectoryUnsafe(f"{name} n'est pas lisible dans le répertoire de reçus.") from exc

    def exists(self, name: str) -> bool:
        _check_name(name)
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except OSError:
            return False
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
        handle = self.open_file(temporary, flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode=0o600)
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
def load_secret(directory: SecureDirectory, name: str) -> str:
    """The stored secret, validated. Never created, never repaired."""
    if not directory.exists(name):
        raise SecretMissing(
            "Aucun secret de signature n'est configuré dans le répertoire de reçus."
        )
    return validate_secret_text(directory.read_text(name))


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
_IDENTIFIER = re.compile("^[0-9a-f]{8,64}$")


def _intent_name(attempt_id: object) -> str:
    if not isinstance(attempt_id, str) or not _IDENTIFIER.match(attempt_id):
        raise DirectoryUnsafe("Un identifiant de tentative est hexadécimal.")
    return f"{attempt_id}{INTENT_SUFFIX}"


def publish_intent(directory: SecureDirectory, intent: Mapping[str, Any]) -> str:
    """Record, durably, that a request is about to be issued.

    Called before the socket, ``fsync``-ed before the socket. If the final receipt
    cannot be published afterwards, this file is the only thing left saying that
    something may have gone out and may have been billed — the failure mode that
    made a five-credit call disappear from the record entirely.

    Idempotent: publishing the same intent twice leaves one file.
    """
    name = _intent_name(intent.get("attempt_id"))
    body = jsonlib.dumps(dict(intent), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    directory.publish_bytes(name, body.encode("utf-8"))
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
    """Every intent still on disk, as it was written. Unreadable ones are named."""
    out: list[dict[str, Any]] = []
    for name in directory.names_ending(INTENT_SUFFIX):
        try:
            payload = jsonlib.loads(directory.read_text(name))
        except (StoreRefused, OSError, ValueError):
            out.append({"attempt_id": name[: -len(INTENT_SUFFIX)], "state": "UNREADABLE"})
            continue
        if isinstance(payload, Mapping):
            out.append(dict(payload))
        else:
            out.append({"attempt_id": name[: -len(INTENT_SUFFIX)], "state": "UNREADABLE"})
    return out
