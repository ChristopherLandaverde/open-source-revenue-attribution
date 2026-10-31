"""Read-only JSON API (/api/v1/): same numbers as the pages, token or session auth, GET only.

Equality tests read the HTML view's own context (what the template renders) and compare it to
the JSON for the bundled sample data, with and without the sample events.
"""

import base64
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse

from api.models import ApiToken, hash_token
from api.views import JOURNEY_MEANING, READINESS_MEANING, REPORT_MEANING, model_id
from collection.models import Workspace
from reports.models import Opportunity
from reports.templatetags.money import minor_unit

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "sample_data" / "events" / "batch.json"
KEY = "test-write-key-0123456789"
METRICS = ["pipeline", "won"]
ENDPOINTS = ["/api/v1/attribution", "/api/v1/journeys/opp-101", "/api/v1/readiness"]
OPPORTUNITIES = ["opp-101", "opp-102", "opp-103", "opp-104", "opp-105", "opp-106"]


@pytest.fixture
def sample():
    call_command("load_sample_data", verbosity=0)


@pytest.fixture(params=["csv only", "csv and events"])
def dataset(request, sample, anon_client):
    """The demo CSVs, and the same plus the sample event batch (sessions, stitching, refusals)."""
    if request.param == "csv and events":
        Workspace.objects.create(name="demo", write_key=KEY)
        auth = "Basic " + base64.b64encode(f"{KEY}:".encode()).decode()
        response = anon_client.post(
            "/v1/batch", EVENTS.read_text(), content_type="application/json",
            HTTP_AUTHORIZATION=auth,
        )  # fmt: skip
        assert response.status_code == 200
    return request.param


def when(value):
    """An API time back to a datetime, to compare with the page's (None stays None)."""
    if value is None:
        return None
    assert value.endswith("Z")  # always UTC
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def money(amount, currency):
    return None if amount is None else str(minor_unit(amount, currency))


def page_context(client, path, metric):
    response = client.get(path, {"metric": metric})
    assert response.status_code == 200
    return response.context


def api(client, path, **params):
    response = client.get(path, params)
    assert response.status_code == 200, response.content
    assert response["Content-Type"] == "application/json"
    return response.json()


# --- Same numbers as the HTML views ---------------------------------------------------


@pytest.mark.parametrize("metric", METRICS)
def test_attribution_equals_the_report_page(client, dataset, metric):
    context = page_context(client, "/", metric)
    report, readiness = context["report"], context["readiness"]
    data = api(client, "/api/v1/attribution", metric=metric)

    ids = [model_id(m.name) for m in report.models]
    assert [m["name"] for m in data["models"]] == [m.name for m in report.models]
    assert [m["id"] for m in data["models"]] == ids
    assert data["window"]["lookbackDays"] == report.lookback_days
    assert data["metric"] == {"id": metric, "label": report.metric_label}
    assert len(data["currencies"]) == len(report.blocks)
    for block, cur in zip(report.blocks, data["currencies"], strict=True):
        assert cur["currency"] == block.currency
        assert cur["total"] == money(block.total, block.currency)
        assert cur["opportunities"] == block.opportunities
        assert cur["unattributed"] == money(block.unattributed, block.currency)
        assert len(cur["rows"]) == len(block.rows)
        for row, out in zip(block.rows, cur["rows"], strict=True):
            assert out["campaignKey"] == row.campaign_key
            assert out["unattributed"] == row.unattributed
            assert out["attributed"] == {
                i: money(c, block.currency) for i, c in zip(ids, row.credits, strict=True)
            }
            if row.unattributed:
                assert out["influenced"] is None  # "Not counted" on the page
            else:
                assert out["influenced"] == {
                    "amount": money(row.influenced, block.currency),
                    "opportunities": row.influenced_opportunities,
                }
    assert [o["id"] for o in data["opportunities"]] == [
        r.opportunity.external_id for r in report.opportunities
    ]
    for row, out in zip(report.opportunities, data["opportunities"], strict=True):
        assert out["amount"] == money(row.opportunity.amount, row.opportunity.currency)
        assert out["name"] == row.opportunity.name
        assert out["stage"] == row.opportunity.stage
        assert out["currency"] == row.opportunity.currency
        assert when(out["convertedAt"]) == row.converted_at
        for model, credits in zip(ids, row.credits, strict=True):
            assert out["credits"][model] == [
                {
                    "touchpointId": c.touchpoint_id,
                    "campaignKey": c.campaign_key,
                    "amount": money(c.amount, c.currency),
                }
                for c in credits
            ]
    assert data["dataReadiness"]["attributable"] == readiness.attributable
    assert data["dataReadiness"]["opportunities"] == readiness.opportunities
    assert data["dataReadiness"]["checksToFix"] == [c.key for c in readiness.to_fix]


