"""Deterministic opportunity journeys (attribution/journey.py), written before the code.

Hand calculation for CONVERSION below (first-touch, 90-day lookback, both ends inclusive):

    conversion  2026-04-01 12:00 UTC  ->  window opens 2026-01-01 12:00 UTC
    t-before    2025-12-31 12:00   before the window            no credit
    t-edge      2026-01-01 12:00   eligible (exactly at start)  1,000.00 (earliest eligible)
    t-a         2026-02-01 09:00   eligible                     0  (ties with t-b; a < b)
    t-b         2026-02-01 09:00   eligible                     0
    t-end       2026-04-01 12:00   eligible (exactly at end)    0
    t-after     2026-04-01 12:00:01 after the conversion        no credit
    total credited 1,000.00 = amount; Unattributed 0.
"""

import itertools
from datetime import UTC, datetime
from decimal import Decimal

from attribution import Conversion, FirstTouch, Touchpoint
from attribution.journey import Eligibility, build_journey


def t(tp_id, *when, source="google"):
    return Touchpoint(id=tp_id, occurred_at=datetime(*when, tzinfo=UTC), source=source)


TOUCHES = (
    t("t-b", 2026, 2, 1, 9),
    t("t-after", 2026, 4, 1, 12, 0, 1),
    t("t-edge", 2026, 1, 1, 12),
    t("t-before", 2025, 12, 31, 12),
    t("t-end", 2026, 4, 1, 12),
    t("t-a", 2026, 2, 1, 9),
)
CONVERSION = Conversion(
    opportunity_id="opp-1",
    amount=Decimal("1000.00"),
    currency="USD",
    converted_at=datetime(2026, 4, 1, 12, tzinfo=UTC),
    touchpoints=TOUCHES,
)


def summary(journey):
    return [(s.touchpoint.id, s.eligibility, s.credit) for s in journey.steps]


def test_journey_orders_every_touch_and_explains_eligibility():
    journey = build_journey(CONVERSION, FirstTouch())
    E = Eligibility
    assert summary(journey) == [
        ("t-before", E.BEFORE_WINDOW, None),
        ("t-edge", E.ELIGIBLE, Decimal("1000.00")),
        ("t-a", E.ELIGIBLE, Decimal("0")),
        ("t-b", E.ELIGIBLE, Decimal("0")),
        ("t-end", E.ELIGIBLE, Decimal("0")),
        ("t-after", E.AFTER_CONVERSION, None),
    ]
    assert [s.position for s in journey.steps] == [1, 2, 3, 4, 5, 6]
    assert journey.window_start == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert (journey.model_name, journey.lookback_days) == ("First-touch", 90)
    assert journey.unattributed == Decimal("0")


def test_journey_credits_reconcile_to_the_amount():
    journey = build_journey(CONVERSION, FirstTouch())
    credited = sum(s.credit for s in journey.steps if s.credit) + journey.unattributed
    assert credited == CONVERSION.amount


def test_journey_is_the_same_for_every_input_order():
    expected = summary(build_journey(CONVERSION, FirstTouch()))
    for order in itertools.permutations(TOUCHES):
        shuffled = Conversion(**{**CONVERSION.__dict__, "touchpoints": order})
        assert summary(build_journey(shuffled, FirstTouch())) == expected


def test_no_eligible_touch_means_the_whole_amount_is_unattributed():
    only_late = Conversion(**{**CONVERSION.__dict__, "touchpoints": (TOUCHES[1],)})
    journey = build_journey(only_late, FirstTouch())
    assert summary(journey) == [("t-after", Eligibility.AFTER_CONVERSION, None)]
    assert journey.unattributed == Decimal("1000.00")
    assert journey.credited_step is None


def test_shorter_lookback_moves_the_window():
    # 30 days back from 04-01 12:00 is 03-02 12:00: only t-end is eligible, so it gets the credit.
    journey = build_journey(CONVERSION, FirstTouch(lookback_days=30))
    assert journey.credited_step.touchpoint.id == "t-end"
    assert journey.window_start == datetime(2026, 3, 2, 12, tzinfo=UTC)


def test_same_id_and_time_keeps_input_order_and_credits_only_one():
    # CSV and event touchpoints may share an ID; the stable sort keeps the caller's order and
    # the credit lands on exactly one step.
    twins = (t("dup", 2026, 2, 1, source="csv"), t("dup", 2026, 2, 1, source="event"))
    journey = build_journey(
        Conversion(**{**CONVERSION.__dict__, "touchpoints": twins}), FirstTouch()
    )
    assert [(s.touchpoint.source, s.credit) for s in journey.steps] == [
        ("csv", Decimal("1000.00")),
        ("event", Decimal("0")),
    ]
