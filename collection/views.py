import base64
import binascii
import json
import re
from collections import Counter

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from collection.models import CollectedEvent, Workspace
from collection.services import convert_events, ingest, workspace_for_write_key
from contracts.touchpoints import SkipReason
from reports.fixes import FIXES
from reports.models import Touchpoint

# RudderStack HTTP API paths. Event types other than page/track/identify are accepted by the
# endpoint so the validator can refuse them with UNSUPPORTED_EVENT_TYPE.
DEMO_CONTACT = "con-nw-li"  # a demo-fixture contact with no opportunities, so reports don't move
SKIP_TEXT = {
    SkipReason.NOT_A_PAGE_VIEW: "Track and identify events are kept, but are not touchpoints.",
    SkipReason.ANONYMOUS: "No userId, and no later identify of this anonymousId.",
    SkipReason.CONTACT_NOT_IMPORTED: (
        "userId is not an imported contact_id. Import the contact; it converts then."
    ),
    SkipReason.SAME_SESSION: (
        "A later page view of a session; the session counts once, as its first page view."
    ),
    SkipReason.AMBIGUOUS_IDENTITY: (
        "This anonymousId was identified as more than one contact, so it is not linked."
    ),
}
TIME_TEXT = {
    "timestamp": "server timestamp",
    "skew_corrected": "skew-corrected",
    "original_timestamp": "browser clock",
}
SINGLE_EVENT_PATHS = ("page", "track", "identify", "screen", "group", "alias")


def _write_key(request) -> str:
    """The write key from `Authorization: Basic base64(<write key>:)`, as the SDK sends it."""
    scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "basic" or not credentials:
        return ""
    try:
        decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return ""
    return decoded.partition(":")[0]


# What a browser may send cross-origin. The RudderStack SDK posts JSON with the write key in
# Authorization, the base64 anonymousId in AnonymousId, SentAt on every request and
# Rsa-Retry-*/Rsa-Since-* on retries; versions add headers. rudder-server allows any request
# header (rs/cors AllowedHeaders "*", which echoes the requested names), so the preflight does
# the same: it echoes every well-formed name the browser asks for, and falls back to the list
# below when none is asked. No cookies are involved, so Access-Control-Allow-Credentials is
# never sent.
CORS_ALLOW_HEADERS = (
    "Authorization, Content-Type, AnonymousId, SentAt, Rsa-Recovered, Rsa-Retry-Attempt, "
    "Rsa-Since-Last-Attempt, Rsa-Since-First-Attempt, Rsa-Retry-Reason"
)
CORS_MAX_AGE = "86400"
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")  # an RFC 9110 token


def _origin_allowed(request, origin: str) -> bool:
    """Same-origin pages always; others when COLLECT_ALLOWED_ORIGINS is "*" or lists them."""
    if origin == request.build_absolute_uri("/").rstrip("/"):
        return True
    allowed = settings.COLLECT_ALLOWED_ORIGINS
    return "*" in allowed or origin.rstrip("/") in {o.rstrip("/") for o in allowed}


def _allowed_request_headers(request) -> str:
    """Validate and echo a bounded header list, or use the fixed SDK-compatible list."""
    requested = request.headers.get("Access-Control-Request-Headers", "")
    if not requested or len(requested) > 1024:
        return CORS_ALLOW_HEADERS
    names = [name.strip() for name in requested.split(",")]
    if len(names) > 20 or any(not HEADER_NAME.fullmatch(name) for name in names):
        return CORS_ALLOW_HEADERS
    return ", ".join(dict.fromkeys(name.lower() for name in names))


def _with_cors(response: HttpResponse, origin: str) -> HttpResponse:
    response["Access-Control-Allow-Origin"] = origin
    patch_vary_headers(response, ["Origin"])
    return response


def _error(status: int, message: str, **headers) -> JsonResponse:
    response = JsonResponse({"error": message}, status=status)
    for name, value in headers.items():
        response[name] = value
    return response


@login_not_required
@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def collect(request, kind: str):
    """RudderStack HTTP API, authenticated by the write key.

    Any origin may send by default (COLLECT_ALLOWED_ORIGINS="*"). When the setting lists
    origins, a browser request whose Origin is neither this server's own nor listed gets 403
    on the preflight and the POST, before anything is stored. Requests without Origin
    (servers, curl) are authenticated by the write key alone.
    """
    if kind != "batch" and kind not in SINGLE_EVENT_PATHS:
        raise Http404("Unknown collection endpoint.")
    origin = request.headers.get("Origin", "")
    if origin and not _origin_allowed(request, origin):
        return _error(
            403,
            f"Origin {origin} is not allowed to send events. Add it to COLLECT_ALLOWED_ORIGINS.",
        )
    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        if origin:
            _with_cors(response, origin)
            response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = _allowed_request_headers(request)
            response["Access-Control-Max-Age"] = CORS_MAX_AGE
            patch_vary_headers(response, ["Access-Control-Request-Headers"])
        return response
    response = _collect(request, kind)
    return _with_cors(response, origin) if origin else response


