"""load_sample_data validates first and refuses invalid rows with a clear message."""

import shutil
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from reports.models import Account, ImportRun, Opportunity, Touchpoint

pytestmark = pytest.mark.django_db
DEMO = Path(__file__).resolve().parent.parent / "sample_data" / "demo"


def load(*args):
    out, err = StringIO(), StringIO()
    call_command("load_sample_data", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_invalid_rows_are_listed_with_reason_codes_and_not_loaded():
    out, err = load()
    assert "10 refused" in out
    assert "accounts.csv row 6 [acc beta]: INVALID_ID account_id" in err
    assert "opportunities.csv row 11 [opp-110]: INVALID_CURRENCY currency" in err
    assert "touchpoints.csv row 17 [tp-16]: TIMESTAMP_WITHOUT_TIMEZONE occurred_at" in err
    assert "Loaded 4 accounts, 7 contacts, 6 opportunities, 15 touchpoints" in out
    assert not Account.objects.filter(external_id="acc beta").exists()
    assert not Opportunity.objects.filter(external_id__in=["opp-107", "opp-110"]).exists()
    assert not Touchpoint.objects.filter(external_id="tp-18").exists()


def test_timestamps_are_stored_in_utc():
    load()
    tp = Touchpoint.objects.get(external_id="tp-14")  # 2026-02-04T00:00:00+09:00 in the CSV
    assert tp.occurred_at.isoformat() == "2026-02-03T15:00:00+00:00"


def test_opportunity_without_contact_is_loaded_against_its_account():
    load()
    opp = Opportunity.objects.get(external_id="opp-104")
    assert opp.contact is None
    assert opp.account.external_id == "acc-umbra"


def test_each_load_records_its_validation_report():
    load()
    run = ImportRun.objects.get()
    assert run.loaded is True
    assert run.source == "sample_data/demo"
    assert run.lookback_days == 90
    assert run.report["counts"]["opportunities"]["rejected"] == 4


def test_strict_refuses_the_whole_import():
    with pytest.raises(CommandError, match=r"Refused the whole import \(--strict\)"):
        load("--strict")
    assert Account.objects.count() == 0
    run = ImportRun.objects.get()
    assert (run.loaded, run.strict) == (False, True)


def test_strict_loads_a_clean_directory(tmp_path):
    for name in ("accounts", "contacts", "opportunities", "touchpoints"):
        shutil.copy(DEMO / f"{name}.csv", tmp_path)
    (tmp_path / "accounts.csv").write_text(
        "account_id,name,domain\nacc-1,One,one.example\n", encoding="utf-8"
    )
    (tmp_path / "contacts.csv").write_text("contact_id,account_id,email\ncon-1,acc-1,\n")
    (tmp_path / "opportunities.csv").write_text(
        "opportunity_id,account_id,contact_id,name,amount,currency,stage,created_at,won_at\n"
        "opp-1,acc-1,con-1,Deal,100.00,USD,open,2026-04-01T12:00:00Z,\n"
    )
    (tmp_path / "touchpoints.csv").write_text(
        "touchpoint_id,contact_id,occurred_at,utm_source,utm_medium,utm_campaign\n"
        "tp-1,con-1,2026-03-01T12:00:00Z,google,cpc,spring\n"
    )
    out, err = load("--strict", "--path", str(tmp_path))
    assert err == ""
    assert "Loaded 1 accounts, 1 contacts, 1 opportunities, 1 touchpoints" in out


def test_missing_file_is_reported_and_its_dependents_refused(tmp_path):
    (tmp_path / "contacts.csv").write_text("contact_id,account_id,email\ncon-1,acc-1,\n")
    out, err = load("--path", str(tmp_path))
    assert "accounts.csv: MISSING_FILE" in err
    assert "contacts.csv row 2 [con-1]: UNKNOWN_ACCOUNT account_id" in err


def test_path_must_be_a_directory(tmp_path):
    with pytest.raises(CommandError, match="not a directory"):
        load("--path", str(tmp_path / "nope"))
