"""One real audit boundary for the suites that need verified receipts.

Why this helper exists
----------------------
Until protocol 7, a qualification suite that needed a verified receipt built one
by calling the provenance type's constructor, or ``trust(payload, secret=…)``.
The sixth re-audit showed why that is not a test of anything: the same two calls
are available to any caller, so a corpus nobody signed reached the human-review
gate. Removing the public constructor removes the shortcut from the suites too —
deliberately. A suite that wants verified receipts now does what production does:
it writes signed files into a throwaway directory that holds a synthetic secret,
and asks the audit to read them.

Everything here is synthetic: the secret is a fixed test value, the directory is
a fresh ``tmp_path``, and no receipt, key or payload of a real installation is
ever read.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from betmaxxing.providers.the_odds_api import activation as act


def _plain(value: Any) -> Any:
    """Recursively convert sealed containers back to what ``json`` accepts.

    A receipt that has already been through an audit holds sealed containers, so a
    round trip through the boundary needs a conversion, and a shallow ``dict(receipt)``
    from a caller leaves the nested ones sealed. This is written generically — any
    ``Mapping``, any non-``str`` ``Sequence`` — rather than by calling the store's own
    private converter, so that these suites run unchanged against the parent commit and
    fail there for their own reasons instead of failing to set up.
    """
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (str, bytes, bytearray)):
        return value
    if isinstance(value, Sequence):
        return [_plain(item) for item in value]
    return value


def write_receipt_files(
    directory: Path, receipts: list[dict[str, Any]], *, secret: str, unreadable: int = 0
) -> Path:
    """Write ``receipts`` as the audit will find them, plus the local secret.

    ``unreadable`` adds that many files the audit must count and refuse to read —
    the honest way to ask for a non-zero ``unverifiable`` count, instead of
    handing the evaluator a number nothing produced.
    """
    directory.mkdir(parents=True, exist_ok=True)
    receipts = [_plain(document) for document in receipts]
    for index, document in enumerate(receipts):
        stamp = f"20260901T{index // 60:02d}{index % 60:02d}00"
        command = document.get("command", "x")
        name = f"{stamp}-{command}-corpus{index:03d}.json"
        (directory / name).write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    for index in range(unreadable):
        (directory / f"20260901T000000-core-unreadable{index:03d}.json").write_text(
            "{ this is not json", encoding="utf-8"
        )
    install_secret(directory, secret)
    return directory


def install_secret(directory: Path, secret: str) -> Path:
    """Write the local signing secret with the permissions the boundary wants."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / act.SECRET_FILENAME
    path.write_text(secret, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def audit_in(directory: Path, monkeypatch: Any) -> Any:
    """Point the harness at ``directory`` and run the real audit."""
    monkeypatch.setenv(act.RECEIPT_DIR_VARIABLE, str(directory))
    monkeypatch.delenv(act.SECRET_VARIABLE, raising=False)
    return act.audit_receipts()


def audited_corpus(
    directory: Path,
    receipts: list[dict[str, Any]],
    *,
    secret: str,
    monkeypatch: Any,
    unreadable: int = 0,
) -> Any:
    """Write, then audit. The only route these suites have to a verified receipt."""
    write_receipt_files(directory, receipts, secret=secret, unreadable=unreadable)
    return audit_in(directory, monkeypatch)


def audited(receipts: Any, unverifiable: int = 0, *, secret: str) -> Any:
    """One audit of a throwaway directory holding exactly these receipts.

    The migration of the five qualification suites, in one function. Each of them used
    to obtain provenance with ``VerifiedReceiptBatch(tuple(trust(r, secret=…)))`` — two
    calls that no longer exist, because both of them were available to any caller and
    that is precisely how a forged corpus reached the gate. The suites keep every
    assertion they had; only the way they acquire evidence changes, and it changes to
    the way production acquires it: signed files in a directory, read by the audit.

    ``unverifiable`` is honoured by writing that many files the audit must refuse to
    read, rather than by asserting a number nothing produced.

    No fixture is available at this depth, so the receipt-directory variable is set and
    restored around the single call. Nothing else in the environment is touched.

    **Throwaway means thrown away.** The directory used to be created with
    ``tempfile.mkdtemp`` and never removed, so every run of the five qualification suites
    left one directory per call in the system temporary area — each holding a synthetic
    signing key and a synthetic corpus, accumulating without bound on a long-lived
    runner. The quinquies re-audit counted 143 182 of them. Creation, audit and removal
    are now one cycle: the ``finally`` runs after a success, after an exception raised
    while writing the corpus, and after an audit the boundary refuses. Only the path
    this call created is ever removed, and the audit result it returns is untouched —
    every receipt it carries was read into memory before the directory went away.
    """
    import os
    import shutil
    import tempfile

    directory = Path(tempfile.mkdtemp(prefix="audited-"))
    previous = os.environ.get(act.RECEIPT_DIR_VARIABLE)
    try:
        write_receipt_files(directory, list(receipts), secret=secret, unreadable=unverifiable)
        os.environ[act.RECEIPT_DIR_VARIABLE] = str(directory)
        return act.audit_receipts()
    finally:
        if previous is None:
            os.environ.pop(act.RECEIPT_DIR_VARIABLE, None)
        else:
            os.environ[act.RECEIPT_DIR_VARIABLE] = previous
        # `ignore_errors` covers the one benign case: a test that removed the directory
        # itself. It cannot widen what is removed — `directory` is the exact path this
        # call created, and nothing else is ever passed here.
        shutil.rmtree(directory, ignore_errors=True)
