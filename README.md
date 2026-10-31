<p align="center">
  <img src="docs/media/logo-256.png" width="96" height="96" alt="Open Source Revenue Attribution logo: a lime revenue line rising through three touch points on a dark green rounded tile">
</p>

<h1 align="center">Open Source Revenue Attribution</h1>

<p align="center">
  <strong>Trace closed-won revenue back to the touches behind it, and check every step of the math.</strong>
</p>

<p align="center">
  5 named models side by side · 7 data-readiness checks · RudderStack-compatible event collection · self-hostable with Docker Compose and PostgreSQL 17
</p>

<p align="center">
  <a href="https://github.com/ChristopherLandaverde/open-source-revenue-attribution/actions/workflows/ci.yml"><img src="https://github.com/ChristopherLandaverde/open-source-revenue-attribution/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/ChristopherLandaverde/open-source-revenue-attribution?color=10231F" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> · <a href="#send-events">Send events</a> · <a href="#what-you-get">What you get</a> · <a href="#known-limits">Known limits</a> · <a href="docs/how-it-works.md">How it works</a> · <a href="docs/self-hosting.md">Self-hosting</a> · <a href="docs/contract.md">Data contract</a>
</p>

Open Source Revenue Attribution is a self-hostable app for B2B marketers, founders and RevOps
analysts who have to explain which campaigns are associated with pipeline and won revenue, and
defend the number. It shows the whole chain: CSV row or event → validated record → contact →
eligible journey → named model → credit that adds up to the deal amount.

On the bundled synthetic sample, `google / cpc / q1-search` gets **39000.00 USD** of the
54000.00 USD pipeline under first-touch and **0** under last-touch. `linkedin / paid-social /
abm-launch` gets the reverse. Same touches; only the named model changed.

That number usually comes from a tool that won't show its work: which touches counted, which
were dropped and why, which rule split the deal. So budget moves on a number nobody can audit,
even though the model choice alone can move a campaign from all of a deal's credit to none.
Attribution here is a
reporting model: it shows association under a named rule and window, not causal impact or
incrementality.

<p align="center">
  <img src="docs/media/proof.gif" width="880" alt="Four storyboard frames on a dark green stage, each with a step counter and a headline. 1 of 4: the bundled synthetic sample, 4 CSVs and 43 rows, 10 of them invalid on purpose; an excerpt of sample_data/demo/touchpoints.csv with the q1-search rows (tp-01, tp-07) and abm-launch rows (tp-02, tp-08) highlighted, beside the Data validation page after Import the demo data set: 10 rows refused, the other 32 loaded, rows by file. 2 of 4: the model comparison's USD table; google / cpc / q1-search gets 39000.00 of 54000.00 USD under first-touch and 0 under last-touch, linkedin / paid-social / abm-launch the reverse; every model column totals 54000.00. 3 of 4: the journey of Northwind platform, touch by touch: tp-01 gets 24000.00 under first-touch and 0.00 under last-touch, tp-02 the reverse, tp-03 came after the conversion and gets no credit; each column adds up to 24000.00 USD. 4 of 4: opportunities.csv row 5, opp-104, has an empty contact_id, beside Data readiness: 3 checks need a fix, the first being 5 of 6 opportunities have a contact, with why, fix, how to verify and the record opp-104.">
  <br><sub>Built by <a href="scripts/readme-demo/">scripts/readme-demo/</a> from the running app on <code>sample_data/demo/</code> (synthetic, <code>*.example</code> domains). Every number in the captions is read from the app during the run.</sub>
