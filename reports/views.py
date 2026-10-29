from django.http import HttpResponseBadRequest
from django.shortcuts import render

from reports.services import ISSUE_VIEWS, METRICS, first_touch_report, validation_view


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
