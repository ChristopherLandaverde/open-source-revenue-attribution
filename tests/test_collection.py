"""POST /v1/batch and /v1/<type>: auth, validation, deduplication, persistence, touchpoints."""

import base64
import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from collection.models import CollectedEvent, Workspace
from reports.models import Touchpoint
from reports.services import first_touch_report

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parent.parent
BATCH = json.loads((ROOT / "sample_data" / "events" / "batch.json").read_text())
KEY = "test-write-key-0123456789"


@pytest.fixture
def workspace():
    return Workspace.objects.create(name="demo", write_key=KEY)


@pytest.fixture
def contacts():
    call_command("load_sample_data", stdout=StringIO(), stderr=StringIO())


def auth(key=KEY):
    return {"HTTP_AUTHORIZATION": "Basic " + base64.b64encode(f"{key}:".encode()).decode()}


def post(client, path, body, **headers):
    data = body if isinstance(body, str | bytes) else json.dumps(body)
    return client.post(path, data, content_type="application/json", **headers)


def page_event(message_id="m-1", **overrides):
    return {
        "type": "page",
        "messageId": message_id,
        "anonymousId": "anon-1",
        "userId": "con-nw-ana",
        "originalTimestamp": "2026-09-10T10:00:00.000Z",
        "sentAt": "2026-09-10T10:00:01.000Z",
        "context": {
            "page": {"url": "https://www.acme.example/", "referrer": ""},
            "campaign": {"source": "google", "medium": "cpc", "name": "fall"},
        },
        **overrides,
    }


# --- auth and request shape ---------------------------------------------------


def test_missing_or_unknown_write_key_is_401(client, workspace):
    assert post(client, "/v1/batch", BATCH).status_code == 401
    response = post(client, "/v1/batch", BATCH, **auth("not-a-key"))
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Basic realm="collect"'
    assert CollectedEvent.objects.count() == 0


def test_malformed_bodies_are_400(client, workspace):
    assert post(client, "/v1/batch", "{nope", **auth()).status_code == 400
    assert post(client, "/v1/batch", {"events": []}, **auth()).status_code == 400
    assert post(client, "/v1/batch", b"\xff\xfe", **auth()).status_code == 400


def test_get_and_unknown_paths_are_refused(client, workspace):
    assert client.get("/v1/batch").status_code == 405
    assert post(client, "/v1/nothing", page_event(), **auth()).status_code == 404


def test_batch_size_is_capped(client, workspace, settings):
    settings.COLLECT_MAX_BATCH = 2
    response = post(
        client, "/v1/batch", {"batch": [page_event(f"m-{i}") for i in range(3)]}, **auth()
    )
    assert response.status_code == 413


# --- outcomes ------------------------------------------------------------------


def test_fixture_batch_outcomes(client, workspace):
    response = post(client, "/v1/batch", BATCH, **auth())
    assert response.status_code == 200
    body = response.json()
    assert (body["received"], body["accepted"], body["duplicates"], body["rejected"]) == (
        10,
        8,
        1,
        1,
    )
    by_position = {e["position"]: e for e in body["events"]}
    assert by_position[8]["outcome"] == "duplicate"
    assert by_position[9]["messageId"] == "evt-09"
    assert by_position[9]["issues"][0]["code"] == "TIMESTAMP_WITHOUT_TIMEZONE"
    assert by_position[5]["issues"][0]["code"] == "MISSING_CAMPAIGN_FIELDS"


def test_raw_payload_and_outcome_are_persisted(client, workspace):
    post(client, "/v1/batch", BATCH, **auth())
    accepted = CollectedEvent.objects.get(message_id="evt-03")
    assert accepted.status == "accepted"
    assert accepted.payload == BATCH["batch"][2]
    assert accepted.times_received == 2  # the batch carries one exact retry of evt-03
    assert accepted.occurred_at.isoformat() == "2026-09-02T08:15:00+00:00"
    assert accepted.workspace == workspace
    refused = CollectedEvent.objects.get(message_id="evt-09")
    assert refused.status == "rejected"
    assert [i["code"] for i in refused.issues] == ["TIMESTAMP_WITHOUT_TIMEZONE"]


