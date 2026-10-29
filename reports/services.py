"""Glue between Django records and the pure attribution package."""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

import attribution
from reports.models import Opportunity

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
            for tp in opportunity.contact.touchpoints.all()
        ),
    )


def first_touch_report(metric: str = "pipeline") -> Report:
    if metric not in METRICS:
        raise ValueError(f"Unknown metric: {metric}")
    model = attribution.FirstTouch(lookback_days=settings.ATTRIBUTION_LOOKBACK_DAYS)
    opportunities = Opportunity.objects.select_related("contact__account").prefetch_related(
        "contact__touchpoints"
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
