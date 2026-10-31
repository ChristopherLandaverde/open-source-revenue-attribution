"""Events forwarded by an existing RudderStack setup (Cloud or rudder-server) to /v1/.

Research and sources: docs/research/rudderstack-forwarding.md.

- The **Webhook** destination POSTs one event per request, "the whole event payload" as the
  JSON body, with `content-type: application/json`, `user-agent: RudderLabs` and any static
  headers set in the destination (rudder-transformer `src/v0/destinations/webhook/transform.js`).
- The **HTTP Webhook** destination does the same with "Send the event payload as is" and
  batching off; its Basic Auth setting sends `Basic base64(username:password)`. With batching
  on it sends a bare JSON array, which /v1/batch does not accept (see the last tests).
- Before any destination, rudder-server's processor sets `receivedAt` and `timestamp`
  (`enhanceWithTimeFields`) and `request_ip`; the Webhook transformer copies `request_ip` to
  `context.ip`.

The payloads below are the identify, page and track samples from
https://www.rudderstack.com/docs/destinations/webhooks/cloud-mode/, field for field. Only the
values that look like personal data are swapped for synthetic `*.example` ones (AGENTS.md).
"""

import base64
import copy
import json
from datetime import datetime

import pytest

from collection.models import CollectedEvent, Workspace

pytestmark = pytest.mark.django_db
KEY = "test-write-key-0123456789"
RECEIVED_AT = datetime.fromisoformat("2026-10-30T12:00:00+00:00")

_CONTEXT = {
    "app": {
        "build": "1.0.0",
        "name": "RudderLabs JavaScript SDK",
        "namespace": "com.rudderlabs.javascript",
        "version": "1.1.1-rc.2",
    },
    "library": {"name": "RudderLabs JavaScript SDK", "version": "1.1.1-rc.2"},
    "userAgent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36"
    ),
    "locale": "en-US",
    "os": {"name": "", "version": ""},
    "screen": {"density": 1.600000023841858},
    "page": {
        "path": "/tests/html/script-test.html",
        "referrer": "http://localhost:1111/tests/html/",
        "search": "",
        "title": "",
        "url": "http://localhost:1111/tests/html/script-test.html",
    },
}
_TRAITS = {
    "name": "User name",
    "email": "user@domain.example",
    "plan": "Enterprise",
    "company": {"id": "company-A"},
    "createdAt": "Thu Mar 24 2016 17:46:45 GMT+0000 (UTC)",
}

DOCS_IDENTIFY = {
    "channel": "web",
    "context": {**_CONTEXT, "traits": _TRAITS},
    "type": "identify",
    "messageId": "508d5e8c-96e4-4301-bd46-1890dba5c866",
    "originalTimestamp": "2020-04-22T08:06:20.337Z",
    "anonymousId": "21b43de4-3b9b-423f-b51f-794eae31fc03",
    "userId": "my-user-id",
    "integrations": {"All": True},
    "sentAt": "2020-04-22T08:06:20.337Z",
}
DOCS_PAGE = {
    "channel": "web",
    "context": {**_CONTEXT, "traits": {}},
    "type": "page",
    "messageId": "97114191-e2f2-42af-97db-14b358b1cfe1",
    "originalTimestamp": "2020-04-22T08:06:20.334Z",
    "anonymousId": "57d95a96-61dc-47bf-8f96-5d37543d7438",
    "userId": "user@domain.example",  # the docs sample uses an email address as userId
    "properties": {
        "path": "/tests/html/script-test.html",
        "referrer": "http://localhost:1111/tests/html/",
        "search": "",
        "title": "",
        "url": "http://localhost:1111/tests/html/script-test.html",
        "experiment": {"variant": "old"},
    },
    "integrations": {"All": True},
    "sentAt": "2020-04-22T08:06:20.334Z",
}
DOCS_TRACK = {
    "channel": "web",
    "context": {**_CONTEXT, "traits": _TRAITS},
    "type": "track",
    "messageId": "04a303b1-a466-4e66-9022-2a24edaca4fc",
    "originalTimestamp": "2020-04-22T08:06:20.338Z",
    "anonymousId": "21b43de4-3b9b-423f-b51f-794eae31fc03",
    "userId": "my-user-id",
    "event": "Product Purchased",
    "properties": {
        "order_ID": "1",
        "category": "boots",
        "product_name": "new_boots",
        "price": 60,
        "currency": "USD",
    },
    "integrations": {"All": True},
    "sentAt": "2020-04-22T08:06:20.338Z",
}


def as_delivered(event, received_at="2020-04-22T08:06:21.000Z"):
    """What reaches the webhook: the event after rudder-server's processor and transformer.

    `enhanceWithTimeFields` sets receivedAt and timestamp = receivedAt - (sentAt -
    originalTimestamp), RFC 3339 with milliseconds; the processor adds request_ip and the
    Webhook transformer copies it to context.ip.
    """
    delivered = copy.deepcopy(event)
    received = datetime.fromisoformat(received_at)
    original = datetime.fromisoformat(event["originalTimestamp"])
    sent = datetime.fromisoformat(event["sentAt"])
    timestamp = received - (sent - original)
    delivered["receivedAt"] = received_at
    delivered["timestamp"] = timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    delivered["request_ip"] = "203.0.113.7"
    delivered["context"]["ip"] = "203.0.113.7"
    return delivered


@pytest.fixture(autouse=True)
def fixed_receive_time(monkeypatch):
    monkeypatch.setattr("collection.services.timezone.now", lambda: RECEIVED_AT)


