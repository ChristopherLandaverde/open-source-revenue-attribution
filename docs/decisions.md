# Decisions

Product and data-meaning decisions, newest first. Each links the issue where it was made.

## 2026-10-31 — MCP server over the JSON API (L2)

Decided by Claude under the standing rule (adopt the industry standard or argue a deviation)
and the portfolio's live-API defaults (read-only, bring your own credentials, nothing
published). Branch `claude/osra-mcp`.

**Adopted from the standard:**
- **An MCP server is how an agent reads attribution data.** Dreamdata's public surface for
  reading data is an MCP server (see the API decision below). Tools are read-only and say so
  with MCP's `readOnlyHint` annotation.
- **The official Python SDK** (`mcp`, pinned to exactly 2.3.0, released 2026-10-02) and the
  stdio transport, which Claude Code, Claude Desktop and Cursor all start from a command line.

**Deviations:**
1. **Local stdio, not a hosted HTTP server with OAuth.** Dreamdata hosts its MCP server and
   signs users in with OAuth 2.1. OSRA is self-hosted and has no authorization server, and the
   portfolio defaults rule out a hosted backend. The agent starts `osra-mcp` on the user's
   machine with the user's own API token (`OSRA_TOKEN`).
2. **A client of the JSON API, not of the database.** The server makes one GET to `/api/v1/` per
   tool call and returns the response unchanged, so the API stays the single source of numbers,
   auth and read-only enforcement. It imports nothing from Django, and a test keeps its
   `meaning` sentences identical to the API's.
3. **Requests go to `OSRA_URL` only.** Journey IDs are checked against the contract's ID rule
   before they go in the path, and redirects are not followed. A server that is missing,
   misconfigured or answers without API JSON gives a structured tool error, never a guess.
## 2026-10-31 — Read-only HubSpot import (L3, fixture-verified)

Decided by Claude under the standing rule (adopt the industry standard or argue a deviation)
and the portfolio's live-API defaults (read-only scopes, bring your own credentials, a test
proving live and file inputs give identical numbers). Branch `claude/hubspot-import`.

