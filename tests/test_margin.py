"""De-vigging. Every method must return a genuine probability distribution, and
must refuse rather than guess when the book is unusable."""

from __future__ import annotations

import pytest

from betmaxxing.config import DevigMethod
from betmaxxing.engine.margin import (
    DevigError,
    devig,
    devig_additive,
    devig_multiplicative,
    devig_power,
    devig_shin,
    overround,
    raw_implied,
    shin_z,
)

#: A realistic 1X2 book carrying ~5% margin.
BOOK_1X2 = [1.63, 4.20, 5.00]
#: A two-way book.
BOOK_2WAY = [1.76, 2.07]

ALL_METHODS = [
    DevigMethod.MULTIPLICATIVE,
    DevigMethod.ADDITIVE,
    DevigMethod.POWER,
    DevigMethod.SHIN,
]


class TestRawImplied:
    def test_sums_above_one_for_a_margined_book(self) -> None:
        assert overround(BOOK_1X2) > 1.0

    def test_rejects_invalid_odds(self) -> None:
        with pytest.raises(DevigError):
            raw_implied([1.0, 2.0])
        with pytest.raises(DevigError):
            raw_implied([])


@pytest.mark.parametrize("method", ALL_METHODS)
class TestEveryMethod:
    def test_returns_a_normalised_distribution(self, method: DevigMethod) -> None:
        probs = devig(BOOK_1X2, method)
        assert sum(probs) == pytest.approx(1.0, abs=1e-9)
        assert all(0.0 < p < 1.0 for p in probs)

    def test_works_on_two_way_books(self, method: DevigMethod) -> None:
        probs = devig(BOOK_2WAY, method)
        assert sum(probs) == pytest.approx(1.0, abs=1e-9)

    def test_preserves_the_favourite_ordering(self, method: DevigMethod) -> None:
        probs = devig(BOOK_1X2, method)
        assert probs[0] > probs[1] > probs[2]

    def test_every_novig_probability_is_below_its_raw_value(self, method: DevigMethod) -> None:
        # Removing margin can only reduce probabilities on a margined book.
        raw = raw_implied(BOOK_1X2)
        probs = devig(BOOK_1X2, method)
        assert all(p < r for p, r in zip(probs, raw, strict=True))

    def test_rejects_an_incomplete_book(self, method: DevigMethod) -> None:
        with pytest.raises(DevigError):
            devig([2.0], method)


class TestMultiplicative:
    def test_scales_proportionally(self) -> None:
        probs = devig_multiplicative(BOOK_1X2)
        raw = raw_implied(BOOK_1X2)
        total = sum(raw)
        assert probs == pytest.approx([r / total for r in raw])


class TestAdditive:
    def test_removes_an_equal_share_from_each_outcome(self) -> None:
        probs = devig_additive(BOOK_1X2)
        raw = raw_implied(BOOK_1X2)
        deltas = [r - p for r, p in zip(raw, probs, strict=True)]
        assert deltas[0] == pytest.approx(deltas[1]) == pytest.approx(deltas[2])

    def test_refuses_rather_than_clamping_a_negative_result(self) -> None:
        """The equal split is what makes this method fragile.

        On a three-way book with a genuine longshot at 50.0, an equal share of a
        12% overround (0.04) exceeds the longshot's raw probability (0.02), so the
        result would be negative. That must raise rather than be clamped to ~0 —
        a clamped zero would silently become an infinitely valuable bet.
        """
        with pytest.raises(DevigError, match="non-positive"):
            devig_additive([1.43, 2.50, 50.0])


class TestPower:
    def test_solves_the_exponent_correctly(self) -> None:
        probs = devig_power(BOOK_1X2)
        assert sum(probs) == pytest.approx(1.0, abs=1e-9)

    def test_compresses_longshots_more_than_multiplicative(self) -> None:
        power = devig_power(BOOK_1X2)
        multiplicative = devig_multiplicative(BOOK_1X2)
        # The longshot keeps less probability under the power method.
        assert power[-1] < multiplicative[-1]


class TestShin:
    def test_returns_a_valid_distribution(self) -> None:
        probs = devig_shin(BOOK_1X2)
        assert sum(probs) == pytest.approx(1.0, abs=1e-9)

    def test_estimated_insider_fraction_is_in_range(self) -> None:
        z = shin_z(BOOK_1X2)
        assert 0.0 <= z < 1.0

    def test_insider_fraction_is_zero_for_a_marginless_book(self) -> None:
        fair = [3.0, 3.0, 3.0]
        assert shin_z(fair) == pytest.approx(0.0)

    def test_falls_back_to_proportional_when_there_is_no_margin(self) -> None:
        fair = [3.0, 3.0, 3.0]
        assert devig_shin(fair) == pytest.approx([1 / 3, 1 / 3, 1 / 3])


class TestPlausibilityGuards:
    def test_rejects_an_absurdly_high_overround(self) -> None:
        with pytest.raises(DevigError, match="implausible overround"):
            devig([1.2, 1.2, 1.2], DevigMethod.SHIN)

    def test_rejects_an_arbitrage_shaped_book(self) -> None:
        with pytest.raises(DevigError, match="implausible overround"):
            devig([5.0, 5.0, 5.0], DevigMethod.SHIN)

    def test_unknown_method_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            devig(BOOK_1X2, "not-a-method")


class TestMethodsDisagree:
    def test_methods_produce_different_answers_on_a_lopsided_book(self) -> None:
        """The choice of method is a real modelling decision, not cosmetic.

        This is why the method is configurable, recorded on every candidate and
        included in the config fingerprint.
        """
        lopsided = [1.20, 6.50, 11.0]
        results = {m: devig(lopsided, m)[0] for m in ALL_METHODS}
        assert max(results.values()) - min(results.values()) > 0.005
