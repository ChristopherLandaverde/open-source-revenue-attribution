"""Glue between Django records and the pure attribution package."""

from dataclasses import dataclass
from decimal import Decimal
from functools import partial

from django.conf import settings
from django.db.models import Count, Prefetch

import attribution
from collection.services import convert_events
from contracts import RejectReason, WarningCode
from contracts.touchpoints import SkipReason, TouchReason
from reports.fixes import FIXES
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
    codes: list[tuple[str, str, str]]  # (code, meaning, how to fix) for every code present
    totals: dict[str, int]


def validation_view(show: str = "rejected") -> ValidationView:
    """The latest import's validation report, shaped for the template."""
    if show not in ISSUE_VIEWS:
        raise ValueError(f"Unknown issue view: {show}")
    run = ImportRun.objects.first()
    if run is None:
        return ValidationView(None, show, [], [], [], {})
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
    issues = rejected if show == "rejected" else warnings
    totals = {
        "accepted": sum(c["accepted"] for c in report["counts"].values()),
        "refused_rows": len(report["rejected"]),
        "file_errors": len(report["file_errors"]),
        "warnings": len(warnings),
    }
    return ValidationView(
        run=run,
        show=show,
        file_rows=file_rows,
        issues=[{**i, "fix": FIXES[i["code"]]} for i in issues],
        codes=[(code, descriptions[code], FIXES[code]) for code in sorted(present)],
        totals=totals,
    )


# --- Opportunity journey (M3) ------------------------------------------------------

VISIT_RULE_TEXT = {
    TouchReason.FIRST_VISIT: "Contact's first page view, so it starts a visit.",
    TouchReason.INACTIVITY: "More than 30 minutes after the previous page view: a new visit.",
    TouchReason.NEW_CAMPAIGN: "Campaign differs from the current visit's: a new visit.",
    TouchReason.NEW_REFERRER: "Arrived from another site: a new visit.",
    TouchReason.CAMPAIGN_DATA: "Carries campaign data inside the current visit.",
    SkipReason.INTERNAL_NAVIGATION: "Same visit, no campaign data: internal navigation.",
}
STATUS = {
    # status: (symbol and word, tag class)
    "credited": ("✓ Credited", "tag-accepted"),
    "eligible": ("□ Eligible", "tag-observed"),
    "before": ("– Before window", "tag-neutral"),
    "after": ("– After conversion", "tag-neutral"),
    "internal": ("– Not a touchpoint", "tag-neutral"),
}


@dataclass(frozen=True)
class JourneyRow:
    position: int | None  # touchpoints only
    touchpoint_id: str
    occurred_at: object
    origin: str  # "csv" | "event"
    campaign_key: str
    landing_page: str
    referrer: str
    how: str  # how it became (or did not become) a touchpoint
    stitched_from: str
    status: str  # a STATUS key
    status_label: str
    status_class: str
    window_text: str
    credit: Decimal | None


@dataclass(frozen=True)
class JourneyView:
    opportunity: Opportunity
    metric: str
    metric_label: str
    won: bool
    model_name: str
    lookback_days: int
    journey: attribution.Journey | None  # None when the metric does not apply (open + won)
    rows: list[JourneyRow]
    eligible_count: int
    other_contacts: list[tuple[str, int]]  # (contact_id, touchpoints), never credited here


def _window_text(status: str, journey: attribution.Journey) -> str:
    if status in ("credited", "eligible"):
        return "Inside the window."
    if status == "before":
        return f"Before the window opened ({journey.window_start:%Y-%m-%d %H:%M} UTC)."
    if status == "after":
        return "After the conversion time."
    return "Not a touchpoint, so never eligible."


def _row(
    tp_id,
    occurred_at,
    origin,
    campaign_key,
    landing_page,
    referrer,
    stitched_from,
    *,
    how,
    status,
    journey,
    position=None,
    credit=None,
) -> JourneyRow:
    label, css = STATUS[status]
    return JourneyRow(
        position=position,
        touchpoint_id=tp_id,
        occurred_at=occurred_at,
        origin=origin,
        campaign_key=campaign_key,
        landing_page=landing_page,
        referrer=referrer,
        how=how,
        stitched_from=stitched_from,
        status=status,
        status_label=label,
        status_class=css,
        window_text=_window_text(status, journey),
        credit=credit,
    )


