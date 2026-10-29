"""Event contract for RudderStack page / track / identify payloads (docs/contract.md, "Events").

`validate_events` checks a batch of payloads in arrival order. It decides what an event
must carry to count; the Django app (`collection/`) stores what it returns.
"""

import hashlib
import json
from collections.abc import Mapping
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


# Top-level fields the SDK rewrites on every delivery attempt. They are transport metadata,
# not event content, so a retry that differs only here is still an exact retry.
TRANSPORT_FIELDS = ("sentAt",)


def content_fingerprint(payload: Any) -> str:
    """SHA-256 of the payload's canonical JSON, ignoring TRANSPORT_FIELDS.

    Two payloads with the same fingerprint are the same event content.
    """
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k not in TRANSPORT_FIELDS}
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Event:
    event_id: str  # RudderStack messageId; the deduplication key
    type: str
    event_name: str  # track only
    anonymous_id: str
    user_id: str  # contact_id from the import contract, set by identify
    occurred_at: datetime  # UTC event time; how it was derived is in `time_source`
    original_timestamp: str  # preserved verbatim
    page_url: str
    referrer: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str
    utm_term: str
    # M3 (decision #5): "timestamp" (server-corrected, used as is), "skew_corrected"
    # (originalTimestamp + receivedAt - sentAt) or "original_timestamp" (browser clock, with a
    # CLOCK_SKEW_NOT_CORRECTED warning). Defaults keep events stored before M3 readable.
    time_source: str = "timestamp"
    sent_at: str = ""  # preserved verbatim


TIME_FROM_TIMESTAMP = "timestamp"
TIME_SKEW_CORRECTED = "skew_corrected"
TIME_BROWSER_CLOCK = "original_timestamp"


@dataclass
class EventReport:
    accepted: list[Event] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def validate_events(
    payloads: list[Any],
    already_accepted: Mapping[str, str] | None = None,
    received_at: datetime | None = None,
) -> EventReport:
    """Validate payloads in arrival order.

    `already_accepted` maps messageIds accepted earlier (for example, in previous requests)
    to their `content_fingerprint`, so retries across requests follow the same rules as
    retries within one batch.

    `received_at` is when the server received the request (UTC-aware). With it, events that
    carry only the browser clock are corrected for clock skew (see `_event_time`).
    """
    report = EventReport()
    first_seen: dict[str, str] = dict(already_accepted or {})  # messageId -> fingerprint
    for position, payload in enumerate(payloads, start=1):
        payload_obj = _obj(payload)
        event_id = _text(payload_obj.get("messageId"))
        issues: list[Issue] = []

        def reject(code, column, message, event_id=event_id, position=position, issues=issues):
            issues.append(Issue("events", position, event_id, code, column, message))

        canonical = content_fingerprint(payload)
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

        event, uncorrected = _parse(payload_obj, reject, received_at)
        if issues:
            report.rejected.append(RejectedRow("events", position, event_id, {}, tuple(issues)))
            continue
        first_seen[event_id] = canonical
        report.accepted.append(event)
        report.warnings.extend(_warnings(event, position, uncorrected))
    return report


def _event_time(
    payload: dict, reject, received_at: datetime | None
) -> tuple[datetime | None, str, str]:
    """(event time in UTC, time_source, why skew was not corrected).

    RudderStack's rule: a server `timestamp` is already corrected and is used as is. Otherwise
    event time = originalTimestamp + (receivedAt - sentAt): the gap between when the browser
    says it sent the event and when the server got it is the browser clock's error (plus
    network latency, as in RudderStack). Without a usable sentAt or receive time the browser
    clock is used and the reason is returned for a CLOCK_SKEW_NOT_CORRECTED warning.
    """
    raw_timestamp = _text(payload.get("timestamp"))
    column = "timestamp" if raw_timestamp else "originalTimestamp"
    raw_time = raw_timestamp or _text(payload.get("originalTimestamp"))
    if not raw_time:
        reject(R.MISSING_REQUIRED_FIELD, "timestamp", "timestamp or originalTimestamp is required.")
        return None, "", ""
    occurred_at, reason = parse_timestamp(raw_time)
    if reason:
        reject(reason, column, f"{raw_time!r} must be ISO 8601 with a UTC offset.")
        return None, "", ""
    if raw_timestamp:
        return occurred_at, TIME_FROM_TIMESTAMP, ""

    raw_sent = _text(payload.get("sentAt"))
    if not raw_sent:
        return occurred_at, TIME_BROWSER_CLOCK, "no sentAt"
    sent_at, sent_reason = parse_timestamp(raw_sent)
    if sent_reason == R.TIMESTAMP_WITHOUT_TIMEZONE:
        return occurred_at, TIME_BROWSER_CLOCK, "sentAt has no UTC offset"
    if sent_reason:
        return occurred_at, TIME_BROWSER_CLOCK, "sentAt is not ISO 8601"
    if received_at is None:
        return occurred_at, TIME_BROWSER_CLOCK, "no receive time"
    return occurred_at + (received_at - sent_at), TIME_SKEW_CORRECTED, ""


def _parse(payload: dict, reject, received_at: datetime | None = None) -> tuple[Event | None, str]:
    """The typed event (None if refused) and why skew was not corrected ("" if it was)."""
    event_type = _text(payload.get("type"))
    if not event_type:
        reject(R.MISSING_REQUIRED_FIELD, "type", "type is required.")
        return None, ""
    if event_type not in EVENT_TYPES:
        reject(R.UNSUPPORTED_EVENT_TYPE, "type", f"{event_type!r} is not page, track or identify.")
        return None, ""

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
    occurred_at, time_source, uncorrected = _event_time(payload, reject, received_at)

    campaign = _obj(context.get("campaign"))
    utm = {ours: _text(campaign.get(theirs)) for theirs, ours in CAMPAIGN_KEYS.items()}
    referrer = _text(page.get("referrer")) or _text(properties.get("referrer"))
    # Text limits from the general rules (docs/contract.md section 1).
    limits = [("page.url", page_url, 500), ("page.referrer", referrer, 500)]
    limits += [(name, value, 200) for name, value in utm.items()]
    for column, value, limit in limits:
        if len(value) > limit:
            reject(R.VALUE_TOO_LONG, column, f"{column} is {len(value)} characters; limit {limit}.")
    if occurred_at is None:
        return None, ""
    return Event(
        event_id=event_id,
        type=event_type,
        event_name=event_name,
        anonymous_id=anonymous_id,
        user_id=user_id,
        occurred_at=occurred_at,
        original_timestamp=original,
        page_url=page_url,
        referrer=referrer,
        **utm,
        time_source=time_source,
        sent_at=_text(payload.get("sentAt")),
    ), uncorrected


def _warnings(event: Event, position: int, uncorrected: str = "") -> list[Issue]:
    warnings = []
    if uncorrected:
        warnings.append(
            Issue(
                "events",
                position,
                event.event_id,
                W.CLOCK_SKEW_NOT_CORRECTED,
                "sentAt",
                f"Event time is the browser clock (originalTimestamp) uncorrected: {uncorrected}.",
            )
        )
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
