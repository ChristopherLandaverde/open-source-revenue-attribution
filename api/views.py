"""Read-only JSON API (/api/v1/): the report pages' numbers for agents and scripts.

Every endpoint calls the same `reports` functions as the HTML view it mirrors and only
reshapes the result; nothing is recomputed here. Amounts are strings at the currency's minor
unit, formatted by the same filter as the pages. Times are ISO 8601 in UTC.

Auth: `Authorization: Bearer <token>` (a per-user token from `manage.py createapitoken`), or
a signed-in session. The views are exempt from LoginRequiredMiddleware only so that a client
without a session gets a JSON 401 instead of a redirect to the sign-in page; `api_endpoint`
enforces authentication itself, before anything is read.
"""

from datetime import UTC, timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

import attribution
from api.models import ApiToken, hash_token
from collection.services import convert_events
from reports.models import Account, Opportunity
from reports.readiness import readiness as readiness_view
from reports.services import METRICS, comparison_report, journey_view
from reports.templatetags.money import minor_unit

SCHEMA_VERSION = "1"

# The pages' own wording (a test checks each sentence is still on its page).
REPORT_MEANING = (
    "Each column applies one named rule to the same touches. The numbers show association "
    "under that rule, not causal impact: no column shows that a campaign caused a deal. A gap "
    "between columns is the rules' difference, not a measured lift."
)
JOURNEY_MEANING = (
    "Every touch of this opportunity's contact, in time order, with why it is or isn't "
    "eligible and the credit each named model gives it. This is association under a named "
    "rule, not causal impact."
)
READINESS_MEANING = (
    "What to fix in your data before you trust the model comparison. "
    "This is association under a named rule, not causal impact."
)
INFLUENCED_DEFINITION = (
    "The full amount of every opportunity with at least one eligible touch from the campaign. "
    "One opportunity counts for every campaign that touched it, so this column overlaps and "
    "is never summed. Opportunities with no eligible touch are left out, as in Dreamdata."
)


# --- Auth, methods, errors -----------------------------------------------------------


def _json(data: dict, status: int = 200, **headers) -> JsonResponse:
    response = JsonResponse({"schemaVersion": SCHEMA_VERSION, **data}, status=status)
    for name, value in headers.items():
        response[name] = value
    add_never_cache_headers(response)  # per-user data: never cached by proxies or browsers
    return response


def _error(status: int, code: str, message: str, **headers) -> JsonResponse:
    return _json({"error": {"code": code, "message": message}}, status, **headers)


TOUCH_INTERVAL = timedelta(seconds=60)  # last_used_at is refreshed at most once a minute


