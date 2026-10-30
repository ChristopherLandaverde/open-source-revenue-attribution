# How it works

The detail behind the [README](../README.md): what each part does today, how events become
touchpoints, how the models split credit, and where the code lives. Field-level rules and every
reason code are in the [data contract](contract.md). Running it on a server is in the
[self-hosting guide](self-hosting.md).

Every number the app shows is association under a named model and window. It shows how a stated
rule assigns credit; it does not estimate causal impact or incrementality.

## The chain behind every number

`CSV row / event → contract validator → stored record → touchpoints of the opportunity's contact → eligible journey → named model → credit per opportunity`

| Step | What happens | Where you see it |
|---|---|---|
| Source | A CSV row (accounts, contacts, opportunities, touchpoints) or a RudderStack event | **Import CSV** page, `load_sample_data`, `POST /v1/batch` |
| Validated record | Checked against the [data contract](contract.md). Refused rows and events get one of 21 reason codes and are never loaded; accepted ones may carry one of 8 warning codes. | `/validation/`, `/events/` |
| Relationship | Opportunity → account → contact by explicit IDs. Only the opportunity's own contact's touches count. | Journey page, "Audit chain" |
| Eligible journey | Every touch of that contact, in time order, marked eligible or not with the reason (after the conversion, outside an optional lookback window) | `/opportunities/<id>/journey/` |
| Named model | Five rule-based models, each shown with its rule and the vendor definition it follows | `/` and the journey page |
| Reconciled credit | Every model column sums to the opportunity amount; leftover cents go to the largest remainder, deterministically | Totals rows on `/` and the journey page |

## What each part does

| Area | What you get |
|---|---|
| Data contract | CSV import and RudderStack event rules, 21 refusal and 8 warning codes ([contract.md](contract.md)) |
| CSV import | `load_sample_data --path <dir>` or the **Import CSV** page: validate, load accepted rows, list refused ones. Partial by default; `--strict` or the Strict checkbox refuses everything on any error. Re-import updates by ID. |
| Validation report | `/validation/`: verdict, counts per file, every refused row and warning with its code and how to fix it |
| Event collection | `POST /v1/batch`, `/v1/page`, `/v1/track`, `/v1/identify` with a per-workspace write key. Validated, deduplicated on `messageId`, raw payload and outcome stored. |
| Events to touchpoints | An identify links the browser's earlier anonymous page views to the contact. Each session (a browser's events less than 30 minutes apart, as in Dreamdata and GA4) is one touchpoint, credited to its first page view's UTMs or referrer; later page views in the session are not counted again. Browser clock skew is corrected with receive time minus `sentAt`. Rules: [contract §3](contract.md#from-events-to-touchpoints). |
| Opportunity journey | `/opportunities/<id>/journey/`: each touch of the opportunity's contact in a fixed order, its lookback status, the session rule that admitted it with the session's page views nested under it, and the credit each model gives it |
| Model comparison | `/`: first-touch, last-touch, linear, position-based (U-shaped, 40/20/40) and time decay (7-day half-life) side by side per campaign and per opportunity. Pipeline (credited at creation) and won revenue (credited at close). No lookback cap by default (optional `ATTRIBUTION_LOOKBACK_DAYS`). Totals per currency, never summed across currencies. |
| Attributed vs influenced | An Influenced column beside the models: the full amount of every opportunity a campaign touched, labelled as overlapping and never totalled. Opportunities with no eligible touch are left out and listed on the readiness page (Dreamdata's definition). |
| Data readiness | `/readiness/`: 7 checks with denominators (contacts, tracked touches, touches in the window, campaign fields, refused import rows, refused events, unlinked page views). Each failing check comes with its fix, a way to verify it, and the affected records. Checks without data show "Not checked". |
| Sign-in | Every page needs a signed-in user (Django auth); the first admin comes from `createsuperuser`. No public sign-up, no default password. `/v1/` keeps write-key auth. |
| Self-hosting | Docker image, `compose.production.yml` with PostgreSQL 17, allowed origins for browser events, `check --deploy` checks, backup and upgrade steps ([self-hosting.md](self-hosting.md)) |

## The models

| Model | Rule | Follows |
|---|---|---|
| First-touch | 100% to the earliest eligible touch | Dreamdata, HockeyStack, GA4 (legacy) |
| Last-touch | 100% to the latest eligible touch | Dreamdata, HockeyStack, GA4 last click |
| Linear | Equal share to every eligible touch | Dreamdata, HockeyStack, GA4 (legacy) |
| Position-based (U-shaped) | 40% first, 40% last, 20% shared by the touches between | Dreamdata U-shaped, GA4 (legacy), HockeyStack |
| Time decay | Weight halves every 7 days before the conversion | GA4 (legacy) and HockeyStack; Dreamdata has no time decay |
| Influenced (not a model) | Full amount of every opportunity with at least one eligible touch from the campaign; overlaps, never summed | Dreamdata |

Ties on time go to the lower touch ID. Pipeline is credited at `created_at`, won revenue at
`won_at`. Why these models, and why no data-driven or W-shaped model yet:
[research/m4-models.md](research/m4-models.md) and [decisions.md](decisions.md). Hand-calculated
results for every model on the demo data: [sample_data/demo/README.md](../sample_data/demo/README.md).

## Send events

With the app running (see the README quick start):

```sh
uv run python manage.py create_workspace demo     # prints: Write key: <key>
curl -u '<key>:' -H 'Content-Type: application/json' \
  --data @sample_data/events/batch.json http://127.0.0.1:8000/v1/batch
```

The response lists each event's outcome. Here: 16 received, 14 accepted, 1 duplicate, 1 refused
(`TIMESTAMP_WITHOUT_TIMEZONE`). Send it again and nothing new is stored: 15 duplicates,
1 refused. http://127.0.0.1:8000/events/ shows the events and which became touchpoints.

Pages on any site can send events from the browser. Set `COLLECT_ALLOWED_ORIGINS` to accept
them only from your own sites ([details](self-hosting.md#send-events-from-your-site)).
With `DEBUG=true`, http://127.0.0.1:8000/events/demo/ loads the RudderStack JavaScript SDK and
sends identify, page and track events from your browser to the same endpoint.

## Code layout

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
