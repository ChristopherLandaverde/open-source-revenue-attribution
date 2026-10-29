"""Collected RudderStack events: every payload received, with its validation outcome."""

from django.db import models
from django.db.models import Q


class Workspace(models.Model):
    """A sender of events, identified by its write key.

    The write key authenticates the sender; it is not a secret in the browser (the SDK
    embeds it in the page). All workspaces share one dataset: there is no per-workspace
    data isolation yet.
    """

    name = models.CharField(max_length=200, unique=True)
    write_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class CollectedEvent(models.Model):
    """One distinct payload. Exact retries increment `times_received` instead of adding rows.

    Accepted events are unique by messageId (the contract's deduplication key). Refused
    payloads are unique by content fingerprint, so re-sending the same bad payload does not
    grow the table either.
    """

    class Status(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Refused"

    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT, related_name="events")
    status = models.CharField(max_length=16, choices=Status.choices)
    message_id = models.CharField(max_length=255, blank=True)  # as received
    fingerprint = models.CharField(max_length=64)  # contracts.content_fingerprint
    payload = models.JSONField()  # the first payload received, verbatim
    issues = models.JSONField(default=list)  # refusal reasons and warnings (Issue.to_dict)
    first_received_at = models.DateTimeField()
    last_received_at = models.DateTimeField()
    times_received = models.PositiveIntegerField(default=1)
    # Typed copy of accepted events (contracts.Event); empty for refused payloads.
    type = models.CharField(max_length=16, blank=True)
    user_id = models.CharField(max_length=64, blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    normalized = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-first_received_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["message_id"],
                condition=Q(status="accepted"),
                name="collected_event_unique_accepted_message_id",
            ),
            models.UniqueConstraint(
                fields=["fingerprint"],
                condition=Q(status="rejected"),
                name="collected_event_unique_rejected_payload",
            ),
        ]

    def __str__(self):
        return f"{self.message_id or '(no messageId)'} ({self.status})"
