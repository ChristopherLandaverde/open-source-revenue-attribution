"""How to fix each reason code (UI copy; the codes themselves live in contracts/codes.py).

Every refused row and warning on the validation and events pages shows the code's meaning
and one of these fixes. tests/test_validation_page.py fails if a code has no fix.
"""

from contracts import RejectReason, WarningCode

R, W = RejectReason, WarningCode

# Where a fix differs for an import read from HubSpot (ImportRun.source starts with "HubSpot").
HUBSPOT_FIXES: dict[str, str] = {
    R.INVALID_STAGE: (
        "Closed-lost deals aren't supported yet; nothing to change in HubSpot. Tracked in "
        "issue #22."
    ),
}

FIXES: dict[str, str] = {
    R.MISSING_FILE: "Add the file to the import. Upload all four CSVs together.",
    R.MISSING_COLUMN: "Add the column to the header row, spelled exactly as in the contract.",
    R.MISSING_REQUIRED_FIELD: "Fill in the value. Required columns cannot be blank.",
    R.INVALID_ID: "Use 1-64 characters of A-Z a-z 0-9 . _ : - with no spaces.",
    R.DUPLICATE_ID: "Keep one row per ID. Remove or correct the conflicting copies.",
    R.INVALID_TIMESTAMP: "Write the time as ISO 8601, for example 2026-04-01T12:00:00Z.",
    R.TIMESTAMP_WITHOUT_TIMEZONE: "Add the UTC offset: Z for UTC, or +02:00 style.",
    R.INVALID_AMOUNT: "Write a plain number like 24000.00, without symbols or separators.",
    R.AMOUNT_PRECISION: "Round to the currency's minor unit: 2 places, or 0 for JPY and KRW.",
    R.INVALID_CURRENCY: "Use an uppercase code from the supported list, for example USD.",
    R.INVALID_STAGE: "Set stage to open or won. Other stages are not supported yet.",
    R.WON_AT_REQUIRED: "Add the won_at time, or set the stage to open.",
    R.WON_AT_NOT_ALLOWED: "Clear won_at, or set the stage to won.",
    R.WON_BEFORE_CREATED: "Correct created_at or won_at so the win comes after creation.",
    R.UNKNOWN_ACCOUNT: "Add the account to accounts.csv, or fix the account_id.",
    R.UNKNOWN_CONTACT: "Add the contact to contacts.csv, or fix the contact_id.",
    R.CONTACT_ACCOUNT_MISMATCH: "Use a contact from the opportunity's account, or fix account_id.",
    R.VALUE_TOO_LONG: "Shorten the value to the column's limit.",
    R.INVALID_EMAIL: "Use the name@domain.tld form, or leave the email blank.",
    R.UNSUPPORTED_EVENT_TYPE: "Send only page, track and identify calls to this endpoint.",
    R.MISSING_IDENTITY: "Send anonymousId (the SDK sets it) or userId with every event.",
    W.UNKNOWN_COLUMN: "Rename the column if it is a typo; otherwise it is ignored.",
    W.DUPLICATE_ROW: "No action needed. Remove the repeat to silence the warning.",
    W.MISSING_CAMPAIGN_FIELDS: "Tag the landing URL with utm_source, utm_medium and utm_campaign.",
    W.TOUCHPOINT_OUTSIDE_LOOKBACK: "Check the date if this touch should count; else no action.",
    W.OPPORTUNITY_WITHOUT_CONTACT: "Add the opportunity's contact_id to credit its touchpoints.",
    W.ZERO_AMOUNT: "Enter the deal amount if it is known.",
    W.UNKNOWN_EVENT_NAME: "Use a funnel milestone name if this event is a milestone.",
    W.CLOCK_SKEW_NOT_CORRECTED: "Send sentAt with a UTC offset (the RudderStack SDK does).",
}
