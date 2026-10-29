"""Import contract rules (docs/contract.md). One test per rule, written before the validator."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from contracts import ImportBatch, RejectReason, WarningCode, validate_import

R, W = RejectReason, WarningCode


def valid_rows():
    return {
        "accounts": [{"account_id": "acc-1", "name": "Acme", "domain": "acme.example"}],
        "contacts": [{"contact_id": "con-1", "account_id": "acc-1", "email": "a@acme.example"}],
        "opportunities": [
            {
                "opportunity_id": "opp-1",
                "account_id": "acc-1",
                "contact_id": "con-1",
                "name": "Deal",
                "amount": "1000.00",
                "currency": "USD",
                "stage": "won",
                "created_at": "2026-04-01T12:00:00Z",
                "won_at": "2026-05-01T12:00:00Z",
            }
        ],
        "touchpoints": [
            {
                "touchpoint_id": "tp-1",
                "contact_id": "con-1",
                "occurred_at": "2026-03-01T12:00:00Z",
                "utm_source": "google",
                "utm_medium": "cpc",
                "utm_campaign": "spring",
            }
        ],
    }


def run(**overrides):
    """Validate the valid batch with some entity's rows replaced or patched."""
    rows = valid_rows()
    for entity, value in overrides.items():
        if isinstance(value, dict):  # patch the first row
            rows[entity] = [{**rows[entity][0], **value}]
        else:
            rows[entity] = value
    return validate_import(ImportBatch.from_rows(**rows))


def reject_codes(report, entity=None):
    return [
        (r.entity, r.record_id, issue.code, issue.field)
        for r in report.rejected
        if entity in (None, r.entity)
        for issue in r.issues
    ]


def warning_codes(report):
    return [(w.entity, w.record_id, w.code) for w in report.warnings]


def test_valid_batch_is_fully_accepted_with_no_warnings():
    report = run()
    assert report.ok
    assert report.rejected == []
    assert report.warnings == []
    assert report.file_errors == []
    assert {e: len(recs) for e, recs in report.accepted.items()} == {
        "accounts": 1,
        "contacts": 1,
        "opportunities": 1,
        "touchpoints": 1,
    }


def test_accepted_records_are_typed_and_normalized():
    report = run(opportunities={"created_at": "2026-04-01T08:00:00-04:00"})
    opp = report.accepted["opportunities"][0]
    assert opp.amount == Decimal("1000.00")
    assert opp.created_at == datetime(2026, 4, 1, 12, tzinfo=UTC)
    assert opp.created_at.tzinfo is UTC
    assert report.accepted["touchpoints"][0].source == "google"


def test_cells_are_trimmed_and_blank_means_missing():
    report = run(accounts={"account_id": "  acc-1 ", "name": "   "})
    assert report.accepted["accounts"][0].account_id == "acc-1"
    assert report.accepted["accounts"][0].name == ""


# --- required fields and IDs -------------------------------------------------


def test_missing_required_field_rejects_row():
    report = run(accounts={"account_id": ""})
    assert ("accounts", "", R.MISSING_REQUIRED_FIELD, "account_id") in reject_codes(report)


def test_id_with_disallowed_characters_is_rejected():
    report = run(accounts={"account_id": "acc 1"})
    assert reject_codes(report, "accounts") == [("accounts", "acc 1", R.INVALID_ID, "account_id")]


def test_id_longer_than_64_characters_is_rejected():
    report = run(accounts={"account_id": "a" * 65})
    assert reject_codes(report, "accounts")[0][2] == R.INVALID_ID


def test_conflicting_duplicate_ids_reject_every_copy():
    rows = valid_rows()["accounts"]
    report = run(accounts=[rows[0], {**rows[0], "name": "Other"}])
    assert reject_codes(report, "accounts") == [
        ("accounts", "acc-1", R.DUPLICATE_ID, "account_id"),
        ("accounts", "acc-1", R.DUPLICATE_ID, "account_id"),
    ]


def test_exact_duplicate_row_is_counted_once_with_a_warning():
    rows = valid_rows()["accounts"]
    report = run(accounts=[rows[0], dict(rows[0])])
    assert len(report.accepted["accounts"]) == 1
    assert report.rejected == []
    assert warning_codes(report) == [("accounts", "acc-1", W.DUPLICATE_ROW)]
    assert report.warnings[0].row == 3
    assert report.counts["accounts"] == {
        "received": 2,
        "accepted": 1,
        "rejected": 0,
        "duplicates": 1,
    }


def test_row_numbers_count_the_header_as_row_one():
    report = run(accounts={"account_id": "bad id"})
    assert report.rejected[0].row == 2


def test_all_reasons_for_a_row_are_reported():
    report = run(opportunities={"amount": "abc", "currency": "usd", "stage": "lost"})
    codes = {code for _, _, code, _ in reject_codes(report, "opportunities")}
    assert codes == {R.INVALID_AMOUNT, R.INVALID_CURRENCY, R.INVALID_STAGE}