@pytest.fixture
def workspace():
    return Workspace.objects.create(name="rudderstack", write_key=KEY)


def basic(username, password=""):
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def webhook_post(client, path, body, authorization):
    """The request the Webhook destination makes: POST, JSON body, its default headers."""
    return client.post(
        path,
        json.dumps(body),
        content_type="application/json",
        HTTP_USER_AGENT="RudderLabs",
        HTTP_AUTHORIZATION=authorization,
    )


def outcome(response):
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["received"] == 1
    return body["events"][0]


# --- Webhook destination: one event per request --------------------------------------------


@pytest.mark.parametrize("path", ["/v1/track", "/v1/page", "/v1/identify"])
def test_webhook_identify_and_track_are_accepted_on_any_single_event_path(
    anon_client, workspace, path
):
    """The event's own type decides, not the path, so one Webhook URL takes every type."""
    for event in (DOCS_IDENTIFY, DOCS_TRACK):
        result = outcome(webhook_post(anon_client, path, as_delivered(event), basic(KEY)))
        assert result["outcome"] == "accepted"
    assert CollectedEvent.objects.filter(status="accepted").count() == 2


def test_webhook_events_keep_rudderstack_server_timestamp(anon_client, workspace):
    delivered = as_delivered(DOCS_TRACK)
    assert outcome(webhook_post(anon_client, "/v1/track", delivered, basic(KEY)))["outcome"] == (
        "accepted"
    )
    stored = CollectedEvent.objects.get(message_id=DOCS_TRACK["messageId"])
    assert stored.normalized["time_source"] == "timestamp"  # rule 1: used as is
    assert stored.occurred_at == datetime.fromisoformat(delivered["timestamp"])
    assert stored.payload == delivered  # stored verbatim, extra fields included


def test_docs_page_sample_is_refused_only_because_its_user_id_is_an_email(anon_client, workspace):
    """Shape accepted; the contract's userId = contact_id rule refuses an email address."""
    result = outcome(webhook_post(anon_client, "/v1/track", as_delivered(DOCS_PAGE), basic(KEY)))
    assert result["outcome"] == "rejected"
    assert [(i["code"], i["field"]) for i in result["issues"]] == [("INVALID_ID", "userId")]

    page = {**as_delivered(DOCS_PAGE), "userId": "con-nw-ana"}
    assert outcome(webhook_post(anon_client, "/v1/track", page, basic(KEY)))["outcome"] == (
        "accepted"
    )
    stored = CollectedEvent.objects.get(message_id=DOCS_PAGE["messageId"], status="accepted")
    assert stored.normalized["page_url"] == DOCS_PAGE["context"]["page"]["url"]


def test_webhook_without_the_write_key_header_is_401(anon_client, workspace):
    response = anon_client.post(
        "/v1/track",
        json.dumps(as_delivered(DOCS_TRACK)),
        content_type="application/json",
        HTTP_USER_AGENT="RudderLabs",
    )
    assert response.status_code == 401
    assert not CollectedEvent.objects.exists()


def test_server_forwarding_needs_no_origin_even_with_an_origin_list(
    anon_client, workspace, settings
):
    settings.COLLECT_ALLOWED_ORIGINS = ["https://www.acme.example"]
    result = outcome(webhook_post(anon_client, "/v1/track", as_delivered(DOCS_TRACK), basic(KEY)))
    assert result["outcome"] == "accepted"


def test_redelivery_of_the_same_event_is_counted_once(anon_client, workspace):
    """rudder-server retries failed deliveries; a retry is the same payload."""
    delivered = as_delivered(DOCS_TRACK)
    webhook_post(anon_client, "/v1/track", delivered, basic(KEY))
    result = outcome(webhook_post(anon_client, "/v1/track", delivered, basic(KEY)))
    assert result["outcome"] == "duplicate"
    assert CollectedEvent.objects.get().times_received == 2


# --- HTTP Webhook destination ---------------------------------------------------------------


@pytest.mark.parametrize("password", ["", "undefined", "anything"])
def test_http_webhook_basic_auth_with_the_write_key_as_username(anon_client, workspace, password):
    """rudder-transformer builds `${username}:${password}`; an unset password is "undefined".

    Only the username is read, as with the SDK's `base64(<write key>:)`.
    """
    result = outcome(
        webhook_post(anon_client, "/v1/track", as_delivered(DOCS_TRACK), basic(KEY, password))
    )
    assert result["outcome"] == "accepted"


def test_http_webhook_write_key_as_password_is_401(anon_client, workspace):
    response = webhook_post(anon_client, "/v1/track", as_delivered(DOCS_TRACK), basic("", KEY))
    assert response.status_code == 401


def test_http_webhook_batch_array_is_not_accepted_by_v1_batch(anon_client, workspace):
    """Known gap: batching sends `[{Event1},...,{EventN}]`; /v1/batch wants {"batch": [...]}."""
    batch = [as_delivered(DOCS_IDENTIFY), as_delivered(DOCS_TRACK)]
    response = webhook_post(anon_client, "/v1/batch", batch, basic(KEY))
    assert response.status_code == 400
    assert not CollectedEvent.objects.exists()


def test_http_webhook_batch_array_on_a_single_event_path_is_refused(anon_client, workspace):
    batch = [as_delivered(DOCS_IDENTIFY), as_delivered(DOCS_TRACK)]
    result = outcome(webhook_post(anon_client, "/v1/track", batch, basic(KEY)))
    assert result["outcome"] == "rejected"
    assert result["issues"][0]["code"] == "MISSING_REQUIRED_FIELD"
    assert not CollectedEvent.objects.filter(status="accepted").exists()