def _collect(request, kind: str) -> JsonResponse:
    workspace = workspace_for_write_key(_write_key(request))
    if workspace is None:
        return _error(
            401,
            "Missing or unknown write key. Send Authorization: Basic base64(<write key>:).",
            **{"WWW-Authenticate": 'Basic realm="collect"'},
        )
    try:
        body = json.loads(request.body or b"null")
    except (ValueError, UnicodeDecodeError):
        return _error(400, "The request body is not valid UTF-8 JSON.")
    if kind == "batch":
        if not isinstance(body, dict) or not isinstance(body.get("batch"), list):
            return _error(400, 'A batch request needs a JSON object with a "batch" list.')
        payloads = body["batch"]
    else:
        payloads = [body]
    if len(payloads) > settings.COLLECT_MAX_BATCH:
        return _error(413, f"At most {settings.COLLECT_MAX_BATCH} events per request.")

    outcomes = ingest(workspace, payloads)
    counts = Counter(o.outcome for o in outcomes)
    return JsonResponse(
        {
            "received": len(outcomes),
            "accepted": counts["accepted"],
            "duplicates": counts["duplicate"],
            "rejected": counts["rejected"],
            "events": [
                {
                    "position": o.position,
                    "messageId": o.message_id,
                    "outcome": o.outcome,
                    "issues": [{k: i[k] for k in ("code", "field", "message")} for i in o.issues],
                }
                for o in outcomes
            ],
        }
    )


def events(request):
    """Collected events: what was accepted, what was refused and why, what became a touchpoint."""
    rows = CollectedEvent.objects.all()
    accepted = rows.filter(status=CollectedEvent.Status.ACCEPTED)
    rejected = rows.filter(status=CollectedEvent.Status.REJECTED)
    conversion = convert_events()
    skipped = dict(conversion.skipped)
    touchpoints = {tp.touchpoint_id: tp for tp in conversion.touchpoints}
    recent = list(accepted.order_by("-occurred_at", "-message_id")[:50])
    for row in recent:
        touchpoint = touchpoints.get(row.message_id)
        row.became = "touchpoint" if touchpoint else skipped.get(row.message_id)
        row.became_text = SKIP_TEXT.get(row.became, "")
        row.stitched_to = touchpoint.contact_id if touchpoint and touchpoint.stitched_from else ""
        row.time_text = TIME_TEXT.get((row.normalized or {}).get("time_source", "timestamp"), "")
        row.campaign_key = " / ".join(
            (row.normalized or {}).get(k) or "(none)"
            for k in ("utm_source", "utm_medium", "utm_campaign")
        )
    refused = list(rejected[:50])
    for row in refused:
        row.issue_rows = [{**i, "fix": FIXES.get(i["code"], "")} for i in row.issues]
    context = {
        "workspaces": Workspace.objects.count(),
        "accepted_count": accepted.count(),
        "rejected_count": rejected.count(),
        "retries": sum(r.times_received - 1 for r in accepted.only("times_received")),
        "touchpoint_count": Touchpoint.objects.filter(origin=Touchpoint.Origin.EVENT).count(),
        "recent": recent,
        "refused": refused,
        "demo_enabled": settings.COLLECT_DEMO_PAGE,
        "any_origin": "*" in settings.COLLECT_ALLOWED_ORIGINS,
        "allowed_origins": [o for o in settings.COLLECT_ALLOWED_ORIGINS if o],
    }
    return render(request, "collection/events.html", context)


def demo(request):
    """A page that loads the vendored RudderStack SDK and sends events to this server."""
    if not settings.COLLECT_DEMO_PAGE:
        raise Http404("The SDK demo page is off. Set COLLECT_DEMO_PAGE=true or DEBUG=true.")
    workspace = Workspace.objects.order_by("id").first()
    context = {
        "workspace": workspace,
        "contact_id": DEMO_CONTACT,
        "has_utms": "utm_source" in request.GET,
        "sdk_config": {
            "writeKey": workspace.write_key if workspace else "",
            "dataPlaneUrl": request.build_absolute_uri("/").rstrip("/"),
            "contactId": DEMO_CONTACT,
        },
    }
    return render(request, "collection/demo.html", context)
