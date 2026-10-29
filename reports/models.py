"""Records loaded through the import contract (docs/contract.md). Physical schema grows in M2-M3."""

from django.db import models


class Account(models.Model):
    external_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200, blank=True)
    domain = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name or self.external_id


class Contact(models.Model):
    """Joined to an account only by explicit ID; never inferred."""

    external_id = models.CharField(max_length=64, unique=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="contacts")
    email = models.EmailField(blank=True)

    def __str__(self):
        return self.external_id


class Opportunity(models.Model):
    class Stage(models.TextChoices):
        OPEN = "open", "Open"
        WON = "won", "Won"

    external_id = models.CharField(max_length=64, unique=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="opportunities")
    # Optional: an opportunity without a contact has no touchpoints and is Unattributed.
    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="opportunities",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    stage = models.CharField(max_length=16, choices=Stage.choices)
    created_at = models.DateTimeField()
    won_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "opportunities"

    def __str__(self):
        return self.name or self.external_id


class Touchpoint(models.Model):
    class Origin(models.TextChoices):
        CSV = "csv", "touchpoints.csv"
        EVENT = "event", "Collected page event"

    # touchpoint_id from touchpoints.csv, or the messageId of the page event it came from.
    external_id = models.CharField(max_length=64)
    origin = models.CharField(max_length=8, choices=Origin.choices, default=Origin.CSV)
    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="touchpoints")
    occurred_at = models.DateTimeField()
    source = models.CharField(max_length=200, blank=True)
    medium = models.CharField(max_length=200, blank=True)
    campaign = models.CharField(max_length=200, blank=True)
    content = models.CharField(max_length=200, blank=True)
    term = models.CharField(max_length=200, blank=True)
    landing_page = models.CharField(max_length=500, blank=True)
    referrer = models.CharField(max_length=500, blank=True)
    # Event touchpoints only (contracts/touchpoints.py): the anonymousId when the page view was
    # linked to the contact by a later identify, and the session rule that made it a touchpoint
    # (a contracts.touchpoints.TouchReason; the column kept its M3 name).
    stitched_from = models.CharField(max_length=255, blank=True)
    visit_rule = models.CharField(max_length=32, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["origin", "external_id"], name="touchpoint_unique_origin_external_id"
            )
        ]

    def __str__(self):
        return self.external_id


class ImportRun(models.Model):
    """Provenance of one import: where it came from and its full validation report."""

    source = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    lookback_days = models.PositiveIntegerField()
    strict = models.BooleanField(default=False)
    loaded = models.BooleanField(help_text="False when a strict import refused everything.")
    report = models.JSONField()  # contracts.ImportReport.to_dict()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.source} @ {self.created_at:%Y-%m-%d %H:%M}"
