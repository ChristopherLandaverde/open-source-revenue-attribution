# Production image: Django app served by gunicorn, static files by WhiteNoise.
# Build: docker compose -f compose.production.yml build   (see docs/self-hosting.md)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    WEB_CONCURRENCY=2

RUN pip install --no-cache-dir uv==0.13.1

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock .python-version ./
# uv reads the MCP server's metadata (a path source in pyproject.toml) to check the lock; the
# image does not install it (it is in the `mcp` group, outside --no-dev).
COPY mcp-server/pyproject.toml mcp-server/
RUN uv sync --locked --no-dev --no-install-project

COPY . .
# collectstatic only reads settings; these throwaway values never reach the running container.
RUN SECRET_KEY=build-only DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py collectstatic --noinput \
    && rm -f /tmp/build.sqlite3 \
    && useradd --system --uid 10001 --create-home osra

USER osra
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# WEB_CONCURRENCY sets the number of gunicorn workers (default 2).
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--access-logfile", "-"]
