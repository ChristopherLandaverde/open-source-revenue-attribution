"""Accepted RudderStack events -> touchpoints (docs/contract.md, "From events to touchpoints").

Deterministic and pure. Decided in #5 (M3):

1. **Stitching.** An identify links its `anonymousId` to its `userId` (a contact_id). Anonymous
   page views with that `anonymousId`, at or before the identify, belong to that contact, so
   the landing visit that carried the UTMs reaches the contact. Only identify events link, and
   only earlier anonymous history. An `anonymousId` identified as two or more different
   contacts is ambiguous (a shared browser) and none of its anonymous views are linked.
2. **Visits.** Per contact, page views in time order form visits. A page view starts a visit
   when it is the contact's first, when more than 30 minutes passed since the contact's
   previous page view, when it carries campaign data different from the visit's, or when it
   arrives from another site (an external referrer host) different from the visit's.
   A page view is a touchpoint when it starts a visit or carries campaign data. Everything
   else is internal navigation: kept, shown in the journey, never credited.
3. Event time is the event contract's (skew-corrected) time.

Campaign fields come only from `context.campaign` (already mapped by `validate_events`);
blanks stay blank. The touchpoint ID is the event's `messageId`, so re-running is idempotent.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit

from contracts.events import Event

VISIT_TIMEOUT = timedelta(minutes=30)  # a gap of more than this starts a new visit


class SkipReason(StrEnum):
    """Why an accepted event did not become a touchpoint. Not a refusal: the event is kept."""

    NOT_A_PAGE_VIEW = "NOT_A_PAGE_VIEW"
    ANONYMOUS = "ANONYMOUS"
    CONTACT_NOT_IMPORTED = "CONTACT_NOT_IMPORTED"
    INTERNAL_NAVIGATION = "INTERNAL_NAVIGATION"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"


class TouchReason(StrEnum):
    """Why a contact's page view is a touchpoint (the visit rule that admitted it)."""

    FIRST_VISIT = "FIRST_VISIT"
    INACTIVITY = "INACTIVITY"
    NEW_CAMPAIGN = "NEW_CAMPAIGN"
    NEW_REFERRER = "NEW_REFERRER"
    CAMPAIGN_DATA = "CAMPAIGN_DATA"


@dataclass(frozen=True)
class EventTouchpoint:
    """A page view attributed to a contact. In `internal_views` it is not a touchpoint."""

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
    visit_rule: str = ""  # a TouchReason, or INTERNAL_NAVIGATION


@dataclass
class TouchpointConversion:
    touchpoints: list[EventTouchpoint] = field(default_factory=list)
    skipped: list[tuple[str, SkipReason]] = field(default_factory=list)
    # The contacts' page views that were not touchpoints (internal navigation), for journeys.
    internal_views: list[EventTouchpoint] = field(default_factory=list)


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


def events_to_touchpoints(
    events: Iterable[Event], known_contacts: Collection[str]
) -> TouchpointConversion:
    """Convert accepted events. Every list in the result is ordered by (time, event ID)."""
    ordered = sorted(events, key=_order)
    links, ambiguous = _identities(ordered)
    result = TouchpointConversion()
    by_contact: dict[str, list[EventTouchpoint]] = defaultdict(list)

    for event in ordered:
        if event.type != "page":
            result.skipped.append((event.event_id, SkipReason.NOT_A_PAGE_VIEW))
            continue
        contact_id, stitched_from = event.user_id, ""
        if not contact_id:
            if event.anonymous_id in ambiguous:
                result.skipped.append((event.event_id, SkipReason.AMBIGUOUS_IDENTITY))
                continue
            later = [
                uid for at, uid in links.get(event.anonymous_id, ()) if at >= event.occurred_at
            ]
            if not later:
                result.skipped.append((event.event_id, SkipReason.ANONYMOUS))
                continue
            contact_id, stitched_from = later[0], event.anonymous_id
        if contact_id not in known_contacts:
            result.skipped.append((event.event_id, SkipReason.CONTACT_NOT_IMPORTED))
            continue
        by_contact[contact_id].append(
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
            )
        )

    internal_ids = set()
    for views in by_contact.values():
        for view, rule in _apply_visits(views):
            if rule == SkipReason.INTERNAL_NAVIGATION:
                internal_ids.add(view.touchpoint_id)
                result.internal_views.append(_with_rule(view, rule))
            else:
                result.touchpoints.append(_with_rule(view, rule))
    if internal_ids:
        # Keep `skipped` in event order: rebuild it with the internal views slotted in.
        reasons = dict(result.skipped)
        reasons.update(dict.fromkeys(internal_ids, SkipReason.INTERNAL_NAVIGATION))
        result.skipped = [
            (e.event_id, reasons[e.event_id]) for e in ordered if e.event_id in reasons
        ]
    result.touchpoints.sort(key=_order)
    result.internal_views.sort(key=_order)
    return result


def _with_rule(view: EventTouchpoint, rule: str) -> EventTouchpoint:
    return EventTouchpoint(**{**view.__dict__, "visit_rule": str(rule)})


def _apply_visits(views: list[EventTouchpoint]):
    """Yield (view, TouchReason or INTERNAL_NAVIGATION) for one contact's views, in order."""
    last_seen: datetime | None = None
    visit_campaign: tuple[str, str, str] | None = None
    visit_referrer = ""
    for view in views:  # already in (time, ID) order
        campaign = (view.source, view.medium, view.campaign)
        has_campaign = any(campaign)
        referrer = _external_referrer(view.landing_page, view.referrer)
        if last_seen is None:
            rule = TouchReason.FIRST_VISIT
        elif view.occurred_at - last_seen > VISIT_TIMEOUT:
            rule = TouchReason.INACTIVITY
        elif has_campaign and campaign != visit_campaign:
            rule = TouchReason.NEW_CAMPAIGN
        elif referrer and referrer != visit_referrer:
            rule = TouchReason.NEW_REFERRER
        else:
            rule = None
        if rule is not None:
            visit_campaign = campaign if has_campaign else None
            visit_referrer = referrer
        last_seen = view.occurred_at
        if rule is None:
            rule = TouchReason.CAMPAIGN_DATA if has_campaign else SkipReason.INTERNAL_NAVIGATION
        yield view, rule
