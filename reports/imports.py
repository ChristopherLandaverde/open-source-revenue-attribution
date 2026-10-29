"""Validate and load one import (docs/contract.md section 2). Shared by load_sample_data and
the upload page, so both have the same partial-by-default / strict semantics.
"""

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from collection.services import sync_event_touchpoints
from contracts import ImportBatch, ImportReport, validate_import
from reports.models import Account, Contact, ImportRun, Opportunity, Touchpoint


@dataclass(frozen=True)
class ImportResult:
    run: ImportRun
    report: ImportReport

    @property
    def refused(self) -> int:
        return len(self.report.rejected) + len(self.report.file_errors)


def run_import(batch: ImportBatch, source: str, strict: bool = False) -> ImportResult:
    """Validate the batch, record an ImportRun, and load accepted rows.

    Partial by default: accepted rows load, refused rows are listed in the report. With
    `strict`, any refused row or file refuses the whole import and nothing loads.
    Re-importing the same rows updates them by ID, so a reload changes nothing.
    """
    lookback = settings.ATTRIBUTION_LOOKBACK_DAYS
    report = validate_import(batch, lookback_days=lookback)
    loaded = not (strict and not report.ok)
    with transaction.atomic():
        if loaded:
            _load(report)
            # Events whose contact has just been imported become touchpoints now.
            sync_event_touchpoints()
        run = ImportRun.objects.create(
            source=source[:500],
            lookback_days=lookback,
            strict=strict,
            loaded=loaded,
            report=report.to_dict(),
        )
    return ImportResult(run, report)


def _load(report: ImportReport) -> None:
    accounts = {
        rec.account_id: Account.objects.update_or_create(
            external_id=rec.account_id, defaults={"name": rec.name, "domain": rec.domain}
        )[0]
        for rec in report.accepted["accounts"]
    }
    contacts = {
        rec.contact_id: Contact.objects.update_or_create(
            external_id=rec.contact_id,
            defaults={"account": accounts[rec.account_id], "email": rec.email},
        )[0]
        for rec in report.accepted["contacts"]
    }
    for rec in report.accepted["opportunities"]:
        Opportunity.objects.update_or_create(
            external_id=rec.opportunity_id,
            defaults={
                "account": accounts[rec.account_id],
                "contact": contacts[rec.contact_id] if rec.contact_id else None,
                "name": rec.name,
                "amount": rec.amount,
                "currency": rec.currency,
                "stage": rec.stage,
                "created_at": rec.created_at,
                "won_at": rec.won_at,
            },
        )
    for rec in report.accepted["touchpoints"]:
        Touchpoint.objects.update_or_create(
            origin=Touchpoint.Origin.CSV,
            external_id=rec.touchpoint_id,
            defaults={
                "contact": contacts[rec.contact_id],
                "occurred_at": rec.occurred_at,
                "source": rec.source,
                "medium": rec.medium,
                "campaign": rec.campaign,
                "content": rec.content,
                "term": rec.term,
                "landing_page": rec.landing_page,
                "referrer": rec.referrer,
            },
        )
