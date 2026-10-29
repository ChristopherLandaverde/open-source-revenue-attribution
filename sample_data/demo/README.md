# Demo fixture (synthetic)

Four CSV files in the canonical import contract ([docs/contract.md](../../docs/contract.md)),
with hand-calculated expected outputs in [`expected/`](expected/). All names and emails are
invented and use `*.example` domains.

```sh
uv run python manage.py load_sample_data          # validates, loads accepted rows, lists refused ones
uv run python manage.py load_sample_data --strict # refuses the whole import (this fixture has bad rows on purpose)
```

`tests/test_demo_fixture.py` asserts that the validator reproduces `expected/validation.json`
and the first-touch model reproduces `expected/first_touch.json` exactly.

## What it covers

| Case | Where |
|---|---|
| Multi-contact account (3 contacts, 2 with opportunities, 1 with touches only) | `acc-northwind`: ana, raj, li |
| Pipeline and won credit going to different touchpoints | `opp-101` |
| Two touchpoints at the same instant (tie broken by touchpoint ID) | `tp-07` / `tp-08`, listed out of ID order |
| Touchpoints after the conversion, before the window, and in no window | `tp-05`, `tp-11`, `tp-15` |
| Inclusive 90-day boundary that only works if UTC offsets are honoured | `tp-14` (in), `tp-15` (out by 1 minute) |
| Missing UTMs (all three, and partial) | `tp-09`, `tp-13` (all); `tp-12` (medium, campaign) |
| Opportunity with no contact → Unattributed | `opp-104` |
| Three currencies, never summed together; a zero-decimal currency | USD, EUR (`18500.50`), JPY (`1200000`) |
| Timestamps with non-UTC offsets | `opp-105` (+02:00), `tp-09` (+02:00), `tp-12` (+01:00), `tp-14`/`tp-15` (+09:00) |
| Exact duplicate row (counted once) | `con-nw-raj` repeated, `contacts.csv` row 9 |
| Deliberately invalid rows, one per reason | see "Validation" below |

## Validation (expected/validation.json)

Rows count the header as row 1. Lookback is 90 days.

**Refused (10 rows, never loaded):**

| File, row | ID | Code | Why |
|---|---|---|---|
| accounts 6 | `acc beta` | `INVALID_ID` | IDs cannot contain spaces. |
| contacts 10 | `con-ghost` | `UNKNOWN_ACCOUNT` | `acc-missing` is not in accounts.csv. |
| opportunities 8 | `opp-107` | `AMOUNT_PRECISION` | `1500.5` JPY: yen has no minor unit. |
| opportunities 9 | `opp-108` | `WON_AT_REQUIRED` | Stage `won` with a blank `won_at`. |
| opportunities 10 | `opp-109` | `CONTACT_ACCOUNT_MISMATCH` | `con-um-sam` belongs to `acc-umbra`, opportunity says `acc-northwind`. |
| opportunities 11 | `opp-110` | `INVALID_CURRENCY` | `usd` must be uppercase. |
| touchpoints 17 | `tp-16` | `TIMESTAMP_WITHOUT_TIMEZONE` | `2026-03-01T10:00:00` has no offset; it is not assumed to be UTC. |
| touchpoints 18 | `tp-17` | `UNKNOWN_CONTACT` | `con-ghost` was itself refused, so the reference cascades. |
| touchpoints 19, 20 | `tp-18` ×2 | `DUPLICATE_ID` | Same ID, different `utm_source`: we can't tell which is right, so both are refused. |

**Accepted with warnings (10):**

