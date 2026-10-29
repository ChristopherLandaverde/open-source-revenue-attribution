"""Load the synthetic sample dataset. Idempotent: re-running updates rows by external_id."""

import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_datetime

from reports.models import Account, Contact, Opportunity, Touchpoint

DEFAULT_PATH = Path(settings.BASE_DIR) / "sample_data" / "sample.json"


def _dt(value):
    return parse_datetime(value) if value else None


class Command(BaseCommand):
    help = "Load the synthetic sample dataset (accounts, contacts, touchpoints, opportunities)."

    def add_arguments(self, parser):
        parser.add_argument("--path", type=Path, default=DEFAULT_PATH)

    @transaction.atomic
    def handle(self, *args, path, **options):
        data = json.loads(path.read_text())
        accounts = {
            row["external_id"]: Account.objects.update_or_create(
                external_id=row["external_id"],
                defaults={"name": row["name"], "domain": row.get("domain", "")},
            )[0]
            for row in data["accounts"]
        }
        contacts = {
            row["external_id"]: Contact.objects.update_or_create(
                external_id=row["external_id"],
                defaults={"account": accounts[row["account"]], "email": row.get("email", "")},
            )[0]
            for row in data["contacts"]
        }
        for row in data["touchpoints"]:
            Touchpoint.objects.update_or_create(
                external_id=row["external_id"],
                defaults={
                    "contact": contacts[row["contact"]],
                    "occurred_at": _dt(row["occurred_at"]),
                    "source": row.get("source", ""),
                    "medium": row.get("medium", ""),
                    "campaign": row.get("campaign", ""),
                    "landing_page": row.get("landing_page", ""),
                },
            )
        for row in data["opportunities"]:
            Opportunity.objects.update_or_create(
                external_id=row["external_id"],
                defaults={
                    "contact": contacts[row["contact"]],
                    "name": row["name"],
                    "amount": Decimal(row["amount"]),
                    "currency": row["currency"],
                    "stage": row["stage"],
                    "created_at": _dt(row["created_at"]),
                    "won_at": _dt(row.get("won_at")),
                },
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(accounts)} accounts, {len(contacts)} contacts, "
                f"{len(data['touchpoints'])} touchpoints, "
                f"{len(data['opportunities'])} opportunities from {path.name}."
            )
        )
