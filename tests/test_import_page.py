"""CSV upload page: same validation, partial/strict semantics and idempotency as the command."""

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from contracts import ENTITIES, RejectReason, WarningCode
from reports.fixes import FIXES
from reports.models import Account, ImportRun, Opportunity, Touchpoint

pytestmark = pytest.mark.django_db
DEMO = Path(__file__).resolve().parent.parent / "sample_data" / "demo"


def demo_files(**replace):
    files = {}
    for entity in ENTITIES:
        content = replace.get(entity, (DEMO / f"{entity}.csv").read_bytes())
        files[entity] = SimpleUploadedFile(f"{entity}.csv", content, content_type="text/csv")
    return files


def test_form_renders(client):
    html = client.get("/import/").content.decode()
    assert 'enctype="multipart/form-data"' in html
    for entity in ENTITIES:
        assert f'name="{entity}"' in html
    assert "Validate and import files" in html and "Import the demo data set" in html


def test_upload_loads_accepted_rows_and_shows_the_validation_report(client):
    response = client.post("/import/", {**demo_files(), "action": "upload"})
    assert response.status_code == 302 and response["Location"] == "/validation/"
    run = ImportRun.objects.get()
    assert run.loaded and not run.strict
    assert run.source == ("upload: accounts.csv, contacts.csv, opportunities.csv, touchpoints.csv")
    assert run.report["counts"]["opportunities"] == {
        "received": 10,
        "accepted": 6,
        "rejected": 4,
        "duplicates": 0,
    }
    assert Opportunity.objects.count() == 6
    html = client.get("/validation/").content.decode()
    assert "10 rows refused" in html
    assert "AMOUNT_PRECISION" in html


def test_upload_matches_the_command_report(client):
    from io import StringIO

    from django.core.management import call_command

    call_command("load_sample_data", stdout=StringIO(), stderr=StringIO())
    from_command = ImportRun.objects.get().report
    client.post("/import/", {**demo_files(), "action": "upload"})
    from_upload = ImportRun.objects.first().report
    assert from_upload == from_command


def test_reupload_is_idempotent(client):
    client.post("/import/", {**demo_files(), "action": "upload"})
    counts = (Account.objects.count(), Opportunity.objects.count(), Touchpoint.objects.count())
    client.post("/import/", {**demo_files(), "action": "upload"})
    assert counts == (
        Account.objects.count(),
        Opportunity.objects.count(),
        Touchpoint.objects.count(),
    )
    assert ImportRun.objects.count() == 2


def test_strict_upload_refuses_everything(client):
    client.post("/import/", {**demo_files(), "action": "upload", "strict": "on"})
    run = ImportRun.objects.get()
    assert (run.loaded, run.strict) == (False, True)
    assert Account.objects.count() == 0
    assert "Nothing from this import was loaded" in client.get("/validation/").content.decode()


def test_demo_button_imports_the_demo_set(client):
    response = client.post("/import/", {"action": "demo"})
    assert response.status_code == 302
    assert ImportRun.objects.get().source == "sample_data/demo"
    assert Opportunity.objects.count() == 6


def test_missing_files_follow_the_contract(client):
    files = demo_files()
    response = client.post("/import/", {"contacts": files["contacts"], "action": "upload"})
    assert response.status_code == 302
    codes = {i["code"] for i in ImportRun.objects.get().report["file_errors"]}
    assert codes == {"MISSING_FILE"}


def test_no_files_is_a_form_error(client):
    response = client.post("/import/", {"action": "upload"})
    assert response.status_code == 400
    assert "Choose at least one CSV file" in response.content.decode()
    assert not ImportRun.objects.exists()


def test_non_utf8_file_is_a_form_error_and_nothing_imports(client):
    files = demo_files(accounts="account_id,name\nacc-1,Caf\xe9\n".encode("latin-1"))
    response = client.post("/import/", {**files, "action": "upload"})
    assert response.status_code == 400
    assert "is not UTF-8 text" in response.content.decode()
    assert not ImportRun.objects.exists()


def test_every_reason_code_has_a_fix():
    assert set(FIXES) == {str(c) for c in [*RejectReason, *WarningCode]}
