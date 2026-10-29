"""Events page and the RudderStack SDK demo page."""

import base64
import json
from pathlib import Path

import pytest

from collection.models import Workspace

pytestmark = pytest.mark.django_db
BATCH = (
    Path(__file__).resolve().parent.parent / "sample_data" / "events" / "batch.json"
).read_text()


@pytest.fixture
def workspace():
    return Workspace.objects.create(name="demo", write_key="test-write-key-0123456789")


def send(client):
    key = base64.b64encode(b"test-write-key-0123456789:").decode()
    client.post(
        "/v1/batch", BATCH, content_type="application/json", HTTP_AUTHORIZATION=f"Basic {key}"
    )


def test_empty_state_says_how_to_start(client):
    html = client.get("/events/").content.decode()
    assert "No events collected yet." in html
    assert "create_workspace" in html


def test_events_page_shows_outcomes(client, workspace):
    client.post("/import/", {"action": "demo"})
    send(client)
    html = client.get("/events/").content.decode()
    assert "1 event payload refused. 8 events accepted." in html
    assert "4 became touchpoints" in html
    assert "TIMESTAMP_WITHOUT_TIMEZONE" in html
    assert "Add the UTC offset" in html  # the fix
    assert "Earlier anonymous views are not linked" in html


def test_demo_page_is_off_without_debug(client, settings, workspace):
    settings.COLLECT_DEMO_PAGE = False
    assert client.get("/events/demo/").status_code == 404


def test_demo_page_loads_the_vendored_sdk_with_the_write_key(client, settings, workspace):
    settings.COLLECT_DEMO_PAGE = True
    html = client.get("/events/demo/").content.decode()
    assert "vendor/rudderstack-analytics-js-3.35.0.bundled.umd.js" in html
    config = json.loads(
        html.split('id="sdk-config" type="application/json">')[1].split("</script>")[0]
    )
    assert config == {
        "writeKey": "test-write-key-0123456789",
        "dataPlaneUrl": "http://testserver",
        "contactId": "con-nw-li",
    }


def test_demo_page_without_workspace_explains(client, settings):
    settings.COLLECT_DEMO_PAGE = True
    assert "create_workspace" in client.get("/events/demo/").content.decode()


def test_retry_count_covers_accepted_events_only(client, workspace):
    send(client)
    send(client)  # replay: 8 accepted retries + 1 refused repeat
    html = client.get("/events/").content.decode()
    # first batch: evt-03 retried once; replay: all 8 accepted again (evt-03 twice) -> 1 + 9 = 10
    assert 'Accepted retries counted once</span><span class="value">10</span>' in html
