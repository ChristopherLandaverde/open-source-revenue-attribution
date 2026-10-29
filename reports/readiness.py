"""Data readiness: what a user must fix before trusting the attribution numbers.

Each check counts a share with its denominator and, when it is short, says which records are
affected, how to fix them and how to verify the fix. A check whose data does not exist yet is
`not_checked` with the reason, never a pass. The checks mirror the gaps Dreamdata labels in its
reports ("No tracking", "Unknown" channel, attributable deals); see docs/research/m4-models.md.
"""

from dataclasses import dataclass, field

from django.conf import settings

import attribution
from collection.models import CollectedEvent
from collection.services import convert_events
from contracts.touchpoints import SkipReason
from reports.models import ImportRun, Touchpoint
from reports.services import METRICS, _conversions

PASS, REVIEW, NOT_CHECKED = "pass", "review", "not_checked"
STATUS_LABELS = {
    PASS: ("✓ Ready", "tag-accepted"),
    REVIEW: ("! Fix", "tag-review"),
    NOT_CHECKED: ("– Not checked", "tag-neutral"),
}
UNLINKED = {SkipReason.ANONYMOUS, SkipReason.CONTACT_NOT_IMPORTED, SkipReason.AMBIGUOUS_IDENTITY}


@dataclass(frozen=True)
class Check:
    key: str
    title: str
    status: str
    count: int | None  # records that pass
    total: int | None  # denominator
    finding: str  # what we saw
    impact: str  # why it matters
    fix: str = ""
    verify: str = ""
    examples: list[str] = field(default_factory=list)  # affected record IDs (evidence)
    link: str = ""  # URL name of the page with the evidence

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status][0]

    @property
    def css(self) -> str:
        return STATUS_LABELS[self.status][1]

    @property
    def percent(self) -> int | None:
        if not self.total:
            return None
        return round(100 * self.count / self.total)


@dataclass(frozen=True)
class Readiness:
    metric: str
    metric_label: str
    lookback_days: int | None
    checks: list[Check]
    opportunities: int
    attributable: int  # opportunities with at least one eligible touch
    no_touch: list[str]  # the others: Unattributed, and left out of Influenced
    touch_period: tuple | None  # (earliest, latest) touch time
    conversion_period: tuple | None

    @property
    def to_fix(self) -> list[Check]:
        return [c for c in self.checks if c.status == REVIEW]

    @property
    def not_checked(self) -> list[Check]:
        return [c for c in self.checks if c.status == NOT_CHECKED]

    @property
    def ready(self) -> list[Check]:
        return [c for c in self.checks if c.status == PASS]


def _share(key, title, passing, total, *, impact, finding, fix, verify, failing, link=""):
    status = PASS if passing == total else REVIEW
    return Check(
        key=key,
        title=title,
        status=status,
        count=passing,
        total=total,
        finding=finding,
        impact=impact,
        fix=fix if status == REVIEW else "",
        verify=verify if status == REVIEW else "",
        examples=sorted(failing)[:10],
        link=link,
    )


