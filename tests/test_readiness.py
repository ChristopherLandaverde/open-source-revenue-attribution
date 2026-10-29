"""Data readiness on the demo fixture. Expected counts are hand-calculated from
sample_data/demo/README.md (default: no lookback cap):

pipeline, 6 opportunities
  contact   5/6  opp-104 has no contact (also the one opportunity left out of Influenced)
  tracked   5/5  every opportunity contact has touches
  window    5/5  a touch at or before the conversion: opp-101 tp-01/02, opp-102 tp-04,
                 opp-103 tp-07/08, opp-105 tp-11/12, opp-106 tp-15/14
  utm       8/9  those 9 eligible touches; tp-12 has only utm_source
won, 3 opportunities (opp-101, opp-103, opp-105)
  contact 3/3, tracked 3/3, window 3/3 (tp-01 02 03; tp-07 08 09; tp-11 12 13)
  utm       6/9  tp-09 and tp-13 have no UTMs, tp-12 only utm_source
90-day window, pipeline: utm 6/7 (tp-11 and tp-15 drop out of the window)
import      32 of 42 distinct rows loaded (43 received, 1 exact duplicate), 10 refused
events      not checked: the demo loads no events
"""

import base64
import json
from pathlib import Path

import pytest
from django.core.management import call_command

from collection.models import Workspace
from reports.readiness import NOT_CHECKED, PASS, REVIEW, readiness

pytestmark = pytest.mark.django_db
EVENTS = Path(__file__).resolve().parent.parent / "sample_data" / "events" / "batch.json"
KEY = "test-write-key-0123456789"


def summary(result):
    return {c.key: (c.status, c.count, c.total) for c in result.checks}


@pytest.fixture
def sample():
    call_command("load_sample_data", verbosity=0)


def test_pipeline_readiness_matches_hand_count(sample):
    result = readiness("pipeline")
    assert summary(result) == {
        "contact": (REVIEW, 5, 6),
        "tracked": (PASS, 5, 5),
        "window": (PASS, 5, 5),
        "utm": (REVIEW, 8, 9),
        "import": (REVIEW, 32, 42),
        "events": (NOT_CHECKED, None, None),
        "linked": (NOT_CHECKED, None, None),
    }
    checks = {c.key: c for c in result.checks}
    assert checks["contact"].examples == ["opp-104"]
    assert checks["utm"].examples == ["tp-12"]
    assert "tp-18" in checks["import"].examples
    assert result.opportunities == 6 and result.attributable == 5
    assert result.no_touch == ["opp-104"]
    assert checks["window"].title == "Touches happen before the conversion"
    assert checks["events"].finding == "No events collected yet."


def test_won_readiness_matches_hand_count(sample):
    result = readiness("won")
    assert summary(result)["contact"] == (PASS, 3, 3)
    assert summary(result)["window"] == (PASS, 3, 3)
    assert summary(result)["utm"] == (REVIEW, 6, 9)
    assert {c.key: c for c in result.checks}["utm"].examples == ["tp-09", "tp-12", "tp-13"]
    assert result.no_touch == []


def test_ninety_day_window_readiness(sample, settings):
    settings.ATTRIBUTION_LOOKBACK_DAYS = 90
    checks = {c.key: c for c in readiness("pipeline").checks}
    assert (checks["utm"].count, checks["utm"].total) == (6, 7)
    assert checks["window"].title == "Touches fall inside the lookback window"


def test_every_check_to_fix_has_a_fix_and_a_verification(sample):
    for metric in ("pipeline", "won"):
        for check in readiness(metric).checks:
            assert check.finding
            if check.status == REVIEW:
                assert check.fix and check.verify and check.impact, check.key
            if check.status == PASS:
                assert not check.fix


def test_empty_database_is_not_checked_never_ready():
    result = readiness("pipeline")
    assert {c.status for c in result.checks} == {NOT_CHECKED}
    assert result.touch_period is None


def test_events_checks_count_refused_and_unlinked(client, sample, settings):
    # sample_data/events/README.md: 16 payloads -> 14 distinct accepted events, 1 duplicate,
    # 1 refused (evt-09). Page views not linked to a contact: evt-06 (con-unknown is not
    # imported) and evt-14 (anon-shared identified as two contacts: ambiguous).
    Workspace.objects.create(name="t", write_key=KEY)
    auth = "Basic " + base64.b64encode(f"{KEY}:".encode()).decode()
    client.post(
        "/v1/batch", EVENTS.read_text(), content_type="application/json", HTTP_AUTHORIZATION=auth
    )
    checks = {c.key: c for c in readiness("pipeline").checks}
    assert (checks["events"].status, checks["events"].count, checks["events"].total) == (
        REVIEW,
        14,
        15,
    )
    assert checks["events"].examples == ["evt-09"]
    assert checks["linked"].status == REVIEW
    assert sorted(checks["linked"].examples) == ["evt-06", "evt-14"]


def test_readiness_page_renders_verdict_and_fixes(client, sample):
    html = client.get("/readiness/").content.decode()
    assert "3 checks need a fix" in html
    assert "opp-104" in html
    assert "Fill contact_id" in html
    assert "Not checked" in html
    assert "No events collected yet." in html
    assert "Left out of Influenced, as in Dreamdata: 1 opportunity with no eligible touch" in html
    assert client.get("/readiness/", {"metric": "nope"}).status_code == 400


def test_readiness_json_shape_is_stable(sample):
    # Keys are the contract for the page; adding a check is fine, renaming one is not.
    keys = [c.key for c in readiness("pipeline").checks]
    assert json.dumps(keys) == json.dumps(
        ["contact", "tracked", "window", "utm", "import", "events", "linked"]
    )
