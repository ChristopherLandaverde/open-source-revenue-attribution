"""Minimal M0 records for the sample dataset. The full schema is designed in M1-M3."""

from django.db import models


class Account(models.Model):
    external_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    domain = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name


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
    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="opportunities")
    name = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    stage = models.CharField(max_length=16, choices=Stage.choices)
    created_at = models.DateTimeField()
    won_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "opportunities"

    def __str__(self):
        return self.name


class Touchpoint(models.Model):
    external_id = models.CharField(max_length=64, unique=True)
    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="touchpoints")
    occurred_at = models.DateTimeField()
    source = models.CharField(max_length=200, blank=True)
    medium = models.CharField(max_length=200, blank=True)
    campaign = models.CharField(max_length=200, blank=True)
    landing_page = models.CharField(max_length=500, blank=True)

    def __str__(self):
        return self.external_id