def readiness(metric: str = "pipeline") -> Readiness:
    if metric not in METRICS:
        raise ValueError(f"Unknown metric: {metric}")
    lookback = settings.ATTRIBUTION_LOOKBACK_DAYS
    pairs = _conversions(metric)
    total = len(pairs)
    checks: list[Check] = []

    with_contact = [(o, c) for o, c in pairs if o.contact_id]
    tracked = [(o, c) for o, c in with_contact if c.touchpoints]
    eligible = {o.external_id: attribution.eligible_touchpoints(c, lookback) for o, c in tracked}
    attributable = [oid for oid, touches in eligible.items() if touches]
    no_touch = sorted(o.external_id for o, _ in pairs if not eligible.get(o.external_id))
    window_title = (
        "Touches happen before the conversion"
        if lookback is None
        else "Touches fall inside the lookback window"
    )
    eligible_touches = [tp for touches in eligible.values() for tp in touches]

    if not total:
        reason = "No opportunities yet." if metric == "pipeline" else "No won opportunities yet."
        for key, title in [
            ("contact", "Opportunities have a contact"),
            ("tracked", "Contacts have tracked touches"),
            ("window", window_title),
            ("utm", "Touches carry source, medium and campaign"),
        ]:
            checks.append(Check(key, title, NOT_CHECKED, None, None, reason, ""))
    else:
        checks.append(
            _share(
                "contact",
                "Opportunities have a contact",
                len(with_contact),
                total,
                finding=f"{len(with_contact)} of {total} opportunities have a contact.",
                impact="Without a contact there are no touches, so the whole amount is "
                "Unattributed under every model.",
                fix="Fill contact_id in opportunities.csv for these opportunities, then import "
                "again.",
                verify="Reload this page: the count reaches the total.",
                failing=[o.external_id for o, _ in pairs if not o.contact_id],
                link="reports:import",
            )
        )
        if with_contact:
            checks.append(
                _share(
                    "tracked",
                    "Contacts have tracked touches",
                    len(tracked),
                    len(with_contact),
                    finding=f"{len(tracked)} of {len(with_contact)} opportunity contacts have "
                    "at least one touch.",
                    impact="A contact with no touches leaves its opportunity Unattributed. "
                    "Dreamdata labels these deals No tracking.",
                    fix="Import touchpoints.csv rows for these contacts, or send page events "
                    "with an identify call carrying their contact_id.",
                    verify="Open the opportunity's journey: its touches are listed.",
                    failing=[o.external_id for o, c in with_contact if not c.touchpoints],
                    link="collection:events",
                )
            )
        else:
            checks.append(
                Check(
                    "tracked",
                    "Contacts have tracked touches",
                    NOT_CHECKED,
                    None,
                    None,
                    "No opportunity has a contact, so there are no touches to look at.",
                    "",
                )
            )
        if tracked:
            if lookback is None:
                where = "at or before the conversion"
                impact = "Touches after the conversion get no credit; the opportunity is "
                fix = "Import the touches from before the conversion (CSV or earlier events)."
            else:
                where = f"inside the {lookback}-day window"
                impact = (
                    "Touches before the window or after the conversion get no credit; "
                    "the opportunity is "
                )
                fix = (
                    "Import the touch history from before the window, or raise or unset "
                    "ATTRIBUTION_LOOKBACK_DAYS and restart the server."
                )
            checks.append(
                _share(
                    "window",
                    window_title,
                    len(attributable),
                    len(tracked),
                    finding=f"{len(attributable)} of {len(tracked)} tracked opportunities have "
                    f"a touch {where}.",
                    impact=impact + "Unattributed and left out of Influenced.",
                    fix=fix,
                    verify="Open the opportunity's journey: a touch shows as eligible.",
                    failing=[oid for oid, touches in eligible.items() if not touches],
                )
            )
        else:
            checks.append(
                Check(
                    "window",
                    window_title,
                    NOT_CHECKED,
                    None,
                    None,
                    "No opportunity contact has touches yet.",
                    "",
                )
            )
        if eligible_touches:
            complete = [tp for tp in eligible_touches if tp.source and tp.medium and tp.campaign]
            checks.append(
                _share(
                    "utm",
                    "Touches carry source, medium and campaign",
                    len(complete),
                    len(eligible_touches),
                    finding=f"{len(complete)} of {len(eligible_touches)} eligible touches have "
                    "all three campaign fields.",
                    impact="Credit for the others is reported under (none), so it cannot be "
                    "tied to a campaign.",
                    fix="Add utm_source, utm_medium and utm_campaign to every link you place, "
                    "and to these touchpoints.csv rows.",
                    verify="Reload this page: (none) rows shrink on the model comparison.",
                    failing={tp.id for tp in eligible_touches} - {tp.id for tp in complete},
                )
            )
        else:
            checks.append(
                Check(
                    "utm",
                    "Touches carry source, medium and campaign",
                    NOT_CHECKED,
                    None,
                    None,
                    "No touch is inside the window yet.",
                    "",
                )
            )

    checks.append(_import_check())
    checks.extend(_event_checks())

    touch_times = Touchpoint.objects.order_by("occurred_at").values_list("occurred_at", flat=True)
    first_touch, last_touch = touch_times.first(), touch_times.last()
    conversion_times = sorted(c.converted_at for _, c in pairs)
    return Readiness(
        metric=metric,
        metric_label=METRICS[metric],
        lookback_days=lookback,
        checks=checks,
        opportunities=total,
        attributable=len(attributable),
        no_touch=no_touch,
        touch_period=(first_touch, last_touch) if first_touch else None,
        conversion_period=(conversion_times[0], conversion_times[-1]) if conversion_times else None,
    )


