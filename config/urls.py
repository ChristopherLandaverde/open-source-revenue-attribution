from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path


@login_not_required
def healthz(request):
    """Liveness and database check for the container health check and uptime monitors."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(redirect_authenticated_user=True),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("healthz", healthz, name="healthz"),
    path("api/v1/", include("api.urls")),
    path("", include("collection.urls")),
    path("", include("reports.urls")),
]
