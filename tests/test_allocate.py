"""Splitting an amount by weights at the currency's minor unit (attribution.types.allocate).

Rule (PRD section 6: "assign any rounding remainder deterministically so totals reconcile"):
compute each exact share, round every share down to the minor unit, then hand the leftover
minor units one at a time to the largest remainders; equal remainders go to the earlier
position (journey order). Hand calculations are in each test.
"""

from decimal import Decimal

import pytest

from attribution.types import allocate


def test_even_split_with_remainder_goes_to_earliest():
    # 100.00 / 3 = 33.333...: floor 33.33 each = 99.99, 1 cent left; remainders tie -> first.
    assert allocate(Decimal("100.00"), [1, 1, 1], 2) == [
        Decimal("33.34"),
        Decimal("33.33"),
        Decimal("33.33"),
    ]


def test_zero_decimal_currency():
    # 1,200,000 JPY / 7 = 171428.571...: floor 171428 x 7 = 1,199,996, 4 yen to the first 4.
    shares = allocate(Decimal("1200000"), [1] * 7, 0)
    assert shares == [Decimal("171429")] * 4 + [Decimal("171428")] * 3
    assert sum(shares) == Decimal("1200000")


def test_largest_remainder_wins_over_position():
    # 10.00 split 0.4 / 0.2 / 0.4 of 3 touches is exact; 10.01 is not:
    # 4.004, 2.002, 4.004 -> floors 4.00, 2.00, 4.00 = 10.00; 1 cent left.
    # Remainders 0.004, 0.002, 0.004: tie between 1st and 3rd -> 1st.
    assert allocate(Decimal("10.01"), [Decimal("0.4"), Decimal("0.2"), Decimal("0.4")], 2) == [
        Decimal("4.01"),
        Decimal("2.00"),
        Decimal("4.00"),
    ]
    # 0.07 split 1:2 -> 0.02333, 0.04666 -> floors 0.02, 0.04; 1 cent to the larger remainder.
    assert allocate(Decimal("0.07"), [1, 2], 2) == [Decimal("0.02"), Decimal("0.05")]


def test_zero_weight_gets_nothing_and_amount_reconciles():
    assert allocate(Decimal("5.00"), [0, 1], 2) == [Decimal("0.00"), Decimal("5.00")]


def test_zero_amount():
    assert allocate(Decimal("0.00"), [1, 1], 2) == [Decimal("0.00"), Decimal("0.00")]


def test_needs_a_positive_weight():
    with pytest.raises(ValueError):
        allocate(Decimal("1.00"), [0, 0], 2)
