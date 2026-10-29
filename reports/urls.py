from django.urls import path

from reports import views

app_name = "reports"
urlpatterns = [
    path("", views.report, name="report"),
    path("validation/", views.validation, name="validation"),
    path("import/", views.import_csv, name="import"),
    path("opportunities/<str:opportunity_id>/journey/", views.journey, name="journey"),
]
