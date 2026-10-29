"""Sample mode end to end: load the demo fixture and render the first-touch report."""

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
    assert Opportunity.objects.count() == 6
    assert Touchpoint.objects.count() == 15


def test_pipeline_report_reconciles_per_currency(sample):
    # Hand-calculated in sample_data/demo/README.md; exact rows in tests/test_demo_fixture.py.
    rows = first_touch_report("pipeline").campaign_rows
    usd = sum(amount for _, currency, amount, _ in rows if currency == "USD")
    assert usd == Decimal("54000.00")  # 24,000 + 6,000 + 15,000 + 9,000 (Unattributed)


def test_report_page_renders_with_model_and_window(client, sample):
    response = client.get("/")
    html = response.content.decode()
    assert response.status_code == 200
    assert "First-touch" in html
    assert "90 days" in html
    assert "google / cpc / q1-search" in html
    assert "not causal impact" in html
    assert 'hx-get="/"' in html
    assert 'href="/validation/"' in html


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
