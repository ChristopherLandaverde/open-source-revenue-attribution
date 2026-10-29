"""Glue between Django records and the pure attribution package."""

from dataclasses import dataclass
from decimal import Decimal
from functools import partial

from django.conf import settings
from django.db.models import Count, Prefetch

import attribution
from collection.services import convert_events
from contracts import CURRENCY_MINOR_UNITS, RejectReason, WarningCode
from contracts.touchpoints import TouchReason
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
    lookback_days: int | None
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
        minor_unit=CURRENCY_MINOR_UNITS.get(opportunity.currency, 2),
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
    TouchReason.FIRST_SESSION: "The contact's first session; credited to its first page view.",
    TouchReason.INACTIVITY: (
        "30 minutes or more after this browser's previous event: a new session."
    ),
    TouchReason.NEW_DEVICE: "The contact's first session from this browser: a new session.",
}
STATUS = {
    # status: (symbol and word, tag class)
    "eligible": ("✓ Eligible", "tag-accepted"),
    "before": ("– Before window", "tag-neutral"),
    "after": ("– After conversion", "tag-neutral"),
    "in_session": ("– In session", "tag-neutral"),
}


@dataclass(frozen=True)
class JourneyRow:
    position: int | None  # touchpoints; in-session rows: their session touch's position
    touchpoint_id: str
    occurred_at: object
    origin: str  # "csv" | "event"
    campaign_key: str
    landing_page: str
    referrer: str
    how: str  # how it became (or did not become) a touchpoint
    stitched_from: str
    session_id: str  # event rows: the messageId of the session's touchpoint
    session_number: int | None  # event rows: their session, 1, 2, ... in journey order
    session_size: int  # touchpoint rows from events: page views in the session
    status: str  # a STATUS key
    status_label: str
    status_class: str
    window_text: str
    credits: list  # per model (JourneyView.models order); None when ineligible or in-session


@dataclass(frozen=True)
class JourneyView:
    opportunity: Opportunity
    metric: str
    metric_label: str
    won: bool
    models: list  # ModelColumn, one credit column each
    lookback_days: int | None
    journey: attribution.Journey | None  # None when the metric does not apply (open + won)
    rows: list[JourneyRow]
    eligible_count: int
    other_contacts: list[tuple[str, int]]  # (contact_id, touchpoints), never credited here


def _window_text(status: str, journey: attribution.Journey) -> str:
    if status == "eligible":
        if journey.window_start is None:
            return "At or before the conversion."
        return "Inside the window."
    if status == "before":
        return f"Before the window opened ({journey.window_start:%Y-%m-%d %H:%M} UTC)."
    if status == "after":
        return "After the conversion time."
    return "Counted once, as its session's touch."


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
    session_id="",
    session_number=None,
    session_size=0,
    position=None,
    credits=None,
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
        session_id=session_id,
        session_number=session_number,
        session_size=session_size,
        status=status,
        status_label=label,
        status_class=css,
        window_text=_window_text(status, journey),
        credits=credits or [],
    )


def _session_row(view, journey: attribution.Journey, number=None, position=None) -> JourneyRow:
    key = attribution.Touchpoint(
        view.touchpoint_id, view.occurred_at, view.source, view.medium, view.campaign
    ).campaign_key
    return _row(
        view.touchpoint_id,
        view.occurred_at,
        Touchpoint.Origin.EVENT,
        key,
        view.landing_page,
        view.referrer,
        view.stitched_from,
        how=f"Part of the session started by {view.session_id}; not counted again.",
        status="in_session",
        journey=journey,
        session_id=view.session_id,
        session_number=number,  # with `position`: the session's own row, for the label
        position=position,
    )


def journey_view(opportunity: Opportunity, metric: str = "pipeline") -> JourneyView:
    """Every touch of the opportunity's contact, why it is (in)eligible, and each model's credit."""
    if metric not in METRICS:
        raise ValueError(f"Unknown metric: {metric}")
    models = attribution.standard_models(lookback_days=settings.ATTRIBUTION_LOOKBACK_DAYS)
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
        models=[ModelColumn(m.name, m.parameters, m.standard) for m in models],
        lookback_days=settings.ATTRIBUTION_LOOKBACK_DAYS,
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
        minor_unit=CURRENCY_MINOR_UNITS.get(opportunity.currency, 2),
    )
    # One journey per model: same steps in the same order, different credits.
    journeys = [attribution.build_journey(conversion, model) for model in models]
    journey = journeys[0]

    # Later page views of each session (#7): shown under their session, never counted again.
    in_session: dict[str, list] = {}
    if contact:
        for page_view in convert_events().session_views:
            if page_view.contact_id == contact.external_id:
                in_session.setdefault(page_view.session_id, []).append(page_view)

    rows, sessions = [], 0
    for index, step in enumerate(journey.steps):
        record = record_for[id(step.touchpoint)]
        if step.eligibility == attribution.Eligibility.ELIGIBLE:
            status = "eligible"
        else:
            status = "before" if step.eligibility == "before_window" else "after"
        session = {}
        if record.origin == Touchpoint.Origin.CSV:
            how = "Imported from touchpoints.csv; counted as given."
        else:
            how = VISIT_RULE_TEXT.get(record.visit_rule, "Collected page event.")
            sessions += 1
            views = in_session.pop(record.external_id, [])
            session = {
                "session_id": record.external_id,
                "session_number": sessions,
                "session_size": 1 + len(views),
            }
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
                credits=[j.steps[index].credit for j in journeys],
                **session,
            )
        )
        if session:
            rows.extend(_session_row(v, journey, sessions, step.position) for v in views)
    # Views whose session touch is not stored yet (a sync in progress) still show, last.
    leftovers = sorted((v for vs in in_session.values() for v in vs), key=lambda v: (
        v.occurred_at, v.touchpoint_id))  # fmt: skip
    rows.extend(_session_row(v, journey) for v in leftovers)
    eligible = sum(1 for s in journey.steps if s.eligibility == attribution.Eligibility.ELIGIBLE)
    return view(journey=journey, rows=rows, eligible_count=eligible)


