"""Event contract rules for RudderStack payloads (docs/contract.md, "Events")."""

from datetime import UTC, datetime

import pytest

from contracts import RejectReason, WarningCode, content_fingerprint, validate_events

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
    # No `timestamp` and no sentAt: the browser clock is used as is, with a warning (M3).
    event = page()
    del event["timestamp"]
    report = validate_events([event])
    [accepted] = report.accepted
    assert accepted.occurred_at == datetime(2026, 3, 1, 9, 59, 58, tzinfo=UTC)
    assert accepted.time_source == "original_timestamp"
    assert [w.code for w in report.warnings] == [W.CLOCK_SKEW_NOT_CORRECTED]


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


# --- M2: dedup across requests -------------------------------------------------


def test_retry_with_a_new_sent_at_is_still_a_retry():
    # The RudderStack SDK rewrites sentAt on every delivery attempt; it is transport metadata.
    report = validate_events(
        [page(sentAt="2026-03-01T10:00:01Z"), page(sentAt="2026-03-01T10:09Z")]
    )
    assert len(report.accepted) == 1
    assert [w.code for w in report.warnings] == [W.DUPLICATE_ROW]


def test_previously_accepted_message_ids_are_honoured():
    first = page()
    already = {"msg-1": content_fingerprint(first)}
    retry = validate_events([page(sentAt="later")], already_accepted=already)
    assert retry.accepted == []
    assert [w.code for w in retry.warnings] == [W.DUPLICATE_ROW]
    conflict = validate_events([page(anonymousId="anon-2")], already_accepted=already)
    assert conflict.accepted == []
    assert codes(conflict) == [("msg-1", R.DUPLICATE_ID, "messageId")]


def test_fingerprint_ignores_key_order_and_sent_at():
    a = {"messageId": "m", "type": "page", "sentAt": "1"}
    b = {"type": "page", "messageId": "m", "sentAt": "2"}
    assert content_fingerprint(a) == content_fingerprint(b)
    assert content_fingerprint(a) != content_fingerprint({**a, "type": "track"})


def test_text_limits_apply_to_events():
    # docs/contract.md section 1: UTM values <= 200, landing page and referrer <= 500.
    long_campaign = {"source": "s" * 201, "medium": "cpc", "name": "spring"}
    report = validate_events(
        [
            page(context={"page": {"url": "https://x.example/" + "p" * 500}, "campaign": {}}),
            page(messageId="msg-2", context={"page": {"url": "/"}, "campaign": long_campaign}),
        ]
    )
    assert codes(report) == [
        ("msg-1", R.VALUE_TOO_LONG, "page.url"),
        ("msg-2", R.VALUE_TOO_LONG, "utm_source"),
    ]


# --- M3: clock-skew correction (decision #5, assumption 19) ----------------------

RECEIVED = datetime(2026, 3, 1, 10, 0, 1, tzinfo=UTC)


def browser_page(**overrides):
    """A page view as the browser SDK sends it: originalTimestamp + sentAt, no `timestamp`."""
    event = page(originalTimestamp="2026-03-01T07:59:58.000Z", sentAt="2026-03-01T07:59:59.000Z")
    del event["timestamp"]
    event.update(overrides)
    return event


def test_skew_is_corrected_with_received_at_minus_sent_at():
    # Hand calculation (RudderStack's rule): the browser clock runs 2h00m02s slow.
    #   skew      = receivedAt 10:00:01 - sentAt 07:59:59         = +2:00:02
    #   event time = originalTimestamp 07:59:58 + skew             = 10:00:00
    report = validate_events([browser_page()], received_at=RECEIVED)
    [event] = report.accepted
    assert event.occurred_at == datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    assert event.time_source == "skew_corrected"
    assert event.original_timestamp == "2026-03-01T07:59:58.000Z"  # still preserved
    assert event.sent_at == "2026-03-01T07:59:59.000Z"
    assert report.warnings == []


def test_skew_correction_handles_a_fast_clock_and_offsets():
    # Browser clock 30 minutes fast, in +02:00: original 12:30:00+02:00 = 10:30:00Z,
    # sentAt 12:30:05+02:00 = 10:30:05Z, received 10:00:06Z -> skew -0:29:59 -> 10:00:01Z.
    event = browser_page(
        originalTimestamp="2026-03-01T12:30:00+02:00", sentAt="2026-03-01T12:30:05+02:00"
    )
    received = datetime(2026, 3, 1, 10, 0, 6, tzinfo=UTC)
    [accepted] = validate_events([event], received_at=received).accepted
    assert accepted.occurred_at == datetime(2026, 3, 1, 10, 0, 1, tzinfo=UTC)


def test_server_timestamp_is_used_as_is():
    # `timestamp` was already corrected by a RudderStack server; it is not corrected twice.
    event = page(sentAt="2026-03-01T07:59:59Z")
    [accepted] = validate_events([event], received_at=RECEIVED).accepted
    assert accepted.occurred_at == datetime(2026, 3, 1, 10, tzinfo=UTC)
    assert accepted.time_source == "timestamp"


@pytest.mark.parametrize(
    ("overrides", "received_at", "why"),
    [
        ({"sentAt": None}, RECEIVED, "no sentAt"),
        ({"sentAt": "2026-03-01T07:59:59"}, RECEIVED, "sentAt has no UTC offset"),
        ({"sentAt": "later"}, RECEIVED, "sentAt is not ISO 8601"),
        ({}, None, "no receive time"),
    ],
)
def test_uncorrectable_skew_falls_back_with_a_warning(overrides, received_at, why):
    event = browser_page()
    for key, value in overrides.items():
        if value is None:
            del event[key]
        else:
            event[key] = value
    report = validate_events([event], received_at=received_at)
    [accepted] = report.accepted  # never refused: sentAt is transport metadata
    assert accepted.occurred_at == datetime(2026, 3, 1, 7, 59, 58, tzinfo=UTC)
    assert accepted.time_source == "original_timestamp"
    [warning] = report.warnings
    assert (warning.code, warning.field) == (W.CLOCK_SKEW_NOT_CORRECTED, "sentAt")
    assert why in warning.message


def test_retry_keeps_the_first_deliverys_corrected_time():
    # A retry differs only in sentAt, so it is a duplicate; the first accepted event stands.
    first = browser_page()
    already = {"msg-1": content_fingerprint(first)}
    retry = validate_events(
        [browser_page(sentAt="2026-03-01T08:05:00Z")],
        already_accepted=already,
        received_at=RECEIVED,
    )
    assert retry.accepted == []
    assert [w.code for w in retry.warnings] == [W.DUPLICATE_ROW]
