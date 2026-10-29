"""First-touch model tests. Expected values are hand-calculated in the comments."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from attribution import (
    UNATTRIBUTED,
    Conversion,
    Credit,
    FirstTouch,
    Touchpoint,
    summarize_by_campaign,
)

CONVERTED = datetime(2026, 4, 1, tzinfo=UTC)


def tp(id_, days_before, campaign="spring", source="google", medium="cpc"):
    return Touchpoint(
        id=id_,
        occurred_at=CONVERTED - timedelta(days=days_before),
        source=source,
        medium=medium,
        campaign=campaign,
    )


def conversion(*touchpoints, amount="1000.00"):
    return Conversion(
        opportunity_id="opp-1",
        amount=Decimal(amount),
        currency="USD",
        converted_at=CONVERTED,
        touchpoints=tuple(touchpoints),
    )


def test_model_is_named():
    assert FirstTouch().name == "First-touch"


def test_all_credit_goes_to_earliest_eligible_touchpoint():
    # t-old (30 days before) is earliest of {30, 10, 2} days before -> gets all 1000.00
    credits = FirstTouch().attribute(
        conversion(tp("t-mid", 10, "b"), tp("t-old", 30, "a"), tp("t-new", 2, "c"))
    )
    assert credits == [
        Credit("opp-1", "t-old", "google / cpc / a", Decimal("1000.00"), "USD"),
    ]


def test_touchpoint_after_conversion_is_ignored():
    # t-after is 1 day AFTER conversion (days_before=-1); only t-before is eligible.
    credits = FirstTouch().attribute(conversion(tp("t-after", -1, "x"), tp("t-before", 5, "y")))
    assert [c.touchpoint_id for c in credits] == ["t-before"]


def test_touchpoint_at_conversion_time_is_eligible():
    credits = FirstTouch().attribute(conversion(tp("t-same", 0)))
    assert credits[0].touchpoint_id == "t-same"


def test_lookback_window_boundary_is_inclusive():
    # With a 90-day window: exactly 90 days before counts, 91 days does not.
    model = FirstTouch(lookback_days=90)
    credits = model.attribute(conversion(tp("t-91", 91, "x"), tp("t-90", 90, "y")))
    assert credits[0].touchpoint_id == "t-90"


def test_default_has_no_lookback_cap():
    # No cap by default (Dreamdata): the 91-day-old touch is the earliest and wins.
    credits = FirstTouch().attribute(conversion(tp("t-91", 91, "x"), tp("t-90", 90, "y")))
    assert credits[0].touchpoint_id == "t-91"


def test_custom_lookback_window():
    # With a 7-day window, the 10-day-old touch is out and the 3-day-old touch wins.
    credits = FirstTouch(lookback_days=7).attribute(conversion(tp("t-10", 10), tp("t-3", 3)))
    assert credits[0].touchpoint_id == "t-3"


def test_no_eligible_touchpoints_is_unattributed():
    # 90-day window, only touch is 120 days old -> outside -> full 1000.00 to Unattributed.
    credits = FirstTouch(lookback_days=90).attribute(conversion(tp("t-120", 120)))
    assert credits == [Credit("opp-1", None, UNATTRIBUTED, Decimal("1000.00"), "USD")]


def test_no_touchpoints_at_all_is_unattributed():
    credits = FirstTouch().attribute(conversion())
    assert credits == [Credit("opp-1", None, UNATTRIBUTED, Decimal("1000.00"), "USD")]


def test_missing_campaign_fields_stay_visible():
    credits = FirstTouch().attribute(conversion(tp("t-1", 1, campaign="", source="", medium="")))
    assert credits[0].campaign_key == "(none) / (none) / (none)"


def test_simultaneous_touchpoints_break_ties_by_id():
    # Same timestamp: deterministic tie-break on touchpoint id ("t-a" < "t-b").
    credits = FirstTouch().attribute(conversion(tp("t-b", 5, "b"), tp("t-a", 5, "a")))
    assert credits[0].touchpoint_id == "t-a"


def test_credit_reconciles_to_opportunity_amount():
    conv = conversion(tp("t-1", 40), tp("t-2", 20), amount="12345.67")
    assert sum(c.amount for c in FirstTouch().attribute(conv)) == Decimal("12345.67")


def test_same_input_same_output():
    conv = conversion(tp("t-1", 40), tp("t-2", 20))
    assert FirstTouch().attribute(conv) == FirstTouch().attribute(conv)


def test_summarize_groups_by_campaign_and_currency():
    credits = [
        Credit("o1", "t1", "google / cpc / a", Decimal("100.00"), "USD"),
        Credit("o2", "t2", "google / cpc / a", Decimal("50.00"), "USD"),
        Credit("o3", "t3", "google / cpc / a", Decimal("70.00"), "EUR"),
        Credit("o4", None, UNATTRIBUTED, Decimal("30.00"), "USD"),
    ]
    # USD: a = 100 + 50 = 150, Unattributed = 30. EUR kept separate: a = 70.
    # Sorted by currency, then amount descending.
    assert summarize_by_campaign(credits) == [
        ("google / cpc / a", "EUR", Decimal("70.00"), 1),
        ("google / cpc / a", "USD", Decimal("150.00"), 2),
        (UNATTRIBUTED, "USD", Decimal("30.00"), 1),
    ]
