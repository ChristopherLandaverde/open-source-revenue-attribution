"""The standard rule-based models, as Dreamdata, GA4 and HockeyStack define them.

Definitions and sources: docs/research/m4-models.md. Deviations: docs/decisions.md.

Each model weights the eligible touches of one conversion (at or before it, and inside the
lookback window when one is set; oldest first, ties by touchpoint ID). It splits the amount by
those weights at the currency's minor unit with `allocate`, so every model's credits sum
exactly to the amount. No eligible touch means the whole amount goes to Unattributed.

These are association rules with fixed parameters. None of them estimates causal impact.
Data-driven (algorithmic) models are deliberately absent: see docs/decisions.md.
"""

from dataclasses import dataclass
from fractions import Fraction

from attribution.first_touch import FirstTouch
from attribution.types import (
    DEFAULT_LOOKBACK_DAYS,
    Conversion,
    Credit,
    Touchpoint,
    allocate,
    eligible_touchpoints,
    unattributed,
)

SECONDS_PER_DAY = 86_400


def _split(conversion: Conversion, touches: list[Touchpoint], weights: list) -> list[Credit]:
    shares = allocate(conversion.amount, weights, conversion.minor_unit)
    return [
        Credit(
            opportunity_id=conversion.opportunity_id,
            touchpoint_id=tp.id,
            campaign_key=tp.campaign_key,
            amount=share,
            currency=conversion.currency,
        )
        for tp, share in zip(touches, shares, strict=True)
    ]


class _Weighted:
    """Shared attribute(): eligible touches -> weights -> credits that sum to the amount."""

    lookback_days: int | None

    def weights(self, touches: list[Touchpoint], conversion: Conversion) -> list:
        raise NotImplementedError

    def attribute(self, conversion: Conversion) -> list[Credit]:
        touches = eligible_touchpoints(conversion, self.lookback_days)
        if not touches:
            return unattributed(conversion)
        return _split(conversion, touches, self.weights(touches, conversion))


@dataclass(frozen=True)
class LastTouch(_Weighted):
    lookback_days: int | None = DEFAULT_LOOKBACK_DAYS
    name: str = "Last-touch"
    parameters: str = "100% to the latest eligible touch"
    standard: str = "Dreamdata, HockeyStack, GA4 last click"

    def attribute(self, conversion: Conversion) -> list[Credit]:
        touches = eligible_touchpoints(conversion, self.lookback_days)
        if not touches:
            return unattributed(conversion)
        return _split(conversion, touches[-1:], [1])


@dataclass(frozen=True)
class Linear(_Weighted):
    lookback_days: int | None = DEFAULT_LOOKBACK_DAYS
    name: str = "Linear"
    parameters: str = "Equal share to every eligible touch"
    standard: str = "Dreamdata, HockeyStack, GA4 (legacy)"

    def weights(self, touches, conversion):
        return [1] * len(touches)


@dataclass(frozen=True)
class PositionBased(_Weighted):
    """U-shaped: 40% to the first touch, 40% to the last, 20% shared by the touches between.

    Split as Dreamdata, GA4 (legacy) and HockeyStack define it. One touch gets 100%. Two touches
    get 50% each. No vendor documents these two cases (Dreamdata, GA4, HockeyStack, HubSpot);
    100% and 50/50 are the only splits that keep the sum and treat first and last alike
    (docs/decisions.md).
    """

    lookback_days: int | None = DEFAULT_LOOKBACK_DAYS
    first_percent: int = 40
    last_percent: int = 40
    name: str = "Position-based (U-shaped)"
    standard: str = "Dreamdata U-shaped, GA4 (legacy), HockeyStack"

    @property
    def parameters(self) -> str:
        middle = 100 - self.first_percent - self.last_percent
        return (
            f"{self.first_percent}% first, {self.last_percent}% last, "
            f"{middle}% shared by the touches between"
        )

    def weights(self, touches, conversion):
        n = len(touches)
        if n == 1:
            return [1]
        if n == 2:
            return [1, 1]
        middle = Fraction(100 - self.first_percent - self.last_percent, n - 2)
        return [self.first_percent, *([middle] * (n - 2)), self.last_percent]


@dataclass(frozen=True)
class TimeDecay(_Weighted):
    """A touch's weight halves for every `half_life_days` it happened before the conversion.

    The 7-day half-life is GA4's legacy default and HockeyStack's. Dreamdata has no time-decay
    model. Weights are normalised so credits still sum to the amount.
    """

    lookback_days: int | None = DEFAULT_LOOKBACK_DAYS
    half_life_days: int = 7
    name: str = "Time decay"
    standard: str = "GA4 (legacy) and HockeyStack, 7-day half-life; Dreamdata has no time decay"

    @property
    def parameters(self) -> str:
        return f"Weight halves every {self.half_life_days} days before the conversion"

    def weights(self, touches, conversion):
        half_life = self.half_life_days * SECONDS_PER_DAY
        return [
            2.0 ** (-(conversion.converted_at - tp.occurred_at).total_seconds() / half_life)
            for tp in touches
        ]


def standard_models(lookback_days: int | None = DEFAULT_LOOKBACK_DAYS) -> list:
    """The models shown side by side, in the order the comparison lists them."""
    return [
        FirstTouch(lookback_days=lookback_days),
        LastTouch(lookback_days=lookback_days),
        Linear(lookback_days=lookback_days),
        PositionBased(lookback_days=lookback_days),
        TimeDecay(lookback_days=lookback_days),
    ]