</p>

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
[data contract](docs/contract.md#2-csv-import-files). To collect events from your site, see
[Send events](#send-events).

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

## Send events

The collection endpoint is RudderStack-compatible: it takes page, track and identify events from
the RudderStack JavaScript SDK on `/v1/`, authenticated by a write key from
`manage.py create_workspace`. Load the SDK (3.35.0, the version vendored in `static/vendor/`)
with your server as its data plane URL:

```html
<script src="https://cdn.jsdelivr.net/npm/@rudderstack/analytics-js@3.35.0/dist/npm/modern/bundled/umd/index.js"></script>
<script>
  const osra = new window.rudderanalytics.RudderAnalytics();
  osra.load("<write key>", "https://attribution.acme.example", {
    // This server is not a RudderStack control plane: give the SDK its source config here.
    getSourceConfig: () => ({
      source: { id: "osra", name: "OSRA", enabled: true, config: {}, destinations: [] },
    }),
  });
  osra.page();
</script>
```

Keep `getSourceConfig`: without it the SDK asks RudderStack's servers for its configuration and
sends nothing. Call `osra.identify("<contact_id>")` when a visitor becomes a known contact; that
links their earlier page views to the contact.

- **Already on RudderStack?** Forward events with a Webhook destination instead of a second SDK:
  [steps](docs/self-hosting.md#forward-from-an-existing-rudderstack-setup). Tested against
  RudderStack's documented payloads, not yet from a live RudderStack workspace.
- **Try it locally** with `curl` and the bundled synthetic events:
  [docs/how-it-works.md](docs/how-it-works.md#send-events).

Not affiliated with RudderStack.

## Use it from an agent / API

Read-only JSON endpoints return what the report pages show, computed by the same functions, so
an agent or script gets the page's numbers rather than its own. Every response has
`schemaVersion: "1"`, the model names, the window, and a `meaning` field with the pages' own
wording: values are association under a named model, not causal impact.

| Endpoint | Returns | Page |
|---|---|---|
| `GET /api/v1/attribution?metric=pipeline\|won&model=<id>` | Credit per campaign for each model (or one), Influenced beside it, per currency; credit per opportunity | `/` |
| `GET /api/v1/journeys/<opportunity or account id>?metric=&model=` | Each touch in order, its eligibility and why, and each model's credit. An account ID returns each opportunity's contact journey, one per opportunity, not combined; an opportunity ID wins over an account ID with the same value | journey |
| `GET /api/v1/readiness?metric=` | The 7 data checks: status, count and total, finding, fix, affected records | `/readiness/` |

Model IDs: `first-touch`, `last-touch`, `linear`, `position-based-u-shaped`, `time-decay`.
There are no date filters (`start`, `end`), because the pages have none; unknown parameters
get a 400 that says so.

Create a token for an existing user (shown once; only its hash is stored), then send it as a
Bearer token. A signed-in browser session works too. Revoke a token by deleting it in the admin
under API tokens.

```console
$ uv run python manage.py createapitoken admin --name agent
Created API token 'agent' for 'admin'.
Token: osra_enx_YAtOVpL06OuBqLovbReqKnBYhTVyYDDquQ46NlM
Copy it now; it is not shown again. Send it as:
  Authorization: Bearer <token>
$ export OSRA_TOKEN=osra_enx_YAtOVpL06OuBqLovbReqKnBYhTVyYDDquQ46NlM
```

(That token is from a throwaway local database; yours will differ.)

On the bundled sample data (`load_sample_data`). The output is trimmed by hand: fields and
list items are left out, and the values shown are unchanged.

```sh
curl -s -H "Authorization: Bearer $OSRA_TOKEN" \
  "http://127.0.0.1:8000/api/v1/attribution?model=linear"
```

```json
{
  "schemaVersion": "1",
  "meaning": "Each column applies one named rule to the same touches. The numbers show association under that rule, not causal impact: no column shows that a campaign caused a deal. A gap between columns is the rules' difference, not a measured lift.",
  "metric": { "id": "pipeline", "label": "Pipeline (credited at opportunity creation)" },
  "window": { "lookbackDays": null, "description": "No lookback cap: every touch up to the conversion" },
  "models": [{ "id": "linear", "name": "Linear", "parameters": "Equal share to every eligible touch", "standard": "Dreamdata, HockeyStack, GA4 (legacy)" }],
  "dataReadiness": { "opportunities": 6, "attributable": 5, "checksToFix": ["contact", "utm", "import"], "details": "/api/v1/readiness?metric=pipeline" },
  "currencies": [
    {
      "currency": "USD", "total": "54000.00", "opportunities": 4, "unattributed": "9000.00",
      "rows": [
        {
          "campaignKey": "google / cpc / q1-search",
          "unattributed": false,
          "attributed": { "linear": "19500.00" },
          "influenced": { "amount": "39000.00", "opportunities": 2 }
        }
      ]
    }
  ]
}
```

```sh
curl -s -H "Authorization: Bearer $OSRA_TOKEN" http://127.0.0.1:8000/api/v1/journeys/opp-101
```

```json
{
  "schemaVersion": "1",
  "subject": { "type": "opportunity", "id": "opp-101" },
  "journeys": [
    {
      "opportunity": { "id": "opp-101", "amount": "24000.00", "currency": "USD", "contactId": "con-nw-ana" },
      "conversionAt": "2026-04-01T12:00:00Z",
      "eligibleTouches": 2,
      "touches": [
        {
          "position": 1, "touchpointId": "tp-01", "campaignKey": "google / cpc / q1-search", "status": "eligible",
          "credits": { "first-touch": "24000.00", "last-touch": "0.00", "linear": "12000.00", "position-based-u-shaped": "12000.00", "time-decay": "2265.76" }
        },
        {
          "position": 3, "touchpointId": "tp-03", "campaignKey": "partner / referral / may-webinar", "status": "after",
          "credits": { "first-touch": null, "last-touch": null, "linear": null, "position-based-u-shaped": null, "time-decay": null }
        }
      ]
    }
  ]
}
```

```sh
curl -s -H "Authorization: Bearer $OSRA_TOKEN" http://127.0.0.1:8000/api/v1/readiness
```

```json
{
  "schemaVersion": "1",
  "verdict": "fix_data_first",
  "opportunities": 6,
  "attributable": 5,
  "noEligibleTouch": ["opp-104"],
  "checks": [
    {
      "key": "contact", "status": "review", "count": 5, "total": 6,
      "finding": "5 of 6 opportunities have a contact.",
      "fix": "Fill contact_id in opportunities.csv for these opportunities, then import again.",
      "examples": ["opp-104"]
    }
  ]
}
```

Without a valid token or session the API answers `401` with
`{"schemaVersion": "1", "error": {"code": "not_authenticated", …}}` and no data. Any method
other than GET or HEAD gets `405`. Amounts are strings at the currency's minor unit (`"1200000"` for
JPY), and times are ISO 8601 in UTC. There is no MCP server yet; it is the next step.

## What you get

- **Every number traced to its source.** Open any opportunity to see each touch of its contact, why it is or isn't eligible, and what each model gives it.
- **Five named models, side by side.** First-touch, last-touch, linear, position-based (U-shaped) and time decay, each with its rule and the vendor definition it follows (Dreamdata, GA4, HockeyStack). Every column adds up to the deal amount.
- **Bad data refused, not silently counted.** Imports and events are checked against a [documented contract](docs/contract.md). Each refused row gets a reason code and a fix.
- **A readiness check before you trust it.** 7 data checks with counts, each failing one with a fix, a way to verify it, and the affected records.
- **Pipeline and won revenue.** Credited at opportunity creation and at close; currencies are reported side by side, never summed.

## Who it's for

- **Marketers and founders at small B2B companies** who have to explain which campaigns are associated with pipeline and won revenue, and defend the number.
- **RevOps and agency analysts** who need to see why a touch counted or didn't before they report on it.
- **Teams that want their data on their own server**, with a data contract they can read instead of a black box.

## What works today

| Area | What you get | Status |
|---|---|---|
| CSV import and validation | Import page or `load_sample_data`; 21 refusal and 8 warning codes; every refused row listed with its fix on `/validation/` | Works |
| Event collection | RudderStack-compatible `/v1/batch`, `/page`, `/track`, `/identify` with a write key; deduplicated; sessions become touchpoints | Works |
| Opportunity journey | Each touch of the opportunity's contact, its eligibility and the reason, and each model's credit | Works |
| Model comparison | 5 rule-based models per campaign and per opportunity, plus an overlapping Influenced column; pipeline and won revenue; optional lookback window | Works |
| Data readiness | 7 checks with denominators, fixes and affected records; "Not checked" when there is no data | Works |
| Read-only JSON API | `/api/v1/attribution`, `/journeys/<id>`, `/readiness` with a per-user Bearer token; same numbers as the pages. An account ID returns each opportunity's contact journey, not combined | Works |
| Sign-in and self-hosting | Every page behind sign-in; Docker image and `compose.production.yml` with PostgreSQL 17 | Works |
| Account journey (all contacts combined), stage history | | Planned |
| W-shaped model (needs a lead milestone in the contract) | | Planned |
| MCP server over the JSON API | | Planned |
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
- **API tokens read everything.** A token acts as its user, who sees all data (there are no
  roles); tokens have no scopes or expiry. Revoke one by deleting it in the admin.
- **Stages are `open` and `won` only**; mixed currencies are reported side by side, never summed.
- **Not yet run on a public domain.** The self-hosted stack was run end to end on 2026-10-29
  behind Caddy with a local certificate; a Let's Encrypt deployment is untested.

## Status

Milestones M0 to M5 are on `main`. v0.1.0 is prepared in [CHANGELOG.md](CHANGELOG.md) but not
tagged or released, and no Docker image or package is published: run it from a clone. The
v0.1.0 browser walkthrough is in
[docs/reviews/2026-10-30-v0.1.0-walkthrough.md](docs/reviews/2026-10-30-v0.1.0-walkthrough.md).
Milestones: [docs/project-management-plan.md](docs/project-management-plan.md).

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