def test_attribution_values_are_the_rendered_ones(client, sample):
    """Spot checks against amounts the page renders (tests/test_comparison_page.py)."""
    html = client.get("/").content.decode()
    data = api(client, "/api/v1/attribution")
    usd = next(c for c in data["currencies"] if c["currency"] == "USD")
    q1 = next(r for r in usd["rows"] if r["campaignKey"] == "google / cpc / q1-search")
    assert q1["attributed"]["time-decay"] == "9765.76" and "9765.76" in html
    jpy = next(c for c in data["currencies"] if c["currency"] == "JPY")
    assert jpy["total"] == "1200000" and "1200000 JPY" in html
    for cur in data["currencies"]:
        for model in [m["id"] for m in data["models"]]:
            total = sum(minor_unit(r["attributed"][model], cur["currency"]) for r in cur["rows"])
            assert str(total) == cur["total"]  # every model column reconciles


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize("opportunity_id", OPPORTUNITIES)
def test_journey_equals_the_journey_page(client, dataset, metric, opportunity_id):
    view = page_context(client, f"/opportunities/{opportunity_id}/journey/", metric)["view"]
    data = api(client, f"/api/v1/journeys/{opportunity_id}", metric=metric)
    assert data["subject"] == {"type": "opportunity", "id": opportunity_id}
    (journey,) = data["journeys"]
    ids = [model_id(m.name) for m in view.models]
    assert [m["id"] for m in data["models"]] == ids
    cur = view.opportunity.currency
    assert journey["applies"] == (view.journey is not None)
    assert journey["eligibleTouches"] == view.eligible_count
    if view.journey:
        assert journey["unattributed"] == money(view.journey.unattributed, cur)
        assert when(journey["conversionAt"]) == view.journey.conversion.converted_at
        assert when(journey["windowStart"]) == view.journey.window_start
    else:
        assert journey["conversionAt"] is journey["windowStart"] is journey["unattributed"] is None
    assert [t["touchpointId"] for t in journey["touches"]] == [r.touchpoint_id for r in view.rows]
    for row, touch in zip(view.rows, journey["touches"], strict=True):
        assert touch["status"] == row.status
        assert touch["position"] == row.position
        assert touch["campaignKey"] == row.campaign_key
        assert touch["how"] == row.how
        assert touch["window"] == row.window_text
        assert when(touch["occurredAt"]) == row.occurred_at
        assert touch["origin"] == row.origin
        assert touch["landingPage"] == row.landing_page
        assert touch["referrer"] == row.referrer
        assert touch["stitchedFrom"] == (row.stitched_from or None)
        if row.session_id:
            assert touch["session"] == {
                "id": row.session_id,
                "number": row.session_number,
                "pageViews": row.session_size or None,
            }
        else:
            assert touch["session"] is None
        if row.status == "in_session":
            assert set(touch["credits"].values()) == {None}  # "—" on the page
        else:
            assert touch["credits"] == {
                i: money(c, cur) for i, c in zip(ids, row.credits, strict=True)
            }
    assert journey["otherContacts"] == [
        {"contactId": c, "touchpoints": n, "credited": False} for c, n in view.other_contacts
    ]


def test_journey_credits_sum_to_the_amount(client, sample):
    (journey,) = api(client, "/api/v1/journeys/opp-101")["journeys"]
    for model in ["first-touch", "last-touch", "linear", "position-based-u-shaped", "time-decay"]:
        credits = [t["credits"][model] for t in journey["touches"] if t["credits"][model]]
        assert sum(minor_unit(c, "USD") for c in credits) == minor_unit("24000", "USD")
    assert journey["touches"][0]["credits"]["first-touch"] == "24000.00"


def test_account_id_returns_each_opportunitys_journey(client, sample):
    data = api(client, "/api/v1/journeys/acc-umbra", metric="won")
    assert data["subject"] == {"type": "account", "id": "acc-umbra", "name": "Umbra Health"}
    assert [j["opportunity"]["id"] for j in data["journeys"]] == ["opp-103", "opp-104"]
    single = api(client, "/api/v1/journeys/opp-103", metric="won")["journeys"][0]
    assert data["journeys"][0] == single
    assert data["journeys"][1]["applies"] is False  # opp-104 is open: no won journey


