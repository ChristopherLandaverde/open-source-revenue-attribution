"""Multi-touch models (attribution/models.py), written before the code.

Every expected amount is calculated by hand in the comments. All conversions are
1,000.00 USD at 2026-04-01 00:00 UTC with a 90-day lookback unless a test says otherwise.
Credits always sum to the amount; leftover cents follow `allocate` (largest remainder,
ties to the earlier touch in journey order).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from attribution import (
    UNATTRIBUTED,
    Conversion,
    Credit,
    FirstTouch,
    LastTouch,
    Linear,
    PositionBased,
    TimeDecay,
    Touchpoint,
    standard_models,
)

CONVERTED = datetime(2026, 4, 1, tzinfo=UTC)


def tp(id_, days_before, campaign=None):
    return Touchpoint(
        id=id_,
        occurred_at=CONVERTED - timedelta(days=days_before),
        source="google",
        medium="cpc",
        campaign=campaign or id_,
    )


def conversion(*touchpoints, amount="1000.00", currency="USD", minor_unit=2):
    return Conversion(
        opportunity_id="opp-1",
        amount=Decimal(amount),
        currency=currency,
        converted_at=CONVERTED,
        touchpoints=tuple(touchpoints),
        minor_unit=minor_unit,
    )


def credits_by_id(credits):
    return {c.touchpoint_id: c.amount for c in credits}


# Four eligible touches (30, 20, 10, 2 days before), one before the window, one after.
FOUR = (
    tp("t-20", 20),
    tp("t-old", 120),  # outside the 90-day window: never credited
    tp("t-30", 30),
    tp("t-2", 2),
    tp("t-10", 10),
    tp("t-after", -1),  # after the conversion: never credited
)

ALL_MODELS = [FirstTouch(), LastTouch(), Linear(), PositionBased(), TimeDecay()]


# --- Last touch -------------------------------------------------------------------


def test_last_touch_credits_latest_eligible():
    # Latest of {30, 20, 10, 2} days before is t-2 -> 1,000.00. t-after is excluded.
    assert LastTouch().attribute(conversion(*FOUR)) == [
        Credit("opp-1", "t-2", "google / cpc / t-2", Decimal("1000.00"), "USD")
    ]


def test_last_touch_tie_goes_to_higher_id():
    # Same instant: journey order is (time, id) -> t-a, t-b; the last of them is t-b.
    a, b = tp("t-a", 5), tp("t-b", 5)
    assert LastTouch().attribute(conversion(b, a))[0].touchpoint_id == "t-b"


# --- Linear -----------------------------------------------------------------------


def test_linear_splits_evenly():
    # 1,000.00 / 4 = 250.00 each, exact.
    assert credits_by_id(Linear().attribute(conversion(*FOUR))) == {
        "t-30": Decimal("250.00"),
        "t-20": Decimal("250.00"),
        "t-10": Decimal("250.00"),
        "t-2": Decimal("250.00"),
    }


def test_linear_remainder_goes_to_earliest():
    # 1,000.00 / 3 = 333.333...: 333.33 x 3 = 999.99; 1 cent to the earliest (t-30).
    got = Linear().attribute(conversion(tp("t-30", 30), tp("t-20", 20), tp("t-10", 10)))
    assert [(c.touchpoint_id, c.amount) for c in got] == [
        ("t-30", Decimal("333.34")),
        ("t-20", Decimal("333.33")),
        ("t-10", Decimal("333.33")),
    ]


def test_linear_zero_decimal_currency():
    # 1,000 JPY / 3 = 333.33...: 333 x 3 = 999; 1 yen to the earliest.
    got = Linear().attribute(
        conversion(
            tp("t-30", 30), tp("t-20", 20), tp("t-10", 10), amount="1000", currency="JPY",
            minor_unit=0,
        )
    )  # fmt: skip
    assert [c.amount for c in got] == [Decimal("334"), Decimal("333"), Decimal("333")]


def test_linear_repeated_campaign_keeps_one_credit_per_touch():
    # Two touches of the same campaign each get 500.00; summed per campaign it is 1,000.00.
    got = Linear().attribute(conversion(tp("t-1", 3, "same"), tp("t-2", 1, "same")))
    assert [c.amount for c in got] == [Decimal("500.00"), Decimal("500.00")]
    assert {c.campaign_key for c in got} == {"google / cpc / same"}


# --- Position-based (U-shaped) ----------------------------------------------------


def test_position_based_40_20_40():
    # 4 touches: first 40% = 400.00, last 40% = 400.00, middle 20% = 200.00 / 2 = 100.00 each.
    assert credits_by_id(PositionBased().attribute(conversion(*FOUR))) == {
        "t-30": Decimal("400.00"),
        "t-20": Decimal("100.00"),
        "t-10": Decimal("100.00"),
        "t-2": Decimal("400.00"),
    }


def test_position_based_two_touches_split_50_50():
    # No middle touches: the middle 20% is shared equally, so 50% / 50% (our reading; see
    # docs/decisions.md: no source documents the two-touch case).
    got = PositionBased().attribute(conversion(tp("t-30", 30), tp("t-2", 2)))
    assert credits_by_id(got) == {"t-30": Decimal("500.00"), "t-2": Decimal("500.00")}


def test_position_based_one_touch_gets_everything():
    got = PositionBased().attribute(conversion(tp("t-2", 2)))
    assert credits_by_id(got) == {"t-2": Decimal("1000.00")}


def test_position_based_three_touches_and_rounding():
    # 3 touches of 100.01: 40.004 / 20.002 / 40.004 -> 40.00 / 20.00 / 40.00 = 100.00,
    # 1 cent left; remainders tie between first and last -> first: 40.01 / 20.00 / 40.00.
    got = PositionBased().attribute(
        conversion(tp("t-30", 30), tp("t-20", 20), tp("t-10", 10), amount="100.01")
    )
    assert [c.amount for c in got] == [Decimal("40.01"), Decimal("20.00"), Decimal("40.00")]


# --- Time decay -------------------------------------------------------------------


def test_time_decay_halves_weight_every_half_life():
    # Half-life 7 days, measured back from the conversion. Touches 14, 7 and 0 days before:
    # weights 0.25, 0.5, 1 (sum 1.75) -> 1,000 x 0.25/1.75 = 142.857..., x 0.5/1.75 = 285.714...,
    # x 1/1.75 = 571.428... Floors 142.85 + 285.71 + 571.42 = 999.98; 2 cents left.
    # Remainders .007, .004, .008 (in cents x 100: 0.714, 0.428, 0.857) -> t-0 then t-14.
    got = TimeDecay().attribute(conversion(tp("t-14", 14), tp("t-7", 7), tp("t-0", 0)))
    assert [(c.touchpoint_id, c.amount) for c in got] == [
        ("t-14", Decimal("142.86")),
        ("t-7", Decimal("285.71")),
        ("t-0", Decimal("571.43")),
    ]


def test_time_decay_custom_half_life():
    # Half-life 1 day: touches 1 and 0 days before weigh 0.5 and 1 -> 333.33..., 666.66...
    # Floors 333.33 + 666.66 = 999.99; remainders 0.333 vs 0.666 cents -> t-0 gets the cent.
    got = TimeDecay(half_life_days=1).attribute(conversion(tp("t-1", 1), tp("t-0", 0)))
    assert credits_by_id(got) == {"t-1": Decimal("333.33"), "t-0": Decimal("666.67")}


# --- Shared behaviour -------------------------------------------------------------


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.name)
def test_no_eligible_touch_is_unattributed(model):
    got = model.attribute(conversion(tp("t-old", 120), tp("t-after", -1)))
    assert got == [Credit("opp-1", None, UNATTRIBUTED, Decimal("1000.00"), "USD")]


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.name)
@pytest.mark.parametrize("amount", ["1000.00", "0.01", "999.99", "18500.50", "0.00"])
def test_credits_reconcile_to_amount(model, amount):
    got = model.attribute(conversion(*FOUR, tp("t-1", 1), tp("t-5", 5), amount=amount))
    assert sum(c.amount for c in got) == Decimal(amount)
    assert all(c.amount >= 0 for c in got)
    assert {c.currency for c in got} == {"USD"}


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.name)
def test_same_input_same_output_whatever_the_input_order(model):
    forward = model.attribute(conversion(*FOUR))
    assert model.attribute(conversion(*reversed(FOUR))) == forward


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.name)
def test_lookback_boundary_is_inclusive(model):
    # 90 days exactly is in; 91 is out. With one eligible touch every model gives it all.
    got = model.attribute(conversion(tp("t-91", 91), tp("t-90", 90)))
    assert credits_by_id(got) == {"t-90": Decimal("1000.00")}


def test_standard_models_are_named_with_parameters():
    models = standard_models(lookback_days=30)
    assert [m.name for m in models] == [
        "First-touch",
        "Last-touch",
        "Linear",
        "Position-based (U-shaped)",
        "Time decay",
    ]
    assert all(m.lookback_days == 30 for m in models)
    assert [m.parameters for m in models] == [
        "100% to the earliest eligible touch",
        "100% to the latest eligible touch",
        "Equal share to every eligible touch",
        "40% first, 40% last, 20% shared by the touches between",
        "Weight halves every 7 days before the conversion",
    ]
