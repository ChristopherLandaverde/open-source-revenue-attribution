"""Deployment checks for this app, run by `manage.py check --deploy` next to Django's own.

Django's deploy checks cover DEBUG, SECRET_KEY, HTTPS redirect, secure cookies and HSTS. These
add the settings that are specific to running this app on a public server.
"""

from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def deployment_checks(app_configs, **kwargs):
    issues = []
    if "*" in settings.ALLOWED_HOSTS:
        issues.append(
            Warning(
                "ALLOWED_HOSTS contains '*', so any Host header is accepted.",
                hint="Set ALLOWED_HOSTS to the domain names this server answers to.",
                id="osra.W001",
            )
        )
    if "*" in settings.COLLECT_ALLOWED_ORIGINS:
        issues.append(
            Warning(
                "COLLECT_ALLOWED_ORIGINS contains '*': any website can send events to /v1/ "
                "with a write key it copies from your pages.",
                hint="List the origins of the sites you track, e.g. https://www.acme.example.",
                id="osra.W002",
            )
        )
    if settings.COLLECT_DEMO_PAGE:
        issues.append(
            Warning(
                "COLLECT_DEMO_PAGE is on: /events/demo/ sends synthetic events into the dataset.",
                hint="Unset COLLECT_DEMO_PAGE (it follows DEBUG) on a real deployment.",
                id="osra.W003",
            )
        )
    if settings.DATABASES["default"]["ENGINE"].endswith("sqlite3"):
        issues.append(
            Warning(
                "The database is SQLite. It is for local use and tests.",
                hint="Set DATABASE_URL to PostgreSQL (the production compose file does).",
                id="osra.W004",
            )
        )
    if not settings.HTTPS:
        issues.append(
            Warning(
                "HTTPS=false: session and CSRF cookies are sent over plain HTTP.",
                hint="Serve the app over HTTPS behind a reverse proxy and remove HTTPS=false.",
                id="osra.W005",
            )
        )
    return issues
