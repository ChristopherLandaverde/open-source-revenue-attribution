#!/bin/sh
# Apply database migrations, then start the given command (gunicorn by default).
# Set MIGRATE_ON_START=false to run migrations yourself (docs/self-hosting.md, Upgrades).
set -e
if [ "${MIGRATE_ON_START:-true}" = "true" ]; then
    python manage.py migrate --noinput
fi
exec "$@"
