"""Influenced vs attributed (attribution/influence.py). Hand calculations in comments."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from attribution import (
    Conversion,
    InfluenceRow,
    Linear,
    Touchpoint,
    influence_by_campaign,
    summarize_by_campaign,
)

CONVERTED = datetime(2026, 4, 1, tzinfo=UTC)


def tp(id_, days_before, campaign):
    return Touchpoint(id_, CONVERTED - timedelta(days=days_before), "s", "m", campaign)


def conv(opp, amount, *touches, currency="USD"):
    return Conversion(opp, Decimal(amount), currency, CONVERTED, tuple(touches))


# opp-1 1,000 USD: a, a, b (two touches of campaign a)  -> a and b each influence 1,000
# opp-2   500 USD: b                                     -> b influences 500
# opp-3   200 USD: only a touch 120 days old             -> with a 90-day window, no eligible
#                                                           touch: left out of influence
# opp-4    90 EUR: a                                     -> a influences 90 EUR (own currency)
CONVERSIONS = [
    conv("opp-1", "1000.00", tp("t1", 30, "a"), tp("t2", 20, "a"), tp("t3", 10, "b")),
    conv("opp-2", "500.00", tp("t4", 5, "b")),
    conv("opp-3", "200.00", tp("t5", 120, "a")),
    conv("opp-4", "90.00", tp("t6", 1, "a"), currency="EUR"),
]


def test_each_touching_campaign_gets_the_full_amount():
    assert influence_by_campaign(CONVERSIONS, 90) == [
        InfluenceRow("s / m / a", "EUR", Decimal("90.00"), 1, 1),
        # b: opp-1 1,000 + opp-2 500 = 1,500 over 2 opportunities, 2 touches
        InfluenceRow("s / m / b", "USD", Decimal("1500.00"), 2, 2),
        # a: opp-1 only (opp-3's touch is outside the window) -> 1,000, 1 opportunity, 2 touches
        InfluenceRow("s / m / a", "USD", Decimal("1000.00"), 1, 2),
    ]  # opp-3 (no eligible touch) influences nothing, as in Dreamdata's attributable deals


def test_no_cap_counts_old_touches():
    # No lookback cap: opp-3's 120-day-old touch of a counts -> a USD 1,000 + 200 = 1,200.
    rows = {
        (r.campaign_key, r.currency): r.amount for r in influence_by_campaign(CONVERSIONS, None)
    }
    assert rows[("s / m / a", "USD")] == Decimal("1200.00")


def test_influence_overlaps_while_attribution_reconciles():
    # USD amounts: 1,000 + 500 + 200 = 1,700. Influence sums to 2,500 (overlap, and opp-3 is
    # left out); linear credit (90-day window, opp-3 Unattributed) sums to exactly 1,700.
    influenced = sum(
        r.amount for r in influence_by_campaign(CONVERSIONS, 90) if r.currency == "USD"
    )
    model = Linear(lookback_days=90)
    credits = [c for conversion in CONVERSIONS for c in model.attribute(conversion)]
    attributed = sum(a for _, cur, a, _ in summarize_by_campaign(credits) if cur == "USD")
    assert influenced == Decimal("2500.00")
    assert attributed == Decimal("1700.00")


def test_shorter_window_drops_influence():
    # 7-day window: opp-1 keeps no touch (10, 20, 30 days) -> left out; opp-2's 5-day b stays.
    rows = {(r.campaign_key, r.currency): r.amount for r in influence_by_campaign(CONVERSIONS, 7)}
    assert rows == {
        ("s / m / a", "EUR"): Decimal("90.00"),
        ("s / m / b", "USD"): Decimal("500.00"),
    }