| File, row | ID | Code | Why |
|---|---|---|---|
| contacts 9 | `con-nw-raj` | `DUPLICATE_ROW` | Exact repeat of row 3; counted once. |
| opportunities 5 | `opp-104` | `OPPORTUNITY_WITHOUT_CONTACT` | No contact, so no touchpoints, so fully Unattributed. |
| touchpoints 6 | `tp-05` | `TOUCHPOINT_OUTSIDE_LOOKBACK` | 05-25 is after `opp-102` was created (05-20) and `opp-102` is not won. |
| touchpoints 7 | `tp-06` | `TOUCHPOINT_OUTSIDE_LOOKBACK` | `con-nw-li` has no opportunities. |
| touchpoints 10 | `tp-09` | `MISSING_CAMPAIGN_FIELDS` | No UTMs at all. |
| touchpoints 11 | `tp-10` | `TOUCHPOINT_OUTSIDE_LOOKBACK` | `con-um-sam` has no accepted opportunities (`opp-109` was refused). |
| touchpoints 12 | `tp-11` | `TOUCHPOINT_OUTSIDE_LOOKBACK` | 2025-12-01 is before both `opp-105` windows (from 01-20 and 04-02). |
| touchpoints 13 | `tp-12` | `MISSING_CAMPAIGN_FIELDS` | Only `utm_source` set. |
| touchpoints 14 | `tp-13` | `MISSING_CAMPAIGN_FIELDS` | No UTMs at all. |
| touchpoints 16 | `tp-15` | `TOUCHPOINT_OUTSIDE_LOOKBACK` | 02-03T14:59Z is one minute before the `opp-106` window opens. |

**Counts:** accounts 5 received / 4 accepted / 1 refused · contacts 9 / 7 / 1 (+1 duplicate)
· opportunities 10 / 6 / 4 · touchpoints 19 / 15 / 4.

## First-touch results (expected/first_touch.json)

Window = `[conversion − 90 days, conversion]`, both ends inclusive, all times converted to UTC.
Pipeline converts at `created_at`, won revenue at `won_at` ([decisions](../../docs/decisions.md)).
Ties on time go to the lower touchpoint ID.

| Opp | Contact's accepted touches (UTC) | Pipeline: window → first | Won: window → first |
|---|---|---|---|
| opp-101, 24,000.00 USD | tp-01 02-10, tp-02 03-05, tp-03 05-10 | created 04-01 12:00, from 01-01 12:00: tp-01, tp-02 → **tp-01 google / cpc / q1-search** | won 06-15 12:00, from 03-17 12:00: only tp-03 → **tp-03 partner / referral / may-webinar** |
| opp-102, 6,000.00 USD, open | tp-04 04-28, tp-05 05-25 | created 05-20 12:00, from 02-19: tp-04 (tp-05 is after) → **tp-04 newsletter / email / april-digest** | not won |
| opp-103, 15,000.00 USD | tp-08 02-20 08:30, tp-07 02-20 08:30, tp-09 04-02 10:00 | created 03-10 09:00, from 2025-12-10: tp-07, tp-08 tie → **tp-07 google / cpc / q1-search** | won 05-01 09:00, from 01-31: tp-07, tp-08, tp-09 → tie again → **tp-07** |
| opp-104, 9,000.00 USD, open | none (no contact) | **Unattributed** | not won |
| opp-105, 18,500.50 EUR | tp-11 2025-12-01, tp-12 03-15 10:00, tp-13 05-20 | created 04-20 10:00, from 01-20 10:00: tp-12 → **tp-12 linkedin / (none) / (none)** | won 07-01 10:00, from 04-02 10:00: tp-13 → **tp-13 (none) / (none) / (none)** |
| opp-106, 1,200,000 JPY, open | tp-15 02-03 14:59, tp-14 02-03 15:00 | created 05-04 15:00, from 02-03 15:00 exactly: tp-14 in, tp-15 out → **tp-14 event / trade-show / robotics-expo** | not won |

Read naively (offsets dropped, local time treated as UTC), `tp-15` would be 02-03 23:59 and
win `opp-106` instead: the fixture fails if timezones are mishandled.

**Pipeline totals by currency** (never summed across currencies):

- USD: google / cpc / q1-search 39,000.00 (opp-101 24,000 + opp-103 15,000) · Unattributed 9,000.00 · newsletter / email / april-digest 6,000.00 — **54,000.00** = 24,000 + 6,000 + 15,000 + 9,000.
- EUR: linkedin / (none) / (none) **18,500.50**.
- JPY: event / trade-show / robotics-expo **1,200,000**.

**Won totals:**

- USD: partner / referral / may-webinar 24,000.00 · google / cpc / q1-search 15,000.00 — **39,000.00**.
- EUR: (none) / (none) / (none) **18,500.50**.

Every opportunity's credits sum to its amount (first-touch gives the whole amount to one
touchpoint or to Unattributed), so totals reconcile with no rounding.