# --- Model comparison (M4) ---------------------------------------------------------


@dataclass(frozen=True)
class ModelColumn:
    name: str
    parameters: str
    standard: str = ""


@dataclass(frozen=True)
class ComparisonRow:
    campaign_key: str
    currency: str
    credits: list[Decimal]  # one per model, in ModelColumn order
    influenced: Decimal  # full amount of every opportunity it touched (overlaps)
    influenced_opportunities: int

    @property
    def unattributed(self) -> bool:
        return self.campaign_key == attribution.UNATTRIBUTED


@dataclass(frozen=True)
class CurrencyBlock:
    currency: str
    rows: list[ComparisonRow]
    total: Decimal  # the opportunities' amount; every model's column sums to it
    opportunities: int
    unattributed: Decimal  # the same under every model: no eligible touch


@dataclass(frozen=True)
class OpportunityComparison:
    opportunity: Opportunity
    converted_at: object
    credits: list[list[attribution.Credit]]  # per model


@dataclass(frozen=True)
class Comparison:
    metric: str
    metric_label: str
    lookback_days: int | None
    models: list[ModelColumn]
    blocks: list[CurrencyBlock]
    opportunities: list[OpportunityComparison]


def _conversions(metric: str) -> list[tuple[Opportunity, attribution.Conversion]]:
    touchpoints = Touchpoint.objects.order_by("occurred_at", "external_id", "origin")
    opportunities = Opportunity.objects.select_related("account", "contact").prefetch_related(
        Prefetch("contact__touchpoints", queryset=touchpoints)
    )
    if metric == "won":
        opportunities = opportunities.filter(stage=Opportunity.Stage.WON)
    return [(o, to_conversion(o, metric)) for o in opportunities.order_by("external_id")]


def comparison_report(metric: str = "pipeline") -> Comparison:
    """Every standard model's credit per campaign, beside the influenced amount, per currency."""
    if metric not in METRICS:
        raise ValueError(f"Unknown metric: {metric}")
    lookback = settings.ATTRIBUTION_LOOKBACK_DAYS
    models = attribution.standard_models(lookback_days=lookback)
    pairs = _conversions(metric)
    conversions = [c for _, c in pairs]

    per_model = []  # per model: {(campaign, currency): amount}
    opportunity_rows = []
    model_credits = [[m.attribute(c) for c in conversions] for m in models]
    for credits_by_conversion in model_credits:
        flat = [credit for credits in credits_by_conversion for credit in credits]
        per_model.append(
            {(k, cur): amount for k, cur, amount, _ in attribution.summarize_by_campaign(flat)}
        )
    for i, (opportunity, conversion) in enumerate(pairs):
        opportunity_rows.append(
            OpportunityComparison(
                opportunity, conversion.converted_at, [mc[i] for mc in model_credits]
            )
        )
    influence = {
        (r.campaign_key, r.currency): r
        for r in attribution.influence_by_campaign(conversions, lookback)
    }

    keys = set(influence)
    for totals in per_model:
        keys |= set(totals)
    blocks = []
    for currency in sorted({cur for _, cur in keys}):
        rows = []
        for campaign in {k for k, cur in keys if cur == currency}:
            key = (campaign, currency)
            row_influence = influence.get(key)
            rows.append(
                ComparisonRow(
                    campaign_key=campaign,
                    currency=currency,
                    credits=[totals.get(key, Decimal("0")) for totals in per_model],
                    influenced=row_influence.amount if row_influence else Decimal("0"),
                    influenced_opportunities=row_influence.conversions if row_influence else 0,
                )
            )
        # Unattributed last; otherwise the largest influence first, then the largest credit.
        rows.sort(key=lambda r: (r.unattributed, -r.influenced, -max(r.credits), r.campaign_key))
        in_currency = [c for c in conversions if c.currency == currency]
        unattributed_row = next((r for r in rows if r.unattributed), None)
        blocks.append(
            CurrencyBlock(
                currency=currency,
                rows=rows,
                total=sum((c.amount for c in in_currency), Decimal("0")),
                opportunities=len(in_currency),
                unattributed=unattributed_row.credits[0] if unattributed_row else Decimal("0"),
            )
        )
    return Comparison(
        metric=metric,
        metric_label=METRICS[metric],
        lookback_days=lookback,
        models=[ModelColumn(m.name, m.parameters, m.standard) for m in models],
        blocks=blocks,
        opportunities=opportunity_rows,
    )
