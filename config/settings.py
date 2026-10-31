"""Django settings. Every deploy-specific value comes from the environment (or a local .env)."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")  # optional; real environment variables win

DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env("SECRET_KEY", default="insecure-dev-only-key" if DEBUG else environ.Env.NOTSET)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
# Full origins (scheme + host) that may submit forms, e.g. https://attribution.example.com.
# Needed when the reverse proxy changes the Host header or the scheme Django sees.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# HTTPS. On by default whenever DEBUG is off: cookies are Secure, plain HTTP redirects to HTTPS
# and HSTS is sent. Set HTTPS=false only for a deployment that is really plain HTTP (a private
# network); `manage.py check --deploy` then warns.
HTTPS = env.bool("HTTPS", default=not DEBUG)
SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=HTTPS)
# The container health check calls /healthz over plain HTTP from inside the container.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
# includeSubDomains and preload commit the whole parent domain to HTTPS, which a self-hosted
# app on attribution.example.com must not decide for example.com. Opt in with the two settings
# above; their `check --deploy` reminders are silenced (docs/decisions.md, M5).
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
# Behind a TLS-terminating reverse proxy, trust its X-Forwarded-Proto header. Only safe when
# the app is reachable through the proxy alone (the production compose file binds the app to
# 127.0.0.1) and the proxy overwrites the header (Caddy and the nginx example do).
if env.bool("BEHIND_PROXY", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "reports",
    "collection",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page needs a signed-in user except those marked @login_not_required: the /v1/
    # collection endpoint (write-key auth), the login page, the health check, and the
    # read-only /api/v1/ endpoints, which check a Bearer token or session themselves (JSON 401).
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL via docker-compose for local dev. Tests and the no-Docker fallback use SQLite:
# DATABASE_URL=sqlite:///db.sqlite3
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = env.path("STATIC_ROOT", default=BASE_DIR / "staticfiles")
# WhiteNoise serves the collected, hashed static files from the app process (no separate web
# server needed). `manage.py collectstatic` must run first; the Docker image does it at build.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Local development (DEBUG): serve straight from static/ without collectstatic.
WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_AUTOREFRESH = DEBUG

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "reports:report"
LOGOUT_REDIRECT_URL = "login"

# Optional attribution lookback cap in days. Unset or blank: no cap, every touch from the first
# interaction up to the conversion counts, as in Dreamdata (docs/decisions.md).
_lookback = env.str("ATTRIBUTION_LOOKBACK_DAYS", default="").strip()
ATTRIBUTION_LOOKBACK_DAYS = int(_lookback) if _lookback else None

# Event collection (collection/). Most events accepted in one /v1/batch request.
COLLECT_MAX_BATCH = env.int("COLLECT_MAX_BATCH", default=500)
# The SDK demo page at /events/demo/ sends synthetic events into the dataset; off unless DEBUG.
COLLECT_DEMO_PAGE = env.bool("COLLECT_DEMO_PAGE", default=DEBUG)
# Which sites' pages may send events to /v1/ from the browser. "*" (the default) allows any
# origin, as Plausible, Umami and PostHog do; write keys are public in page JS either way.
# A comma-separated list of origins (scheme + host, e.g. https://www.acme.example) restricts
# it, as Matomo's cors_domains does: other origins get 403. Same-origin pages and server-side
# senders (no Origin header) are always allowed. docs/decisions.md, M5.
COLLECT_ALLOWED_ORIGINS = env.list("COLLECT_ALLOWED_ORIGINS", default=["*"])

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
}
