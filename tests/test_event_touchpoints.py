"""Accepted events -> touchpoints (docs/contract.md section 3, "From events to touchpoints").

Expected output is hand-written in sample_data/events/expected/touchpoints.json and derived
in sample_data/events/README.md. Never regenerate it from code output.
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from contracts import ImportBatch, validate_events, validate_import
from contracts.touchpoints import SkipReason, TouchReason, events_to_touchpoints

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "sample_data" / "events"
EXPECTED = json.loads((EVENTS / "expected" / "touchpoints.json").read_text())


def demo_contacts() -> set[str]:
    report = validate_import(ImportBatch.from_csv_dir(ROOT / "sample_data" / "demo"))
    return {c.contact_id for c in report.accepted["contacts"]}


# The fixture's hand calculation assumes the whole batch is received at this instant.
RECEIVED_AT = datetime.fromisoformat(EXPECTED["received_at"])


def fixture_report():
    return validate_events(
        json.loads((EVENTS / "batch.json").read_text())["batch"], received_at=RECEIVED_AT
    )


def test_fixture_validation_matches_hand_count():
    report = fixture_report()
    expected = EXPECTED["validation"]
    assert [e.event_id for e in report.accepted] == expected["accepted"]
    assert {r.record_id: [i.code for i in r.issues] for r in report.rejected} == expected[
        "rejected"
    ]
    warnings: dict[str, list[str]] = {}
    for w in report.warnings:
        warnings.setdefault(w.record_id, []).append(str(w.code))
    assert warnings == expected["warnings"]
    times = {e.event_id: e.occurred_at.isoformat() for e in report.accepted}
    assert {k: times[k] for k in expected["event_times"]} == expected["event_times"]


def test_fixture_converts_to_hand_calculated_touchpoints():
    result = events_to_touchpoints(fixture_report().accepted, demo_contacts())
    touchpoints = [
        {**asdict(tp), "occurred_at": tp.occurred_at.isoformat()} for tp in result.touchpoints
    ]
    assert touchpoints == EXPECTED["touchpoints"]
    assert [{"event_id": e, "reason": str(r)} for e, r in result.skipped] == EXPECTED["skipped"]
    internal = [(tp.touchpoint_id, tp.contact_id) for tp in result.internal_views]
    assert internal == [tuple(pair) for pair in EXPECTED["internal_views"]]


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


def test_user_id_must_be_an_imported_contact():
    result = events_to_touchpoints(_page(), set())
    assert result.skipped == [("m-1", SkipReason.CONTACT_NOT_IMPORTED)]


# --- M3: stitching (decision #5, assumption 16) ----------------------------------


def ev(kind, message_id, at, anon="a-1", user=None, campaign=None, url=None, referrer=""):
    """One accepted event with a server `timestamp` (no skew correction involved)."""
    payload = {
        "type": kind,
        "messageId": message_id,
        "anonymousId": anon,
        "timestamp": f"2026-09-01T{at}Z",
    }
    if user:
        payload["userId"] = user
    if kind == "page":
        payload["context"] = {
            "page": {"url": url or "https://www.acme.example/page", "referrer": referrer},
            "campaign": dict(zip(("source", "medium", "name"), campaign or (), strict=False)),
        }
    (event,) = validate_events([payload]).accepted
    return event


ADS = ("google", "cpc", "fall")


def test_identify_stitches_earlier_anonymous_page_views_to_the_contact():
    anon_view = ev("page", "m-anon", "10:00:00", campaign=ADS)
    identify = ev("identify", "m-id", "10:05:00", user="con-1")
    result = events_to_touchpoints([identify, anon_view], {"con-1"})
    (tp,) = result.touchpoints
    assert (tp.touchpoint_id, tp.contact_id, tp.stitched_from) == ("m-anon", "con-1", "a-1")
    assert (tp.source, tp.medium, tp.campaign) == ADS  # the visit that carried the UTMs
    assert tp.visit_rule == TouchReason.FIRST_VISIT
    assert result.skipped == [("m-id", SkipReason.NOT_A_PAGE_VIEW)]


def test_identify_at_the_same_instant_still_stitches():
    anon_view = ev("page", "m-anon", "10:00:00", campaign=ADS)
    identify = ev("identify", "m-id", "10:00:00", user="con-1")
    assert events_to_touchpoints([anon_view, identify], {"con-1"}).touchpoints[0].contact_id == (
        "con-1"
    )


def test_anonymous_views_after_the_identify_are_not_stitched():
    # Only *earlier* anonymous history is linked (decision #5). After an identify the SDK sends
    # userId itself; an anonymous view after it is left alone.
    identify = ev("identify", "m-id", "10:00:00", user="con-1")
    later = ev("page", "m-later", "10:05:00", campaign=ADS)
    result = events_to_touchpoints([identify, later], {"con-1"})
    assert result.touchpoints == []
    assert ("m-later", SkipReason.ANONYMOUS) in result.skipped


def test_other_anonymous_ids_are_not_stitched():
    other = ev("page", "m-other", "10:00:00", anon="a-2", campaign=ADS)
    identify = ev("identify", "m-id", "10:05:00", user="con-1")
    result = events_to_touchpoints([other, identify], {"con-1"})
    assert result.touchpoints == []
    assert result.skipped[0] == ("m-other", SkipReason.ANONYMOUS)


def test_anonymous_id_identified_as_two_contacts_is_not_stitched():
    # A shared browser: we can't tell whose anonymous visit it was, so it goes to nobody.
    view = ev("page", "m-anon", "10:00:00", campaign=ADS)
    first = ev("identify", "m-id1", "10:05:00", user="con-1")
    second = ev("identify", "m-id2", "11:00:00", user="con-2")
    result = events_to_touchpoints([view, first, second], {"con-1", "con-2"})
    assert result.touchpoints == []
    assert result.skipped[0] == ("m-anon", SkipReason.AMBIGUOUS_IDENTITY)


def test_identifying_the_same_contact_twice_is_not_ambiguous():
    view = ev("page", "m-anon", "10:00:00", campaign=ADS)
    first = ev("identify", "m-id1", "10:05:00", user="con-1")
    again = ev("identify", "m-id2", "11:00:00", user="con-1")
    assert len(events_to_touchpoints([view, first, again], {"con-1"}).touchpoints) == 1


def test_stitched_views_wait_for_the_contact_import():
    view = ev("page", "m-anon", "10:00:00", campaign=ADS)
    identify = ev("identify", "m-id", "10:05:00", user="con-1")
    result = events_to_touchpoints([view, identify], set())
    assert result.skipped[0] == ("m-anon", SkipReason.CONTACT_NOT_IMPORTED)


# --- M3: visits (decision #5, assumption 17) -------------------------------------


def rules(events, contacts=frozenset({"con-1"})):
    result = events_to_touchpoints(events, contacts)
    counted = {tp.touchpoint_id: str(tp.visit_rule) for tp in result.touchpoints}
    internal = {tp.touchpoint_id: str(tp.visit_rule) for tp in result.internal_views}
    return counted, internal


def test_internal_navigation_is_not_a_touchpoint():
    counted, internal = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1", campaign=ADS),
            ev("page", "m-2", "10:10:00", user="con-1", referrer="https://www.acme.example/page"),
        ]
    )
    assert counted == {"m-1": "FIRST_VISIT"}
    assert internal == {"m-2": "INTERNAL_NAVIGATION"}


def test_thirty_minutes_exactly_is_the_same_visit_and_one_second_more_is_a_new_one():
    counted, internal = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1"),
            ev("page", "m-2", "10:30:00", user="con-1"),  # gap 30:00 -> same visit
            ev("page", "m-3", "11:00:01", user="con-1"),  # gap 30:01 -> new visit
        ]
    )
    assert counted == {"m-1": "FIRST_VISIT", "m-3": "INACTIVITY"}
    assert internal == {"m-2": "INTERNAL_NAVIGATION"}


def test_the_gap_counts_from_the_previous_page_view_not_the_visit_start():
    counted, _ = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1"),
            ev("page", "m-2", "10:25:00", user="con-1"),
            ev("page", "m-3", "10:50:00", user="con-1"),  # 50 min after start, 25 after m-2
        ]
    )
    assert counted == {"m-1": "FIRST_VISIT"}


def test_a_new_campaign_starts_a_visit():
    counted, _ = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1", campaign=ADS),
            ev("page", "m-2", "10:05:00", user="con-1", campaign=("linkedin", "paid", "abm")),
        ]
    )
    assert counted == {"m-1": "FIRST_VISIT", "m-2": "NEW_CAMPAIGN"}


def test_campaign_data_inside_a_visit_still_counts():
    # Decision #5: page views that carry campaign data are touchpoints even mid-visit.
    counted, _ = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1", campaign=ADS),
            ev("page", "m-2", "10:05:00", user="con-1", campaign=ADS),
        ]
    )
    assert counted == {"m-1": "FIRST_VISIT", "m-2": "CAMPAIGN_DATA"}


def test_arriving_from_another_site_starts_a_visit():
    counted, internal = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1"),
            ev("page", "m-2", "10:05:00", user="con-1", referrer="https://duckduckgo.com/"),
            # Same external referrer again (a reload keeps document.referrer): same visit.
            ev("page", "m-3", "10:06:00", user="con-1", referrer="https://duckduckgo.com/"),
            # Own site with and without www. is internal.
            ev("page", "m-4", "10:07:00", user="con-1", referrer="https://acme.example/x"),
        ]
    )
    assert counted == {"m-1": "FIRST_VISIT", "m-2": "NEW_REFERRER"}
    assert internal == {"m-3": "INTERNAL_NAVIGATION", "m-4": "INTERNAL_NAVIGATION"}


def test_visits_are_per_contact_and_include_stitched_views():
    counted, internal = rules(
        [
            ev("page", "m-anon", "10:00:00", campaign=ADS),
            ev("identify", "m-id", "10:01:00", user="con-1"),
            ev("page", "m-2", "10:02:00", user="con-1", referrer="https://www.acme.example/"),
            ev("page", "m-other", "10:03:00", anon="a-9", user="con-2"),
        ],
        contacts={"con-1", "con-2"},
    )
    assert counted == {"m-anon": "FIRST_VISIT", "m-other": "FIRST_VISIT"}
    assert internal == {"m-2": "INTERNAL_NAVIGATION"}


def test_track_events_do_not_extend_a_visit():
    (track,) = validate_events(
        [
            {
                "type": "track",
                "event": "Demo Requested",
                "messageId": "m-t",
                "userId": "con-1",
                "anonymousId": "a-1",
                "timestamp": "2026-09-01T10:20:00Z",
            }
        ]
    ).accepted
    counted, _ = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1"),
            track,
            ev("page", "m-2", "10:40:00", user="con-1"),  # 40 min after the last page view
        ]
    )
    assert counted == {"m-1": "FIRST_VISIT", "m-2": "INACTIVITY"}
