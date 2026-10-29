"""The opportunity journey page (M3): every touch, why it is (in)eligible, and its credit.

Expected values are the demo fixture's hand calculation (sample_data/demo/README.md).
"""

import base64
import json
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from collection.models import Workspace
from reports.models import Opportunity
from reports.services import journey_view

pytestmark = pytest.mark.django_db
KEY = "test-write-key-0123456789"


@pytest.fixture
def sample():
    call_command("load_sample_data", verbosity=0)


def statuses(view):
    """(touch, status, first-touch credit); the first model column is first-touch."""
    return [(r.touchpoint_id, r.status, r.credits[0] if r.credits else None) for r in view.rows]


def all_credits(view):
    return {r.touchpoint_id: r.credits for r in view.rows if r.credits}


D = Decimal


def test_pipeline_journey_matches_the_hand_calculation(sample):
    # opp-101 created 04-01 12:00: tp-01, tp-02 eligible (no cap), tp-03 after.
    view = journey_view(Opportunity.objects.get(external_id="opp-101"), "pipeline")
    assert statuses(view) == [
        ("tp-01", "eligible", Decimal("24000.00")),
        ("tp-02", "eligible", Decimal("0")),
        ("tp-03", "after", None),
    ]
    # Every model's column (sample_data/demo/README.md, model comparison):
    # First, Last, Linear, Position-based, Time decay.
    assert all_credits(view) == {
        "tp-01": [D("24000.00"), D("0"), D("12000.00"), D("12000.00"), D("2265.76")],
        "tp-02": [D("0"), D("24000.00"), D("12000.00"), D("12000.00"), D("21734.24")],
        "tp-03": [None] * 5,
    }
    assert view.eligible_count == 2
    # Colleagues at Northwind are shown but never credited (contract section 5).
    assert view.other_contacts == [("con-nw-li", 1), ("con-nw-raj", 2)]


def test_won_journey_moves_the_window(sample, settings):
    # 90-day window: opp-101 won 06-15 12:00, window from 03-17 12:00: tp-01, tp-02 before it.
    settings.ATTRIBUTION_LOOKBACK_DAYS = 90
    view = journey_view(Opportunity.objects.get(external_id="opp-101"), "won")
    assert statuses(view) == [
        ("tp-01", "before", None),
        ("tp-02", "before", None),
        ("tp-03", "eligible", Decimal("24000.00")),
    ]


def test_won_journey_without_cap_credits_every_touch(sample):
    # No cap: all three touches are eligible for the win (README, won model comparison).
    view = journey_view(Opportunity.objects.get(external_id="opp-101"), "won")
    assert all_credits(view) == {
        "tp-01": [D("24000.00"), D("0"), D("8000.00"), D("9600.00"), D("3.54")],
        "tp-02": [D("0"), D("0"), D("8000.00"), D("4800.00"), D("33.92")],
        "tp-03": [D("0"), D("24000.00"), D("8000.00"), D("9600.00"), D("23962.54")],
    }


def test_tie_and_timezone_boundary_cases(sample, settings):
    # opp-103: tp-07 and tp-08 share an instant; tp-07 wins first-touch by ID.
    view = journey_view(Opportunity.objects.get(external_id="opp-103"), "pipeline")
    assert statuses(view)[:2] == [
        ("tp-07", "eligible", Decimal("15000.00")),
        ("tp-08", "eligible", Decimal("0")),
    ]
    # opp-106 without a cap: tp-15 (one minute earlier) is first; time decay 599979 / 600021.
    view = journey_view(Opportunity.objects.get(external_id="opp-106"), "pipeline")
    assert all_credits(view) == {
        "tp-15": [D("1200000"), D("0"), D("600000"), D("600000"), D("599979")],
        "tp-14": [D("0"), D("1200000"), D("600000"), D("600000"), D("600021")],
    }
    # With a 90-day window: tp-15 is one minute before it, tp-14 exactly at its start.
    settings.ATTRIBUTION_LOOKBACK_DAYS = 90
    view = journey_view(Opportunity.objects.get(external_id="opp-106"), "pipeline")
    assert statuses(view) == [("tp-15", "before", None), ("tp-14", "eligible", Decimal("1200000"))]


def test_journey_page_renders_the_audit_chain(client, sample):
    html = client.get("/opportunities/opp-101/journey/").content.decode()
    assert "2 eligible touches share the full 24000.00 USD; each model splits it" in html
    assert "2026-04-01 12:00 UTC</span> · Pipeline (credited at opportunity creation)" in html
    assert "No lookback cap: every touch up to" in html
    for name in ["First-touch", "Last-touch", "Linear", "Position-based (U-shaped)", "Time decay"]:
        assert name in html
    assert "21734.24" in html
    assert "After the conversion time." in html
    assert "not causal impact" in html
    assert "Total, equal to the opportunity amount" in html
    assert "Other contacts at Northwind Logistics" in html


def test_contactless_opportunity_is_unattributed(client, sample):
    html = client.get("/opportunities/opp-104/journey/").content.decode()
    assert "No contact on this opportunity, so the full 9000.00 USD is Unattributed." in html


