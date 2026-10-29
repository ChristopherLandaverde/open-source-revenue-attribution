"""Test settings: always SQLite in memory, so tests never touch a local .env database."""

import os

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

from config.settings import *  # noqa: E402,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# Tests run with the default (no lookback cap) whatever a local .env says.
ATTRIBUTION_LOOKBACK_DAYS = None
# Deterministic security settings whatever a local .env says.
COLLECT_ALLOWED_ORIGINS = []
SECURE_SSL_REDIRECT = False
# Templates resolve {% static %} without a collectstatic manifest.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# Static files come from the finders in tests; WhiteNoise would warn about a missing STATIC_ROOT.
MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]  # noqa: F405
