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
    in_session = [(tp.touchpoint_id, tp.session_id) for tp in result.session_views]
    assert in_session == [tuple(pair) for pair in EXPECTED["session_views"]]
    assert all(tp.session_id == tp.touchpoint_id for tp in result.touchpoints)


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
    assert tp.visit_rule == TouchReason.FIRST_SESSION
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


# --- #7: sessions (replaces M3's visit rules, assumption 17) ---------------------
# A session is one browser's (anonymousId's) events for one contact, each less than 30
# minutes after the previous one. Each session is one touchpoint: its first page view.


def rules(events, contacts=frozenset({"con-1"})):
    result = events_to_touchpoints(events, contacts)
    counted = {tp.touchpoint_id: str(tp.visit_rule) for tp in result.touchpoints}
    in_session = {tp.touchpoint_id: tp.session_id for tp in result.session_views}
    return counted, in_session


def test_later_page_views_in_a_session_are_not_counted_again():
    counted, in_session = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1", campaign=ADS),
            ev("page", "m-2", "10:10:00", user="con-1", referrer="https://www.acme.example/page"),
        ]
    )
    assert counted == {"m-1": "FIRST_SESSION"}
    assert in_session == {"m-2": "m-1"}  # labelled with the session's credited page view


def test_a_reload_with_the_same_utms_is_the_same_session():
    # M3 counted this twice (CAMPAIGN_DATA). Decision #7: one session, one touch.
    counted, in_session = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1", campaign=ADS),
            ev("page", "m-2", "10:00:20", user="con-1", campaign=ADS),
        ]
    )
    assert counted == {"m-1": "FIRST_SESSION"}
    assert in_session == {"m-2": "m-1"}


def test_thirty_minutes_exactly_starts_a_new_session():
    # Decision #7 and Dreamdata: events "less than 30 minutes" apart share a session, so a
    # gap of exactly 30:00 starts a new one. (GA4 says "more than 30 minutes"; see contract.)
    counted, in_session = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1"),
            ev("page", "m-2", "10:29:59", user="con-1"),  # gap 29:59 -> same session
            ev("page", "m-3", "10:59:59", user="con-1"),  # gap 30:00 -> new session
        ]
    )
    assert counted == {"m-1": "FIRST_SESSION", "m-3": "INACTIVITY"}
    assert in_session == {"m-2": "m-1"}


def test_the_gap_counts_from_the_previous_event_not_the_session_start():
    counted, _ = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1"),
            ev("page", "m-2", "10:25:00", user="con-1"),
            ev("page", "m-3", "10:50:00", user="con-1"),  # 50 min after start, 25 after m-2
        ]
    )
    assert counted == {"m-1": "FIRST_SESSION"}


def test_a_new_campaign_does_not_split_a_session():
    # Dreamdata and GA4: only inactivity ends a session; mid-session campaigns are not credited.
    counted, in_session = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1", campaign=ADS),
            ev("page", "m-2", "10:05:00", user="con-1", campaign=("linkedin", "paid", "abm")),
        ]
    )
    assert counted == {"m-1": "FIRST_SESSION"}
    assert in_session == {"m-2": "m-1"}


def test_a_new_referrer_does_not_split_a_session():
    counted, in_session = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1"),
            ev("page", "m-2", "10:05:00", user="con-1", referrer="https://duckduckgo.com/"),
        ]
    )
    assert counted == {"m-1": "FIRST_SESSION"}
    assert in_session == {"m-2": "m-1"}


def test_sessions_are_not_split_at_midnight():
    # GA4: "Sessions aren't restarted at midnight." Times are UTC instants; no day boundary.
    page = {
        "type": "page",
        "userId": "con-1",
        "anonymousId": "a-1",
        "context": {"page": {"url": "https://www.acme.example/"}, "campaign": {}},
    }
    late = validate_events(
        [
            {**page, "messageId": "m-1", "timestamp": "2026-09-01T23:50:00Z"},
            {**page, "messageId": "m-2", "timestamp": "2026-09-02T00:10:00Z"},
        ]
    ).accepted  # fmt: skip
    assert len(late) == 2
    counted, in_session = rules(late)
    assert counted == {"m-1": "FIRST_SESSION"}
    assert in_session == {"m-2": "m-1"}


