# Open Source Revenue Attribution

**See which marketing touchpoints are associated with B2B pipeline and won revenue, and inspect the math behind every number.**

[![CI](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/actions/workflows/ci.yml/badge.svg)](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[Quick start](#quick-start) · [Self-host](#self-host) · [What works today](#what-works-today) · [Known limits](#known-limits) · [Feedback](#feedback) · [Data contract](docs/contract.md)

A self-hostable Django app for marketers, founders and agency analysts at small B2B companies
who need a revenue report they can explain. It collects RudderStack events, imports accounts,
contacts, opportunities and touchpoints from CSV, refuses data that breaks a
[documented contract](docs/contract.md) with a reason code, and credits each opportunity under
five named models, side by side. By default every touch up to the conversion counts, as in
Dreamdata; a lookback window in days is optional.

Attribution here is a reporting model. It shows how a stated rule assigns credit; it does not
estimate causal impact or incrementality.

**Status:** M0 to M4 are on `main`. M5 (sign-in, allowed origins, Docker self-hosting,
release checklist) is on a work branch awaiting review. v0.1.0 is prepared in
[CHANGELOG.md](CHANGELOG.md) but not tagged or released, and the repository is private.
Milestones: [docs/project-management-plan.md](docs/project-management-plan.md).

![Model comparison on the synthetic demo data: a "Fix data first" verdict with the top fix, then credit per source / medium / campaign under first-touch, last-touch, linear, position-based and time-decay models, with an overlapping Influenced column](docs/media/report.png)

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). These steps use SQLite; the
Postgres setup is below.

```sh
git clone https://github.com/ChristopherLandaverde/open-source-revenue-attribution.git
cd open-source-revenue-attribution
uv sync
cp .env.example .env
sed -i 's|^DATABASE_URL=.*|DATABASE_URL=sqlite:///db.sqlite3|' .env
uv run python manage.py migrate
uv run python manage.py load_sample_data
uv run python manage.py createsuperuser          # asks for a username and password
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/ and sign in with that account. You land on the model comparison on the synthetic demo data: credit per
campaign under five models, each named with its rule, and the influenced amount beside them.
Switch between **Pipeline** and **Won revenue** to swap the tables in place. Click an
opportunity to open its journey: every touch of its contact, why each one is or isn't eligible,
and each model's credit for it.
http://127.0.0.1:8000/readiness/ lists what to fix in the data before you trust the numbers.
On the demo data, 3 checks need a fix. Each one comes with its fix and a way to verify it.
http://127.0.0.1:8000/validation/ shows what the import refused and why: the demo data has 10
invalid rows on purpose.

![Data validation page after importing the demo CSVs: verdict "10 rows refused. The other 32 rows were loaded.", rows by file, and each refused row with its reason code and how to fix it](docs/media/validation.png)

The clone URL works for collaborators while the repository is private.

### Send events

```sh
uv run python manage.py create_workspace demo     # prints: Write key: <key>
curl -u '<key>:' -H 'Content-Type: application/json' \
  --data @sample_data/events/batch.json http://127.0.0.1:8000/v1/batch
```

The response lists each event's outcome. Here: 16 received, 14 accepted, 1 duplicate, 1 refused
(`TIMESTAMP_WITHOUT_TIMEZONE`). Send it again and nothing new is stored: 15 duplicates,
1 refused. http://127.0.0.1:8000/events/ shows the events and which became touchpoints.

Pages on any site can send events from the browser. Set `COLLECT_ALLOWED_ORIGINS` to accept
them only from your own sites
([details](docs/self-hosting.md#send-events-from-your-site)).
With `DEBUG=true`, http://127.0.0.1:8000/events/demo/ loads the RudderStack JavaScript SDK and
sends identify, page and track events from your browser to the same endpoint.

<details>
<summary>Local Postgres with Docker</summary>

`.env.example` points at the PostgreSQL 17 service in `docker-compose.yml`. Skip the `sed`
line and start the database before migrating:

```sh
docker compose up -d --wait db
uv run python manage.py migrate
```
</details>

## Self-host

For a server: the app (gunicorn) and PostgreSQL 17 from `compose.production.yml`, behind your
own TLS proxy (Caddy and nginx examples in [`deploy/`](deploy/)). Requires Docker with Compose v2.

```sh
cp .env.example .env      # set DEBUG=false, SECRET_KEY, POSTGRES_PASSWORD, ALLOWED_HOSTS, ...
docker compose -f compose.production.yml up -d --build --wait
docker compose -f compose.production.yml exec app python manage.py createsuperuser
```

The app listens on `127.0.0.1:8000` for the proxy, applies migrations on start and refuses to
run with `DEBUG=false` and no `SECRET_KEY`. `manage.py check --deploy` reports unsafe
settings. The [self-hosting guide](docs/self-hosting.md) has the production `.env`, TLS, allowed
origins, backups and restore, upgrades and a security checklist. It was run end to end on
2026-10-29 behind Caddy with a local certificate, not yet on a public domain.

## What works today

| Area | What you get | Status |
|---|---|---|
| Data contract | CSV import and RudderStack event rules, 21 refusal and 8 warning codes ([docs/contract.md](docs/contract.md)) | Works |
| CSV import | `load_sample_data --path <dir>` or the **Import CSV** page: validate, load accepted rows, list refused ones. Partial by default, `--strict` / Strict checkbox refuses everything on any error. Re-import updates by ID. | Works |
| Validation report | `/validation/`: verdict, counts per file, every refused row and warning with its code and how to fix it | Works |
| Event collection | `POST /v1/batch`, `/v1/page`, `/v1/track`, `/v1/identify` with a per-workspace write key. Validated, deduplicated on `messageId`, raw payload and outcome stored. | Works |
| Events to touchpoints | An identify links the browser's earlier anonymous page views to the contact. Each session (a browser's events less than 30 minutes apart, as in Dreamdata and GA4) is one touchpoint, credited to its first page view's UTMs or referrer; later page views in the session are not counted again. Browser clock skew corrected with receive time minus `sentAt`. | Works |
| Opportunity journey | `/opportunities/<id>/journey/`: each touch of the opportunity's contact in a fixed order, its lookback status, the session rule that admitted it with the session's page views nested under it, and the credit each model gives it | Works |
| Model comparison | `/`: first-touch, last-touch, linear, position-based (U-shaped, 40/20/40) and time decay (7-day half-life) side by side per campaign and per opportunity. Pipeline (at creation) and won revenue (at close), no lookback cap by default (optional `ATTRIBUTION_LOOKBACK_DAYS`), totals per currency. Every model column sums to the amount, with leftover cents assigned deterministically. | Works |
| Attributed vs influenced | An Influenced column beside the models: the full amount of every opportunity a campaign touched, labelled as overlapping and never totalled. Opportunities with no eligible touch are left out and listed on the readiness page (Dreamdata's definition). | Works |
| Data readiness | `/readiness/`: 7 checks with denominators (contacts, tracked touches, touches in the window, campaign fields, refused import rows, refused events, unlinked page views). Each failing check comes with its fix, a way to verify it, and the affected records. Checks without data show "Not checked". | Works |
| Demo fixtures | Synthetic CSVs and events with hand-calculated expected results ([sample_data/](sample_data/)) | Works |
| Combined account journey, stage history | | Planned |
| W-shaped model (needs a planned `lead_created_at` lead milestone in the contract) | | Planned |
| Sign-in | Every page needs a signed-in user (Django auth); the first admin comes from `createsuperuser`. No public sign-up, no default password. `/v1/` keeps write-key auth. | Works |
| Self-hosting | Docker image, `compose.production.yml` with PostgreSQL 17, allowed origins for browser events, `check --deploy` checks, backup and upgrade steps ([docs/self-hosting.md](docs/self-hosting.md)) | Works (M5 branch) |
| Release | Checklist in [docs/release.md](docs/release.md), v0.1.0 entry in [CHANGELOG.md](CHANGELOG.md) | Prepared, not tagged |

## Known limits

- **Rule-based models only.** No data-driven model: it needs volume and can't be checked by
  hand. No W-shaped model yet. Model definitions and their sources:
  [docs/research/m4-models.md](docs/research/m4-models.md).
- **Time decay is not a Dreamdata model.** It follows GA4's legacy model and HockeyStack
  (7-day half-life), and the page says so.
- **One dataset, one role.** Write keys identify the sender; workspaces do not isolate data.
  Every signed-in user sees and can import everything; there are no roles or per-workspace
  permissions.
- **Allowed origins are global.** `COLLECT_ALLOWED_ORIGINS` applies to every write key, not
  per workspace. It is not authentication: the write key is visible in your pages.
- **Identity is identify-only.** Anonymous views link to a contact only through an identify on
  the same browser (`anonymousId`), and only views before it. A browser identified as two
  contacts links to neither. Rules: [contract §3](docs/contract.md#from-events-to-touchpoints).
- **Touchpoints are recomputed from all events** on every collection request; fine for demo
  volumes, not tuned for large ones.
- **Journeys are per opportunity contact.** The page lists the account's other contacts but
  does not combine them into an account journey yet.
- **Stages are `open` and `won` only**; mixed currencies are reported side by side, never summed.
- **Not yet run on a public domain.** The self-hosted stack was verified with Caddy's local
  certificate on localhost; a Let's Encrypt deployment is untested.

## How it works

`CSV row / event → contract validator → stored record → touchpoints of the opportunity's contact → eligible journey → named model → credit per opportunity`

| Path | What |
|---|---|
| `contracts/` | Pure-Python contract: import and event validators, reason codes, clock-skew correction, event → touchpoint conversion (stitching, sessions). No Django imports (a test enforces it). |
| `attribution/` | Pure-Python models, types and journeys. No Django imports. |
| `collection/` | Django app: write-key workspaces, `/v1/` endpoint, stored events, events page, SDK demo page. |
| `reports/` | Django app: records, imports (command and upload page), model comparison, data readiness, journey and validation pages. |
| `config/` | Settings (every value from the environment), URLs, sign-in, `/healthz`, deployment checks. |
| `deploy/`, `Dockerfile`, `compose.production.yml` | Self-hosting: image, app + PostgreSQL stack, Caddy and nginx examples. |
| `sample_data/` | Synthetic demo CSVs and events with hand-calculated expected results. |
| `static/` | Plain CSS with Focosys design tokens; vendored HTMX, RudderStack SDK and fonts (versions and hashes in `static/vendor/README.md`). |
| `docs/` | Data contract, self-hosting guide, release process, PRD, decisions, research, project management plan, market research. |

## Development

```sh
uv run ruff check . && uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
```

Tests use in-memory SQLite (`config/settings_test.py`) and need no `.env` or Docker. Set
`TEST_DATABASE_URL=postgres://osra:osra@localhost:5432/osra` to run them on PostgreSQL instead.
They cover the contract rules, both fixtures against their hand-calculated results, the
endpoint (write-key auth, allowed origins, dedup, replay), sign-in on every page, deployment
checks, imports from the command and the upload page, and every page. CI runs the same
commands, `check --deploy` with production-like settings, and the tests on PostgreSQL 17.
Releases: [docs/release.md](docs/release.md). Repo conventions for contributors and agents: [AGENTS.md](AGENTS.md).

## Feedback

User feedback comes before new connectors. If you try it, open a
[feedback issue](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/new?template=feedback.yml):
what you wanted to find out, what got in the way, and where your data lives today (CRM, ad
platforms, tracking). Bugs and wrong-looking numbers:
[bug report](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/new?template=bug_report.yml).
Don't paste real customer data or write keys.

## License

MIT. See [LICENSE](LICENSE).