def test_opportunity_id_wins_over_an_account_with_the_same_id(client, sample):
    from reports.models import Account

    Account.objects.create(external_id="opp-101", name="Same ID as an opportunity")
    assert api(client, "/api/v1/journeys/opp-101")["subject"]["type"] == "opportunity"


def test_account_journey_converts_events_once(client, dataset, monkeypatch):
    """Collected events are read once per request, however many opportunities the account has."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    import collection.services
    import reports.services

    calls = []
    real = collection.services.convert_events

    def counted():
        calls.append(1)
        return real()

    monkeypatch.setattr("api.views.convert_events", counted)
    monkeypatch.setattr(reports.services, "convert_events", counted)
    with CaptureQueriesContext(connection) as queries:
        data = api(client, "/api/v1/journeys/acc-northwind")
    assert [j["opportunity"]["id"] for j in data["journeys"]] == ["opp-101", "opp-102"]
    assert len(calls) == 1
    event_reads = [q for q in queries if "collection_collectedevent" in q["sql"]]
    assert len(event_reads) == 1, [q["sql"] for q in event_reads]
    # Each opportunity's journey is still what its own endpoint returns.
    for journey in data["journeys"]:
        single = api(client, f"/api/v1/journeys/{journey['opportunity']['id']}")
        assert single["journeys"] == [journey]


@pytest.mark.parametrize("metric", METRICS)
def test_readiness_equals_the_readiness_page(client, dataset, metric):
    view = page_context(client, "/readiness/", metric)["view"]
    data = api(client, "/api/v1/readiness", metric=metric)
    assert data["opportunities"] == view.opportunities
    assert data["attributable"] == view.attributable
    assert data["noEligibleTouch"] == view.no_touch
    assert data["verdict"] == "fix_data_first"  # the demo data has refused rows
    assert [
        (c["key"], c["title"], c["status"], c["count"], c["total"], c["percent"], c["finding"])
        for c in data["checks"]
    ] == [(c.key, c.title, c.status, c.count, c.total, c.percent, c.finding) for c in view.checks]
    assert [c["examples"] for c in data["checks"]] == [list(c.examples) for c in view.checks]
    assert [(c["fix"], c["impact"], c["verify"]) for c in data["checks"]] == [
        (c.fix, c.impact, c.verify) for c in view.checks
    ]
    assert [c["evidence"] for c in data["checks"]] == [
        reverse(c.link) if c.link else None for c in view.checks
    ]
    assert (data["touchPeriod"] is None) == (view.touch_period is None)
    if view.touch_period:
        assert when(data["touchPeriod"]["from"]) == view.touch_period[0]
        assert when(data["touchPeriod"]["to"]) == view.touch_period[1]
    assert when(data["conversionPeriod"]["from"]) == view.conversion_period[0]
    assert when(data["conversionPeriod"]["to"]) == view.conversion_period[1]


def test_readiness_on_an_empty_dataset(client):
    data = api(client, "/api/v1/readiness")
    assert data["verdict"] == "not_checked"
    assert {c["status"] for c in data["checks"]} == {"not_checked"}


# --- Model filter and parameters -----------------------------------------------------


def test_model_filter_returns_one_models_columns(client, sample):
    full = api(client, "/api/v1/attribution")
    for wanted in ["linear", "Linear", "position-based-u-shaped", "Position-based (U-shaped)"]:
        data = api(client, "/api/v1/attribution", model=wanted)
        (model,) = data["models"]
        assert wanted in (model["id"], model["name"])
        for cur, full_cur in zip(data["currencies"], full["currencies"], strict=True):
            for row, full_row in zip(cur["rows"], full_cur["rows"], strict=True):
                assert row["attributed"] == {model["id"]: full_row["attributed"][model["id"]]}
    (journey,) = api(client, "/api/v1/journeys/opp-101", model="first-touch")["journeys"]
    assert set(journey["touches"][0]["credits"]) == {"first-touch"}


@pytest.mark.parametrize(
    ("path", "params", "code"),
    [
        ("/api/v1/attribution", {"model": "data-driven"}, "unknown_model"),
        ("/api/v1/attribution", {"metric": "nope"}, "unknown_metric"),
        ("/api/v1/attribution", {"start": "2026-01-01"}, "unknown_parameter"),
        ("/api/v1/readiness", {"model": "linear"}, "unknown_parameter"),
        ("/api/v1/journeys/opp-101", {"metric": "lost"}, "unknown_metric"),
    ],
)
def test_bad_parameters_are_400_with_a_reason(client, sample, path, params, code):
    response = client.get(path, params)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    assert response.json()["schemaVersion"] == "1"


def test_unknown_journey_is_404(client, sample):
    response = client.get("/api/v1/journeys/opp-999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- Meaning: the pages' own wording --------------------------------------------------


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


@pytest.mark.parametrize(
    ("endpoint", "meaning", "page"),
    [
        ("/api/v1/attribution", REPORT_MEANING, "/"),
        ("/api/v1/journeys/opp-101", JOURNEY_MEANING, "/opportunities/opp-101/journey/"),
        ("/api/v1/readiness", READINESS_MEANING, "/readiness/"),
    ],
)
def test_meaning_reuses_the_pages_wording(client, sample, endpoint, meaning, page):
    assert api(client, endpoint)["meaning"] == meaning
    assert "association under" in meaning and "not causal impact" in meaning
    pages = (
        _text(client.get(page).content.decode())
        + " "
        + _text(client.get("/opportunities/opp-101/journey/").content.decode())
    )
    for sentence in re.split(r"(?<=\.) ", meaning):
        assert sentence in pages, sentence


# --- Auth --------------------------------------------------------------------------


@pytest.fixture
def token(django_user_model):
    user = django_user_model.objects.create_user(username="agent-owner", password="x-pw-12345")
    return ApiToken.issue(user, "agent")[1]


def bearer(value):
    return {"HTTP_AUTHORIZATION": f"Bearer {value}"}


@pytest.mark.parametrize("path", ENDPOINTS)
def test_anonymous_is_refused_without_data(anon_client, sample, path):
    response = anon_client.get(path)
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="osra"'
    assert set(response.json()) == {"schemaVersion", "error"}


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize(
    "header",
    [
        "Bearer osra_not-a-real-token",
        "Bearer ",
        "Basic " + base64.b64encode(b"agent-owner:x-pw-12345").decode(),
        "Token whatever",
    ],
)
def test_bad_credentials_are_refused(anon_client, sample, token, path, header):
    response = anon_client.get(path, HTTP_AUTHORIZATION=header)
    assert response.status_code == 401
    assert "error" in response.json() and "currencies" not in response.json()


@pytest.mark.parametrize("path", ENDPOINTS)
def test_valid_token_succeeds(anon_client, sample, token, path):
    response = anon_client.get(path, **bearer(token))
    assert response.status_code == 200
    assert response.json()["schemaVersion"] == "1"
    assert "no-store" in response["Cache-Control"]
    assert ApiToken.objects.get().last_used_at is not None


@pytest.mark.parametrize("path", ENDPOINTS)
def test_signed_in_session_succeeds(client, sample, path):
    assert client.get(path).status_code == 200


def test_a_wrong_token_is_refused_even_with_a_session(client, sample):
    assert client.get("/api/v1/readiness", **bearer("osra_wrong")).status_code == 401


@pytest.mark.parametrize("header", ["Basic " + base64.b64encode(b"x:y").decode(), "Token whatever"])
def test_other_authorization_schemes_fall_back_to_the_session(client, sample, header):
    assert client.get("/api/v1/readiness", HTTP_AUTHORIZATION=header).status_code == 200


def test_last_used_is_marked_only_after_validation_and_at_most_once_a_minute(
    anon_client, sample, token
):
    record = ApiToken.objects.get()
    assert anon_client.get("/api/v1/readiness", {"start": "x"}, **bearer(token)).status_code == 400
    assert anon_client.get("/api/v1/readiness", {"metric": "x"}, **bearer(token)).status_code == 400
    record.refresh_from_db()
    assert record.last_used_at is None
    assert anon_client.get("/api/v1/readiness", **bearer(token)).status_code == 200
    record.refresh_from_db()
    first = record.last_used_at
    assert first is not None
    assert anon_client.get("/api/v1/readiness", **bearer(token)).status_code == 200
    record.refresh_from_db()
    assert record.last_used_at == first  # within a minute: not written again
    ApiToken.objects.update(last_used_at=first - timedelta(minutes=2))
    assert anon_client.get("/api/v1/readiness", **bearer(token)).status_code == 200
    record.refresh_from_db()
    assert record.last_used_at > first - timedelta(minutes=2)


def test_inactive_users_token_is_refused(anon_client, sample, token):
    ApiToken.objects.get().user.__class__.objects.update(is_active=False)
    assert anon_client.get("/api/v1/readiness", **bearer(token)).status_code == 401


def test_revoked_token_is_refused(anon_client, sample, token):
    ApiToken.objects.all().delete()
    assert anon_client.get("/api/v1/readiness", **bearer(token)).status_code == 401


def test_only_the_hash_is_stored(token):
    record = ApiToken.objects.get()
    assert token.startswith("osra_") and len(token) > 40
    assert record.token_hash == hash_token(token) and token not in record.token_hash
    assert token.startswith(record.prefix)


def test_createapitoken_prints_a_working_token(anon_client, sample, django_user_model, capsys):
    django_user_model.objects.create_user(username="ops", password="x-pw-12345")
    call_command("createapitoken", "ops", "--name", "claude")
    out = capsys.readouterr().out
    token = re.search(r"Token: (osra_\S+)", out).group(1)
    assert ApiToken.objects.get().name == "claude"
    assert "Authorization: Bearer <token>" in out
    assert out.count(token) == 1  # printed once, never echoed in part
    assert anon_client.get("/api/v1/attribution", **bearer(token)).status_code == 200


def test_createapitoken_refuses_unknown_and_inactive_users(django_user_model):
    with pytest.raises(CommandError, match="No user"):
        call_command("createapitoken", "nobody")
    django_user_model.objects.create_user(username="gone", password="x", is_active=False)
    with pytest.raises(CommandError, match="inactive"):
        call_command("createapitoken", "gone")
    assert not ApiToken.objects.exists()


# --- Read-only ---------------------------------------------------------------------


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete", "options", "trace"])
def test_every_other_method_is_405(anon_client, sample, token, path, method):
    response = getattr(anon_client, method)(path, **bearer(token))
    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD"
    assert ApiToken.objects.get().last_used_at is None  # refused before the token is marked used
    assert Opportunity.objects.count() == 6  # nothing changed


@pytest.mark.parametrize("path", ENDPOINTS)
def test_head_is_allowed(anon_client, sample, token, path):
    response = anon_client.head(path, **bearer(token))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert anon_client.head(path).status_code == 401


def test_write_method_with_session_and_no_csrf_token_is_405_not_a_write(sample, django_user_model):
    from django.test import Client

    user = django_user_model.objects.create_user(username="csrf", password="x-pw-12345")
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(user)
    assert strict.post("/api/v1/attribution").status_code == 405


@pytest.mark.parametrize("path", ENDPOINTS)
def test_cors_is_not_widened(anon_client, sample, token, path):
    response = anon_client.get(path, HTTP_ORIGIN="https://evil.example", **bearer(token))
    assert "Access-Control-Allow-Origin" not in response


# --- Schema pinning ----------------------------------------------------------------


def shape(value):
    """Keys and value types, recursively; a list's items must all share one shape."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        shapes = [shape(v) for v in value]
        merged = _merge(shapes)
        return [merged] if shapes else []
    return type(value).__name__