def test_each_device_has_its_own_sessions():
    # GA4 scopes a session to one browser (user_pseudo_id + session_id); Dreamdata is silent.
    # Two browsers of the same contact at overlapping times are two sessions.
    counted, in_session = rules(
        [
            ev("page", "m-1", "10:00:00", anon="a-1", user="con-1", campaign=ADS),
            ev("page", "m-2", "10:05:00", anon="a-2", user="con-1", campaign=("li", "social", "x")),
            ev("page", "m-3", "10:06:00", anon="a-1", user="con-1"),
        ]
    )
    assert counted == {"m-1": "FIRST_SESSION", "m-2": "NEW_DEVICE"}
    assert in_session == {"m-3": "m-1"}


def test_returning_on_a_known_device_after_inactivity_is_inactivity():
    counted, _ = rules(
        [
            ev("page", "m-1", "10:00:00", anon="a-1", user="con-1"),
            ev("page", "m-2", "10:05:00", anon="a-2", user="con-1"),
            ev("page", "m-3", "11:00:00", anon="a-2", user="con-1"),
        ]
    )
    assert counted == {"m-1": "FIRST_SESSION", "m-2": "NEW_DEVICE", "m-3": "INACTIVITY"}


def test_stitched_anonymous_views_and_later_identified_views_are_one_session():
    # Same browser before and after the identify: one session, credited to the anonymous
    # landing view (GA4 keeps the session when a user ID is set mid-session).
    counted, in_session = rules(
        [
            ev("page", "m-anon", "10:00:00", campaign=ADS),
            ev("identify", "m-id", "10:01:00", user="con-1"),
            ev("page", "m-2", "10:02:00", user="con-1", referrer="https://www.acme.example/"),
            ev("page", "m-other", "10:03:00", anon="a-9", user="con-2"),
        ],
        contacts={"con-1", "con-2"},
    )
    assert counted == {"m-anon": "FIRST_SESSION", "m-other": "FIRST_SESSION"}
    assert in_session == {"m-2": "m-anon"}


def track(message_id, at, anon="a-1", user="con-1"):
    payload = {"type": "track", "event": "Demo Requested", "messageId": message_id,
               "anonymousId": anon, "timestamp": f"2026-09-01T{at}Z"}  # fmt: skip
    if user:
        payload["userId"] = user
    (event,) = validate_events([payload]).accepted
    return event


def test_track_events_keep_a_session_alive():
    # Dreamdata and GA4 time out on inactivity across all of the session's events, not only
    # page views. (M3: track events did not extend a visit.)
    counted, in_session = rules(
        [
            ev("page", "m-1", "10:00:00", user="con-1"),
            track("m-t", "10:20:00"),
            ev("page", "m-2", "10:40:00", user="con-1"),  # 40 min after m-1, 20 after m-t
        ]
    )
    assert counted == {"m-1": "FIRST_SESSION"}
    assert in_session == {"m-2": "m-1"}


def test_a_session_is_credited_to_its_first_page_view_even_if_a_track_came_first():
    counted, _ = rules(
        [
            ev("page", "m-0", "09:00:00", user="con-1"),
            track("m-t", "10:00:00"),  # starts the second session (60 min idle)
            ev("page", "m-1", "10:05:00", user="con-1", campaign=ADS),
        ]
    )
    assert counted == {"m-0": "FIRST_SESSION", "m-1": "INACTIVITY"}


def test_a_session_without_utms_is_credited_to_its_referrer():
    # Decision #7: the first page view's UTMs, or its referrer when it has none. The referrer
    # host becomes the source with medium "referral" (GA4's Referral channel).
    result = events_to_touchpoints(
        [ev("page", "m-1", "10:00:00", user="con-1", referrer="https://www.duckduckgo.com/q")],
        {"con-1"},
    )
    (tp,) = result.touchpoints
    assert (tp.source, tp.medium, tp.campaign) == ("duckduckgo.com", "referral", "")
    assert tp.referrer == "https://www.duckduckgo.com/q"


def test_utms_win_over_the_referrer_and_own_site_referrers_are_not_referrals():
    utm = ev("page", "m-1", "10:00:00", user="con-1", campaign=ADS,
             referrer="https://www.google.com/")  # fmt: skip
    own = ev("page", "m-2", "11:00:00", user="con-1", referrer="https://acme.example/x")
    result = events_to_touchpoints([utm, own], {"con-1"})
    assert [(t.source, t.medium, t.campaign) for t in result.touchpoints] == [ADS, ("", "", "")]
