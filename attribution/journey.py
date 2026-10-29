"""The journey behind one conversion: every touch of the opportunity's contact, in a fixed
order, with whether it is eligible under the lookback window and the credit a model gives it.

This is the auditable middle of the chain: relationship -> eligible journey -> named model ->
credit. It uses the same window rule as the models (`attribution.types`), so the journey and
the report can't disagree.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from attribution.types import AttributionModel, Conversion, Credit, Touchpoint, window_start


class Eligibility(StrEnum):
    ELIGIBLE = "eligible"
    BEFORE_WINDOW = "before_window"  # earlier than conversion - lookback
    AFTER_CONVERSION = "after_conversion"  # later than the conversion time


@dataclass(frozen=True)
class JourneyStep:
    position: int  # 1-based, in journey order
    touchpoint: Touchpoint
    eligibility: Eligibility
    credit: Decimal | None  # None when ineligible; Decimal("0") when eligible but uncredited


@dataclass(frozen=True)
class Journey:
    conversion: Conversion
    model_name: str
    lookback_days: int | None
    window_start: datetime | None  # None: no lookback cap
    steps: tuple[JourneyStep, ...]
    credits: tuple[Credit, ...]

    @property
    def unattributed(self) -> Decimal:
        return sum((c.amount for c in self.credits if c.touchpoint_id is None), Decimal("0"))

    @property
    def credited_step(self) -> JourneyStep | None:
        """The first step with credit (first-touch credits exactly one)."""
        return next((s for s in self.steps if s.credit), None)


def journey_order(touchpoints) -> list[Touchpoint]:
    """Oldest first; ties on time by touchpoint ID; equal (time, ID) keep the caller's order."""
    return sorted(touchpoints, key=lambda tp: (tp.occurred_at, tp.id))


def build_journey(conversion: Conversion, model: AttributionModel) -> Journey:
    start = window_start(conversion, model.lookback_days)
    credits = tuple(model.attribute(conversion))
    owed = {}  # touchpoint_id -> credit not yet placed on a step
    for credit in credits:
        if credit.touchpoint_id is not None:
            owed[credit.touchpoint_id] = (
                owed.get(credit.touchpoint_id, Decimal("0")) + credit.amount
            )
    steps = []
    for position, tp in enumerate(journey_order(conversion.touchpoints), start=1):
        if start is not None and tp.occurred_at < start:
            eligibility, credit = Eligibility.BEFORE_WINDOW, None
        elif tp.occurred_at > conversion.converted_at:
            eligibility, credit = Eligibility.AFTER_CONVERSION, None
        else:
            # Place each credit on the first eligible step with its ID (IDs can repeat
            # across sources), so the steps' credits sum to the model's credits exactly once.
            eligibility, credit = Eligibility.ELIGIBLE, owed.pop(tp.id, Decimal("0"))
        steps.append(JourneyStep(position, tp, eligibility, credit))
    return Journey(
        conversion=conversion,
        model_name=model.name,
        lookback_days=model.lookback_days,
        window_start=start,
        steps=tuple(steps),
        credits=credits,
    )
