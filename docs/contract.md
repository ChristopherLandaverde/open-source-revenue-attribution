# Data contract (v1)

What data the product accepts, and what it refuses. Derived from [the PRD](prd.md) sections
5–7. Where the PRD is silent the conservative choice was taken; each one is listed under
[Assumptions](#assumptions) for review.

The contract is enforced in code by the pure-Python `contracts/` package
(`validate_import` for CSV imports, `validate_events` for RudderStack payloads). Nothing is
loaded unless the validator accepts it. Reason codes are a fixed enum: new codes may be added;
existing codes are never renamed or repurposed.

## 1. General rules (all files and events)

| Rule | Detail |
|---|---|
| Encoding | UTF-8 CSV (a BOM is tolerated), comma-separated, RFC 4180 quoting, one header row. |
| Header | Column names are exact and lowercase. Column order does not matter. |
| Blank values | Every cell is trimmed of surrounding whitespace; an empty cell means "missing". |
| Row numbers | Reports count the header as row 1, so the first data row is row 2. |
| IDs | 1–64 characters from `A-Z a-z 0-9 . _ : -`. Case-sensitive. Stable: the same record keeps the same ID across imports. Refused otherwise (`INVALID_ID`). |
| Timestamps | ISO 8601 with a time and an explicit UTC offset: `2026-04-01T12:00:00Z` or `2026-04-01T08:00:00-04:00`. Converted to UTC for storage and every comparison. A timestamp without an offset is refused (`TIMESTAMP_WITHOUT_TIMEZONE`), never assumed to be UTC; a date without a time is refused the same way. |
| Text limits | Names, domains and UTM values ≤ 200 characters; landing page and referrer ≤ 500; email ≤ 254 (`VALUE_TOO_LONG`). |
| Unknown columns | Ignored, with an `UNKNOWN_COLUMN` warning so a misspelt column is visible. |
| Missing column / file | A missing required column refuses the whole file (`MISSING_COLUMN`); a missing file is `MISSING_FILE`. Rows that reference a refused file's records are then refused too. A header-only file is valid and empty. |
| Duplicates | An exact repeat of an earlier row is counted once (`DUPLICATE_ROW` warning). The same ID with different content refuses **every** copy (`DUPLICATE_ID`): the validator can't tell which is right. |
| References | Resolve within one import, against rows that were **accepted**. A row pointing at a refused or absent parent is refused (`UNKNOWN_ACCOUNT`, `UNKNOWN_CONTACT`), so rejections cascade. Account matches are never inferred from names, domains or emails. |
| Personal data | The only person-identifying fields are IDs and the optional contact email. Fixtures and screenshots use synthetic `*.example` data. |

## 2. CSV import files

Validated in this order (parents first): `accounts.csv`, `contacts.csv`, `opportunities.csv`,
`touchpoints.csv`. Load with `uv run python manage.py load_sample_data --path <dir>`.

### accounts.csv

| Column | Required | Type | Rules |
|---|---|---|---|
| `account_id` | yes | ID | Unique. |
| `name` | no | text | Display only. |
| `domain` | no | text | Display only; never used to match contacts. |

### contacts.csv

| Column | Required | Type | Rules |
|---|---|---|---|
| `contact_id` | yes | ID | Unique. This is the `userId` that identify events must send. |
| `account_id` | yes | ID | Must be an accepted account. Every contact belongs to exactly one account. |
| `email` | no | email | `name@domain.tld` shape (`INVALID_EMAIL`). |

### opportunities.csv

| Column | Required | Type | Rules |
|---|---|---|---|
| `opportunity_id` | yes | ID | Unique. |
| `account_id` | yes | ID | Must be an accepted account. Accounts own opportunities. |
| `contact_id` | no | ID | The opportunity's contact. If set, must be an accepted contact **of the same account** (`CONTACT_ACCOUNT_MISMATCH`). If blank, accepted with `OPPORTUNITY_WITHOUT_CONTACT`: it has no touchpoints, so every model gives it to Unattributed. |
| `name` | no | text | Display only; the ID is shown when blank. |
| `amount` | yes | decimal | See [money](#money-and-currency). For a won opportunity this is the won value. |
| `currency` | yes | ISO 4217 | See [money](#money-and-currency). |
| `stage` | yes | `open` \| `won` | Anything else is refused (`INVALID_STAGE`). |
| `created_at` | yes | timestamp | Pipeline conversion time. |
| `won_at` | if won | timestamp | Required when `stage` is `won` (`WON_AT_REQUIRED`), must be blank when `open` (`WON_AT_NOT_ALLOWED`), not before `created_at` (`WON_BEFORE_CREATED`). Won-revenue conversion time. |

### touchpoints.csv

A touchpoint is a marketing touch (typically a landing-page visit) by a known contact.

| Column | Required | Type | Rules |
|---|---|---|---|
| `touchpoint_id` | yes | ID | Unique. |
| `contact_id` | yes | ID | Must be an accepted contact. |
| `occurred_at` | yes | timestamp | When the touch happened. |
| `utm_source` | no | text | Blank is kept blank and shown as `(none)`. Any of source/medium/campaign blank → `MISSING_CAMPAIGN_FIELDS` warning. |
| `utm_medium` | no | text | As above. |
| `utm_campaign` | no | text | As above. |
| `utm_content` | no | text | Stored; not part of the campaign key. |
| `utm_term` | no | text | Stored; not part of the campaign key. |
| `landing_page` | no | text | Path or URL. |
| `referrer` | no | text | URL. Never used to fill in missing UTMs. |

The campaign key reports group by is `utm_source / utm_medium / utm_campaign`, values taken
verbatim (case-sensitive), with `(none)` for a blank part.

### Money and currency

- `amount` is a plain non-negative decimal with `.` as the decimal point: `24000.00`,
  `1200000`. No currency symbols, thousands separators, signs or exponents
  (`INVALID_AMOUNT`). Maximum 999,999,999,999.99.
- It may not have more decimal places than the currency's minor unit (`AMOUNT_PRECISION`):
  `10.005 USD` and `1500.5 JPY` are refused; trailing zeros (`1500.00 JPY`) are fine.
- `0` is accepted with a `ZERO_AMOUNT` warning.
- `currency` is an uppercase ISO 4217 code from the supported list (`INVALID_CURRENCY`):
  AUD BRL CAD CHF CNY DKK EUR GBP HKD INR JPY KRW MXN NOK NZD PLN SEK SGD USD ZAR.
  Currencies with three minor-unit digits (KWD, BHD, …) are not supported yet.
- Amounts in different currencies are never added together. Reports group totals by
  currency (PRD §6) until conversion rates with effective dates exist.

### How the records link

```
account 1──* contact 1──* touchpoint
   1                1
   └──* opportunity *┘ (contact optional, same account)
```

Attribution is per opportunity and uses the touchpoints of **the opportunity's contact**
(PRD §6). Other contacts at the same account, and account-level activity, are not credited in
v1. The opportunity journey lists the account's other contacts as not credited; a combined
account journey with drill-down (PRD) is not built yet.

## 3. Events (RudderStack)

Events arrive from the RudderStack JavaScript SDK (`static/vendor/`) or any client that speaks
RudderStack's HTTP API (see [Collection](#collection-endpoint)). This section fixes what an
event must carry to be accepted. Field names are RudderStack's.

| Field | page | track | identify | Rule |
|---|---|---|---|---|
| `type` | `page` | `track` | `identify` | Other types (screen, group, alias) are refused (`UNSUPPORTED_EVENT_TYPE`). |
| `messageId` | required | required | required | The event ID and deduplication key. Same ID rules as imports. |
| `anonymousId` / `userId` | one of them | one of them | `userId` required | Neither → `MISSING_IDENTITY`. `userId` is a `contact_id` and must be a valid ID. |
| `event` | — | required | — | The track event name. |
| `context.page.url` (or `properties.url`) | required | optional | — | Page URL. |
| `context.page.referrer` (or `properties.referrer`) | optional | optional | — | Kept as-is. |
| `timestamp` (else `originalTimestamp`) | required | required | required | Must carry a UTC offset. |
| `context.campaign.source/medium/name/content/term` | optional | optional | — | Mapped to `utm_source/utm_medium/utm_campaign/utm_content/utm_term`. A page event with any of the first three blank gets `MISSING_CAMPAIGN_FIELDS`. |

- **Event time** ([decision #5](decisions.md)), in order of preference:
  1. `timestamp`, when sent: a RudderStack server already corrected it. Used as is.
  2. Otherwise `originalTimestamp + (receivedAt − sentAt)`, RudderStack's own rule:
     `receivedAt` is when this server received the request, so `receivedAt − sentAt` is the
     browser clock's error (plus network latency, as in RudderStack).
  3. Otherwise (no `sentAt`, `sentAt` without a UTC offset or not ISO 8601, or no receive
     time) `originalTimestamp` as the browser sent it, with a `CLOCK_SKEW_NOT_CORRECTED`
     warning. A bad `sentAt` never refuses an event: it is transport metadata.

  `originalTimestamp` and `sentAt` are preserved verbatim; the stored event records which of
  the three rules gave its time (`time_source`). A retry keeps the first delivery's time.
- **Campaign values** come only from `context.campaign`, which the SDK fills from the landing
  URL's UTM parameters. They are not re-parsed from the URL or guessed from the referrer.
- **Funnel milestones** are the track names `Demo Requested`, `Lead Qualified`,
  `Opportunity Created`, `Opportunity Won`. Other track names are accepted with
  `UNKNOWN_EVENT_NAME` and are not milestones.
- **Identity:** browsing is anonymous (`anonymousId` only) until an identify event sends
  `userId` = `contact_id`. The identify then links that browser's **earlier** anonymous page
  views to the contact (see [From events to touchpoints](#from-events-to-touchpoints)).
  Nothing else links anonymous activity to a contact.
- **Retries:** a repeat of an already-accepted `messageId` with identical content is counted
  once (`DUPLICATE_ROW`), whether it arrives in the same request or a later one. The same
  `messageId` with different content is refused (`DUPLICATE_ID`); the first accepted event
  stands. "Identical" ignores the top-level `sentAt`, which the SDK rewrites on every delivery
  attempt.
- **Text limits** from the general rules apply: `context.campaign` values ≤ 200 characters,
  page URL and referrer ≤ 500 (`VALUE_TOO_LONG`).
- **Browser time:** the browser SDK sends `originalTimestamp` (the visitor's clock) and
  `sentAt`, not `timestamp`; RudderStack's server normally adds `timestamp`. Events collected
  directly from the SDK are therefore skew-corrected here (rule 2 above).

### Collection endpoint

| | |
|---|---|
| Paths | `POST /v1/batch` with `{"batch": [event, ...]}` (at most `COLLECT_MAX_BATCH`, default 500), or `POST /v1/page`, `/v1/track`, `/v1/identify` with one event. The event's own `type` decides; the path does not. |
| Auth | `Authorization: Basic base64(<write key>:)`, as the SDK sends it. A write key belongs to a workspace (`manage.py create_workspace`). Write keys are visible in browser code; they identify the sender, they are not secrets. |
| Response | `200` with counts and one outcome per event in order: `accepted`, `duplicate` or `rejected`, with its codes. `401` missing or unknown key, `400` body is not a JSON object/batch, `413` too many events. Refused events still get `200`: the SDK does not retry 4xx, and a refused event will not become valid by retrying. |
| Storage | Every distinct payload is stored verbatim with its outcome (`collection.CollectedEvent`). Accepted events are unique by `messageId`; refused payloads by content. Exact repeats increment a counter, so replaying the same data never adds rows. |
| Scope | All workspaces write to one dataset (no per-workspace isolation), and `messageId` is unique across it. Same-origin only: no CORS headers yet. |

### From events to touchpoints

`contracts/touchpoints.py` turns accepted events into touchpoints, deterministically, in three
steps ([decision #5](decisions.md)).

**1. Whose page view is it?**

| Page view | Contact |
|---|---|
| carries `userId` | That `userId`. |
| anonymous, and an identify with the same `anonymousId` happens **at or after** it | The identify's `userId` (*stitched*; the touchpoint records the `anonymousId`). This is how the landing visit that carried the UTMs reaches the contact. |
| anonymous, with no identify of its `anonymousId` at or after it | Nobody (`ANONYMOUS`). |
| anonymous, and its `anonymousId` was identified as **two or more different** contacts | Nobody (`AMBIGUOUS_IDENTITY`): a shared browser; we can't tell whose visit it was. |
| its contact is not an imported `contact_id` | Nobody yet (`CONTACT_NOT_IMPORTED`). It converts after the import that adds the contact. |

Only identify events link an `anonymousId` to a contact, and only backwards in time.

**2. Visits.** Each contact's page views (identified and stitched, across devices) are taken
in time order, ties by `messageId`. A page view **starts a visit** when:

| Rule | Code |
|---|---|
| it is the contact's first page view | `FIRST_VISIT` |
| more than 30 minutes passed since the contact's previous page view (exactly 30:00 is the same visit) | `INACTIVITY` |
| it carries campaign data (`utm_source`, `utm_medium` or `utm_campaign`) different from the current visit's | `NEW_CAMPAIGN` |
| it arrives from another site: the referrer's host differs from the page's host (a leading `www.` is ignored) and from the referrer host that opened the current visit | `NEW_REFERRER` |

Track and identify events do not extend a visit. A reload keeps the same referrer, so it does
not start a visit.

**3. Touchpoints.** A page view is a touchpoint when it starts a visit, or when it carries
campaign data inside the current visit (`CAMPAIGN_DATA`). Every other page view is internal
navigation (`INTERNAL_NAVIGATION`): kept and shown in the journey, never credited.

| Event | Becomes |
|---|---|
| `page` that passes 1–3 | One touchpoint. ID = `messageId`, time = event time, UTMs from `context.campaign` (blank stays blank), `landing_page` = page URL, `referrer` as sent, plus `stitched_from` and `visit_rule`. |
| `page` that fails 1 or 3 | Nothing, with the reason code above. |
| `track`, `identify` | Nothing (`NOT_A_PAGE_VIEW`). Kept for the funnel. |

Touchpoints from events are stored with `origin = event` next to CSV touchpoints. They are
recomputed from every accepted event after each collection request and each import, because a
later identify or page view can change earlier decisions; page views that no longer qualify
lose their touchpoint. CSV touchpoints are counted as given: the visit rules apply to events
only. The hand-calculated fixture is `sample_data/events/`.

### Journeys

Each opportunity has a journey (`attribution/journey.py`, page `/opportunities/<id>/journey/`):
every touchpoint of **the opportunity's contact** (never other contacts at the account), in
the order `(occurred_at, touchpoint ID)`, with equal pairs kept in a fixed source order (CSV
before event). Each touch is `eligible`, `before_window` or `after_conversion` under the rule in
section 5, and carries the credit the named model gives it; the contact's internal-navigation
page views are listed as not touchpoints. Credits plus Unattributed equal the amount.

## 4. Validation report

The CSV import runs the same way from `load_sample_data` and from the **Import CSV** page
(`/import/`): partial by default, strict on request.

`validate_import` returns, per file: rows received, accepted, refused and exact duplicates
ignored; the list of refused rows, each with **all** its reasons (code, field, message);
file-level errors; and warnings. Accepted rows are typed records with timestamps in UTC and
amounts as `Decimal`. `load_sample_data` loads only accepted rows, prints every refused row,
and stores the report (as an `ImportRun`) for the **Data validation** page at `/validation/`.
With `--strict` any refusal refuses the whole import and nothing is loaded.

### Reason codes: refused

| Code | Meaning |
|---|---|
| `MISSING_FILE` | A required import file is absent. |
| `MISSING_COLUMN` | A required column is absent; the whole file is refused. |
| `MISSING_REQUIRED_FIELD` | A required value is blank. |
| `INVALID_ID` | An ID is not 1–64 characters of `A-Z a-z 0-9 . _ : -`. |
| `DUPLICATE_ID` | The same ID appears with different content. |
| `INVALID_TIMESTAMP` | A timestamp is not ISO 8601. |
| `TIMESTAMP_WITHOUT_TIMEZONE` | A timestamp has no UTC offset. |
| `INVALID_AMOUNT` | An amount is not a plain non-negative decimal. |
| `AMOUNT_PRECISION` | An amount has more decimal places than its currency's minor unit. |
| `INVALID_CURRENCY` | A currency is not a supported uppercase ISO 4217 code. |
| `INVALID_STAGE` | An opportunity stage is not `open` or `won`. |
| `WON_AT_REQUIRED` | A won opportunity has no `won_at`. |
| `WON_AT_NOT_ALLOWED` | An open opportunity has a `won_at`. |
| `WON_BEFORE_CREATED` | `won_at` is earlier than `created_at`. |
| `UNKNOWN_ACCOUNT` | `account_id` does not match an accepted account. |
| `UNKNOWN_CONTACT` | `contact_id` does not match an accepted contact. |
| `CONTACT_ACCOUNT_MISMATCH` | The opportunity's contact belongs to a different account. |
| `VALUE_TOO_LONG` | A text value is longer than its column allows. |
| `INVALID_EMAIL` | An email is not of the form `name@domain`. |
| `UNSUPPORTED_EVENT_TYPE` | An event type is not page, track or identify. |
| `MISSING_IDENTITY` | An event has neither `anonymousId` nor `userId`. |

### Reason codes: warnings (accepted and loaded)

| Code | Meaning |
|---|---|
| `UNKNOWN_COLUMN` | A column is not in the contract and was ignored. |
| `DUPLICATE_ROW` | An exact repeat of an earlier row or event; counted once. |
| `MISSING_CAMPAIGN_FIELDS` | `utm_source`, `utm_medium` or `utm_campaign` is blank; shown as `(none)`. |
| `TOUCHPOINT_OUTSIDE_LOOKBACK` | The touchpoint is outside every lookback window (pipeline and won) of its contact's opportunities, or the contact has no opportunities, so no model can credit it. |
| `OPPORTUNITY_WITHOUT_CONTACT` | No contact, so no touchpoints: the full amount is Unattributed. |
| `ZERO_AMOUNT` | The opportunity amount is 0. |
| `UNKNOWN_EVENT_NAME` | A track event name is not a funnel milestone. |
| `CLOCK_SKEW_NOT_CORRECTED` | No usable `sentAt` or receive time, so the event time is the browser clock (`originalTimestamp`), not corrected for skew. |

## 5. How the contract feeds attribution

- One conversion per opportunity per metric: **pipeline** at `created_at`, **won revenue** at
  `won_at` for won opportunities only ([decisions](decisions.md)).
- Eligible touchpoints: the opportunity contact's touchpoints with
  `conversion − lookback ≤ occurred_at ≤ conversion`, both ends inclusive, compared in UTC.
  Lookback defaults to 90 days (`ATTRIBUTION_LOOKBACK_DAYS`).
- Same-instant touchpoints are ordered by touchpoint ID.
- No eligible touchpoints → the whole amount goes to `Unattributed`.

## Assumptions

Choices the PRD does not make, taken conservatively. Each is a candidate for
[decisions.md](decisions.md) once reviewed.

1. **Timestamps without an offset are refused**, not assumed to be UTC; date-only values are
   refused too. A wrong guess would silently move touches in or out of a window.
2. **Event time is RudderStack `timestamp`** (skew-corrected), not the raw client
   `originalTimestamp`, which is still preserved. Client clocks can be off by days.
3. **UTMs come only from `context.campaign`** (events) or the UTM columns (CSV). Never parsed
   from a URL, inferred from the referrer, or defaulted to "direct".
4. **Every contact needs an `account_id`.** No unlinked contacts are imported (SWOT:
   "Require imported account IDs for the demo").
5. **Opportunities belong to an account and have at most one contact, which is optional.** An
   opportunity without a contact is accepted and fully Unattributed; it does not borrow the
   touchpoints of other contacts at its account.
6. **A contact/account mismatch on an opportunity is refused**, not corrected either way.
7. **Stages are `open` and `won` only.** `lost` and custom stages are refused until stage
   history is designed (M3). The single `amount` is the won value for won opportunities.
8. **Money is strict:** plain decimals only, no more places than the currency allows,
   uppercase codes from a fixed list; `usd` is refused rather than upper-cased. Zero amounts
   are allowed with a warning.
9. **Conflicting duplicate IDs refuse every copy** in an import; exact duplicates count once.
   For events, the first accepted `messageId` stands and a conflicting later one is refused
   (an accepted event can't be withdrawn from a stream).
10. **References resolve within one import.** A contact can't point at an account loaded by an
    earlier import. Re-importing upserts by ID; records missing from a later import are not
    deleted.
11. **Unknown columns are warned and ignored**, not refused; a missing required column refuses
    the file.
12. **The default load is partial** (accepted rows load, refused rows are listed); `--strict`
    refuses everything on any error.
13. **Track names outside the four milestones are accepted** with a warning, not refused.
14. **`TOUCHPOINT_OUTSIDE_LOOKBACK` checks both the pipeline and the won window**, using the
    configured lookback.
15. **Supported currencies** are the 20 listed above (all with 0 or 2 minor-unit digits, to fit
    the current amount column).

### M2 assumptions

Taken during M2 where the contract was silent, then decided by Christopher in
[#5](decisions.md) (2026-10-29).

16. **Decided: an identify stitches earlier anonymous page views** with the same
    `anonymousId` to its contact, so the landing visit that carried the UTMs reaches the
    contact. *M3 implementation choices:* only identify events link; only views at or before
    the identify; an `anonymousId` identified as more than one contact links to nobody.
17. **Decided: only page views that start a visit, or carry campaign data, are touchpoints.**
    Internal navigation is not. *M3 implementation choices:* visits are per contact; a new
    visit after more than 30 minutes of inactivity, a new campaign or a new external referrer
    host; campaign-carrying views inside a visit still count.
18. **Decided: `sentAt` is transport metadata**, ignored when deciding whether a repeat is a
    retry.
19. **Decided: browser events are corrected for clock skew** with
    `originalTimestamp + (receivedAt − sentAt)`, as RudderStack does. Without a usable
    `sentAt` the browser clock is used, with a `CLOCK_SKEW_NOT_CORRECTED` warning.
20. **Decided: refused events get HTTP 200** with per-event outcomes, not 4xx, so one bad event
    does not fail a batch.
21. **Decided: one dataset for all workspaces**; `messageId` deduplication is global.

## Not in v1

Linking anonymous history by anything other than identify (no fingerprinting, no
probabilistic matching), a combined account journey, CORS for cross-site collection,
per-workspace data isolation, account-level touchpoints, stage history and `lost`/custom stages, currency conversion, import provenance beyond the `ImportRun` record,
and deleting records that disappear from a re-import.