def test_open_opportunity_has_no_won_journey(client, sample):
    html = client.get("/opportunities/opp-102/journey/?metric=won").content.decode()
    assert "is still open, so it has no won-revenue journey" in html


def test_htmx_returns_the_fragment_and_errors_are_explicit(client, sample):
    fragment = client.get("/opportunities/opp-101/journey/?metric=won", HTTP_HX_REQUEST="true")
    assert fragment.content.decode().startswith('<section id="results"')
    assert client.get("/opportunities/nope/journey/").status_code == 404
    assert client.get("/opportunities/opp-101/journey/?metric=x").status_code == 400


def test_report_links_each_opportunity_to_its_journey(client, sample):
    html = client.get("/?metric=won").content.decode()
    assert 'href="/opportunities/opp-101/journey/?metric=won"' in html


# --- End to end: anonymous visit with UTMs -> identify -> opportunity -> journey ---------


def post_event(client, event):
    auth = "Basic " + base64.b64encode(f"{KEY}:".encode()).decode()
    path = f"/v1/{event['type']}"
    return client.post(path, json.dumps(event), content_type="application/json",
                       HTTP_AUTHORIZATION=auth)  # fmt: skip


def upload(client, **files):
    data = {
        name: SimpleUploadedFile(f"{name}.csv", text.encode(), content_type="text/csv")
        for name, text in files.items()
    }
    return client.post("/import/", {**data, "action": "upload"})


def landing_view(message_id, at):
    landing = "https://www.acme.example/pricing?utm_source=google&utm_medium=cpc&utm_campaign=oct"
    return {
        "type": "page", "messageId": message_id, "anonymousId": "anon-e2e",
        "timestamp": f"2026-10-01T{at}Z",
        "context": {"page": {"url": landing, "referrer": "https://www.google.com/"},
                    "campaign": {"source": "google", "medium": "cpc", "name": "oct"}},
    }  # fmt: skip


def test_stitched_landing_session_gets_the_credit(client):
    # The M3 live flow: anonymous UTM view -> reload -> back -> identify -> opportunity.
    # Decision #7: all of it is one session, so one credited touch with its views nested.
    Workspace.objects.create(name="demo", write_key=KEY)
    post_event(client, landing_view("e2e-1", "10:00:00"))
    post_event(client, landing_view("e2e-2", "10:00:30"))  # reload: same URL, same UTMs
    post_event(client, {
        "type": "page", "messageId": "e2e-3", "anonymousId": "anon-e2e",
        "timestamp": "2026-10-01T10:02:00Z",
        "context": {"page": {"url": "https://www.acme.example/features",
                             "referrer": "https://www.acme.example/pricing"}, "campaign": {}},
    })  # fmt: skip
    post_event(client, landing_view("e2e-4", "10:03:00"))  # back to the landing page
    post_event(client, {
        "type": "identify", "messageId": "e2e-5", "anonymousId": "anon-e2e",
        "userId": "con-e2e", "timestamp": "2026-10-01T10:05:00Z",
    })  # fmt: skip
    response = upload(
        client,
        accounts="account_id,name,domain\nacc-e2e,E2E Corp,e2e.example\n",
        contacts="contact_id,account_id,email\ncon-e2e,acc-e2e,pat@e2e.example\n",
        opportunities=(
            "opportunity_id,account_id,contact_id,name,amount,currency,stage,created_at,won_at\n"
            "opp-e2e,acc-e2e,con-e2e,E2E pilot,5000.00,USD,open,2026-10-15T09:00:00Z,\n"
        ),
        touchpoints="touchpoint_id,contact_id,occurred_at,utm_source,utm_medium,utm_campaign,"
        "utm_content,utm_term,landing_page,referrer\n",
    )
    assert response.status_code == 302

    view = journey_view(Opportunity.objects.get(external_id="opp-e2e"))
    assert statuses(view) == [
        ("e2e-1", "eligible", Decimal("5000.00")),  # the session, credited to its first view
        ("e2e-2", "in_session", None),  # its page views: shown, never counted again
        ("e2e-3", "in_session", None),
        ("e2e-4", "in_session", None),
    ]
    assert [r.session_id for r in view.rows] == ["e2e-1"] * 4
    assert view.rows[0].stitched_from == "anon-e2e"
    assert view.eligible_count == 1
    html = client.get("/opportunities/opp-e2e/journey/").content.decode()
    assert "One eligible touch gets the full 5000.00 USD under every model." in html
    assert "linked by an identify of" in html and "anon-e2e" in html
    assert "Session 1 · 4 page views" in html
    assert "Part of session 1, started by touch #1; not counted again." in html


def test_contact_without_touches_says_so(client, sample):
    from reports.models import Account, Contact

    contact = Contact.objects.create(external_id="con-new", account=Account.objects.first())
    Opportunity.objects.create(
        external_id="opp-new", account=contact.account, contact=contact, amount=Decimal("10.00"),
        currency="USD", stage="open", created_at="2026-05-01T00:00:00Z",
    )  # fmt: skip
    html = client.get("/opportunities/opp-new/journey/").content.decode()
    assert "has no touches, so the full 10.00 USD is Unattributed." in html
    assert "No touches recorded for" in html
