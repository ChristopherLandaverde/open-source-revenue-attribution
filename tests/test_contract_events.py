"""Event contract rules for RudderStack payloads (docs/contract.md, "Events")."""

from datetime import UTC, datetime

import pytest

from contracts import RejectReason, WarningCode, validate_events

R, W = RejectReason, WarningCode


def page(**overrides):
    event = {
        "type": "page",
        "messageId": "msg-1",
        "anonymousId": "anon-1",
        "originalTimestamp": "2026-03-01T09:59:58.000Z",
        "timestamp": "2026-03-01T10:00:00.000Z",
        "context": {
            "page": {
                "url": "https://www.acme.example/pricing?utm_source=google",
                "referrer": "https://www.google.com/",
            },
            "campaign": {"source": "google", "medium": "cpc", "name": "spring"},
        },
    }
    event.update(overrides)
    return event


def track(name="Demo Requested", **overrides):
    return {
        **page(),
        "type": "track",
        "event": name,
        "messageId": "msg-t",
        "userId": "con-1",
        **overrides,
    }


def identify(**overrides):
    return {
        "type": "identify",
        "messageId": "msg-i",
        "anonymousId": "anon-1",
        "userId": "con-1",
        "timestamp": "2026-03-01T10:05:00Z",
        **overrides,
    }


def codes(report):
    return [(r.record_id, i.code, i.field) for r in report.rejected for i in r.issues]


def test_valid_page_track_identify_are_accepted():
    report = validate_events([page(), track(), identify()])
    assert report.rejected == []
    assert report.warnings == []
    assert [e.type for e in report.accepted] == ["page", "track", "identify"]


def test_accepted_event_is_normalized():
    [event] = validate_events([page()]).accepted
    assert event.event_id == "msg-1"
    assert event.occurred_at == datetime(2026, 3, 1, 10, tzinfo=UTC)  # `timestamp`, not original
    assert event.original_timestamp == "2026-03-01T09:59:58.000Z"  # preserved verbatim
    assert event.utm_source == "google"
    assert event.utm_campaign == "spring"
    assert event.page_url.endswith("/pricing?utm_source=google")


def test_campaign_values_are_not_parsed_from_the_url():
    event = page()
    event["context"]["campaign"] = {}
    report = validate_events([event])
    assert report.accepted[0].utm_source == ""
    assert [(w.code, w.field) for w in report.warnings] == [
        (W.MISSING_CAMPAIGN_FIELDS, "utm_source, utm_medium, utm_campaign")
    ]


def test_unsupported_type_is_rejected():
    assert codes(validate_events([page(type="screen")])) == [
        ("msg-1", R.UNSUPPORTED_EVENT_TYPE, "type")
    ]


def test_missing_message_id_is_rejected():
    assert codes(validate_events([page(messageId="")])) == [
        ("", R.MISSING_REQUIRED_FIELD, "messageId")
    ]


def test_event_needs_an_anonymous_or_user_id():
    assert codes(validate_events([page(anonymousId="")])) == [
        ("msg-1", R.MISSING_IDENTITY, "anonymousId")
    ]


def test_identify_requires_user_id():
    assert codes(validate_events([identify(userId="")])) == [
        ("msg-i", R.MISSING_REQUIRED_FIELD, "userId")
    ]


def test_user_id_must_be_a_valid_contact_id():
    assert codes(validate_events([identify(userId="con 1")])) == [("msg-i", R.INVALID_ID, "userId")]


def test_track_requires_event_name():
    assert codes(validate_events([track(name="")])) == [
        ("msg-t", R.MISSING_REQUIRED_FIELD, "event")
    ]


def test_page_requires_url():
    event = page()
    del event["context"]["page"]["url"]
    assert codes(validate_events([event])) == [("msg-1", R.MISSING_REQUIRED_FIELD, "page.url")]


def test_page_url_from_properties_is_accepted():
    event = page(properties={"url": "https://www.acme.example/"})
    del event["context"]["page"]
    assert validate_events([event]).rejected == []


def test_falls_back_to_original_timestamp():
    event = page()
    del event["timestamp"]
    [accepted] = validate_events([event]).accepted
    assert accepted.occurred_at == datetime(2026, 3, 1, 9, 59, 58, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "code"),
    [("2026-03-01T10:00:00", R.TIMESTAMP_WITHOUT_TIMEZONE), ("soon", R.INVALID_TIMESTAMP)],
)
def test_bad_timestamp_is_rejected(value, code):
    assert codes(validate_events([page(timestamp=value)])) == [("msg-1", code, "timestamp")]


def test_missing_timestamp_is_rejected():
    event = page()
    del event["timestamp"], event["originalTimestamp"]
    assert codes(validate_events([event])) == [("msg-1", R.MISSING_REQUIRED_FIELD, "timestamp")]


def test_unknown_track_name_is_accepted_with_a_warning():
    report = validate_events([track(name="Button Clicked")])
    assert len(report.accepted) == 1
    assert [w.code for w in report.warnings] == [W.UNKNOWN_EVENT_NAME]


def test_retried_event_is_counted_once():
    report = validate_events([page(), page()])
    assert len(report.accepted) == 1
    assert [w.code for w in report.warnings] == [W.DUPLICATE_ROW]


def test_reused_message_id_with_different_content_is_rejected():
    report = validate_events([page(), page(anonymousId="anon-2")])
    assert len(report.accepted) == 1
    assert codes(report) == [("msg-1", R.DUPLICATE_ID, "messageId")]


def test_non_object_payload_is_rejected():
    assert codes(validate_events(["nope"])) == [("", R.MISSING_REQUIRED_FIELD, "type")]
