# AGENTS.md — Open Source Revenue Attribution

Repo-specific rules for agents. These win over the portfolio-wide `AGENTS.md` on repo matters.
Product scope: `docs/prd.md`. Delivery and quality gates: `docs/project-management-plan.md`.

## Commands

```sh
uv sync                                                   # install (Python 3.12, locked)
cp .env.example .env                                      # once; set DATABASE_URL
docker compose up -d --wait db                            # local Postgres
uv run python manage.py migrate
uv run python manage.py load_sample_data                  # idempotent
uv run python manage.py runserver                         # http://127.0.0.1:8000/

uv run ruff check . && uv run ruff format --check .       # lint + format
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest                                             # all tests (in-memory SQLite)
```

All of the check commands must pass before a commit; CI runs the same list.

## Stack (decided; don't relitigate)

Django 5.2 LTS + Django templates + HTMX · plain CSS with tokens in `static/css/tokens.css` ·
HTMX and RudderStack JS SDK vendored as pinned files in `static/vendor/` (no Node toolchain,
no React/Vite) · Django ORM + migrations on PostgreSQL · pytest + pytest-django · Ruff · uv.

## Conventions

- **Architecture boundary:** `attribution/` is pure Python. No `django`, `reports`, or
  `config` imports (`tests/test_architecture.py` fails otherwise). Django code converts
  records to `attribution` types in `reports/services.py`.
- **Models are test-first** with hand-calculated expected outputs written in the test or
  fixture docs. Credits must reconcile to the opportunity amount.
- **Copy:** reports state association under a named model and window, never causal
  impact. Always show the model name and lookback window next to numbers.
- **Data:** synthetic only (`*.example` domains). Never commit `.env` or real personal data.
- **Changing attribution math or report meaning** needs a `needs-decision` issue first.
- HTMX endpoints return HTML fragments; full page and fragment share one template include.
- Migrations: generate with `makemigrations`; migrations are exempt from Ruff format/E501.
- Vendored assets: record version, source URL, license, and SHA-256 in
  `static/vendor/README.md`.
- Commit messages end with the co-author line the session specifies.
