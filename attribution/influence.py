"""Influenced amounts: the full amount of every conversion a campaign touched.

Attributed credit is a split: each conversion's amount is divided among its touches, so
campaign totals add up to the total amount. Influence is not a split: a campaign with at
least one eligible touch (inside the same lookback window as the models) is counted with the
conversion's whole amount, and so is every other campaign that touched it. Influenced totals
therefore overlap and must never be added together across campaigns.

The rule follows Dreamdata's influenced metrics (docs/research/m4-models.md).
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from attribution.types import eligible_touchpoints


@dataclass(frozen=True)
class InfluenceRow:
    campaign_key: str
    currency: str
    amount: Decimal  # the sum of the full amounts of the conversions it touched
    conversions: int
    touches: int  # eligible touches of this campaign across those conversions


def influence_by_campaign(conversions, lookback_days: int | None) -> list[InfluenceRow]:
    """One row per (campaign, currency). Conversions with no eligible touch are left out.

    As in Dreamdata, influence covers attributable deals only: a conversion with no eligible
    touch influences nothing. The data readiness page counts those conversions instead.

    Rows sort by currency, then amount descending, then campaign key. Currencies never mix.
    """
    amounts: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    touches: dict[tuple[str, str], int] = defaultdict(int)
    for conversion in conversions:
        eligible = eligible_touchpoints(conversion, lookback_days)
        per_campaign: dict[str, int] = defaultdict(int)
        for tp in eligible:
            per_campaign[tp.campaign_key] += 1
        for campaign, n in per_campaign.items():
            key = (campaign, conversion.currency)
            amounts[key] += conversion.amount
            counts[key] += 1
            touches[key] += n
    rows = [
        InfluenceRow(campaign, currency, amounts[key], counts[key], touches[key])
        for key in amounts
        for campaign, currency in [key]
    ]
    return sorted(rows, key=lambda r: (r.currency, -r.amount, r.campaign_key))
