from django.urls import path

from collection import views

app_name = "collection"
urlpatterns = [
    path("v1/<slug:kind>", views.collect, name="collect"),
    path("events/", views.events, name="events"),
    path("events/demo/", views.demo, name="demo"),
]
