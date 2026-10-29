"""Fixed reason codes for rejected rows and warnings. Documented in docs/contract.md.

Codes are part of the contract: add new ones, never rename or repurpose existing ones.
"""

from enum import StrEnum


class _Described(StrEnum):
    def __new__(cls, value: str, description: str):
        member = str.__new__(cls, value)
        member._value_ = value
        member.description = description
        return member


class RejectReason(_Described):
    """Why a row (or event, or whole file) was refused. Refused data is never loaded."""

    MISSING_FILE = "MISSING_FILE", "A required import file is absent."
    MISSING_COLUMN = "MISSING_COLUMN", "A required column is absent; the whole file is refused."
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD", "A required value is blank."
    INVALID_ID = "INVALID_ID", "An ID is not 1-64 characters of A-Z a-z 0-9 . _ : -"
    DUPLICATE_ID = "DUPLICATE_ID", "The same ID appears with different content."
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP", "A timestamp is not ISO 8601."
    TIMESTAMP_WITHOUT_TIMEZONE = (
        "TIMESTAMP_WITHOUT_TIMEZONE",
        "A timestamp has no UTC offset (Z or +HH:MM); it is not assumed to be UTC.",
    )
    INVALID_AMOUNT = (
        "INVALID_AMOUNT",
        "An amount is not a plain non-negative decimal (no symbols, separators or exponents).",
    )
    AMOUNT_PRECISION = (
        "AMOUNT_PRECISION",
        "An amount has more decimal places than its currency's minor unit.",
    )
    INVALID_CURRENCY = (
        "INVALID_CURRENCY",
        "A currency is not a supported uppercase ISO 4217 code.",
    )
    INVALID_STAGE = "INVALID_STAGE", "An opportunity stage is not 'open' or 'won'."
    WON_AT_REQUIRED = "WON_AT_REQUIRED", "A won opportunity has no won_at."
    WON_AT_NOT_ALLOWED = "WON_AT_NOT_ALLOWED", "An open opportunity has a won_at."
    WON_BEFORE_CREATED = "WON_BEFORE_CREATED", "won_at is earlier than created_at."
    UNKNOWN_ACCOUNT = "UNKNOWN_ACCOUNT", "account_id does not match an accepted account."
    UNKNOWN_CONTACT = "UNKNOWN_CONTACT", "contact_id does not match an accepted contact."
    CONTACT_ACCOUNT_MISMATCH = (
        "CONTACT_ACCOUNT_MISMATCH",
        "The opportunity's contact belongs to a different account.",
    )
    VALUE_TOO_LONG = "VALUE_TOO_LONG", "A text value is longer than its column allows."
    INVALID_EMAIL = "INVALID_EMAIL", "An email is not of the form name@domain."
    UNSUPPORTED_EVENT_TYPE = (
        "UNSUPPORTED_EVENT_TYPE",
        "An event type is not page, track or identify.",
    )
    MISSING_IDENTITY = "MISSING_IDENTITY", "An event has neither anonymousId nor userId."


class WarningCode(_Described):
    """Accepted data that deserves attention. Warned rows are loaded."""

    UNKNOWN_COLUMN = "UNKNOWN_COLUMN", "A column is not in the contract and was ignored."
    DUPLICATE_ROW = "DUPLICATE_ROW", "An exact repeat of an earlier row or event; counted once."
    MISSING_CAMPAIGN_FIELDS = (
        "MISSING_CAMPAIGN_FIELDS",
        "utm_source, utm_medium or utm_campaign is blank; shown as (none), never guessed.",
    )
    TOUCHPOINT_OUTSIDE_LOOKBACK = (
        "TOUCHPOINT_OUTSIDE_LOOKBACK",
        "The touchpoint is outside every lookback window of its contact's opportunities, "
        "so no model can credit it.",
    )
    OPPORTUNITY_WITHOUT_CONTACT = (
        "OPPORTUNITY_WITHOUT_CONTACT",
        "The opportunity has no contact, so it has no touchpoints and is fully Unattributed.",
    )
    ZERO_AMOUNT = "ZERO_AMOUNT", "The opportunity amount is 0."
    UNKNOWN_EVENT_NAME = (
        "UNKNOWN_EVENT_NAME",
        "A track event name is not one of the funnel milestones; kept but not a milestone.",
    )
