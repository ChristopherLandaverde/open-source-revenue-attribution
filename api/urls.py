from django.urls import path

from api import views

app_name = "api"
urlpatterns = [
    path("attribution", views.attribution_results, name="attribution"),
    path("journeys/<str:subject_id>", views.journey, name="journey"),
    path("readiness", views.readiness, name="readiness"),
]
