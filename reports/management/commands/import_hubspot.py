"""Read companies, contacts and deals from HubSpot (read-only) and import them.

The records are mapped to the CSV import contract (reports/hubspot.py) and go through the same
validation and load as `load_sample_data` and the import page. HubSpot holds no web touches,
so touchpoints come from collected events, or from a touchpoints.csv passed with --touchpoints.
"""

import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from contracts import ImportBatch, validate_import
from reports.hubspot import API_HOST, SCOPES, HubSpotClient, HubSpotError, fetch, to_batch
from reports.imports import describe_report, run_import
from reports.models import Opportunity

SOURCE = f"HubSpot ({API_HOST})"


class Command(BaseCommand):
    help = (
        "Read companies, contacts and deals from HubSpot with a read-only token "
        "(HUBSPOT_TOKEN), map them to the import contract, validate and load them. "
        "--dry-run validates and prints the report without writing anything."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read from HubSpot and validate, print counts and the report; write nothing.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Refuse the whole import if any row fails validation.",
        )
        parser.add_argument(
            "--touchpoints",
            type=Path,
            help="A touchpoints.csv to import with the HubSpot records (its contact_id values "
            "are HubSpot contact IDs). Without it, touchpoints come from collected events.",
        )
        parser.add_argument(
            "--currency",
            default="",
            help="Currency for deals with no currency (deal_currency_code), e.g. USD. Without "
            "it, such deals use the portal's company currency from HubSpot.",
        )

    def handle(self, *args, dry_run, strict, touchpoints, currency, **options):
        token = os.environ.get("HUBSPOT_TOKEN", "").strip()
        if not token:
            raise CommandError(
                "Set HUBSPOT_TOKEN to a HubSpot service key or private app access token with "
                f"read scopes only: {', '.join(SCOPES)}. Nothing was read or written."
            )
        touch_table = None
        if touchpoints is not None:
            if not touchpoints.is_file():
                raise CommandError(f"{touchpoints} is not a file.")
            text = touchpoints.read_bytes().decode("utf-8-sig")
            touch_table = ImportBatch.from_csv_texts({"touchpoints": text}).tables["touchpoints"]

        try:
            data = fetch(HubSpotClient(token), company_currency=not currency.strip())
        except HubSpotError as exc:
            raise CommandError(f"{exc} Nothing was written.") from None
        mapping = to_batch(data, touch_table, default_currency=currency.strip())
        notes = [*mapping.notes, *_loaded_now_lost(mapping.lost_ids)]
        self.stdout.write(
            f"Read {len(data.companies)} companies, {len(data.contacts)} contacts and "
            f"{len(data.deals)} deals from {API_HOST} in {data.requests} GET requests."
        )
        for note in notes:
            self.stdout.write(f"  {note}")
        self.stdout.write(
            "Rows are numbered in the order HubSpot returned them; the ID in brackets is the "
            "HubSpot record ID."
        )

        if dry_run:
            report = validate_import(
                mapping.batch, lookback_days=settings.ATTRIBUTION_LOOKBACK_DAYS
            )
            describe_report(self, report, SOURCE)
            accepted = {e: len(r) for e, r in report.accepted.items()}
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run: would load {accepted['accounts']} accounts, {accepted['contacts']} "
                    f"contacts, {accepted['opportunities']} opportunities, "
                    f"{accepted['touchpoints']} touchpoints. Nothing was written."
                )
            )
            return

        result = run_import(mapping.batch, source=SOURCE, strict=strict, notes=notes)
        describe_report(self, result.report, SOURCE)
        if not result.run.loaded:
            raise CommandError(
                f"Refused the whole import (--strict): {result.refused} rows failed "
                "validation. Nothing was loaded. Fix them in HubSpot and re-run."
            )
        loaded = {e: len(r) for e, r in result.report.accepted.items()}
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {loaded['accounts']} accounts, {loaded['contacts']} contacts, "
                f"{loaded['opportunities']} opportunities, {loaded['touchpoints']} touchpoints "
                f"from {SOURCE}. Full validation report: /validation/"
            )
        )


LOST_STAGE_ISSUE = "#22"


def _loaded_now_lost(lost_ids: list[str]) -> list[str]:
    """Deals loaded by an earlier import that HubSpot now has as closed-lost.

    The contract refuses the lost stage, so their refused rows never update the loaded
    opportunity: it keeps its last imported stage. Nothing is deleted; this says so.
    """
    loaded = Opportunity.objects.filter(external_id__in=lost_ids).order_by("external_id")
    notes = []
    for stage, counted_as in [("open", "open pipeline"), ("won", "won revenue")]:
        ids = [o.external_id for o in loaded if o.stage == stage]
        if ids:
            notes.append(
                f"{len(ids)} deals already loaded are now closed-lost and still count as "
                f"{counted_as} ({', '.join(ids)}). Nothing was deleted; supporting the lost "
                f"stage is tracked in {LOST_STAGE_ISSUE}."
            )
    return notes