def _merge(shapes):
    """Merge item shapes; a field that is null in some items and typed in others is 'T|None'."""
    if not shapes:
        return None
    # An object that is null in some items: {"or None": <its shape>}.
    nullable_object = any(isinstance(s, dict) and list(s) == ["or None"] for s in shapes)
    shapes = [s["or None"] if isinstance(s, dict) and list(s) == ["or None"] else s for s in shapes]
    typed = [s for s in shapes if s != "NoneType"]
    if typed and all(isinstance(s, dict) for s in typed):
        if nullable_object or len(typed) < len(shapes):
            return {"or None": _merge(typed)}
    first = shapes[0]
    if all(isinstance(s, dict) for s in shapes):
        keys = list(first)
        assert all(list(s) == keys for s in shapes), "list items have different keys"
        return {k: _merge([s[k] for s in shapes]) for k in keys}
    if all(isinstance(s, list) for s in shapes):
        inner = [s[0] for s in shapes if s]
        return [_merge(inner)] if inner else []
    names = sorted({s for s in shapes if isinstance(s, str)} - {"NoneType"})
    nullable = any(s == "NoneType" for s in shapes)
    return "|".join(names) + ("|None" if nullable else "") if names else "NoneType"


MODEL = {"id": "str", "name": "str", "parameters": "str", "standard": "str"}
CREDITS = dict.fromkeys(
    ["first-touch", "last-touch", "linear", "position-based-u-shaped", "time-decay"]
)
HEADER = {
    "schemaVersion": "str",
    "meaning": "str",
    "metric": {"id": "str", "label": "str"},
    "window": {"lookbackDays": "NoneType", "description": "str"},
    "models": [MODEL],
}


