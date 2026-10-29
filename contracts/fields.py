"""Field-level parsers shared by the import and event contracts.

Each parser returns (value, reason). reason is None when the value is valid.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from contracts.codes import RejectReason

ID_PATTERN = re.compile(r"[A-Za-z0-9._:\-]{1,64}")
AMOUNT_PATTERN = re.compile(r"\d+(\.\d+)?")
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
MAX_AMOUNT = Decimal("999999999999.99")  # fits the database column (14 digits, 2 places)

# ISO 4217 codes accepted in v1, with their minor-unit digits. Currencies with three
# minor-unit digits (KWD, BHD, ...) are not supported until amounts are stored with more
# precision.
CURRENCY_MINOR_UNITS = {
    "AUD": 2,
    "BRL": 2,
    "CAD": 2,
    "CHF": 2,
    "CNY": 2,
    "DKK": 2,
    "EUR": 2,
    "GBP": 2,
    "HKD": 2,
    "INR": 2,
    "JPY": 0,
    "KRW": 0,
    "MXN": 2,
    "NOK": 2,
    "NZD": 2,
    "PLN": 2,
    "SEK": 2,
    "SGD": 2,
    "USD": 2,
    "ZAR": 2,
}


def parse_id(value: str) -> tuple[str, RejectReason | None]:
    return value, None if ID_PATTERN.fullmatch(value) else RejectReason.INVALID_ID


def parse_timestamp(value: str) -> tuple[datetime | None, RejectReason | None]:
    """ISO 8601 with an explicit offset, normalized to UTC. Naive values are refused."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, RejectReason.INVALID_TIMESTAMP
    if parsed.tzinfo is None or "T" not in value:
        return None, RejectReason.TIMESTAMP_WITHOUT_TIMEZONE
    return parsed.astimezone(UTC), None


def parse_amount(value: str) -> tuple[Decimal | None, RejectReason | None]:
    if not AMOUNT_PATTERN.fullmatch(value):
        return None, RejectReason.INVALID_AMOUNT
    try:
        amount = Decimal(value)
    except InvalidOperation:  # pragma: no cover - the pattern already excludes these
        return None, RejectReason.INVALID_AMOUNT
    if amount > MAX_AMOUNT:
        return None, RejectReason.INVALID_AMOUNT
    return amount, None


def parse_currency(value: str) -> tuple[str, RejectReason | None]:
    return value, None if value in CURRENCY_MINOR_UNITS else RejectReason.INVALID_CURRENCY


def fits_currency(amount: Decimal, currency: str) -> bool:
    """True if the amount needs no more decimal places than the currency's minor unit."""
    places = CURRENCY_MINOR_UNITS[currency]
    return amount == amount.quantize(Decimal(1).scaleb(-places))


def parse_email(value: str) -> tuple[str, RejectReason | None]:
    return value, None if EMAIL_PATTERN.fullmatch(value) else RejectReason.INVALID_EMAIL
