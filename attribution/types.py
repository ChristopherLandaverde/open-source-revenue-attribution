"""Data types and the model interface shared by every attribution model."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

DEFAULT_LOOKBACK_DAYS = 90
UNATTRIBUTED = "Unattributed"
MISSING = "(none)"


@dataclass(frozen=True)
class Touchpoint:
    """A marketing touch connected to the converting contact."""

    id: str
    occurred_at: datetime
    source: str = ""
    medium: str = ""
    campaign: str = ""

    @property
    def campaign_key(self) -> str:
        """Source / medium / campaign, with missing values shown rather than guessed."""
        return " / ".join(value or MISSING for value in (self.source, self.medium, self.campaign))


@dataclass(frozen=True)
class Conversion:
    """One opportunity outcome to attribute, with the touchpoints of its contact."""

    opportunity_id: str
    amount: Decimal
    currency: str
    converted_at: datetime
    touchpoints: tuple[Touchpoint, ...]


@dataclass(frozen=True)
class Credit:
    """Amount credited to one touchpoint (or to Unattributed when touchpoint_id is None)."""

    opportunity_id: str
    touchpoint_id: str | None
    campaign_key: str
    amount: Decimal
    currency: str


class AttributionModel(Protocol):
    """Every model takes one conversion and returns credits that sum to its amount."""

    name: str
    lookback_days: int

    def attribute(self, conversion: Conversion) -> list[Credit]: ...


def eligible_touchpoints(conversion: Conversion, lookback_days: int) -> list[Touchpoint]:
    """Touchpoints inside [converted_at - lookback, converted_at], oldest first.

    Both window ends are inclusive. Ties on time are broken by touchpoint id so the
    same input always produces the same order.
    """
    window_start = conversion.converted_at - timedelta(days=lookback_days)
    eligible = [
        tp
        for tp in conversion.touchpoints
        if window_start <= tp.occurred_at <= conversion.converted_at
    ]
    return sorted(eligible, key=lambda tp: (tp.occurred_at, tp.id))


def unattributed(conversion: Conversion) -> list[Credit]:
    return [
        Credit(
            opportunity_id=conversion.opportunity_id,
            touchpoint_id=None,
            campaign_key=UNATTRIBUTED,
            amount=conversion.amount,
            currency=conversion.currency,
        )
    ]


def summarize_by_campaign(credits: list[Credit]) -> list[tuple[str, str, Decimal, int]]:
    """Total credit per (campaign_key, currency): (campaign_key, currency, amount, opportunities).

    Currencies are never added together. Rows sort by currency, then amount descending,
    then campaign key.
    """
    totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    opportunities: dict[tuple[str, str], set[str]] = defaultdict(set)
    for credit in credits:
        key = (credit.campaign_key, credit.currency)
        totals[key] += credit.amount
        opportunities[key].add(credit.opportunity_id)
    rows = [
        (campaign, currency, amount, len(opportunities[(campaign, currency)]))
        for (campaign, currency), amount in totals.items()
    ]
    return sorted(rows, key=lambda row: (row[1], -row[2], row[0]))
