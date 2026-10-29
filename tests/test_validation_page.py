"""Validation report page: counts and refused rows with reasons for the last import."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def loaded():
    call_command("load_sample_data", verbosity=0, stderr=StringIO())


def test_empty_state_explains_how_to_load(client):
    response = client.get("/validation/")
    assert response.status_code == 200
    assert "load_sample_data" in response.content.decode()


def test_page_shows_counts_and_refused_rows(client, loaded):
    response = client.get("/validation/")
    html = response.content.decode()
    assert response.status_code == 200
    assert "sample_data/demo" in html
    assert "90-day lookback" in html
    # opportunities.csv: 10 received, 6 accepted, 4 refused
    assert '<th scope="row">opportunities.csv</th><td class="num">10</td>' in html
    assert "INVALID_ID" in html and "acc beta" in html
    assert "CONTACT_ACCOUNT_MISMATCH" in html
    assert "TOUCHPOINT_OUTSIDE_LOOKBACK" not in html.split('id="issues"')[1].split("</table>")[0]
    assert 'hx-get="/validation/"' in html
    assert 'href="/"' in html


def test_code_meanings_are_explained(client, loaded):
    html = client.get("/validation/").content.decode()
    assert "more decimal places than its currency" in html  # AMOUNT_PRECISION


def test_htmx_returns_warnings_fragment(client, loaded):
    response = client.get("/validation/", {"show": "warnings"}, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert html.lstrip().startswith('<section id="issues"')
    assert "<html" not in html
    assert "TOUCHPOINT_OUTSIDE_LOOKBACK" in html
    assert "OPPORTUNITY_WITHOUT_CONTACT" in html
    assert "INVALID_ID" not in html


def test_unknown_filter_is_rejected(client):
    assert client.get("/validation/", {"show": "bogus"}).status_code == 400


def test_refused_strict_import_says_nothing_was_loaded(client):
    with pytest.raises(CommandError):
        call_command("load_sample_data", "--strict", verbosity=0, stderr=StringIO())
    html = client.get("/validation/").content.decode()
    assert "Nothing from this import was loaded" in html
