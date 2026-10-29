"""First-touch: all credit to the earliest eligible touchpoint."""

from dataclasses import dataclass

from attribution.types import (
    DEFAULT_LOOKBACK_DAYS,
    Conversion,
    Credit,
    eligible_touchpoints,
    unattributed,
)


@dataclass(frozen=True)
class FirstTouch:
    lookback_days: int | None = DEFAULT_LOOKBACK_DAYS
    name: str = "First-touch"
    parameters: str = "100% to the earliest eligible touch"
    standard: str = "Dreamdata, HockeyStack, GA4 (legacy)"

    def attribute(self, conversion: Conversion) -> list[Credit]:
        eligible = eligible_touchpoints(conversion, self.lookback_days)
        if not eligible:
            return unattributed(conversion)
        first = eligible[0]
        return [
            Credit(
                opportunity_id=conversion.opportunity_id,
                touchpoint_id=first.id,
                campaign_key=first.campaign_key,
                amount=conversion.amount,
                currency=conversion.currency,
            )
        ]
