"""Glue between Django records and the pure attribution package."""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db.models import Prefetch

import attribution
from contracts import RejectReason, WarningCode
from reports.models import ImportRun, Opportunity, Touchpoint

METRICS = {
    "pipeline": "Pipeline (credited at opportunity creation)",
    "won": "Won revenue (credited at opportunity close)",
}


@dataclass(frozen=True)
class OpportunityRow:
    opportunity: Opportunity
    converted_at: object
    credit: attribution.Credit


@dataclass(frozen=True)
class Report:
    metric: str
    metric_label: str
    model_name: str
    lookback_days: int
    campaign_rows: list[tuple[str, str, Decimal, int]]
    opportunity_rows: list[OpportunityRow]


def to_conversion(opportunity: Opportunity, metric: str) -> attribution.Conversion:
    # Pipeline is measured from creation, won revenue from the win (docs/decisions.md).
    converted_at = opportunity.won_at if metric == "won" else opportunity.created_at
    return attribution.Conversion(
        opportunity_id=opportunity.external_id,
        amount=opportunity.amount,
        currency=opportunity.currency,
        converted_at=converted_at,
        touchpoints=tuple(
            attribution.Touchpoint(
                id=tp.external_id,
                occurred_at=tp.occurred_at,
                source=tp.source,
                medium=tp.medium,
                campaign=tp.campaign,
            )
            # Contact-level attribution (PRD section 6): no contact means no touchpoints.
            for tp in (opportunity.contact.touchpoints.all() if opportunity.contact else ())
        ),
    )


def first_touch_report(metric: str = "pipeline") -> Report:
    if metric not in METRICS:
        raise ValueError(f"Unknown metric: {metric}")
    model = attribution.FirstTouch(lookback_days=settings.ATTRIBUTION_LOOKBACK_DAYS)
    # Touchpoints from CSV and from events can share an ID; a fixed order keeps ties stable.
    touchpoints = Touchpoint.objects.order_by("occurred_at", "external_id", "origin")
    opportunities = Opportunity.objects.select_related("account", "contact").prefetch_related(
        Prefetch("contact__touchpoints", queryset=touchpoints)
    )
    if metric == "won":
        opportunities = opportunities.filter(stage=Opportunity.Stage.WON)
    credits, rows = [], []
    for opportunity in opportunities.order_by("external_id"):
        conversion = to_conversion(opportunity, metric)
        for credit in model.attribute(conversion):
            credits.append(credit)
            rows.append(OpportunityRow(opportunity, conversion.converted_at, credit))
    return Report(
        metric=metric,
        metric_label=METRICS[metric],
        model_name=model.name,
        lookback_days=model.lookback_days,
        campaign_rows=attribution.summarize_by_campaign(credits),
        opportunity_rows=rows,
    )


ISSUE_VIEWS = {"rejected": "Refused rows", "warnings": "Warnings"}


@dataclass(frozen=True)
class ValidationView:
    run: ImportRun | None
    show: str
    file_rows: list[dict]
    issues: list[dict]
    codes: list[tuple[str, str]]  # (code, description) for every code in this report


def validation_view(show: str = "rejected") -> ValidationView:
    """The latest import's validation report, shaped for the template."""
    if show not in ISSUE_VIEWS:
        raise ValueError(f"Unknown issue view: {show}")
    run = ImportRun.objects.first()
    if run is None:
        return ValidationView(None, show, [], [], [])
    report = run.report
    rejected = [issue for row in report["rejected"] for issue in row["issues"]]
    warnings = report["warnings"]
    file_rows = []
    for entity, counts in report["counts"].items():
        file_rows.append(
            {
                "file": f"{entity}.csv",
                **counts,
                "warnings": sum(1 for w in warnings if w["entity"] == entity),
            }
        )
    descriptions = {str(code): code.description for code in [*RejectReason, *WarningCode]}
    present = {i["code"] for i in [*rejected, *warnings, *report["file_errors"]]}
    return ValidationView(
        run=run,
        show=show,
        file_rows=file_rows,
        issues=rejected if show == "rejected" else warnings,
        codes=[(code, descriptions[code]) for code in sorted(present)],
    )
