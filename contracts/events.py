"""Event contract for RudderStack page / track / identify payloads (docs/contract.md, "Events").

`validate_events` checks a batch of payloads in arrival order. Collection and storage are
M2; this module only decides what an event must carry to count.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from contracts.codes import RejectReason, WarningCode
from contracts.fields import parse_id, parse_timestamp
from contracts.imports import Issue, RejectedRow

R, W = RejectReason, WarningCode

EVENT_TYPES = ("page", "track", "identify")
FUNNEL_MILESTONES = ("Demo Requested", "Lead Qualified", "Opportunity Created", "Opportunity Won")
# RudderStack's context.campaign keys -> our UTM names (the SDK maps utm_campaign to "name").
CAMPAIGN_KEYS = {
    "source": "utm_source",
    "medium": "utm_medium",
    "name": "utm_campaign",
    "content": "utm_content",
    "term": "utm_term",
}


@dataclass(frozen=True)
class Event:
    event_id: str  # RudderStack messageId; the deduplication key
    type: str
    event_name: str  # track only
    anonymous_id: str
    user_id: str  # contact_id from the import contract, set by identify
    occurred_at: datetime  # UTC, from `timestamp` (falls back to originalTimestamp)
    original_timestamp: str  # preserved verbatim
    page_url: str
    referrer: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str
    utm_term: str


@dataclass
class EventReport:
    accepted: list[Event] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def validate_events(payloads: list[Any]) -> EventReport:
    report = EventReport()
    first_seen: dict[str, str] = {}  # messageId -> canonical JSON of the first payload
    for position, payload in enumerate(payloads, start=1):
        payload_obj = _obj(payload)
        event_id = _text(payload_obj.get("messageId"))
        issues: list[Issue] = []

        def reject(code, column, message, event_id=event_id, position=position, issues=issues):
            issues.append(Issue("events", position, event_id, code, column, message))

        canonical = json.dumps(payload, sort_keys=True, default=str)
        if event_id in first_seen:
            if first_seen[event_id] == canonical:
                report.warnings.append(
                    Issue(
                        "events",
                        position,
                        event_id,
                        W.DUPLICATE_ROW,
                        "messageId",
                        "Retry of an earlier event; counted once.",
                    )
                )
                continue
            reject(R.DUPLICATE_ID, "messageId", "messageId was already used by another event.")
            report.rejected.append(RejectedRow("events", position, event_id, {}, tuple(issues)))
            continue

        event = _parse(payload_obj, reject)
        if issues:
            report.rejected.append(RejectedRow("events", position, event_id, {}, tuple(issues)))
            continue
        first_seen[event_id] = canonical
        report.accepted.append(event)
        report.warnings.extend(_warnings(event, position))
    return report


def _parse(payload: dict, reject) -> Event | None:
    event_type = _text(payload.get("type"))
    if not event_type:
        reject(R.MISSING_REQUIRED_FIELD, "type", "type is required.")
        return None
    if event_type not in EVENT_TYPES:
        reject(R.UNSUPPORTED_EVENT_TYPE, "type", f"{event_type!r} is not page, track or identify.")
        return None

    event_id = _text(payload.get("messageId"))
    if not event_id:
        reject(R.MISSING_REQUIRED_FIELD, "messageId", "messageId is required.")
    elif parse_id(event_id)[1]:
        reject(R.INVALID_ID, "messageId", f"{event_id!r} is not a valid ID.")

    anonymous_id = _text(payload.get("anonymousId"))
    user_id = _text(payload.get("userId"))
    if event_type == "identify" and not user_id:
        reject(R.MISSING_REQUIRED_FIELD, "userId", "identify needs userId (the contact_id).")
    elif not anonymous_id and not user_id:
        reject(R.MISSING_IDENTITY, "anonymousId", "Needs anonymousId or userId.")
    if user_id and parse_id(user_id)[1]:
        reject(R.INVALID_ID, "userId", f"{user_id!r} is not a valid contact_id.")

    event_name = _text(payload.get("event"))
    if event_type == "track" and not event_name:
        reject(R.MISSING_REQUIRED_FIELD, "event", "track needs an event name.")

    context = _obj(payload.get("context"))
    page = _obj(context.get("page"))
    properties = _obj(payload.get("properties"))
    page_url = _text(page.get("url")) or _text(properties.get("url"))
    if event_type == "page" and not page_url:
        reject(R.MISSING_REQUIRED_FIELD, "page.url", "page needs context.page.url.")

    original = _text(payload.get("originalTimestamp"))
    column = "timestamp" if _text(payload.get("timestamp")) else "originalTimestamp"
    raw_time = _text(payload.get(column))
    occurred_at = None
    if not raw_time:
        reject(R.MISSING_REQUIRED_FIELD, "timestamp", "timestamp or originalTimestamp is required.")
    else:
        occurred_at, reason = parse_timestamp(raw_time)
        if reason:
            reject(reason, column, f"{raw_time!r} must be ISO 8601 with a UTC offset.")

    campaign = _obj(context.get("campaign"))
    utm = {ours: _text(campaign.get(theirs)) for theirs, ours in CAMPAIGN_KEYS.items()}
    if occurred_at is None:
        return None
    return Event(
        event_id=event_id,
        type=event_type,
        event_name=event_name,
        anonymous_id=anonymous_id,
        user_id=user_id,
        occurred_at=occurred_at,
        original_timestamp=original,
        page_url=page_url,
        referrer=_text(page.get("referrer")) or _text(properties.get("referrer")),
        **utm,
    )


def _warnings(event: Event, position: int) -> list[Issue]:
    warnings = []
    if event.type == "track" and event.event_name not in FUNNEL_MILESTONES:
        warnings.append(
            Issue(
                "events",
                position,
                event.event_id,
                W.UNKNOWN_EVENT_NAME,
                "event",
                f"{event.event_name!r} is not a funnel milestone.",
            )
        )
    if event.type == "page":
        blank = [
            name
            for name in ("utm_source", "utm_medium", "utm_campaign")
            if not getattr(event, name)
        ]
        if blank:
            warnings.append(
                Issue(
                    "events",
                    position,
                    event.event_id,
                    W.MISSING_CAMPAIGN_FIELDS,
                    ", ".join(blank),
                    "Blank campaign fields are reported as (none), not guessed.",
                )
            )
    return warnings
