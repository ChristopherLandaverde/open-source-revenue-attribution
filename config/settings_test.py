"""Test settings: always SQLite in memory, so tests never touch a local .env database."""

import os

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

from config.settings import *  # noqa: E402,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
