# Open Source Revenue Attribution

**Trace closed-won revenue back to the touches behind it, and check every step of the math.**

[![CI](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/actions/workflows/ci.yml/badge.svg)](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[Quick start](#quick-start) · [What works today](#what-works-today) · [Known limits](#known-limits) · [How it works](docs/how-it-works.md) · [Self-hosting](docs/self-hosting.md) · [Data contract](docs/contract.md)

On the bundled synthetic sample, `google / cpc / q1-search` gets **39000.00 USD** of the
54000.00 USD pipeline under first-touch and **0** under last-touch. `linkedin / paid-social /
abm-launch` gets the reverse. Same touches; only the named model changed.

Ask a B2B team which campaigns are behind last quarter's closed-won revenue and the answer
usually comes from a tool that won't show its work. Nobody can see which touches counted, which
were dropped and why, or which rule split the deal. So budget moves on a number nobody can audit.
And as the sample shows, the model choice alone can move a campaign from all of a deal's credit
to none.

Open Source Revenue Attribution is a self-hostable app that shows the whole chain for every
number: source event or CSV row → validated record → account and contact → eligible journey →
named model → credit that adds up to the deal amount. Attribution here is a reporting model: it
shows association under a named rule and window, not causal impact or incrementality.

<img src="docs/media/proof.gif" width="880" alt="Five captioned frames from the running app on the bundled synthetic demo data. 1: the Import CSV page with accounts.csv, contacts.csv, opportunities.csv and touchpoints.csv chosen. 2: Data validation: 10 rows refused, the other 32 rows loaded, rows by file, and the first refused row with its reason code INVALID_ID and how to fix it. 3: the journey of opportunity Northwind platform: three touches in time order, two eligible and one after the conversion, with credit under first-touch, last-touch, linear, position-based and time decay, each column totalling 24000.00 USD. 4: the model comparison's USD table: google / cpc / q1-search gets 39000.00 under first-touch and 0 under last-touch, linkedin / paid-social / abm-launch the reverse, every column totalling 54000.00, plus an Influenced column marked as overlapping. 5: Data readiness: Fix data first, 3 checks need a fix, the first being 5 of 6 opportunities have a contact, with why, fix and how to verify.">

<sub>Recorded with Playwright from the running app on `sample_data/demo/` (synthetic, `*.example` domains). The captions are added for the recording.</sub>

## Who it's for

- **Marketers and founders at small B2B companies** who have to explain which campaigns are associated with pipeline and won revenue, and defend the number.
- **RevOps and agency analysts** who need to see why a touch counted or didn't before they report on it.
- **Teams that want their data on their own server**, with a data contract they can read instead of a black box.

## What you get

- **Every number traced to its source.** Open any opportunity to see each touch of its contact, why it is or isn't eligible, and what each model gives it.
- **Five named models, side by side.** First-touch, last-touch, linear, position-based (U-shaped) and time decay, each with its rule and the vendor definition it follows (Dreamdata, GA4, HockeyStack). Every column adds up to the deal amount.
- **Bad data refused, not silently counted.** Imports and events are checked against a [documented contract](docs/contract.md). Each refused row gets a reason code and a fix.
- **A readiness check before you trust it.** 7 data checks with counts, each failing one with a fix, a way to verify it, and the affected records.
- **Pipeline and won revenue.** Credited at opportunity creation and at close; currencies are reported side by side, never summed.

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). This path uses SQLite and the
bundled synthetic data.

```sh
git clone https://github.com/ChristopherLandaverde/open-source-revenue-attribution.git
cd open-source-revenue-attribution
uv sync
cp .env.example .env
export DATABASE_URL=sqlite:///db.sqlite3          # leave out to use the Postgres in docker-compose.yml
uv run python manage.py migrate
uv run python manage.py load_sample_data          # loads 32 rows, refuses 10 on purpose
uv run python manage.py createsuperuser           # asks for a username and password
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/ and sign in with that account. You land on the model comparison:
under the Pipeline amount, the USD table shows `q1-search` at 39000.00 under first-touch and 0
under last-touch, and every model column totals 54000.00. Click **Northwind platform** to open
its journey, then **Data readiness** in the top bar: 3 checks need a fix on the demo data, each
with how to verify it.

To load your own data, use **Import CSV** with the four files described in the
[data contract](docs/contract.md#2-csv-import-files). To send RudderStack events to `/v1/`, see
[Send events](docs/how-it-works.md#send-events).

<details>
<summary>Local Postgres with Docker</summary>

`.env.example` points at the PostgreSQL 17 service in `docker-compose.yml`. Skip the `export`
line and start the database before migrating:

```sh
docker compose up -d --wait db
uv run python manage.py migrate
```
</details>

To run it on a server (Docker Compose with PostgreSQL 17 behind your own TLS proxy), follow the
[self-hosting guide](docs/self-hosting.md).

## What works today

| Area | What you get | Status |
|---|---|---|
| CSV import and validation | Import page or `load_sample_data`; 21 refusal and 8 warning codes; every refused row listed with its fix on `/validation/` | Works |
| Event collection | RudderStack-compatible `/v1/batch`, `/page`, `/track`, `/identify` with a write key; deduplicated; sessions become touchpoints | Works |
| Opportunity journey | Each touch of the opportunity's contact, its eligibility and the reason, and each model's credit | Works |
| Model comparison | 5 rule-based models per campaign and per opportunity, plus an overlapping Influenced column; pipeline and won revenue; optional lookback window | Works |
| Data readiness | 7 checks with denominators, fixes and affected records; "Not checked" when there is no data | Works |
| Sign-in and self-hosting | Every page behind sign-in; Docker image and `compose.production.yml` with PostgreSQL 17 | Works |
| Account journey (all contacts combined), stage history | | Planned |
| W-shaped model (needs a lead milestone in the contract) | | Planned |
| Release | v0.1.0 prepared in [CHANGELOG.md](CHANGELOG.md) | Prepared, not tagged |

Details for every row: [docs/how-it-works.md](docs/how-it-works.md).

## Known limits

- **Association, not causation.** Every number is credit under a named rule and window. A gap
  between models is the rules' difference, not a measured lift.
- **Rule-based models only.** No data-driven model: it needs volume and can't be checked by
  hand. No W-shaped model yet. Model definitions and sources:
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
- **Not yet run on a public domain.** The self-hosted stack was run end to end on 2026-10-29
  behind Caddy with a local certificate; a Let's Encrypt deployment is untested.

## Status

Milestones M0 to M5 are on `main`. v0.1.0 is prepared in [CHANGELOG.md](CHANGELOG.md) but not
tagged or released, and the repository is private for now, so the clone URL works for
collaborators only. Milestones: [docs/project-management-plan.md](docs/project-management-plan.md).

## Development

```sh
uv run ruff check . && uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
```

Tests use in-memory SQLite and need no `.env` or Docker; set
`TEST_DATABASE_URL=postgres://osra:osra@localhost:5432/osra` to run them on PostgreSQL. Both
demo fixtures are checked against hand-calculated results. CI also runs `check --deploy` with
production-like settings and the tests on PostgreSQL 17. Code layout:
[docs/how-it-works.md](docs/how-it-works.md#code-layout). Releases:
[docs/release.md](docs/release.md). Conventions for contributors and agents: [AGENTS.md](AGENTS.md).

## Feedback

User feedback comes before new connectors. If you try it, open a
[feedback issue](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/new?template=feedback.yml):
what you wanted to find out, what got in the way, and where your data lives today (CRM, ad
platforms, tracking). Bugs and wrong-looking numbers:
[bug report](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/new?template=bug_report.yml).
Don't paste real customer data or write keys.

## License

MIT. See [LICENSE](LICENSE).