def test_attribution_schema_is_pinned(client, sample):
    data = api(client, "/api/v1/attribution")
    assert data["schemaVersion"] == "1"
    assert shape(data) == {
        **HEADER,
        "influenced": {"definition": "str", "additive": "bool"},
        "dataReadiness": {
            "opportunities": "int",
            "attributable": "int",
            "checksToFix": ["str"],
            "details": "str",
        },
        "currencies": [
            {
                "currency": "str",
                "total": "str",
                "opportunities": "int",
                "unattributed": "str",
                "rows": [
                    {
                        "campaignKey": "str",
                        "unattributed": "bool",
                        "attributed": dict.fromkeys(CREDITS, "str"),
                        "influenced": {"or None": {"amount": "str", "opportunities": "int"}},
                    }
                ],
            }
        ],
        "opportunities": [
            {
                "id": "str",
                "name": "str",
                "amount": "str",
                "currency": "str",
                "stage": "str",
                "convertedAt": "str",
                "journey": "str",
                "credits": dict.fromkeys(
                    CREDITS,
                    [{"touchpointId": "str|None", "campaignKey": "str", "amount": "str"}],
                ),
            }
        ],
        "links": {"page": "str"},
    }


def test_journey_schema_is_pinned(client, dataset):
    data = api(client, "/api/v1/journeys/acc-kestrel")  # page events, sessions and stitching
    assert data["schemaVersion"] == "1"
    touch = {
        "position": "int",
        "touchpointId": "str",
        "occurredAt": "str",
        "origin": "str",
        "campaignKey": "str",
        "landingPage": "str",
        "referrer": "str",
        "status": "str",
        "how": "str",
        "window": "str",
        "stitchedFrom": "NoneType",
        "session": "NoneType"
        if dataset == "csv only"
        else {"or None": {"id": "str", "number": "int", "pageViews": "int|None"}},
        "credits": dict.fromkeys(CREDITS, "str|None"),
    }
    assert shape(data) == {
        **HEADER,
        "subject": {"type": "str", "id": "str", "name": "str"},
        "journeys": [
            {
                "opportunity": {
                    "id": "str",
                    "name": "str",
                    "stage": "str",
                    "amount": "str",
                    "currency": "str",
                    "account": {"id": "str", "name": "str"},
                    "contactId": "str",
                },
                "applies": "bool",
                "conversionAt": "str",
                "windowStart": "NoneType",
                "eligibleTouches": "int",
                "unattributed": "str",
                "touches": [touch],
                "otherContacts": [],
                "links": {"page": "str"},
            }
        ],
    }


def test_readiness_schema_is_pinned(client, sample):
    data = api(client, "/api/v1/readiness")
    assert data["schemaVersion"] == "1"
    period = {"from": "str", "to": "str"}
    assert shape(data) == {
        **HEADER,
        "verdict": "str",
        "opportunities": "int",
        "attributable": "int",
        "noEligibleTouch": ["str"],
        "touchPeriod": period,
        "conversionPeriod": period,
        "checks": [
            {
                "key": "str",
                "title": "str",
                "status": "str",
                "count": "int|None",
                "total": "int|None",
                "percent": "int|None",
                "finding": "str",
                "impact": "str",
                "fix": "str",
                "verify": "str",
                "examples": ["str"],
                "evidence": "str|None",
            }
        ],
        "links": {"page": "str"},
    }
    assert {c["status"] for c in data["checks"]} <= {"pass", "review", "not_checked"}
    assert data["verdict"] in {"fix_data_first", "ready", "not_checked"}


def test_api_urls_are_named(sample):
    assert reverse("api:attribution") == "/api/v1/attribution"
    assert reverse("api:readiness") == "/api/v1/readiness"
    assert reverse("api:journey", args=["opp-101"]) == "/api/v1/journeys/opp-101"