def journey_view(opportunity: Opportunity, metric: str = "pipeline") -> JourneyView:
    """Every touch of the opportunity's contact, why it is (in)eligible, and its credit."""
    if metric not in METRICS:
        raise ValueError(f"Unknown metric: {metric}")
    model = attribution.FirstTouch(lookback_days=settings.ATTRIBUTION_LOOKBACK_DAYS)
    won = opportunity.stage == Opportunity.Stage.WON
    contact = opportunity.contact
    db_touchpoints = (
        list(contact.touchpoints.order_by("occurred_at", "external_id", "origin"))
        if contact
        else []
    )
    others = []
    if contact:
        siblings = opportunity.account.contacts.exclude(pk=contact.pk).order_by("external_id")
        others = [(c.external_id, c.n) for c in siblings.annotate(n=Count("touchpoints"))]
    view = partial(
        JourneyView,
        opportunity=opportunity,
        metric=metric,
        metric_label=METRICS[metric],
        won=won,
        model_name=model.name,
        lookback_days=model.lookback_days,
        other_contacts=others,
    )
    if metric == "won" and not won:
        return view(journey=None, rows=[], eligible_count=0)

    converted_at = opportunity.won_at if metric == "won" else opportunity.created_at
    pure = [
        attribution.Touchpoint(
            id=tp.external_id,
            occurred_at=tp.occurred_at,
            source=tp.source,
            medium=tp.medium,
            campaign=tp.campaign,
        )
        for tp in db_touchpoints
    ]
    record_for = {id(p): tp for p, tp in zip(pure, db_touchpoints, strict=True)}
    conversion = attribution.Conversion(
        opportunity_id=opportunity.external_id,
        amount=opportunity.amount,
        currency=opportunity.currency,
        converted_at=converted_at,
        touchpoints=tuple(pure),
    )
    journey = attribution.build_journey(conversion, model)

    rows = []
    for step in journey.steps:
        record = record_for[id(step.touchpoint)]
        if step.eligibility == attribution.Eligibility.ELIGIBLE:
            status = "credited" if step.credit else "eligible"
        else:
            status = "before" if step.eligibility == "before_window" else "after"
        if record.origin == Touchpoint.Origin.CSV:
            how = "Imported from touchpoints.csv; counted as given."
        else:
            how = VISIT_RULE_TEXT.get(record.visit_rule, "Collected page event.")
        rows.append(
            _row(
                record.external_id,
                record.occurred_at,
                record.origin,
                step.touchpoint.campaign_key,
                record.landing_page,
                record.referrer,
                record.stitched_from,
                how=how,
                status=status,
                journey=journey,
                position=step.position,
                credit=step.credit,
            )
        )
    if contact:
        for internal in convert_events().internal_views:
            if internal.contact_id != contact.external_id:
                continue
            key = attribution.Touchpoint(
                internal.touchpoint_id,
                internal.occurred_at,
                internal.source,
                internal.medium,
                internal.campaign,
            ).campaign_key
            rows.append(
                _row(
                    internal.touchpoint_id,
                    internal.occurred_at,
                    Touchpoint.Origin.EVENT,
                    key,
                    internal.landing_page,
                    internal.referrer,
                    internal.stitched_from,
                    how=VISIT_RULE_TEXT[internal.visit_rule],
                    status="internal",
                    journey=journey,
                )
            )
    # Same key as the journey order, and a stable sort, so touchpoint order is unchanged.
    rows.sort(key=lambda r: (r.occurred_at, r.touchpoint_id))
    eligible = sum(1 for s in journey.steps if s.eligibility == attribution.Eligibility.ELIGIBLE)
    return view(journey=journey, rows=rows, eligible_count=eligible)
