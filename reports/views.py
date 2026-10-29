from pathlib import Path

from django.conf import settings
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render

from contracts import ImportBatch
from reports.forms import ImportForm
from reports.imports import run_import
from reports.models import ImportRun, Opportunity
from reports.services import (
    ISSUE_VIEWS,
    METRICS,
    first_touch_report,
    journey_view,
    validation_view,
)

DEMO_PATH = Path(settings.BASE_DIR) / "sample_data" / "demo"


def report(request):
    metric = request.GET.get("metric", "pipeline")
    if metric not in METRICS:
        return HttpResponseBadRequest("Unknown metric.")
    context = {"report": first_touch_report(metric), "metrics": METRICS}
    template = (
        "reports/_results.html" if request.headers.get("HX-Request") else "reports/report.html"
    )
    return render(request, template, context)


def validation(request):
    show = request.GET.get("show", "rejected")
    if show not in ISSUE_VIEWS:
        return HttpResponseBadRequest("Unknown view.")
    context = {"view": validation_view(show), "issue_views": ISSUE_VIEWS}
    template = (
        "reports/_issues.html" if request.headers.get("HX-Request") else "reports/validation.html"
    )
    return render(request, template, context)


def import_csv(request):
    """Upload the four CSVs (or use the demo set), validate, load accepted rows, show the report."""
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        strict = form.cleaned_data["strict"]
        if request.POST.get("action") == "demo":
            run_import(ImportBatch.from_csv_dir(DEMO_PATH), "sample_data/demo", strict)
        else:
            source = "upload: " + ", ".join(form.cleaned_data["names"])
            run_import(ImportBatch.from_csv_texts(form.cleaned_data["texts"]), source, strict)
        return redirect("reports:validation")
    status = 400 if request.method == "POST" else 200
    context = {"form": form, "last_run": ImportRun.objects.first()}
    return render(request, "reports/import.html", context, status=status)


def journey(request, opportunity_id: str):
    """One opportunity's journey: every touch, why it is (in)eligible, and its credit."""
    opportunity = get_object_or_404(
        Opportunity.objects.select_related("account", "contact"), external_id=opportunity_id
    )
    metric = request.GET.get("metric", "pipeline")
    if metric not in METRICS:
        return HttpResponseBadRequest("Unknown metric.")
    context = {"view": journey_view(opportunity, metric), "metrics": METRICS}
    template = (
        "reports/_journey.html" if request.headers.get("HX-Request") else "reports/journey.html"
    )
    return render(request, template, context)
