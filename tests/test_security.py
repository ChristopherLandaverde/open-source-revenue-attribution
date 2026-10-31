"""M5 security: pages need a login, /v1/ keeps write-key auth, CORS allowlist, deploy checks."""

import base64
import json
import re
from pathlib import Path

import pytest
from django.core.checks import WARNING, run_checks
from django.core.management import call_command
from django.urls import reverse

from collection.models import CollectedEvent, Workspace

pytestmark = pytest.mark.django_db
KEY = "test-write-key-0123456789"
ALLOWED = "https://www.acme.example"
OTHER = "https://evil.example"
ROOT = Path(__file__).resolve().parent.parent
SDK_FILE = "rudderstack-analytics-js-3.35.0.bundled.umd.js"

PAGES = [
    "/",
    "/?metric=won",
    "/readiness/",
    "/validation/",
    "/import/",
    "/events/",
    "/events/demo/",
    "/opportunities/opp-101/journey/",
]


@pytest.fixture
def workspace():
    return Workspace.objects.create(name="demo", write_key=KEY)


def auth(key=KEY):
    return {"HTTP_AUTHORIZATION": "Basic " + base64.b64encode(f"{key}:".encode()).decode()}


def event(message_id="m-sec-1"):
    return {
        "type": "track",
        "event": "Signed Up",
        "messageId": message_id,
        "anonymousId": "anon-sec",
        "originalTimestamp": "2026-09-10T10:00:00.000Z",
        "sentAt": "2026-09-10T10:00:01.000Z",
    }


def send(client, body=None, **headers):
    data = json.dumps({"batch": [body or event()]})
    return client.post("/v1/batch", data, content_type="application/json", **headers)


# --- Login required ---------------------------------------------------------------------


@pytest.mark.parametrize("path", PAGES)
def test_every_page_redirects_anonymous_visitors_to_login(anon_client, path):
    response = anon_client.get(path)
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login") + "?next=")


def test_import_post_is_refused_without_login(anon_client):
    response = anon_client.post("/import/", {"action": "demo"})
    assert response.status_code == 302
    assert not CollectedEvent.objects.exists()
    from reports.models import ImportRun

    assert not ImportRun.objects.exists()


def test_signed_in_user_sees_pages(client):
    assert client.get("/").status_code == 200
    page = client.get("/readiness/").content.decode()
    assert "Signed in as" in page and "analyst" in page and "Sign out" in page


def test_login_page_is_public_and_signs_in(anon_client, django_user_model):
    django_user_model.objects.create_user(username="owner", password="a-long-test-pw-42")
    page = anon_client.get(reverse("login"))
    assert page.status_code == 200
    assert "Sign in" in page.content.decode()
    assert "Model comparison" not in page.content.decode()  # no nav before sign-in

    response = anon_client.post(
        reverse("login"),
        {"username": "owner", "password": "a-long-test-pw-42", "next": "/readiness/"},
    )
    assert response.status_code == 302 and response["Location"] == "/readiness/"
    assert anon_client.get("/readiness/").status_code == 200


def test_wrong_password_shows_an_error(anon_client, django_user_model):
    django_user_model.objects.create_user(username="owner", password="a-long-test-pw-42")
    response = anon_client.post(reverse("login"), {"username": "owner", "password": "nope"})
    assert response.status_code == 200
    assert "didn't match" in response.content.decode()


def test_sign_out_needs_post_and_ends_the_session(client):
    response = client.post(reverse("logout"))
    assert response.status_code == 302 and response["Location"] == reverse("login")
    assert client.get("/").status_code == 302


def test_health_check_is_public(anon_client):
    response = anon_client.get("/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_first_admin_can_be_created_non_interactively(monkeypatch, django_user_model):
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "a-long-test-pw-42")
    call_command(
        "createsuperuser", "--noinput", "--username", "admin", "--email", "admin@acme.example"
    )
    assert django_user_model.objects.get(username="admin").is_superuser


# --- Collection keeps write-key auth --------------------------------------------------------


def test_collection_works_without_login_with_a_write_key(anon_client, workspace):
    response = send(anon_client, **auth())
    assert response.status_code == 200
    assert response.json()["accepted"] == 1


