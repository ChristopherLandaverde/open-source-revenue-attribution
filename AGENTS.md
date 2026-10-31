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
uv run python manage.py create_workspace demo             # prints a write key for /v1/
uv run python manage.py createsuperuser                   # every page needs a sign-in
uv run python manage.py runserver                         # http://127.0.0.1:8000/

uv run ruff check . && uv run ruff format --check .       # lint + format
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest                                             # all tests (in-memory SQLite)
TEST_DATABASE_URL=postgres://osra:osra@localhost:5432/osra uv run pytest   # same, on Postgres
```

Production-like deploy check (CI runs it too):
`DEBUG=false SECRET_KEY=<50+ random chars> DATABASE_URL=postgres://u:p@db/x ALLOWED_HOSTS=attribution.example.com BEHIND_PROXY=true SECURE_HSTS_SECONDS=3600 uv run python manage.py check --deploy --fail-level WARNING`.
Self-hosted stack: `docker compose -f compose.production.yml up -d --build --wait` (see
`docs/self-hosting.md`). Releases: `docs/release.md`; never tag or publish without Christopher.

All of the check commands must pass before a commit; CI runs the same list.

## Stack (decided; don't relitigate)

Django 5.2 LTS + Django templates + HTMX · plain CSS with tokens in `static/css/tokens.css` ·
HTMX and RudderStack JS SDK vendored as pinned files in `static/vendor/` (no Node toolchain,
no React/Vite) · Django ORM + migrations on PostgreSQL · pytest + pytest-django · Ruff · uv.

## Conventions

- **Architecture boundary:** `attribution/` and `contracts/` are pure Python. No `django`,
  `reports`, or `config` imports (`tests/test_architecture.py` fails otherwise). Django code
  converts records to `attribution` types in `reports/services.py`. `collection/` (event
  endpoint, storage) only persists what `contracts.validate_events` and
  `contracts.touchpoints.events_to_touchpoints` decide; data rules never live in views.
- **Data contract:** `docs/contract.md` is the source of truth for import/event fields and
  reason codes; `contracts/` enforces it. Reason codes are append-only. Changing what is
  accepted is a data-meaning change (needs a decision). A test fails if a code or column is
  missing from the doc.
- **Fixture expectations** in `sample_data/demo/expected/` and `sample_data/events/expected/`
  are hand-calculated and derived in
  `sample_data/*/README.md`. Never regenerate them from code output.
- **Models are test-first** with hand-calculated expected outputs written in the test or
  fixture docs. Credits must reconcile to the opportunity amount.
- **Copy:** reports state association under a named model and window, never causal
  impact. Always show the model name and lookback window next to numbers.
- **Data:** synthetic only (`*.example` domains). Never commit `.env` or real personal data.
- **Changing attribution math or report meaning** needs a `needs-decision` issue first.
- **Auth:** `LoginRequiredMiddleware` protects every view. Only `/v1/` (write-key auth), the
  sign-in page, `/healthz` and `/api/v1/` are `@login_not_required`; don't add another without
  a reason in the PR. `/api/v1/` views use `api.views.api_endpoint`, which checks a Bearer
  token (`manage.py createapitoken`) or a session itself and answers a JSON 401, never data.
  Page tests use the signed-in `client` fixture (`tests/conftest.py`); `anon_client` is for
  unauthenticated checks.
- **MCP server:** `mcp-server/osra_mcp` (entry point `osra-mcp`, dependency group `mcp`) is a
  client of `/api/v1/` only: it imports no Django or app code (`tests/test_architecture.py`),
  returns the API's JSON unchanged, and sends requests only to `OSRA_URL`. `mcp` is pinned
  exactly; upgrade it on purpose. New tools are read-only and go through the API.
- **HubSpot import:** `reports/hubspot.py` is GET-only against api.hubapi.com, `/crm/` paths
  plus exactly `/account-info/2026-09/details`, no redirects (`tests/test_hubspot_import.py`
  fails on any other request) and maps HubSpot records to the CSV contract's rows. It never adds a parallel validation or load path: `run_import` loads.
  Its tests use synthetic responses in HubSpot's documented shapes, never real portal data.
- **API:** `/api/v1/` is read-only (GET and HEAD; other methods 405) and only reshapes what
  the `reports` functions return for the matching page; a test compares each endpoint with its
  page's context. Changing a field's name or meaning bumps `schemaVersion`.
- **Settings:** every new environment setting goes in `.env.example` (a test enforces it) and,
  if it matters on a server, in `docs/self-hosting.md`.
- **Changelog:** user-visible changes add a line under `## [Unreleased]` in `CHANGELOG.md`.
- HTMX endpoints return HTML fragments; full page and fragment share one template include.
- Every reason code needs a fix line in `reports/fixes.py` (UI copy; a test enforces it).
- UI follows the `ux-standards` skill (Focosys tokens in `static/css/tokens.css`; no raw hex in
  `app.css`).
- Migrations: generate with `makemigrations`; migrations are exempt from Ruff format/E501.
- Vendored assets: record version, source URL, license, and SHA-256 in
  `static/vendor/README.md`.
- Commit messages end with the co-author line the session specifies.

## Merging

Standing permission from the owner (Christopher Landaverde, 2026-10-30): agents merge their own pull requests, user-visible ones included, without asking, when all of these hold:
- CI is green on GitHub on the PR's latest commit (`gh pr checks <n>`; local runs don't count).
- An agent other than the author reviewed the diff and posted `Blocking findings: none`.
- The PR merges cleanly into `main`.

Merge with `gh pr merge <n> --squash --delete-branch`, then confirm `main` CI passes. Still stop and ask for: releases, tags, store or package publishing, deploys, repo settings or visibility, spending money, and deleting anything you didn't create. Never push directly to `main` or force-push a shared branch.