def _bearer_token(request) -> str | None:
    """The token of an `Authorization: Bearer` header ("" when empty); None for no Bearer."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else None


def _token_record(token: str) -> ApiToken | None:
    """The valid token record, or None for an unknown token or an inactive user."""
    if not token:
        return None
    record = ApiToken.objects.select_related("user").filter(token_hash=hash_token(token)).first()
    if record is None or not record.user.is_active:
        return None
    return record


def _mark_used(record: ApiToken) -> None:
    now = timezone.now()
    if record.last_used_at is None or now - record.last_used_at > TOUCH_INTERVAL:
        ApiToken.objects.filter(pk=record.pk).update(last_used_at=now)


def api_endpoint(*params: str):
    """GET/HEAD-only, authenticated JSON endpoint accepting only the named query parameters."""

    def decorate(view):
        # csrf_exempt: nothing here writes, and a write method must reach the 405 below
        # instead of failing CSRF first. login_not_required: see the module docstring.
        @login_not_required
        @csrf_exempt
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            token, record = _bearer_token(request), None
            if token is not None:
                # A Bearer token must be valid, session or not.
                record = _token_record(token)
                user = record.user if record else None
            else:
                user = request.user if request.user.is_authenticated else None
            if user is None:
                return _error(
                    401,
                    "not_authenticated",
                    "Send Authorization: Bearer <token> (create one with "
                    "`manage.py createapitoken <username>`), or sign in.",
                    **{"WWW-Authenticate": 'Bearer realm="osra"'},
                )
            request.user = user
            if request.method not in ("GET", "HEAD"):  # HEAD: RFC 9110 section 9.3.2
                return _error(
                    405,
                    "method_not_allowed",
                    "This API is read-only: use GET.",
                    Allow="GET, HEAD",
                )
            unknown = sorted(set(request.GET) - set(params))
            if unknown:
                allowed = ", ".join(params)
                return _error(
                    400,
                    "unknown_parameter",
                    f"Unknown query parameter: {', '.join(unknown)}. Allowed: {allowed}. "
                    "Date filters (start, end) are not supported: the report pages have none.",
                )
            metric = request.GET.get("metric", "pipeline")
            if metric not in METRICS:
                return _error(
                    400, "unknown_metric", f"Unknown metric. Use one of: {', '.join(METRICS)}."
                )
            if record is not None:
                _mark_used(record)
            return view(request, metric, *args, **kwargs)

        return wrapped

    return decorate


# --- Shared shapes -------------------------------------------------------------------


def model_id(name: str) -> str:
    """URL-friendly model ID: "Position-based (U-shaped)" -> "position-based-u-shaped"."""
    return slugify(name)


def _model_indexes(request, models) -> list[int] | JsonResponse:
    """Which model columns to return: all, or the one named by ?model= (ID or name)."""
    wanted = request.GET.get("model", "").strip()
    if not wanted:
        return list(range(len(models)))
    for i, model in enumerate(models):
        if wanted.lower() in (model_id(model.name), model.name.lower()):
            return [i]
    ids = ", ".join(model_id(m.name) for m in models)
    return _error(400, "unknown_model", f"Unknown model {wanted!r}. Use one of: {ids}.")


def _models(models, indexes) -> list[dict]:
    return [
        {
            "id": model_id(models[i].name),
            "name": models[i].name,
            "parameters": models[i].parameters,
            "standard": models[i].standard,
        }
        for i in indexes
    ]


def _money(amount, currency: str) -> str | None:
    return None if amount is None else str(minor_unit(amount, currency))


def _time(value) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _metric(metric: str) -> dict:
    return {"id": metric, "label": METRICS[metric]}


def _window(lookback_days) -> dict:
    return {
        "lookbackDays": lookback_days,
        "description": attribution.describe_window(lookback_days),
    }


# --- GET /api/v1/attribution ---------------------------------------------------------


@api_endpoint("metric", "model")
def attribution_results(request, metric: str):
    """The model comparison page: credit per campaign per model, beside Influenced."""
    report = comparison_report(metric)
    data_readiness = readiness_view(metric)  # the page's verdict line uses the same object
    indexes = _model_indexes(request, report.models)
    if isinstance(indexes, JsonResponse):
        return indexes
    model_ids = [model_id(report.models[i].name) for i in indexes]
    currencies = []
    for block in report.blocks:
        cur = block.currency
        currencies.append(
            {
                "currency": cur,
                "total": _money(block.total, cur),
                "opportunities": block.opportunities,
                "unattributed": _money(block.unattributed, cur),
                "rows": [
                    {
                        "campaignKey": row.campaign_key,
                        "unattributed": row.unattributed,
                        "attributed": {
                            mid: _money(row.credits[i], cur)
                            for mid, i in zip(model_ids, indexes, strict=True)
                        },
                        # Unattributed has no eligible touch, so it is never in Influenced.
                        "influenced": None
                        if row.unattributed
                        else {
                            "amount": _money(row.influenced, cur),
                            "opportunities": row.influenced_opportunities,
                        },
                    }
                    for row in block.rows
                ],
            }
        )
    opportunities = []
    for row in report.opportunities:
        opp = row.opportunity
        opportunities.append(
            {
                "id": opp.external_id,
                "name": opp.name,
                "amount": _money(opp.amount, opp.currency),
                "currency": opp.currency,
                "stage": opp.stage,
                "convertedAt": _time(row.converted_at),
                "journey": _url("api:journey", opp.external_id, metric=metric),
                "credits": {
                    mid: [
                        {
                            "touchpointId": credit.touchpoint_id,
                            "campaignKey": credit.campaign_key,
                            "amount": _money(credit.amount, credit.currency),
                        }
                        for credit in row.credits[i]
                    ]
                    for mid, i in zip(model_ids, indexes, strict=True)
                },
            }
        )
    return _json(
        {
            "meaning": REPORT_MEANING,
            "metric": _metric(metric),
            "window": _window(report.lookback_days),
            "models": _models(report.models, indexes),
            "influenced": {"definition": INFLUENCED_DEFINITION, "additive": False},
            "dataReadiness": {
                "opportunities": data_readiness.opportunities,
                "attributable": data_readiness.attributable,
                "checksToFix": [c.key for c in data_readiness.to_fix],
                "details": _url("api:readiness", metric=metric),
            },
            "currencies": currencies,
            "opportunities": opportunities,
            "links": {"page": _url("reports:report", metric=metric)},
        }
    )


# --- GET /api/v1/journeys/<id> -------------------------------------------------------


@api_endpoint("metric", "model")
def journey(request, metric: str, subject_id: str):
    """An opportunity's journey page as JSON; for an account ID, each of its opportunities'."""
    related = Opportunity.objects.select_related("account", "contact")
    opportunity = related.filter(external_id=subject_id).first()
    if opportunity is not None:
        subject = {"type": "opportunity", "id": opportunity.external_id}
        opportunities = [opportunity]
    else:
        account = Account.objects.filter(external_id=subject_id).first()
        if account is None:
            return _error(404, "not_found", f"No opportunity or account with ID {subject_id!r}.")
        subject = {"type": "account", "id": account.external_id, "name": account.name}
        opportunities = list(related.filter(account=account).order_by("external_id"))
    events = convert_events()  # once for all of an account's opportunities
    views = [journey_view(o, metric, events=events) for o in opportunities]
    model_columns = views[0].models if views else []
    if not model_columns:
        models = attribution.standard_models(lookback_days=settings.ATTRIBUTION_LOOKBACK_DAYS)
        model_columns = models
    indexes = _model_indexes(request, model_columns)
    if isinstance(indexes, JsonResponse):
        return indexes
    model_ids = [model_id(model_columns[i].name) for i in indexes]
    return _json(
        {
            "meaning": JOURNEY_MEANING,
            "metric": _metric(metric),
            "window": _window(settings.ATTRIBUTION_LOOKBACK_DAYS),
            "models": _models(model_columns, indexes),
            "subject": subject,
            "journeys": [_journey(view, model_ids, indexes) for view in views],
        }
    )


def _journey(view, model_ids, indexes) -> dict:
    opp, journey_ = view.opportunity, view.journey
    cur = opp.currency
    touches = []
    for row in view.rows:
        counted = row.status != "in_session"
        touches.append(
            {
                "position": row.position,
                "touchpointId": row.touchpoint_id,
                "occurredAt": _time(row.occurred_at),
                "origin": row.origin,
                "campaignKey": row.campaign_key,
                "landingPage": row.landing_page,
                "referrer": row.referrer,
                "status": row.status,
                "how": row.how,
                "window": row.window_text,
                "stitchedFrom": row.stitched_from or None,
                "session": {
                    "id": row.session_id,
                    "number": row.session_number,
                    "pageViews": row.session_size or None,
                }
                if row.session_id
                else None,
                # None: not eligible (or a later page view of a session), as "—" on the page.
                "credits": {
                    mid: _money(row.credits[i], cur) if counted else None
                    for mid, i in zip(model_ids, indexes, strict=True)
                },
            }
        )
    return {
        "opportunity": {
            "id": opp.external_id,
            "name": opp.name,
            "stage": opp.stage,
            "amount": _money(opp.amount, cur),
            "currency": cur,
            "account": {"id": opp.account.external_id, "name": opp.account.name},
            "contactId": opp.contact.external_id if opp.contact else None,
        },
        # False when the metric does not apply: won revenue for an open opportunity.
        "applies": journey_ is not None,
        "conversionAt": _time(journey_.conversion.converted_at) if journey_ else None,
        "windowStart": _time(journey_.window_start) if journey_ else None,
        "eligibleTouches": view.eligible_count,
        "unattributed": _money(journey_.unattributed, cur) if journey_ else None,
        "touches": touches,
        "otherContacts": [
            {"contactId": contact_id, "touchpoints": count, "credited": False}
            for contact_id, count in view.other_contacts
        ],
        "links": {"page": _url("reports:journey", opp.external_id, metric=view.metric)},
    }


# --- GET /api/v1/readiness -----------------------------------------------------------


@api_endpoint("metric")
def readiness(request, metric: str):
    """The data readiness page: each check with its status, count, evidence and fix."""
    view = readiness_view(metric)
    models = attribution.standard_models(lookback_days=view.lookback_days)
    if view.to_fix:
        verdict = "fix_data_first"
    elif view.ready:
        verdict = "ready"
    else:
        verdict = "not_checked"
    return _json(
        {
            "meaning": READINESS_MEANING,
            "metric": _metric(metric),
            "window": _window(view.lookback_days),
            "models": _models(models, range(len(models))),
            "verdict": verdict,
            "opportunities": view.opportunities,
            "attributable": view.attributable,
            "noEligibleTouch": view.no_touch,
            "touchPeriod": _period(view.touch_period),
            "conversionPeriod": _period(view.conversion_period),
            "checks": [
                {
                    "key": check.key,
                    "title": check.title,
                    "status": check.status,
                    "count": check.count,
                    "total": check.total,
                    "percent": check.percent,
                    "finding": check.finding,
                    "impact": check.impact,
                    "fix": check.fix,
                    "verify": check.verify,
                    "examples": list(check.examples),
                    "evidence": reverse(check.link) if check.link else None,
                }
                for check in view.checks
            ],
            "links": {"page": _url("reports:readiness", metric=metric)},
        }
    )


def _period(period) -> dict | None:
    return {"from": _time(period[0]), "to": _time(period[1])} if period else None


def _url(name: str, *args, metric: str) -> str:
    return f"{reverse(name, args=args)}?metric={metric}"