def test_collection_without_a_write_key_is_401_not_a_login_redirect(anon_client, workspace):
    response = send(anon_client)
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Basic")


# --- CORS -----------------------------------------------------------------------------------


def test_server_side_senders_need_no_origin(anon_client, workspace):
    response = send(anon_client, **auth())
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response


def test_any_origin_is_allowed_by_default(anon_client, workspace):
    """The industry default (Plausible, Umami, PostHog): browser events from any site."""
    preflight = anon_client.options(
        "/v1/batch", HTTP_ORIGIN=OTHER, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST"
    )
    assert preflight.status_code == 204
    assert preflight["Access-Control-Allow-Origin"] == OTHER  # echoed, never a literal "*"

    response = send(anon_client, HTTP_ORIGIN=OTHER, **auth())
    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    assert response["Access-Control-Allow-Origin"] == OTHER


def test_any_origin_still_needs_a_write_key(anon_client, workspace):
    response = send(anon_client, HTTP_ORIGIN=OTHER)
    assert response.status_code == 401
    assert not CollectedEvent.objects.exists()


def test_empty_list_allows_same_origin_only(anon_client, workspace, settings):
    settings.COLLECT_ALLOWED_ORIGINS = []
    assert anon_client.options("/v1/batch", HTTP_ORIGIN=ALLOWED).status_code == 403
    response = send(anon_client, HTTP_ORIGIN=ALLOWED, **auth())
    assert response.status_code == 403
    assert "COLLECT_ALLOWED_ORIGINS" in response.json()["error"]
    assert send(anon_client, HTTP_ORIGIN="http://testserver", **auth()).status_code == 200


def test_same_origin_browser_requests_are_allowed(anon_client, workspace, settings):
    settings.COLLECT_ALLOWED_ORIGINS = [ALLOWED]
    response = send(anon_client, HTTP_ORIGIN="http://testserver", **auth())
    assert response.status_code == 200
    assert response.json()["accepted"] == 1


def test_allowed_origin_gets_preflight_and_cors_headers(anon_client, workspace, settings):
    settings.COLLECT_ALLOWED_ORIGINS = [ALLOWED + "/"]  # a trailing slash is tolerated
    preflight = anon_client.options(
        "/v1/batch",
        HTTP_ORIGIN=ALLOWED,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization, content-type, anonymousid",
    )
    assert preflight.status_code == 204
    assert preflight["Access-Control-Allow-Origin"] == ALLOWED
    assert "POST" in preflight["Access-Control-Allow-Methods"]
    allowed_headers = preflight["Access-Control-Allow-Headers"].lower()
    assert {"authorization", "content-type", "anonymousid"} <= {
        h.strip() for h in allowed_headers.split(",")
    }
    assert "Access-Control-Allow-Credentials" not in preflight
    assert "Origin" in preflight["Vary"]

    response = send(anon_client, HTTP_ORIGIN=ALLOWED, **auth())
    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    assert response["Access-Control-Allow-Origin"] == ALLOWED


def _sdk_request_headers() -> set[str]:
    """Header names the vendored RudderStack SDK sets on its event requests."""
    sdk = (ROOT / "static" / "vendor" / SDK_FILE).read_text(encoding="utf-8")
    names = set(re.findall(r"headers\['(Rsa-[A-Za-z-]+)'\]", sdk))
    names |= set(re.findall(r"headers\.([A-Z][A-Za-z]+)=", sdk))
    names |= set(re.findall(r"const headers=\{[^}]*?\b([A-Z][A-Za-z]+):", sdk))
    return {"Authorization", "Content-Type", *names}


def test_preflight_allows_every_header_the_sdk_sends(anon_client, workspace):
    """Cross-origin SDK delivery: rudder-server allows any request header (rs/cors "*").

    SDK 3.35.0 adds SentAt on every request and Rsa-Retry-*/Rsa-Since-* on retries; a preflight
    that refuses one of them blocks the event in the browser before it is sent.
    """
    sdk_headers = _sdk_request_headers()
    assert {"AnonymousId", "SentAt", "Rsa-Retry-Attempt", "Rsa-Since-Last-Attempt"} <= sdk_headers
    requested = ",".join(sorted(h.lower() for h in sdk_headers))
    preflight = anon_client.options(
        "/v1/page",
        HTTP_ORIGIN=OTHER,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS=requested,
    )
    assert preflight.status_code == 204
    allowed = {h.strip() for h in preflight["Access-Control-Allow-Headers"].lower().split(",")}
    assert {h.lower() for h in sdk_headers} <= allowed
    assert "Access-Control-Request-Headers" in preflight["Vary"]


