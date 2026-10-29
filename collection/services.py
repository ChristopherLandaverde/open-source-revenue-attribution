"""Store collected events through the event contract, and turn them into touchpoints.

The rules live in `contracts/` (validation, deduplication, event -> touchpoint). This module
only persists what those pure functions decide.
"""

import secrets
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from collection.models import CollectedEvent, Workspace
from contracts import Event, WarningCode, content_fingerprint, validate_events
from contracts.touchpoints import TouchpointConversion, events_to_touchpoints
from reports.models import Contact, Touchpoint


@dataclass
class Outcome:
    """What happened to one payload in a request, in the order received."""

    position: int
    message_id: str
    outcome: str  # "accepted" | "duplicate" | "rejected"
    issues: list[dict] = field(default_factory=list)


def new_write_key() -> str:
    return secrets.token_urlsafe(24)


def workspace_for_write_key(write_key: str) -> Workspace | None:
    if not write_key:
        return None
    return Workspace.objects.filter(write_key=write_key).first()


def _message_id(payload: Any) -> str:
    value = payload.get("messageId") if isinstance(payload, dict) else None
    return "" if value is None else str(value).strip()[:255]


def _issue_dicts(issues, position: int) -> list[dict]:
    return [{**issue.to_dict(), "row": position} for issue in issues]


def ingest(workspace: Workspace, payloads: list[Any]) -> list[Outcome]:
    """Validate and store each payload in order; return one Outcome per payload.

    Touchpoints are then recomputed from every accepted event, because an identify can
    stitch earlier page views and a new page view can change which views start a visit.
    """
    outcomes = []
    for position, payload in enumerate(payloads, start=1):
        try:
            outcomes.append(_ingest_one(workspace, payload, position))
        except IntegrityError:
            # A concurrent request stored the same messageId or payload first: re-run, and
            # the payload now meets the stored row (a retry or a conflict).
            outcomes.append(_ingest_one(workspace, payload, position))
    if any(o.outcome == "accepted" for o in outcomes):
        sync_event_touchpoints()
    return outcomes


@transaction.atomic
def _ingest_one(workspace: Workspace, payload: Any, position: int) -> Outcome:
    now = timezone.now()
    message_id = _message_id(payload)
    fingerprint = content_fingerprint(payload)
    earlier = (
        CollectedEvent.objects.filter(status=CollectedEvent.Status.ACCEPTED, message_id=message_id)
        .only("id", "fingerprint")
        .first()
        if message_id
        else None
    )
    report = validate_events(
        [payload],
        already_accepted={message_id: earlier.fingerprint} if earlier else None,
        received_at=now,  # receivedAt for clock-skew correction (decision #5)
    )

    if report.accepted:
        (event,) = report.accepted
        CollectedEvent.objects.create(
            workspace=workspace,
            status=CollectedEvent.Status.ACCEPTED,
            message_id=event.event_id,
            fingerprint=fingerprint,
            payload=payload,
            issues=_issue_dicts(report.warnings, position),
            first_received_at=now,
            last_received_at=now,
            type=event.type,
            user_id=event.user_id,
            occurred_at=event.occurred_at,
            normalized=_to_json(event),
        )
        warnings = _issue_dicts(report.warnings, position)
        return Outcome(position, event.event_id, "accepted", warnings)

    retry = [w for w in report.warnings if w.code == WarningCode.DUPLICATE_ROW]
    if retry and earlier:
        CollectedEvent.objects.filter(pk=earlier.pk).update(
            times_received=F("times_received") + 1, last_received_at=now
        )
        return Outcome(position, message_id, "duplicate", _issue_dicts(retry, position))

    issues = _issue_dicts([i for row in report.rejected for i in row.issues], position)
    updated = CollectedEvent.objects.filter(
        status=CollectedEvent.Status.REJECTED, fingerprint=fingerprint
    ).update(times_received=F("times_received") + 1, last_received_at=now)
    if not updated:
        CollectedEvent.objects.create(
            workspace=workspace,
            status=CollectedEvent.Status.REJECTED,
            message_id=message_id,
            fingerprint=fingerprint,
            payload=payload,
            issues=issues,
            first_received_at=now,
            last_received_at=now,
        )
    return Outcome(position, message_id, "rejected", issues)


# --- events -> touchpoints ------------------------------------------------------


def _to_json(event: Event) -> dict:
    return {**asdict(event), "occurred_at": event.occurred_at.isoformat()}


def _from_json(data: dict) -> Event:
    known = {f.name for f in fields(Event)}
    data = {k: v for k, v in data.items() if k in known}
    return Event(**{**data, "occurred_at": datetime.fromisoformat(data["occurred_at"])})


def accepted_events() -> list[Event]:
    rows = CollectedEvent.objects.filter(status=CollectedEvent.Status.ACCEPTED)
    return [_from_json(row.normalized) for row in rows.only("normalized")]


def _contacts_for(events: list[Event]) -> set[str]:
    user_ids = {e.user_id for e in events if e.user_id}  # identify userIds cover stitched views
    found = Contact.objects.filter(external_id__in=user_ids)
    return set(found.values_list("external_id", flat=True))


def _save_touchpoints(conversion: TouchpointConversion) -> None:
    contacts = {
        c.external_id: c
        for c in Contact.objects.filter(
            external_id__in={tp.contact_id for tp in conversion.touchpoints}
        )
    }
    for tp in conversion.touchpoints:
        Touchpoint.objects.update_or_create(
            origin=Touchpoint.Origin.EVENT,
            external_id=tp.touchpoint_id,
            defaults={
                "contact": contacts[tp.contact_id],
                "occurred_at": tp.occurred_at,
                "source": tp.source,
                "medium": tp.medium,
                "campaign": tp.campaign,
                "content": tp.content,
                "term": tp.term,
                "landing_page": tp.landing_page,
                "referrer": tp.referrer,
                "stitched_from": tp.stitched_from[:255],
                "visit_rule": tp.visit_rule,
            },
        )
    # Page views that no longer qualify (now internal navigation, or now ambiguous) go away.
    stale = Touchpoint.objects.filter(origin=Touchpoint.Origin.EVENT).exclude(
        external_id__in=[tp.touchpoint_id for tp in conversion.touchpoints]
    )
    stale.delete()


def convert_events() -> TouchpointConversion:
    """What every accepted event converts to, given the contacts imported so far."""
    events = accepted_events()
    return events_to_touchpoints(events, _contacts_for(events))


@transaction.atomic
def sync_event_touchpoints() -> TouchpointConversion:
    """Create or update touchpoints for every accepted event. Idempotent.

    Run after each import, because an event whose contact was not imported yet becomes a
    touchpoint once the contact arrives.
    """
    conversion = convert_events()
    _save_touchpoints(conversion)
    return conversion
