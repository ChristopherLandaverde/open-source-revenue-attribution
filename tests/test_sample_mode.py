"""Sample mode end to end: load the fixture, render the report, check hand-calculated numbers."""

from decimal import Decimal

import pytest
from django.core.management import call_command

from reports.models import Opportunity, Touchpoint
from reports.services import first_touch_report

pytestmark = pytest.mark.django_db


@pytest.fixture
def sample():
    call_command("load_sample_data", verbosity=0)


def test_load_is_idempotent(sample):
    call_command("load_sample_data", verbosity=0)
    assert Opportunity.objects.count() == 3
    assert Touchpoint.objects.count() == 5


def test_pipeline_first_touch_matches_hand_calculation(sample):
    report = first_touch_report("pipeline")
    assert report.campaign_rows == [
        ("google / cpc / q1-search", "USD", Decimal("12000.00"), 1),
        ("newsletter / email / april-digest", "USD", Decimal("8000.00"), 1),
        ("Unattributed", "USD", Decimal("5000.00"), 1),
    ]
    assert sum(row[2] for row in report.campaign_rows) == Decimal("25000.00")


def test_won_first_touch_matches_hand_calculation(sample):
    report = first_touch_report("won")
    assert report.campaign_rows == [
        ("google / cpc / q1-search", "USD", Decimal("12000.00"), 1),
        ("partner / referral / may-webinar", "USD", Decimal("5000.00"), 1),
    ]


def test_report_page_renders_with_model_and_window(client, sample):
    response = client.get("/")
    html = response.content.decode()
    assert response.status_code == 200
    assert "First-touch" in html
    assert "90 days" in html
    assert "google / cpc / q1-search" in html
    assert "not causal impact" in html
    assert 'hx-get="/"' in html


def test_htmx_request_returns_fragment_only(client, sample):
    response = client.get("/", {"metric": "won"}, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert response.status_code == 200
    assert html.lstrip().startswith('<section id="results"')
    assert "<html" not in html
    assert "partner / referral / may-webinar" in html
    assert "april-digest" not in html


def test_unknown_metric_is_rejected(client):
    assert client.get("/", {"metric": "bogus"}).status_code == 400


def test_empty_state_explains_how_to_load_sample(client):
    response = client.get("/")
    assert "load_sample_data" in response.content.decode()


def test_report_copy_never_claims_causation(client, sample):
    html = client.get("/").content.decode().lower()
    for phrase in ("caused by", "drove revenue", "impact of", "roi"):
        assert phrase not in html
