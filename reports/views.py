from django.http import HttpResponseBadRequest
from django.shortcuts import render

from reports.services import METRICS, first_touch_report


def report(request):
    metric = request.GET.get("metric", "pipeline")
    if metric not in METRICS:
        return HttpResponseBadRequest("Unknown metric.")
    context = {"report": first_touch_report(metric), "metrics": METRICS}
    template = (
        "reports/_results.html" if request.headers.get("HX-Request") else "reports/report.html"
    )
    return render(request, template, context)