# --- files and columns -------------------------------------------------------


def test_missing_file_is_a_file_error_and_dependents_cascade():
    rows = valid_rows()
    del rows["accounts"]
    report = validate_import(ImportBatch.from_rows(**rows))
    assert [(e.entity, e.code) for e in report.file_errors] == [("accounts", R.MISSING_FILE)]
    assert ("contacts", "con-1", R.UNKNOWN_ACCOUNT, "account_id") in reject_codes(report)


def test_missing_required_column_rejects_whole_file():
    batch = ImportBatch.from_rows(**valid_rows())
    batch.tables["accounts"] = batch.tables["accounts"].without_column("account_id")
    report = validate_import(batch)
    assert [(e.entity, e.code, e.field) for e in report.file_errors] == [
        ("accounts", R.MISSING_COLUMN, "account_id")
    ]
    assert report.accepted["accounts"] == []
    assert report.counts["accounts"] == {
        "received": 1,
        "accepted": 0,
        "rejected": 1,
        "duplicates": 0,
    }


def test_unknown_column_is_a_warning_and_ignored():
    report = run(accounts={"industry": "Robotics"})
    assert report.ok
    assert [(w.entity, w.code, w.field) for w in report.warnings] == [
        ("accounts", W.UNKNOWN_COLUMN, "industry")
    ]


def test_header_only_file_is_valid_and_empty():
    report = run(touchpoints=[])
    assert report.ok
    assert report.accepted["touchpoints"] == []


# --- timestamps --------------------------------------------------------------


@pytest.mark.parametrize("value", ["2026-04-01T12:00:00", "2026-04-01"])
def test_timestamp_without_offset_is_rejected(value):
    report = run(opportunities={"created_at": value})
    assert reject_codes(report, "opportunities") == [
        ("opportunities", "opp-1", R.TIMESTAMP_WITHOUT_TIMEZONE, "created_at")
    ]


def test_unparseable_timestamp_is_rejected():
    report = run(touchpoints={"occurred_at": "yesterday"})
    assert reject_codes(report)[0][2:] == (R.INVALID_TIMESTAMP, "occurred_at")


# --- money -------------------------------------------------------------------


@pytest.mark.parametrize("amount", ["1,000.00", "$1000", "-5.00", "1e3", "abc", "1000000000000.00"])
def test_malformed_or_negative_amount_is_rejected(amount):
    report = run(opportunities={"amount": amount})
    assert reject_codes(report, "opportunities")[0][2] == R.INVALID_AMOUNT


def test_amount_with_more_decimals_than_the_currency_allows_is_rejected():
    assert reject_codes(run(opportunities={"amount": "10.005"}))[0][2] == R.AMOUNT_PRECISION
    jpy = run(opportunities={"amount": "1500.5", "currency": "JPY"})
    assert reject_codes(jpy)[0][2] == R.AMOUNT_PRECISION


def test_whole_number_amount_is_fine_for_any_currency():
    assert run(opportunities={"amount": "1500", "currency": "JPY"}).ok
    assert run(opportunities={"amount": "1500", "currency": "USD"}).ok


@pytest.mark.parametrize("currency", ["usd", "US", "XYZ", "KWD"])
def test_unsupported_or_lowercase_currency_is_rejected(currency):
    report = run(opportunities={"currency": currency})
    assert reject_codes(report, "opportunities")[0][2:] == (R.INVALID_CURRENCY, "currency")


def test_zero_amount_is_accepted_with_a_warning():
    report = run(opportunities={"amount": "0"})
    assert report.ok
    assert warning_codes(report) == [("opportunities", "opp-1", W.ZERO_AMOUNT)]


# --- stages ------------------------------------------------------------------


def test_unknown_stage_is_rejected():
    report = run(opportunities={"stage": "Closed Won"})
    assert reject_codes(report)[0][2] == R.INVALID_STAGE


def test_won_stage_requires_won_at():
    report = run(opportunities={"won_at": ""})
    assert reject_codes(report) == [("opportunities", "opp-1", R.WON_AT_REQUIRED, "won_at")]


def test_open_stage_must_not_have_won_at():
    report = run(opportunities={"stage": "open"})
    assert reject_codes(report) == [("opportunities", "opp-1", R.WON_AT_NOT_ALLOWED, "won_at")]


def test_won_before_created_is_rejected():
    report = run(opportunities={"won_at": "2026-03-01T12:00:00Z"})
    assert reject_codes(report) == [("opportunities", "opp-1", R.WON_BEFORE_CREATED, "won_at")]


# --- relationships -----------------------------------------------------------


def test_contact_must_reference_an_accepted_account():
    report = run(contacts={"account_id": "acc-missing"})
    assert ("contacts", "con-1", R.UNKNOWN_ACCOUNT, "account_id") in reject_codes(report)


