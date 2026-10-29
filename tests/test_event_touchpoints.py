"""Accepted events -> touchpoints (docs/contract.md section 3, "From events to touchpoints").

Expected output is hand-written in sample_data/events/expected/touchpoints.json and derived
in sample_data/events/README.md. Never regenerate it from code output.
"""

import json
from dataclasses import asdict
from pathlib import Path

from contracts import ImportBatch, validate_events, validate_import
from contracts.touchpoints import SkipReason, events_to_touchpoints

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "sample_data" / "events"
EXPECTED = json.loads((EVENTS / "expected" / "touchpoints.json").read_text())


def demo_contacts() -> set[str]:
    report = validate_import(ImportBatch.from_csv_dir(ROOT / "sample_data" / "demo"))
    return {c.contact_id for c in report.accepted["contacts"]}


def fixture_report():
    return validate_events(json.loads((EVENTS / "batch.json").read_text())["batch"])


def test_fixture_validation_matches_hand_count():
    report = fixture_report()
    expected = EXPECTED["validation"]
    assert [e.event_id for e in report.accepted] == expected["accepted"]
    assert {r.record_id: [i.code for i in r.issues] for r in report.rejected} == expected[
        "rejected"
    ]
    assert {w.record_id: [w.code] for w in report.warnings} == expected["warnings"]


def test_fixture_converts_to_hand_calculated_touchpoints():
    result = events_to_touchpoints(fixture_report().accepted, demo_contacts())
    touchpoints = [
        {**asdict(tp), "occurred_at": tp.occurred_at.isoformat()} for tp in result.touchpoints
    ]
    assert touchpoints == EXPECTED["touchpoints"]
    assert [{"event_id": e, "reason": str(r)} for e, r in result.skipped] == EXPECTED["skipped"]


def test_conversion_is_deterministic_regardless_of_input_order():
    events = fixture_report().accepted
    contacts = demo_contacts()
    assert events_to_touchpoints(events, contacts) == events_to_touchpoints(
        list(reversed(events)), contacts
    )


def _page(**overrides):
    payload = {
        "type": "page",
        "messageId": "m-1",
        "anonymousId": "a-1",
        "userId": "con-1",
        "originalTimestamp": "2026-09-01T10:00:00Z",
        "context": {
            "page": {"url": "https://x.example/?utm_source=from-url", "referrer": ""},
            "campaign": {},
        },
    }
    payload.update(overrides)
    return validate_events([payload]).accepted


def test_utms_come_only_from_context_campaign_never_the_url():
    (tp,) = events_to_touchpoints(_page(), {"con-1"}).touchpoints
    assert (tp.source, tp.medium, tp.campaign) == ("", "", "")


def test_identify_does_not_link_earlier_anonymous_page_views():
    anonymous = _page(userId=None, messageId="m-anon")
    identify = validate_events(
        [
            {
                "type": "identify",
                "messageId": "m-id",
                "anonymousId": "a-1",
                "userId": "con-1",
                "originalTimestamp": "2026-09-01T10:05:00Z",
            }
        ]
    ).accepted
    result = events_to_touchpoints([*anonymous, *identify], {"con-1"})
    assert result.touchpoints == []
    assert result.skipped == [
        ("m-anon", SkipReason.ANONYMOUS),
        ("m-id", SkipReason.NOT_A_PAGE_VIEW),
    ]


def test_user_id_must_be_an_imported_contact():
    result = events_to_touchpoints(_page(), set())
    assert result.skipped == [("m-1", SkipReason.CONTACT_NOT_IMPORTED)]
