"""Refuse a populated secret variable in a tracked file.

Why this exists
---------------
A provider key was committed to ``.env.example`` — a *tracked* file, and the
template every clone copies — and the history had to be rewritten to remove it.
The detection was never the missing piece: CI already refused that file and went
red four seconds after the push. What was missing was a check that runs *before*
a commit exists, one implementation shared by every caller, and a failure
message that says what is wrong without repeating the secret.

The rule, in two parts
----------------------
An environment file (``.env``, ``.env.example``, ``.env.local``, …) may name a
secret variable but must never give it a value. That file format exists to be
copied, so a value in it is a value handed to everyone.

Every other tracked file — prose, tests, scripts — may show a *placeholder*,
because documentation that cannot show the shape of a setting is documentation
nobody follows. What it may not contain is something shaped like a real
credential. The credential shape used here is a bare run of hexadecimal
characters, which is what this project's provider keys and receipt secrets look
like, and which no placeholder in this repository resembles.

Deliberately not a general secret scanner: it knows this project's variables and
this project's credential shape. ``.github/workflows/ci.yml`` keeps the broad,
vendor-prefix patterns (``sk-``, ``AKIA``, ``ghp_``, PEM blocks) for everything
else. The two are complementary and must never be made to overlap, because two
scanners with two opinions produce an argument instead of a verdict.

Never handled here
------------------
No value is read, returned, logged, measured, hashed or compared against a known
value. A finding carries a path, a line number, a variable name and a reason.
That is enough to fix the problem and not enough to leak it, which is the whole
design constraint: a guard whose failure output must itself be redacted has
simply moved the leak.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

#: Every variable this project uses to carry a credential. Adding a secret
#: setting means adding it here; the test suite pins the list against
#: ``.env.example`` so the two cannot drift apart silently.
SECRET_VARIABLES: tuple[str, ...] = (
    "BETMAXXING_THE_ODDS_API_KEY",
    "BETMAXXING_ODDS_API_KEY",
    "BETMAXXING_SPORTSDATA_API_KEY",
    "BETMAXXING_ACTIVATION_RECEIPT_SECRET",
    "BETMAXXING_TELEGRAM_BOT_TOKEN",
    "BETMAXXING_SMTP_PASSWORD",
    "BETMAXXING_API_TOKEN",
    "ANTHROPIC_API_KEY",
)

#: Optional indentation, an optional ``export``, the variable name, optional
#: blanks around ``=``, then the value. Case-insensitive and anchored at the
#: start of the line, so a commented line (``#  export NAME=…``) does not match:
#: a comment is prose about an assignment, not an assignment.
ASSIGNMENT = re.compile(
    r"^[ \t]*(?:export[ \t]+)?(?P<name>"
    + "|".join(re.escape(name) for name in SECRET_VARIABLES)
    + r")[ \t]*=(?P<value>.*)$",
    re.IGNORECASE,
)

#: What a credential looks like in this project: a bare hexadecimal run. The
#: provider key is 32 hex characters and the receipt secret is longer; every
#: placeholder in the documentation contains something hex cannot contain.
CREDENTIAL_SHAPE = re.compile(r"^[0-9a-fA-F]{16,}$")

IN_ENVIRONMENT_FILE = "an environment file must name the variable and leave it empty"
LOOKS_LIKE_A_CREDENTIAL = "the value has the shape of a real credential"

_REMEDIATION = (
    "Put real values in `.env` (git-ignored) or a secret manager, never in a "
    "tracked file. If a value was already committed, emptying it is not enough: "
    "it stays reachable in the history, so rotate it at the provider."
)


@dataclass(frozen=True)
class Finding:
    """A located violation. Carries no part of the offending value."""

    path: str
    line: int
    variable: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.variable} — {self.reason}"


def is_environment_file(path: str | Path) -> bool:
    """True for ``.env`` and its variants, whatever directory they sit in."""
    name = Path(path).name
    return name == ".env" or name.startswith(".env")


def value_is_present(raw: str) -> bool:
    """True when the right-hand side carries something rather than nothing.

    Quoting does not launder a value: ``NAME=""`` assigns nothing while
    ``NAME="x"`` assigns something. Surrounding blanks and any nesting of
    matching quotes are stripped first, so neither spacing nor quoting can slip
    a value past the check.
    """
    text = raw.strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    return bool(text)


def looks_like_a_credential(raw: str) -> bool:
    """True when the value could be a real credential rather than a placeholder."""
    text = raw.strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    return bool(CREDENTIAL_SHAPE.match(text))


def scan_text(text: str, *, path: str = "<text>") -> list[Finding]:
    """Return every violation in ``text``, judged by ``path``'s file kind."""
    strict = is_environment_file(path)
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = ASSIGNMENT.match(line)
        if match is None:
            continue
        value = match.group("value")
        if not value_is_present(value):
            continue
        if strict:
            reason = IN_ENVIRONMENT_FILE
        elif looks_like_a_credential(value):
            reason = LOOKS_LIKE_A_CREDENTIAL
        else:
            # A placeholder in prose. Allowed on purpose.
            continue
        findings.append(
            Finding(
                path=path,
                line=number,
                variable=match.group("name").upper(),
                reason=reason,
            )
        )
    return findings


def scan_paths(paths: Iterable[str | Path]) -> list[Finding]:
    """Scan files on disk, skipping anything unreadable or not a file."""
    findings: list[Finding] = []
    for path in paths:
        candidate = Path(path)
        if not candidate.is_file():
            continue
        try:
            payload = candidate.read_bytes()
        except OSError:
            continue
        text = payload.decode("utf-8", errors="replace")
        findings.extend(scan_text(text, path=str(path)))
    return findings


def tracked_files(root: str | Path = ".") -> list[str]:
    """Every file Git tracks, which is exactly the set that can be published."""
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [name for name in completed.stdout.decode("utf-8").split("\0") if name]


def main(argv: Sequence[str] | None = None) -> int:
    """Scan the given paths, or every tracked file when given none."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    paths: Sequence[str | Path] = arguments or tracked_files()
    findings = scan_paths(paths)
    for finding in findings:
        print(str(finding))
    if findings:
        print(f"\n{len(findings)} populated secret variable(s) in tracked files.")
        print(_REMEDIATION)
        return 1
    print(f"ok — no populated secret variable in {len(list(paths))} file(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
