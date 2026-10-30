"""Test settings: SQLite in memory by default, so tests never touch a local .env database."""

import os

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

from config.settings import *  # noqa: E402,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
# Opt in to PostgreSQL: TEST_DATABASE_URL=postgres://osra:osra@localhost:5432/osra uv run pytest
# (pytest-django creates and drops a separate test_<name> database).
if os.environ.get("TEST_DATABASE_URL"):
    DATABASES = {"default": env.db_url_config(os.environ["TEST_DATABASE_URL"])}  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# Tests run with the default (no lookback cap) whatever a local .env says.
ATTRIBUTION_LOOKBACK_DAYS = None
# Deterministic security settings whatever a local .env says.
COLLECT_ALLOWED_ORIGINS = ["*"]  # the default, whatever a local .env says
SECURE_SSL_REDIRECT = False
# Templates resolve {% static %} without a collectstatic manifest.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# Static files come from the finders in tests; WhiteNoise would warn about a missing STATIC_ROOT.
MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]  # noqa: F405
