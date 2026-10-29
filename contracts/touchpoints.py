"""Accepted RudderStack events -> touchpoints (docs/contract.md, "From events to touchpoints").

Deterministic and pure. Decided in #5 (M3) and #7:

1. **Stitching (#5).** An identify links its `anonymousId` to its `userId` (a contact_id).
   Anonymous events with that `anonymousId`, at or before the identify, belong to that
   contact, so the landing session that carried the UTMs reaches the contact. Only identify
   events link, and only earlier anonymous history. An `anonymousId` identified as two or more
   different contacts is ambiguous (a shared browser) and none of its anonymous events link.
2. **Sessions (#7, Dreamdata and GA4).** Per contact and browser (`anonymousId`), events in
   time order form sessions: each event less than 30 minutes after the previous one stays in
   the session; a gap of 30 minutes or more starts a new one. A new campaign, a new referrer
   or midnight does not. Page, track and identify events all keep a session alive.
3. **One touchpoint per session:** its first page view, credited to that view's UTMs, or to
   its external referrer (source = host, medium = `referral`) when it has none. The session's
   other page views are kept and shown in the journey (`SAME_SESSION`), never counted again.
4. Event time is the event contract's (skew-corrected) time.

Campaign fields come only from `context.campaign` (already mapped by `validate_events`). The
touchpoint ID is the event's `messageId`, so re-running is idempotent.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit

from contracts.events import Event

SESSION_TIMEOUT = timedelta(minutes=30)  # a gap of this or more starts a new session
REFERRAL_MEDIUM = "referral"  # GA4's Referral channel: medium "referral"


class SkipReason(StrEnum):
    """Why an accepted event did not become a touchpoint. Not a refusal: the event is kept."""

    NOT_A_PAGE_VIEW = "NOT_A_PAGE_VIEW"
    ANONYMOUS = "ANONYMOUS"
    CONTACT_NOT_IMPORTED = "CONTACT_NOT_IMPORTED"
    SAME_SESSION = "SAME_SESSION"  # a later page view of a session (#7; was INTERNAL_NAVIGATION)
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"


class TouchReason(StrEnum):
    """Why a session started, recorded on its touchpoint (#7)."""

    FIRST_SESSION = "FIRST_SESSION"  # the contact's first session
    INACTIVITY = "INACTIVITY"  # 30 minutes or more since this browser's previous event
    NEW_DEVICE = "NEW_DEVICE"  # the contact's first session from this browser (anonymousId)


@dataclass(frozen=True)
class EventTouchpoint:
    """A page view attributed to a contact. In `session_views` it is not a touchpoint."""

    touchpoint_id: str  # the event's messageId
    contact_id: str
    occurred_at: datetime  # UTC
    source: str
    medium: str
    campaign: str
    content: str
    term: str
    landing_page: str
    referrer: str
    stitched_from: str = ""  # the anonymousId, when linked by a later identify
    visit_rule: str = ""  # a TouchReason, or SAME_SESSION
    session_id: str = ""  # the messageId of the session's touchpoint (its first page view)


@dataclass
class TouchpointConversion:
    touchpoints: list[EventTouchpoint] = field(default_factory=list)
    skipped: list[tuple[str, SkipReason]] = field(default_factory=list)
    # The contacts' later page views inside a session (not touchpoints), for journeys.
    session_views: list[EventTouchpoint] = field(default_factory=list)


def _order(item) -> tuple[datetime, str]:
    return (item.occurred_at, item.event_id if isinstance(item, Event) else item.touchpoint_id)


def _host(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")


def _external_referrer(page_url: str, referrer: str) -> str:
    """The referrer's host when it is another site ("" for none, or the same site)."""
    host = _host(referrer)
    return host if host and host != _host(page_url) else ""


def _identities(events: list[Event]) -> tuple[dict[str, list[tuple[datetime, str]]], set[str]]:
    """anonymousId -> [(identify time, userId)], and the anonymousIds with conflicting userIds."""
    links: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for event in events:
        if event.type == "identify" and event.anonymous_id:
            links[event.anonymous_id].append((event.occurred_at, event.user_id))
    ambiguous = {anon for anon, ids in links.items() if len({uid for _, uid in ids}) > 1}
    return links, ambiguous


def _whose(event: Event, links, ambiguous) -> tuple[str, str, SkipReason | None]:
    """(contact_id, stitched_from, reason it has no contact)."""
    if event.user_id:
        return event.user_id, "", None
    if event.anonymous_id in ambiguous:
        return "", "", SkipReason.AMBIGUOUS_IDENTITY
    later = [uid for at, uid in links.get(event.anonymous_id, ()) if at >= event.occurred_at]
    if not later:
        return "", "", SkipReason.ANONYMOUS
    return later[0], event.anonymous_id, None


def events_to_touchpoints(
    events: Iterable[Event], known_contacts: Collection[str]
) -> TouchpointConversion:
    """Convert accepted events. Every list in the result is ordered by (time, event ID)."""
    ordered = sorted(events, key=_order)
    links, ambiguous = _identities(ordered)
    result = TouchpointConversion()
    # (contact, browser) -> its events in order; page views as EventTouchpoint, others as None.
    activity: dict[tuple[str, str], list[tuple[datetime, EventTouchpoint | None]]]
    activity = defaultdict(list)

    for event in ordered:
        contact_id, stitched_from, no_contact = _whose(event, links, ambiguous)
        device = (contact_id, event.anonymous_id)
        if event.type != "page":
            result.skipped.append((event.event_id, SkipReason.NOT_A_PAGE_VIEW))
            if contact_id in known_contacts:
                activity[device].append((event.occurred_at, None))  # keeps a session alive
            continue
        if no_contact:
            result.skipped.append((event.event_id, no_contact))
            continue
        if contact_id not in known_contacts:
            result.skipped.append((event.event_id, SkipReason.CONTACT_NOT_IMPORTED))
            continue
        activity[device].append(
            (
                event.occurred_at,
                EventTouchpoint(
                    touchpoint_id=event.event_id,
                    contact_id=contact_id,
                    occurred_at=event.occurred_at,
                    source=event.utm_source,
                    medium=event.utm_medium,
                    campaign=event.utm_campaign,
                    content=event.utm_content,
                    term=event.utm_term,
                    landing_page=event.page_url,
                    referrer=event.referrer,
                    stitched_from=stitched_from,
                ),
            )
        )

    in_session = set()
    for touch, views in _sessions(activity):
        result.touchpoints.append(touch)
        for view in views:
            in_session.add(view.touchpoint_id)
            result.session_views.append(view)
    if in_session:
        # Keep `skipped` in event order: rebuild it with the in-session views slotted in.
        reasons = dict(result.skipped)
        reasons.update(dict.fromkeys(in_session, SkipReason.SAME_SESSION))
        result.skipped = [
            (e.event_id, reasons[e.event_id]) for e in ordered if e.event_id in reasons
        ]
    result.touchpoints.sort(key=_order)
    result.session_views.sort(key=_order)
    return result


def _sessions(activity):
    """Yield (touchpoint, [later page views]) for every session that has a page view."""
    by_contact = defaultdict(list)  # contact -> [(start time, first view ID, browser, views)]
    for (contact_id, browser), items in activity.items():
        sessions, last = [], None
        for at, view in items:  # already in (time, ID) order
            if last is None or at - last >= SESSION_TIMEOUT:
                sessions.append((at, []))
            last = at
            if view is not None:
                sessions[-1][1].append(view)
        for start, views in sessions:
            if views:
                by_contact[contact_id].append((start, views[0].touchpoint_id, browser, views))
    for sessions in by_contact.values():
        seen = set()
        for _, _, browser, views in sorted(sessions, key=lambda s: s[:2]):
            if not seen:
                rule = TouchReason.FIRST_SESSION
            elif browser not in seen:
                rule = TouchReason.NEW_DEVICE
            else:
                rule = TouchReason.INACTIVITY
            seen.add(browser)
            first, *rest = views
            session_id = first.touchpoint_id
            yield (
                replace(first, visit_rule=str(rule), session_id=session_id, **_credit(first)),
                [
                    replace(v, visit_rule=str(SkipReason.SAME_SESSION), session_id=session_id)
                    for v in rest
                ],
            )


def _credit(view: EventTouchpoint) -> dict[str, str]:
    """The session's UTMs as given; with none, its external referrer as a referral (#7)."""
    if any((view.source, view.medium, view.campaign)):
        return {}
    host = _external_referrer(view.landing_page, view.referrer)
    return {"source": host, "medium": REFERRAL_MEDIUM} if host else {}