def test_preflight_echoes_only_valid_header_names(anon_client, workspace):
    preflight = anon_client.options(
        "/v1/batch",
        HTTP_ORIGIN=OTHER,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization, bad header, x-ok",
    )
    assert preflight["Access-Control-Allow-Headers"] == "authorization, x-ok"


def test_allowed_origin_still_needs_a_write_key(anon_client, workspace, settings):
    settings.COLLECT_ALLOWED_ORIGINS = [ALLOWED]
    response = send(anon_client, HTTP_ORIGIN=ALLOWED, **auth("wrong-key-0123456789"))
    assert response.status_code == 401
    # Readable by the allowed page, so the SDK can report the problem.
    assert response["Access-Control-Allow-Origin"] == ALLOWED


def test_unlisted_origin_is_refused_when_others_are_allowed(anon_client, workspace, settings):
    settings.COLLECT_ALLOWED_ORIGINS = [ALLOWED]
    assert anon_client.options("/v1/batch", HTTP_ORIGIN=OTHER).status_code == 403
    response = send(anon_client, HTTP_ORIGIN=OTHER, **auth())
    assert response.status_code == 403
    assert "Access-Control-Allow-Origin" not in response
    assert not CollectedEvent.objects.exists()


def test_get_on_the_endpoint_is_405(anon_client, workspace):
    assert anon_client.get("/v1/batch").status_code == 405


# --- Deployment checks ----------------------------------------------------------------------


def deploy_ids():
    return {issue.id for issue in run_checks(include_deployment_checks=True)}


def test_deploy_checks_flag_unsafe_settings(settings):
    settings.ALLOWED_HOSTS = ["*"]
    settings.COLLECT_ALLOWED_ORIGINS = ["*"]
    settings.COLLECT_DEMO_PAGE = True
    settings.HTTPS = False
    ids = deploy_ids()
    assert {"osra.W001", "osra.W003", "osra.W005"} <= ids
    sqlite = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")
    assert ("osra.W004" in ids) == sqlite  # tests may run on PostgreSQL (TEST_DATABASE_URL)


def test_deploy_checks_quiet_for_a_safe_configuration(settings):
    settings.ALLOWED_HOSTS = ["attribution.acme.example"]
    settings.COLLECT_ALLOWED_ORIGINS = [ALLOWED]
    settings.COLLECT_DEMO_PAGE = False
    settings.HTTPS = True
    ids = deploy_ids()
    assert not {"osra.W001", "osra.W003", "osra.W005", "osra.I001"} & ids


def test_unrestricted_origins_are_reported_as_info_not_a_failure(settings):
    settings.COLLECT_ALLOWED_ORIGINS = ["*"]
    issues = [i for i in run_checks(include_deployment_checks=True) if i.id == "osra.I001"]
    assert len(issues) == 1
    assert issues[0].level < WARNING


def test_events_page_says_which_sites_may_send(client, settings):
    page = client.get("/events/").content.decode()
    assert "Any site." in page and "COLLECT_ALLOWED_ORIGINS" in page
    settings.COLLECT_ALLOWED_ORIGINS = []
    assert "Browser pages on this server only" in client.get("/events/").content.decode()
    settings.COLLECT_ALLOWED_ORIGINS = [ALLOWED]
    page = client.get("/events/").content.decode()
    assert ALLOWED in page and "Other sites get 403" in page


def test_malformed_allowed_origins_are_flagged(settings):
    settings.COLLECT_ALLOWED_ORIGINS = ["www.acme.example", "https://acme.example/blog", ALLOWED]
    warnings = [i for i in run_checks() if i.id == "osra.W006"]
    assert len(warnings) == 2
