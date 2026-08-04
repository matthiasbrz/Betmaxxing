"""Bookmaker margin removal (de-vigging).

Comparing a model probability against ``1/o`` is comparing against a number that
includes the bookmaker's margin — it systematically understates the model's edge
in the book's favour. The engine therefore always computes both:

* ``p_raw = 1/o``          — kept for transparency, never used as "the market";
* ``p_novig``              — margin removed with an explicit, configurable method.

Four methods are implemented. They differ in *where* they assume the margin sits:

``multiplicative``
    Margin proportional to each raw probability. Simple, but known to overstate
    favourite probabilities (the favourite-longshot bias is left untouched).
``additive``
    Margin split equally in probability space. Can produce negative values on
    very lopsided books, so it is rejected rather than clamped.
``power``
    ``p_i = r_i ** k``. Compresses longshots more than favourites.
``shin``
    Shin's insider-trading model. Estimates a fraction ``z`` of informed money
    and removes it. Usually the best-behaved on 2- and 3-outcome books, and the
    project default.

Every function takes and returns plain floats so the module stays trivially
testable and free of domain imports.
"""

from __future__ import annotations

from betmaxxing.config import DevigMethod

#: Books whose overround sits outside this band are treated as unusable.
MIN_PLAUSIBLE_OVERROUND = 0.95
MAX_PLAUSIBLE_OVERROUND = 1.60

_TOL = 1e-12
_MAX_ITER = 200


class DevigError(ValueError):
    """Raised when a book cannot be de-vigged in a defensible way."""


def raw_implied(odds: list[float]) -> list[float]:
    """``1/o`` for each price. Includes the margin."""
    if not odds:
        raise DevigError("empty book")
    for o in odds:
        if o <= 1.0:
            raise DevigError(f"decimal odds must be > 1.0, got {o}")
    return [1.0 / o for o in odds]


def overround(odds: list[float]) -> float:
    """Sum of raw implied probabilities. 1.05 means a 5% book."""
    return sum(raw_implied(odds))


def _check_book(odds: list[float]) -> list[float]:
    if len(odds) < 2:
        raise DevigError("a book needs at least two outcomes to be de-vigged")
    raw = raw_implied(odds)
    total = sum(raw)
    if not (MIN_PLAUSIBLE_OVERROUND <= total <= MAX_PLAUSIBLE_OVERROUND):
        raise DevigError(f"implausible overround {total:.4f} — book rejected")
    return raw


def devig_multiplicative(odds: list[float]) -> list[float]:
    raw = _check_book(odds)
    total = sum(raw)
    return [r / total for r in raw]


def devig_additive(odds: list[float]) -> list[float]:
    raw = _check_book(odds)
    total = sum(raw)
    excess = (total - 1.0) / len(raw)
    out = [r - excess for r in raw]
    if any(p <= 0.0 for p in out):
        raise DevigError("additive de-vig produced a non-positive probability")
    return out


def devig_power(odds: list[float]) -> list[float]:
    """Solve ``sum(r_i ** k) == 1`` for ``k``.

    Each ``r_i`` is in ``(0, 1)``, so ``r_i ** k`` decreases as ``k`` grows: the
    sum is monotonically decreasing in ``k`` and a bisection is exact enough.
    """
    raw = _check_book(odds)
    total = sum(raw)
    if abs(total - 1.0) < _TOL:
        return list(raw)

    def _sum_at(k: float) -> float:
        return sum(r**k for r in raw)

    lo, hi = (1.0, 64.0) if total > 1.0 else (1e-6, 1.0)
    # Guard: widen once if the bracket does not contain the root.
    if (_sum_at(lo) - 1.0) * (_sum_at(hi) - 1.0) > 0:
        raise DevigError("power de-vig could not bracket a solution")
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        value = _sum_at(mid) - 1.0
        if abs(value) < _TOL:
            break
        if value > 0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2.0
    out = [r**k for r in raw]
    scale = sum(out)
    return [p / scale for p in out]


def devig_shin(odds: list[float]) -> list[float]:
    """Shin's model.

    With ``r_i = 1/o_i`` and ``S = sum(r_i)``::

        p_i(z) = ( sqrt( z**2 + 4*(1-z)*r_i**2 / S ) - z ) / ( 2*(1-z) )

    ``sum(p_i(z))`` decreases monotonically in ``z``, so ``z`` is found by
    bisection on ``[0, 1)``. At ``z = 0`` the sum is ``sqrt(S) >= 1`` for any
    book carrying margin. A book with no margin (``S <= 1``) has no insider
    fraction to remove, so it falls back to proportional normalisation.
    """
    raw = _check_book(odds)
    total = sum(raw)
    if total <= 1.0 + _TOL:
        return [r / total for r in raw]

    def _probs_at(z: float) -> list[float]:
        return [
            ((z * z + 4.0 * (1.0 - z) * r * r / total) ** 0.5 - z) / (2.0 * (1.0 - z)) for r in raw
        ]

    lo, hi = 0.0, 0.999999
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        value = sum(_probs_at(mid)) - 1.0
        if abs(value) < _TOL:
            break
        if value > 0:
            lo = mid
        else:
            hi = mid
    z = (lo + hi) / 2.0
    out = _probs_at(z)
    scale = sum(out)
    return [p / scale for p in out]


_METHODS = {
    DevigMethod.MULTIPLICATIVE: devig_multiplicative,
    DevigMethod.ADDITIVE: devig_additive,
    DevigMethod.POWER: devig_power,
    DevigMethod.SHIN: devig_shin,
}


def devig(odds: list[float], method: DevigMethod | str) -> list[float]:
    """De-vig a complete book with the named method.

    Raises :class:`DevigError` when the book is incomplete, implausible, or the
    method cannot produce a valid distribution — the caller turns that into a
    ``MARKET_INCOMPLETE`` rejection rather than falling back silently.
    """
    key = DevigMethod(method)
    fn = _METHODS.get(key)
    if fn is None:  # pragma: no cover - DevigMethod is exhaustive
        raise DevigError(f"unknown de-vig method {method!r}")
    probs = fn(odds)
    if any(p <= 0.0 or p >= 1.0 for p in probs):
        raise DevigError("de-vig produced a probability outside (0, 1)")
    if abs(sum(probs) - 1.0) > 1e-9:
        raise DevigError("de-vigged probabilities do not sum to 1")
    return probs


def shin_z(odds: list[float]) -> float:
    """The estimated insider fraction ``z`` for a book. Diagnostic only."""
    raw = _check_book(odds)
    total = sum(raw)
    if total <= 1.0 + _TOL:
        return 0.0
    lo, hi = 0.0, 0.999999
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        probs = [
            ((mid * mid + 4.0 * (1.0 - mid) * r * r / total) ** 0.5 - mid) / (2.0 * (1.0 - mid))
            for r in raw
        ]
        value = sum(probs) - 1.0
        if abs(value) < _TOL:
            return mid
        if value > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