**Sources (read 2026-10-31):**
- Dreamdata, [Setting up HubSpot](https://docs.dreamdata.io/article/rholhyxnwo-hubspot-integration):
  companies, contacts and deals are mapped to Dreamdata's companies, contacts and deals. A
  contact associated with several companies has its events counted for each.
- Dreamdata, [Creation of Opportunities/Deals](https://docs.dreamdata.io/article/j6ut9wyyjw-setup-guide-creation-of-opportunities-deals):
  the deal-created stage uses HubSpot's `hs_createdate`; `closedate` is the optional close
  timestamp; the stage value is the deal Amount.
- Dreamdata, [Currency exchange in stage models](https://docs.dreamdata.io/article/onh0zy6mio-how-dreamdata-handles-currency-exchange-in-stage-models):
  a CRM object without a currency defaults to the account's primary currency, and amounts are
  converted to it at ECB daily rates.
- HubSpot, [List deals (CRM v3)](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/deals/get-deals.md):
  `GET /crm/v3/objects/<type>` with `limit`, `after` (from `paging.next.after`), `properties`,
  `associations` and `archived`. Associations come back inline as `{id, type}` with their own
  `paging`.
- HubSpot, [Using object APIs](https://developers.hubspot.com/docs/api-reference/latest/crm/using-object-apis):
  up to 100 records per request, cursor paging, and a 403 naming `crm.objects.deals.read`.
- HubSpot, [Associations v4](https://developers.hubspot.com/docs/api-reference/crm-associations-v4/guide):
  type 5 is "Deal to primary company", 341 is "Deal to company", 1 is "Contact to primary
  company", 279 is "Contact to company" and 3 is "Deal to contact". In v3 inline results, the
  primary association is listed as `deal_to_company` next to `deal_to_company_unlabeled`
  ([HubSpot Community, confirmed by a community manager](https://community.hubspot.com/t5/APIs-Integrations/Object-data-fetch-sorting-out-associations/td-p/658333)).
- HubSpot, [Usage guidelines](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines.md):
  private apps get 100 (Free/Starter) or 190 (Pro/Enterprise) requests per 10 seconds, plus a
  daily cap. A 429 has `errorType: RATE_LIMIT`. `Retry-After` is not documented.
- HubSpot, [Legacy private apps](https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview)
  (Bearer token; no new legacy private apps after 2026-10-26) and
  [Service keys](https://developers.hubspot.com/blog/hubspot-service-keys-the-right-api-credential-for-data-integrations)
  (account-level, data-only credentials, sent as a Bearer token).
- HubSpot, [Default deal properties](https://knowledge.hubspot.com/properties/hubspots-default-deal-properties):
  Amount ("in the deal's currency"), Currency, Close Date ("expected to close, or was
  closed"), Create Date, Is Closed Won, Is closed lost.

**Adopted from the standard (Dreamdata):**
- Companies become accounts, contacts become contacts and deals become opportunities. HubSpot's
  record IDs are the IDs, as Dreamdata matches companies by ID.
- **Pipeline conversion = `hs_createdate`** (then `createdate`, then the record's `createdAt`).
  This matches Dreamdata's deal-created stage and our 2026-10-29 decision that pipeline credit
  is measured at creation.
- **Won = `hs_is_closed_won`**, with `won_at = closedate`, Dreamdata's close timestamp. For an
  open deal, `closedate` is the *expected* close date, so it is not passed on (the contract
  refuses `won_at` on an open opportunity).
- **Value = `amount` in `deal_currency_code`**, as stored.
- Read-only access with the three `crm.objects.*.read` scopes. Nothing is written to HubSpot.
  Dreamdata's reverse sync to HubSpot properties is out of scope.

**Deviations:**
1. **Amounts are not converted.** Dreamdata converts every deal to one account currency. OSRA
   reports each currency side by side and never sums them (existing contract), so the import
   keeps the deal's own currency. A deal with no currency is refused
   (`MISSING_REQUIRED_FIELD`) unless `--currency` names one. We don't read HubSpot's company
   currency, which would need another endpoint and scope.
2. **One contact per deal.** Dreamdata is account-based and counts the touches of every
   contact. OSRA's journeys are per opportunity contact (known limit). A deal with several
   contacts uses one of its own company's contacts first, then the earliest created contact,
   then the lowest ID. The command reports how many deals had more than one contact.
3. **One company per contact and per deal: the primary one.** Dreamdata counts a contact's
   events for every company it is associated with. Our contract has one `account_id`, so we use
   the primary association. If there is no primary, we use the only company. If several
   companies are associated and none is primary, the row is refused (`MISSING_REQUIRED_FIELD`)
   rather than guessed.
4. **Closed-lost deals are refused visibly.** They are passed on as stage `lost`, and the
   contract refuses it (`INVALID_STAGE`, decision of 2026-10-29: `lost` is refused for now).
   Dreamdata would count them in pipeline. Accepting them needs the `lost` stage decision.
5. **No touches from HubSpot.** Dreamdata also maps engagements (calls, meetings, emails) to
   events on paid plans. OSRA's touches stay web sessions (events or `touchpoints.csv`). An
   `identify` call must use the HubSpot contact ID as `userId` for events to join.
6. **Full read on every run**, with no incremental sync or deletes, the same as re-importing
   CSVs. Dreamdata syncs on a schedule.
7. **CRM v3 object endpoints**, as briefed. HubSpot's reference now lists v3 under "legacy",
   next to date-versioned paths (`/crm/objects/2026-03/…`). Moving to those paths later doesn't
   change the mapping.
8. **Backoff:** `Retry-After` if HubSpot sends it, otherwise 1, 2, 4, 8 and 16 seconds (more
   than one 10-second burst window). We retry 429 and 5xx at most 5 times, then stop with an
   error and write nothing.

**Not used:** the CRM search endpoint (`POST /crm/v3/objects/<type>/search`). List endpoints
with `associations=` cover the read without a POST, so there is no allowlisted exception: the
client sends only GET requests.

## 2026-10-31 — Read-only JSON API and its auth (L1)

Decided by Claude under the standing rule (adopt the industry standard or argue a deviation)
and the portfolio's live-API defaults (read-only, nothing published). Branch
`claude/read-only-json-api`.

**Adopted from the standard:**
- **Per-user API key sent as `Authorization: Bearer <key>`**, as Plausible's Stats API
  ("sending the key in the Authorization header", keys created in account settings and
  "shown once") and PostHog's personal API keys (Bearer header; stored hashed; not viewable
  after creation) do. Dreamdata's public surface for reading data is an MCP server with
  OAuth 2.1, which needs an authorization server; that is out of scope for a self-hosted
  Django app with no new dependency. Its ingestion API uses Basic auth with a source key,
  which we already mirror on `/v1/`.
- **Stored as a SHA-256 hash, shown once** (PostHog). Tokens are 256-bit random values with an
  `osra_` prefix, so a fast hash is safe; a slow password hash would add nothing.
- **Version in the path** (`/api/v1/`, like Plausible's `/api/v2/query`), plus
  `schemaVersion: "1"` in every body so a saved response says which schema it follows.
- **Read-only.** GET and HEAD (RFC 9110) only; other methods get 405 with `Allow: GET, HEAD`.
  Responses are `Cache-Control: no-store, private`. No CORS headers: the API is for servers
  and agents, not other sites' pages, and `/v1/` CORS is unchanged. A token's `last_used_at`
  is its only write, at most once a minute and only for a request that passed validation.

**Deviations:**
1. **Tokens come from a management command, not a settings page.** `manage.py createapitoken
   <username>` follows `createsuperuser` and `create_workspace`: it needs shell access to the
   server, and no page can leak a token. The admin lists tokens (prefix, last use) and deletes
   them; it cannot create or show one.
2. **No scopes or expiry yet.** Plausible and PostHog scope keys; here every signed-in user
   already sees all data and the API cannot write, so a scope would not narrow anything. Add
   scopes with roles.
3. **No date filters.** Plausible's query takes a date range; the report pages have none, and
   the API must return the pages' numbers. Unknown parameters (`start`, `end`) get a 400 that
   says so instead of being ignored.

A signed-in browser session also authenticates (the same login as the pages). A request with
an `Authorization: Bearer` header is judged on the token alone: a wrong token is a 401 even
with a session. Other `Authorization` schemes are ignored, and the session decides.

## 2026-10-30 — Accept bare event arrays on `/v1/batch` (#16)

Decision A, chosen by Christopher: accept both `{"batch": [...]}` and a bare JSON array on
`POST /v1/batch`. Both shapes share the same maximum batch size, per-event validation, auth and
deduplication. This supports RudderStack HTTP Webhook batching and avoids a collection request
and touchpoint recomputation per event. The existing object shape remains supported.

## 2026-10-30 — CORS request headers on `/v1/` (proposed in PR, for Christopher's review)

Proposed by Claude under the standing rule (adopt the industry standard or argue a deviation).
Research and sources: [research/rudderstack-forwarding.md](research/rudderstack-forwarding.md).
Branch `docs/rudderstack-front-and-center`.

**Adopted from the standard** (rudder-server: rs/cors with `AllowedHeaders: ["*"]`, which
echoes the requested names): the `/v1/` preflight allows every well-formed header name the
browser asks for. The M5 list (`Authorization, Content-Type, AnonymousId`) refused the
RudderStack SDK's own `SentAt` and `Rsa-*` retry headers, so pages on other sites could not
send events. The M5 deviations stay: origins can be restricted, the origin is echoed rather
than `*`, and `Access-Control-Allow-Credentials` is never sent.

## 2026-10-29 — M5 self-hosting, sign-in and allowed origins

Decided by Claude under Christopher's standing rule (adopt the industry standard or argue for
a deviation). Research and sources: [docs/research/m5-self-hosting.md](research/m5-self-hosting.md).
Branch `claude/m5-self-hosting`. Christopher's review (via the coordinating session,
2026-10-29): adopt the standard for CORS; keep deviations 1 and 2 below.

**Adopted from the standard** (Plausible CE, Umami, PostHog):
- Docker Compose with the app and PostgreSQL, configured from a `.env` file.
- Migrations run when the app container starts, with an opt-out (`MIGRATE_ON_START=false`,
  like Umami's `SKIP_DB_MIGRATION`).
- Bring-your-own reverse proxy for TLS, with documented Caddy and nginx configs (Umami,
  Matomo, and Plausible's documented alternative). We don't bundle Caddy as PostHog and
  Plausible's built-in TLS do; a bundled Caddy profile can come later.
- No public sign-up (Umami; Plausible's `DISABLE_REGISTRATION`).
- Semver releases, a changelog in Keep a Changelog format (Plausible), and per-release
  migration and upgrade notes.
- Backups with `pg_dump` / `pg_restore`. No tool documents more than this.
- **Browser events from any origin by default** (`COLLECT_ALLOWED_ORIGINS="*"`), as Umami
  (`*`), Plausible (CORSPlug defaults) and PostHog (mirrors any origin) do. The first draft
  refused cross-origin events until sites were listed. That was dropped: write keys are public
  in every page snippet, and non-browser clients send no `Origin` (or any they like), so
  deny-by-default added setup friction without real protection. Listing origins restricts it,
  as Matomo's `cors_domains[]` does: other origins get 403 on the preflight and the POST, and
  nothing is stored. Same-origin pages and requests without `Origin` are always allowed.
  `check --deploy` reports the unrestricted default as `osra.I001`, an info message that does
  not fail `--fail-level WARNING`. `osra.W006` flags malformed list entries. The origin is
  echoed back, never a literal `*`, and `Access-Control-Allow-Credentials` is never sent.

**Deviations:**
1. **The first admin is created with `manage.py createsuperuser`, not on first visit (kept).**
   Plausible, PostHog and Matomo give the instance to whoever visits first, and Umami ships
   `admin`/`umami`. With first-visitor setup, whoever reaches a freshly exposed instance first
   owns it, including a scanner that gets there before the operator. A default password has
   the same flaw for as long as nobody changes it. `createsuperuser` is Django's normal way to
   bootstrap an admin: it runs only with shell access to the server, has no race window and
   no default password. `createsuperuser --noinput` with `DJANGO_SUPERUSER_PASSWORD` covers
   scripted installs.
2. **HSTS `includeSubDomains` and `preload` stay off, and their `check --deploy` reminders
   (`security.W005`, `security.W021`) are silenced.** Both commit the whole parent domain to
   HTTPS, which an app on `attribution.example.com` must not decide for `example.com`. The
   operator can opt in with `SECURE_HSTS_INCLUDE_SUBDOMAINS` / `SECURE_HSTS_PRELOAD`.
   `SECURE_HSTS_SECONDS` defaults to 0; the guide says to start at 3600. Kept because these are
   Django's own safe defaults and HSTS mistakes are hard to undo: browsers cache the policy
   for its max-age, and preload-list removal takes months.

**Also decided:** every page needs a signed-in user (Django's `LoginRequiredMiddleware`). Only
`/v1/`, the sign-in page and `/healthz` are open. All signed-in users see all data: no roles
yet. Workspaces still share one dataset (assumption 21).

## 2026-10-29 — M4 models, lookback, influence and readiness

Decided by Claude (the coordinating session), under Christopher's standing rule for this
project: adopt the industry standard, or argue for a deviation from the docs. Research and
sources: [docs/research/m4-models.md](research/m4-models.md). Branch `claude/m4-models`.

1. **No lookback cap by default (matches Dreamdata).** Dreamdata counts "from the first
   interaction up to the stage you selected". A day-based window is now an optional model
   parameter (`ATTRIBUTION_LOOKBACK_DAYS`, for example 90, GA4's default). Every page names
   the window in use. This replaces the PRD's 90-day demo default.
   **Numbers that moved on the demo** (hand-derived in `sample_data/demo/README.md`):
   - Pipeline first-touch: opp-105 moves to tp-11 (google / cpc / q4-search) and opp-106 to
     tp-15 (google / cpc / q1-search-jp).
   - Won first-touch: opp-101 moves to tp-01 (q1-search) and opp-105 to tp-11.
   - Every multi-touch model for opp-105 (both metrics), opp-106 pipeline and opp-101 won.
   - Two fewer `TOUCHPOINT_OUTSIDE_LOOKBACK` warnings (tp-11, tp-15) on the live import.
   - The 90-day results stay in each expected file under `lookback_90`.
2. **W-shaped deferred.** Its third anchor is "the touch containing the conversion", which
   needs a lead milestone. `lead_created_at` is listed in the contract as planned, not
   implemented.
3. **Time decay kept.** Its 7-day half-life is measured back from the conversion, per GA4
   (legacy) and HockeyStack. The UI labels those sources and says that Dreamdata has no
   time-decay model. Weights are normalised so credits reconcile.
4. **Position-based with one or two touches: 100%, or 50/50.** No vendor documents these
   cases (checked Dreamdata, GA4, HockeyStack and HubSpot). They are the only splits that
   keep the total and treat first and last alike.
5. **Influenced matches Dreamdata.** A campaign counts the full amount of every opportunity it
   touched, so totals overlap and are never summed. Opportunities with no eligible touch are
   left out ("attributable deals" only). The readiness page lists them instead.
6. **PRD updated.** Position-based is in scope for M4 (PRD section 9, dated note).
7. **Journeys show every model's credit per touch**, not first-touch only.

**Also adopted from the standard:**
- First-touch, last-touch, linear and U-shaped 40/20/40, as in Dreamdata.
- Direct and `(none)` touches get credit, as in Dreamdata (GA4 excludes direct).
- Data-driven is skipped: Dreamdata's version falls back toward linear below 50 journeys, and
  its credit can't be checked by hand.
- Rounding happens at the currency's minor unit; leftover units go to the largest
  remainders, ties to the earlier touch.

**Data readiness:** seven counted checks with denominators. Each check has a fix and a way to
verify it, and shows "Not checked" with the reason when its data is missing. They map to
Dreamdata's No tracking, Unknown and attributable-deals labels.

Code: `attribution/models.py`, `attribution/influence.py`, `attribution/types.py`
(`allocate`, `describe_window`), `reports/readiness.py`. Fixtures:
`sample_data/demo/expected/models.json` and `first_touch.json`.

## 2026-10-29 — One touchpoint per session (replaces assumption 17's visit rule)

[#7](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/7)

- **Session:** a contact's web events (page, track, identify) from one browser less than 30
  minutes apart. Only inactivity (30 minutes or more) starts a new session; a new campaign or
  referrer does not.
- **One touch per session,** credited to its first page view's UTMs, or to its referrer
  (source = host, medium = `referral`) when it has none.
- **Page views inside a session** stay visible in the journey, labelled as part of the
  session started by its touch, and are never counted again.
- **Why:** this is the industry standard. Dreamdata: "Attribution is done on session level"
  ([What is a session?](https://docs.dreamdata.io/article/q8lw5qwdt8-what-is-a-session));
  GA4: sessions "aren't restarted at midnight or when new campaign parameters are
  encountered" ([Comparing metrics](https://support.google.com/analytics/answer/11986666)).
  Matching it keeps our numbers comparable with Dreamdata's. It also fixes M3 counting a
  reload of a UTM landing page as a second touch.
- **Unchanged:** stitching (16), dedup (18), clock skew (19), HTTP 200 (20), one dataset (21).

Edge cases, checked against the docs (details and quotes in `docs/contract.md`, assumption 17):
exactly 30:00 starts a new session (Dreamdata's "less than 30 minutes"; GA4 would keep it in
the session, a one-tick difference); midnight never splits a session (GA4); each browser
(`anonymousId`) has its own sessions, so two devices are two sessions (GA4; Dreamdata silent);
the stitched anonymous views and the identified views of the same browser are one session
(GA4); track and identify events keep a session alive. Known search engines are not mapped to
`organic` yet. Implemented in `contracts/touchpoints.py`; fixture in
`sample_data/events/README.md`.

## 2026-10-29 — Event identity, visits and time (M2 assumptions 16–21)

[#5](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/5)

- **Stitching (16):** an identify links the visitor's earlier `anonymousId` page views to its
  `userId` (the `contact_id`), so the visit that carried the UTMs reaches the contact.
- **Visits (17, superseded by #7 above):** only page views that start a visit (30-minute inactivity gap, new campaign
  or new referrer) or carry campaign data become touchpoints. Internal navigation does not.
- **Clock skew (19):** event time is corrected with `receivedAt − sentAt`, as RudderStack
  does. Missing `sentAt` falls back to the browser clock with a `CLOCK_SKEW_NOT_CORRECTED`
  warning.
- **Unchanged:** `sentAt` is ignored for deduplication (18), refused events get HTTP 200 (20),
  and all workspaces share one dataset (21).

Implemented in M3 (`contracts/events.py`, `contracts/touchpoints.py`). Choices made while
implementing, flagged for review: an `anonymousId` identified as two different contacts links
to nobody; only views at or before an identify are stitched; visits are per contact across
devices; exactly 30:00 is the same visit; a leading `www.` is ignored when comparing referrer
and page hosts; campaign-carrying views inside a visit still count, as the decision says.
Rules and fixture: `docs/contract.md` §3, `sample_data/events/README.md`.

## 2026-10-29 — M1 contract assumptions accepted as written

[#3](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/3)

All 15 assumptions in `docs/contract.md` §Assumptions stand: timestamps without an offset are refused, UTMs never come from URL parsing, an opportunity without a contact is fully Unattributed, `lost` is refused for now, lowercase currencies are refused, conflicting duplicate IDs refuse every copy, references resolve within one import, and the default load is partial (`--strict` refuses everything). Revisit later: account-level fallback for contactless opportunities (candidate opt-in model in M4) and the `lost` stage (needed for win-rate reporting).

## 2026-10-29 — Pipeline conversion time is the opportunity's created date

[#1](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/1)

- **Pipeline** reports measure the lookback window back from when the opportunity was **created** — they credit what generated the opportunity.
- **Won revenue** reports measure it back from when the opportunity was **won**.

The PRD did not state this; it was the M0 implementation's reading, confirmed by Christopher. Implemented in `reports/services.py`.
