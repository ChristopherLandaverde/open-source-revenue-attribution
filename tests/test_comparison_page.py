"""The model comparison page (M4): models named with parameters, influence kept apart."""

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def sample():
    call_command("load_sample_data", verbosity=0)


def test_every_model_is_named_with_its_parameters_and_window(client, sample):
    html = client.get("/").content.decode()
    for text in [
        "First-touch",
        "Last-touch",
        "Linear",
        "Position-based (U-shaped)",
        "40% first, 40% last, 20% shared by the touches between",
        "Time decay",
        "Weight halves every 7 days before the conversion",
        "90-day lookback",
        "not causal impact",
    ]:
        assert text in html, text


def test_influence_is_labelled_as_overlapping(client, sample):
    html = client.get("/").content.decode()
    assert 'Influenced <span class="muted">(overlaps)</span>' in html
    assert "Not additive" in html
    assert "never summed" in html


def test_amounts_render_at_minor_unit_per_currency(client, sample):
    html = client.get("/").content.decode()
    assert "9765.76" in html  # time decay, google / cpc / q1-search, USD
    assert "1200000 JPY" in html  # zero-decimal currency, never 1200000.00
    assert "18500.50 EUR" in html


def test_readiness_verdict_comes_first(client, sample):
    html = client.get("/").content.decode()
    assert html.index("Fix data first") < html.index("Credit by campaign")
    assert "5 of 6 opportunities have an eligible touch" in html
    assert 'href="/readiness/?metric=pipeline"' in html


def test_won_fragment(client, sample):
    response = client.get("/", {"metric": "won"}, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert html.lstrip().startswith('<section id="results"')
    assert "14502.70" in html  # time decay, (none) / (none) / (none)


def test_empty_state(client):
    html = client.get("/").content.decode()
    assert "No opportunities yet." in html


def test_unknown_metric_is_400(client):
    assert client.get("/", {"metric": "nope"}).status_code == 400