def _import_check() -> Check:
    title = "The last import loaded every row"
    run = ImportRun.objects.first()
    if run is None:
        return Check("import", title, NOT_CHECKED, None, None, "No CSV import yet.", "")
    report = run.report
    counts = report["counts"].values()
    distinct = sum(c["accepted"] + c["rejected"] for c in counts)  # exact duplicates count once
    refused = len(report["rejected"]) + len(report["file_errors"])
    if not run.loaded:
        refused_ids = []
        loaded = 0
    else:
        refused_ids = [row["record_id"] for row in report["rejected"] if row.get("record_id")]
        loaded = sum(c["accepted"] for c in counts)
    status = PASS if run.loaded and not refused else REVIEW
    return Check(
        key="import",
        title=title,
        status=status,
        count=loaded,
        total=distinct,
        finding=(
            f"Strict mode refused the whole import ({refused} rows or files failed)."
            if not run.loaded
            else f"{loaded} of {distinct} distinct rows were loaded; {refused} refused."
        ),
        impact="Refused rows are in no report, so their opportunities and touches are missing.",
        fix="Open Data validation, correct each refused row as its fix says, and import again."
        if status == REVIEW
        else "",
        verify="Data validation shows every row accepted." if status == REVIEW else "",
        examples=sorted(set(refused_ids))[:10],
        link="reports:validation",
    )


def _event_checks() -> list[Check]:
    refused_title = "Collected events were accepted"
    linked_title = "Collected page views reach a contact"
    statuses = CollectedEvent.objects.values_list("status", flat=True)
    total = statuses.count()
    if not total:
        reason = "No events collected yet."
        events = "collection:events"
        return [
            Check("events", refused_title, NOT_CHECKED, None, None, reason, "", link=events),
            Check("linked", linked_title, NOT_CHECKED, None, None, reason, "", link=events),
        ]
    accepted = statuses.filter(status=CollectedEvent.Status.ACCEPTED).count()
    checks = [
        _share(
            "events",
            refused_title,
            accepted,
            total,
            finding=f"{accepted} of {total} distinct events were accepted.",
            impact="Refused events never become touches, so their visits get no credit.",
            fix="Open Events, read each refused event's reason and fix, then resend it.",
            verify="Events shows no refused rows for new sends.",
            failing=CollectedEvent.objects.filter(status=CollectedEvent.Status.REJECTED)
            .exclude(message_id="")
            .values_list("message_id", flat=True),
            link="collection:events",
        )
    ]
    conversion = convert_events()
    unlinked = [mid for mid, reason in conversion.skipped if reason in UNLINKED]
    page_views = len(conversion.touchpoints) + len(conversion.session_views) + len(unlinked)
    if not page_views:
        checks.append(
            Check(
                "linked",
                linked_title,
                NOT_CHECKED,
                None,
                None,
                "No accepted page views yet.",
                "",
                link="collection:events",
            )
        )
    else:
        checks.append(
            _share(
                "linked",
                linked_title,
                page_views - len(unlinked),
                page_views,
                finding=f"{page_views - len(unlinked)} of {page_views} page views are linked to "
                "an imported contact.",
                impact="Anonymous or unmatched views are kept but credit no opportunity.",
                fix="Call identify with the contact_id on sign-up or login, and import the "
                "contact in contacts.csv.",
                verify="Events shows these views as touches or session views.",
                failing=unlinked,
                link="collection:events",
            )
        )
    return checks