def test_single_event_endpoint_uses_the_payload_type(client, workspace):
    response = post(client, "/v1/page", page_event(), **auth())
    assert response.json()["accepted"] == 1
    screen = post(client, "/v1/screen", page_event("m-2", type="screen"), **auth())
    assert screen.json()["events"][0]["issues"][0]["code"] == "UNSUPPORTED_EVENT_TYPE"


# --- deduplication and idempotency -------------------------------------------


def test_replaying_the_same_batch_adds_nothing(client, workspace):
    post(client, "/v1/batch", BATCH, **auth())
    rows = CollectedEvent.objects.count()
    replay = post(client, "/v1/batch", BATCH, **auth()).json()
    assert (replay["accepted"], replay["duplicates"], replay["rejected"]) == (0, 9, 1)
    assert CollectedEvent.objects.count() == rows == 9  # 8 accepted + 1 refused payload
    assert CollectedEvent.objects.get(message_id="evt-09").times_received == 2


def test_sdk_retry_with_new_sent_at_is_a_duplicate(client, workspace):
    post(client, "/v1/page", page_event(), **auth())
    retry = post(client, "/v1/page", page_event(sentAt="2026-09-10T10:05:00Z"), **auth())
    assert retry.json()["duplicates"] == 1
    assert CollectedEvent.objects.get(message_id="m-1").times_received == 2


def test_reused_message_id_with_new_content_is_refused_and_first_stands(client, workspace):
    post(client, "/v1/page", page_event(), **auth())
    conflict = post(client, "/v1/page", page_event(userId="con-nw-raj"), **auth()).json()
    assert conflict["events"][0]["issues"][0]["code"] == "DUPLICATE_ID"
    kept = CollectedEvent.objects.get(message_id="m-1", status="accepted")
    assert kept.user_id == "con-nw-ana"


def test_corrected_resend_of_a_refused_event_is_accepted(client, workspace):
    post(client, "/v1/page", page_event(originalTimestamp="2026-09-10T10:00:00"), **auth())
    fixed = post(client, "/v1/page", page_event(), **auth()).json()
    assert fixed["accepted"] == 1


# --- events -> touchpoints -----------------------------------------------------


def test_identified_page_events_become_touchpoints(client, workspace, contacts):
    post(client, "/v1/batch", BATCH, **auth())
    created = Touchpoint.objects.filter(origin="event").order_by("occurred_at", "external_id")
    assert [tp.external_id for tp in created] == ["evt-03", "evt-05", "evt-10", "evt-07"]
    assert created[0].contact.external_id == "con-nw-li"
    assert (created[0].source, created[0].medium, created[0].campaign) == (
        "google",
        "cpc",
        "fall-search",
    )


def test_events_before_their_contact_convert_after_the_import(client, workspace):
    post(client, "/v1/batch", BATCH, **auth())
    assert not Touchpoint.objects.filter(origin="event").exists()
    call_command("load_sample_data", stdout=StringIO(), stderr=StringIO())
    assert Touchpoint.objects.filter(origin="event").count() == 4
    call_command("load_sample_data", stdout=StringIO(), stderr=StringIO())
    assert Touchpoint.objects.filter(origin="event").count() == 4  # idempotent


def test_event_touchpoints_do_not_change_the_demo_report(client, workspace, contacts):
    before = {m: first_touch_report(m).campaign_rows for m in ("pipeline", "won")}
    post(client, "/v1/batch", BATCH, **auth())
    after = {m: first_touch_report(m).campaign_rows for m in ("pipeline", "won")}
    assert before == after  # fixture events are dated after every demo conversion


# --- workspace command ---------------------------------------------------------


def test_create_workspace_is_idempotent_by_name():
    out = StringIO()
    call_command("create_workspace", "demo", "--write-key", KEY, stdout=out)
    call_command("create_workspace", "demo", stdout=out)
    assert Workspace.objects.get().write_key == KEY
    assert out.getvalue().count(f"Write key: {KEY}") == 2
    with pytest.raises(CommandError):
        call_command("create_workspace", "other", "--write-key", "short")
