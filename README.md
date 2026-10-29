# Open Source Revenue Attribution

**See which marketing touchpoints are associated with B2B pipeline and won revenue, and inspect the math behind every number.**

[![CI](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/actions/workflows/ci.yml/badge.svg)](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[Quick start](#quick-start) · [What works today](#what-works-today) · [Known limits](#known-limits) · [Data contract](docs/contract.md)

A self-hostable Django app for marketers, founders and agency analysts at small B2B companies
who need a revenue report they can explain. It collects RudderStack events, imports accounts,
contacts, opportunities and touchpoints from CSV, refuses data that breaks a
[documented contract](docs/contract.md) with a reason code, and credits each opportunity under
five named models and a lookback window, side by side.

Attribution here is a reporting model. It shows how a stated rule assigns credit; it does not
estimate causal impact or incrementality.

**Status:** M4 (model comparison, influenced amounts, data readiness) is on a work branch,
awaiting review; M3 and session-level touchpoints (#7) are on `main`. Milestones:
[docs/project-management-plan.md](docs/project-management-plan.md).

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
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/ for the model comparison on the synthetic demo data: credit per
campaign under five models, each named with its rule, and the influenced amount beside them.
Switch between **Pipeline** and **Won revenue** to swap the tables in place. Click an
opportunity to open its journey: every touch of its contact, why each one is or isn't eligible,
and its first-touch credit.
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

With `DEBUG=true`, http://127.0.0.1:8000/events/demo/ loads the RudderStack JavaScript SDK and
sends identify, page and track events from your browser to the same endpoint.

<details>
<summary>Postgres with Docker (untested)</summary>

`.env.example` points at the Postgres service in `docker-compose.yml`. Skip the `sed` line and
start the database before migrating:

```sh
docker compose up -d --wait db
uv run python manage.py migrate
```

The Postgres path has not been run end to end yet; tests and the steps above use SQLite.
</details>

## What works today

| Area | What you get | Status |
|---|---|---|
| Data contract | CSV import and RudderStack event rules, 21 refusal and 8 warning codes ([docs/contract.md](docs/contract.md)) | Works |
| CSV import | `load_sample_data --path <dir>` or the **Import CSV** page: validate, load accepted rows, list refused ones. Partial by default, `--strict` / Strict checkbox refuses everything on any error. Re-import updates by ID. | Works |
| Validation report | `/validation/`: verdict, counts per file, every refused row and warning with its code and how to fix it | Works |
| Event collection | `POST /v1/batch`, `/v1/page`, `/v1/track`, `/v1/identify` with a per-workspace write key. Validated, deduplicated on `messageId`, raw payload and outcome stored. | Works |
| Events to touchpoints | An identify links the browser's earlier anonymous page views to the contact. Each session (a browser's events less than 30 minutes apart, as in Dreamdata and GA4) is one touchpoint, credited to its first page view's UTMs or referrer; later page views in the session are not counted again. Browser clock skew corrected with receive time minus `sentAt`. | Works |
| Opportunity journey | `/opportunities/<id>/journey/`: each touch of the opportunity's contact in a fixed order, its lookback status, the session rule that admitted it with the session's page views nested under it, and its first-touch credit | Works |
| Model comparison | `/`: first-touch, last-touch, linear, position-based (U-shaped, 40/20/40) and time decay (7-day half-life) side by side per campaign and per opportunity. Pipeline (at creation) and won revenue (at close), 90-day lookback, totals per currency. Every model column sums to the amount, with leftover cents assigned deterministically. | Works |
| Attributed vs influenced | An Influenced column beside the models: the full amount of every opportunity a campaign touched, labelled as overlapping and never totalled (Dreamdata's definition) | Works |
| Data readiness | `/readiness/`: 7 checks with denominators (contacts, tracked touches, touches in the window, campaign fields, refused import rows, refused events, unlinked page views). Each failing check comes with its fix, a way to verify it, and the affected records. Checks without data show "Not checked". | Works |
| Demo fixtures | Synthetic CSVs and events with hand-calculated expected results ([sample_data/](sample_data/)) | Works |
| Combined account journey, stage history | | Planned |
| W-shaped model (needs a lead milestone), journeys under every model | | Planned |
| Self-hosting guide, release | | Planned (M5) |

## Known limits

- **Rule-based models only.** No data-driven model: it needs volume and can't be checked by
  hand. No W-shaped model yet. Model definitions and their sources:
  [docs/research/m4-models.md](docs/research/m4-models.md).
- **The window is fixed at 90 days** (GA4's default). Dreamdata counts from the first
  interaction instead, so long journeys show more Unattributed here.
- **Journeys show first-touch credit.** The other models' per-touch credit is in the
  comparison's "Credit by opportunity" table.
- **No login.** Every page, including CSV upload, is open to anyone who can reach the server.
  Run it locally or behind your own access control.
- **Same-origin collection only.** The endpoint sends no CORS headers, so a site on another
  domain cannot post to it from the browser yet.
- **One dataset.** Write keys identify the sender; workspaces do not isolate data.
- **Identity is identify-only.** Anonymous views link to a contact only through an identify on
  the same browser (`anonymousId`), and only views before it. A browser identified as two
  contacts links to neither. Rules: [contract §3](docs/contract.md#from-events-to-touchpoints).
- **Touchpoints are recomputed from all events** on every collection request; fine for demo
  volumes, not tuned for large ones.
- **Journeys are per opportunity contact.** The page lists the account's other contacts but
  does not combine them into an account journey yet.
- **Stages are `open` and `won` only**; mixed currencies are reported side by side, never summed.
- **Postgres is untested**; SQLite is what tests and the steps above use.

## How it works

`CSV row / event → contract validator → stored record → touchpoints of the opportunity's contact → eligible journey → named model → credit per opportunity`

| Path | What |
|---|---|
| `contracts/` | Pure-Python contract: import and event validators, reason codes, clock-skew correction, event → touchpoint conversion (stitching, sessions). No Django imports (a test enforces it). |
| `attribution/` | Pure-Python models, types and journeys. No Django imports. |
| `collection/` | Django app: write-key workspaces, `/v1/` endpoint, stored events, events page, SDK demo page. |
| `reports/` | Django app: records, imports (command and upload page), model comparison, data readiness, journey and validation pages. |
| `sample_data/` | Synthetic demo CSVs and events with hand-calculated expected results. |
| `static/` | Plain CSS with Focosys design tokens; vendored HTMX, RudderStack SDK and fonts (versions and hashes in `static/vendor/README.md`). |
| `docs/` | Data contract, PRD, decisions, model research, project management plan, market research. |

## Development

```sh
uv run ruff check . && uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
```

Tests use in-memory SQLite (`config/settings_test.py`) and need no `.env` or Docker. They cover
the contract rules, both fixtures against their hand-calculated results, the endpoint
(auth, dedup, replay), imports from the command and the upload page, and every page. CI runs the
same commands. Repo conventions for contributors and agents: [AGENTS.md](AGENTS.md).

## License

MIT. See [LICENSE](LICENSE).
