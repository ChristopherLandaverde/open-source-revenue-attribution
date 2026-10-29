"""Accepted RudderStack events -> touchpoints (docs/contract.md, "From events to touchpoints").

Deterministic and pure. One identified page view is one touchpoint:

- only `page` events become touchpoints; `track` and `identify` never do;
- the event must itself carry `userId`, and that `userId` must be an imported `contact_id`.
  Earlier anonymous page views are not linked back through an identify event;
- campaign fields come only from `context.campaign` (already mapped by `validate_events`);
  blanks stay blank and are reported as `(none)`;
- the touchpoint ID is the event's `messageId`, so re-running the conversion is idempotent.

No sessionisation yet: every identified page view counts, including ones without UTMs.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from contracts.events import Event


class SkipReason(StrEnum):
    """Why an accepted event did not become a touchpoint. Not a refusal: the event is kept."""

    NOT_A_PAGE_VIEW = "NOT_A_PAGE_VIEW"
    ANONYMOUS = "ANONYMOUS"
    CONTACT_NOT_IMPORTED = "CONTACT_NOT_IMPORTED"


@dataclass(frozen=True)
class EventTouchpoint:
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


@dataclass
class TouchpointConversion:
    touchpoints: list[EventTouchpoint] = field(default_factory=list)
    skipped: list[tuple[str, SkipReason]] = field(default_factory=list)


def events_to_touchpoints(
    events: Iterable[Event], known_contacts: Collection[str]
) -> TouchpointConversion:
    """Convert accepted events. Output is ordered by (occurred_at, event ID)."""
    result = TouchpointConversion()
    for event in sorted(events, key=lambda e: (e.occurred_at, e.event_id)):
        if event.type != "page":
            result.skipped.append((event.event_id, SkipReason.NOT_A_PAGE_VIEW))
        elif not event.user_id:
            result.skipped.append((event.event_id, SkipReason.ANONYMOUS))
        elif event.user_id not in known_contacts:
            result.skipped.append((event.event_id, SkipReason.CONTACT_NOT_IMPORTED))
        else:
            result.touchpoints.append(
                EventTouchpoint(
                    touchpoint_id=event.event_id,
                    contact_id=event.user_id,
                    occurred_at=event.occurred_at,
                    source=event.utm_source,
                    medium=event.utm_medium,
                    campaign=event.utm_campaign,
                    content=event.utm_content,
                    term=event.utm_term,
                    landing_page=event.page_url,
                    referrer=event.referrer,
                )
            )
    return result