def test_rejection_cascades_to_dependent_rows():
    # Account rejected -> its contact is rejected -> that contact's opp and touchpoint too.
    report = run(accounts={"account_id": "bad id"})
    assert reject_codes(report) == [
        ("accounts", "bad id", R.INVALID_ID, "account_id"),
        ("contacts", "con-1", R.UNKNOWN_ACCOUNT, "account_id"),
        ("opportunities", "opp-1", R.UNKNOWN_ACCOUNT, "account_id"),
        ("opportunities", "opp-1", R.UNKNOWN_CONTACT, "contact_id"),
        ("touchpoints", "tp-1", R.UNKNOWN_CONTACT, "contact_id"),
    ]


def test_opportunity_contact_must_belong_to_the_opportunity_account():
    rows = valid_rows()
    rows["accounts"].append({"account_id": "acc-2", "name": "Other"})
    rows["opportunities"][0]["account_id"] = "acc-2"
    report = validate_import(ImportBatch.from_rows(**rows))
    assert reject_codes(report) == [
        ("opportunities", "opp-1", R.CONTACT_ACCOUNT_MISMATCH, "contact_id")
    ]


def test_opportunity_without_contact_is_accepted_with_a_warning():
    report = run(opportunities={"contact_id": ""})
    assert report.ok
    assert report.accepted["opportunities"][0].contact_id == ""
    assert (
        "opportunities",
        "opp-1",
        W.OPPORTUNITY_WITHOUT_CONTACT,
    ) in warning_codes(report)


def test_overlong_text_is_rejected():
    report = run(touchpoints={"utm_campaign": "x" * 201})
    assert reject_codes(report) == [("touchpoints", "tp-1", R.VALUE_TOO_LONG, "utm_campaign")]


def test_invalid_email_is_rejected():
    report = run(contacts={"email": "not-an-email"})
    assert reject_codes(report, "contacts") == [("contacts", "con-1", R.INVALID_EMAIL, "email")]


# --- touchpoint warnings -----------------------------------------------------


def test_partially_missing_campaign_fields_warn_but_are_kept_blank():
    report = run(touchpoints={"utm_medium": "", "utm_campaign": ""})
    assert report.ok
    assert report.accepted["touchpoints"][0].medium == ""
    [warning] = report.warnings
    assert (warning.code, warning.field) == (W.MISSING_CAMPAIGN_FIELDS, "utm_medium, utm_campaign")


def test_touchpoint_outside_every_lookback_window_warns():
    # Pipeline window: [2026-01-01T12:00, 2026-04-01T12:00]; won window starts 2026-01-31T12:00.
    report = run(touchpoints={"occurred_at": "2025-12-31T12:00:00Z"})
    assert warning_codes(report) == [("touchpoints", "tp-1", W.TOUCHPOINT_OUTSIDE_LOOKBACK)]


def test_touchpoint_inside_only_the_won_window_does_not_warn():
    report = run(touchpoints={"occurred_at": "2026-04-20T12:00:00Z"})
    assert report.warnings == []


def test_lookback_window_is_configurable():
    batch = ImportBatch.from_rows(**valid_rows())
    # tp-1 is 31 days before creation and 61 days before the win.
    report = validate_import(batch, lookback_days=30)
    assert warning_codes(report) == [("touchpoints", "tp-1", W.TOUCHPOINT_OUTSIDE_LOOKBACK)]


def test_touchpoint_of_contact_without_opportunities_warns():
    report = run(opportunities=[])
    assert warning_codes(report) == [("touchpoints", "tp-1", W.TOUCHPOINT_OUTSIDE_LOOKBACK)]
    assert "no opportunities" in report.warnings[0].message


# --- report shape ------------------------------------------------------------


def test_report_serializes_to_plain_data():
    report = run(accounts={"account_id": "bad id"})
    data = report.to_dict()
    assert data["ok"] is False
    assert data["counts"]["accounts"] == {
        "received": 1,
        "accepted": 0,
        "rejected": 1,
        "duplicates": 0,
    }
    assert data["rejected"][0]["issues"][0]["code"] == "INVALID_ID"
    assert data["lookback_days"] == 90


def test_every_code_has_a_description():
    for code in [*RejectReason, *WarningCode]:
        assert code.description


def test_every_code_and_column_is_documented():
    from pathlib import Path

    from contracts import SCHEMAS

    doc = (Path(__file__).resolve().parent.parent / "docs" / "contract.md").read_text()
    for code in [*RejectReason, *WarningCode]:
        assert f"| `{code}` |" in doc, f"{code} missing from docs/contract.md"
    for entity, columns in SCHEMAS.items():
        assert f"### {entity}.csv" in doc
        for column in columns:
            assert f"| `{column.name}` |" in doc, f"{entity}.{column.name} not documented"
