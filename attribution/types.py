"""Data types and the model interface shared by every attribution model."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from fractions import Fraction
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
    minor_unit: int = 2  # decimal places of the currency (0 for JPY); credits round to it


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
    parameters: str  # the rule in one line, shown next to the model name

    def attribute(self, conversion: Conversion) -> list[Credit]: ...


def window_start(conversion: Conversion, lookback_days: int) -> datetime:
    """The earliest eligible instant: conversion time minus the lookback (inclusive)."""
    return conversion.converted_at - timedelta(days=lookback_days)


def eligible_touchpoints(conversion: Conversion, lookback_days: int) -> list[Touchpoint]:
    """Touchpoints inside [converted_at - lookback, converted_at], oldest first.

    Both window ends are inclusive. Ties on time are broken by touchpoint id so the
    same input always produces the same order.
    """
    start = window_start(conversion, lookback_days)
    eligible = [
        tp for tp in conversion.touchpoints if start <= tp.occurred_at <= conversion.converted_at
    ]
    return sorted(eligible, key=lambda tp: (tp.occurred_at, tp.id))


def allocate(amount: Decimal, weights: Sequence, places: int) -> list[Decimal]:
    """Split `amount` in proportion to `weights`, each share at `places` decimals, summing exactly.

    Largest-remainder rounding: every exact share is rounded down to the minor unit, then the
    leftover minor units go one each to the largest remainders, ties to the earlier position.
    Weights may be int, Decimal, Fraction or float; they are used exactly (as Fractions).
    """
    exact_weights = [Fraction(w) for w in weights]
    total_weight = sum(exact_weights, Fraction(0))
    if total_weight <= 0 or any(w < 0 for w in exact_weights):
        raise ValueError("allocate needs non-negative weights with a positive total")
    unit = Fraction(1, 10**places)
    exact = [Fraction(amount) * w / total_weight for w in exact_weights]
    floors = [(share // unit) * unit for share in exact]
    leftover = int((Fraction(amount) - sum(floors, Fraction(0))) / unit)
    by_remainder = sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in by_remainder[:leftover]:
        floors[i] += unit
    quantum = Decimal(1).scaleb(-places)
    return [
        (Decimal(f.numerator) / Decimal(f.denominator)).quantize(quantum, rounding=ROUND_FLOOR)
        for f in floors
    ]


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
