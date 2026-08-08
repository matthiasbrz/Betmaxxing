"""Repository-level safety checks that are not application logic.

These live inside the package, rather than in a loose script, so that the same
code runs from the test suite, from CI and from a pre-commit hook. One
implementation, one verdict: a guard that disagrees with itself depending on
which entry point invoked it is not a guard.

Nothing is re-exported here on purpose. ``secret_hygiene`` is executable with
``python -m betmaxxing.security.secret_hygiene``, and importing it from this
file would make ``runpy`` warn that the module was already in ``sys.modules``
before it ran — a warning that becomes an error under ``-W error``.
"""

from __future__ import annotations
