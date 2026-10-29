# Events fixture (synthetic)

`batch.json` is a RudderStack `/v1/batch` body: sixteen events, all dated September 2026, which
is after every demo opportunity's conversion, so posting them does not change the demo report.
Contacts are the demo fixture's (`sample_data/demo/contacts.csv`). Expected results are written
by hand in [`expected/touchpoints.json`](expected/touchpoints.json) and checked by
`tests/test_event_touchpoints.py` and `tests/test_collection.py`.

**Receive time.** Clock-skew correction depends on when the server received each event. The
hand calculation assumes the whole batch arrives at **2026-09-03T09:00:03Z** (the tests fix
the clock there). If you post it live, the three events without a `timestamp` (`evt-07`,
`evt-11`, `evt-12`) get times near "now" instead, exactly as RudderStack would treat a replay.

```sh
uv run python manage.py create_workspace demo        # prints the write key
curl -u '<write key>:' -H 'Content-Type: application/json' \
  --data @sample_data/events/batch.json http://127.0.0.1:8000/v1/batch
```

## Validation (event contract, docs/contract.md section 3)

| # | messageId | Event | Outcome | Why |
|---|---|---|---|---|
| 1 | `evt-01` | page, anonymous (`anon-li-1`), google / cpc / fall-search | accepted | Has `anonymousId`. |
| 2 | `evt-02` | identify `anon-li-1` as `con-nw-li` | accepted | |
| 3 | `evt-03` | page `con-nw-li`, `timestamp` 10:15 **+02:00** | accepted | |
| 4 | `evt-04` | track `Demo Requested` | accepted | A funnel milestone, so no warning. |
| 5 | `evt-05` | page `con-nw-li`, empty `context.campaign` | accepted, `MISSING_CAMPAIGN_FIELDS` | |
| 6 | `evt-06` | page `con-unknown` | accepted | Valid ID; the contract does not check it against contacts. |
| 7 | `evt-07` | page `con-ke-otto`, URL in `properties.url`, **no `timestamp`** | accepted | Skew-corrected (below). |
| 8 | `evt-03` | same content as #3, different `sentAt` | duplicate, `DUPLICATE_ROW` | `sentAt` is ignored; counted once. |
| 9 | `evt-09` | page, `timestamp` `2026-09-04T10:00:00` | refused, `TIMESTAMP_WITHOUT_TIMEZONE` | No offset; not assumed UTC. |
| 10 | `evt-10` | page `con-nw-li` (second device `anon-li-2`), linkedin / paid-social / fall-abm | accepted | Same instant as `evt-05`. |
| 11 | `evt-11` | page `con-ke-otto`, no UTMs, browser clock **2 hours slow** | accepted, `MISSING_CAMPAIGN_FIELDS` | Skew-corrected (below). |
| 12 | `evt-12` | page `con-ke-otto`, no UTMs, **no `sentAt`**, referrer duckduckgo.com | accepted, `CLOCK_SKEW_NOT_CORRECTED`, `MISSING_CAMPAIGN_FIELDS` | Browser clock used as is. |
| 13 | `evt-13` | page `con-nw-li`, no UTMs, no referrer | accepted, `MISSING_CAMPAIGN_FIELDS` | |
| 14 | `evt-14` | page, anonymous (`anon-shared`), bing / cpc / fall-brand | accepted | |
| 15 | `evt-15` | identify `anon-shared` as `con-nw-ana` | accepted | |
| 16 | `evt-16` | identify `anon-shared` as `con-nw-raj` | accepted | |

Received 16 · accepted 14 · duplicates 1 · refused 1.

## Event time (clock skew, decision #5)

Events with a `timestamp` use it as is. The others use
`originalTimestamp + (receivedAt − sentAt)`, with receivedAt = 09-03 09:00:03Z:

| Event | originalTimestamp | sentAt | receivedAt − sentAt | Event time (UTC) |
|---|---|---|---|---|
| `evt-07` | 09-03 09:00:00 | 09:00:02 | +0:00:01 | **09:00:01** (M2: 09:00:00) |
| `evt-11` | 09-03 07:00:30 | 07:00:31 | +1:59:32 | **09:00:02** |
| `evt-12` | 09-03 09:10:00 | — | not computable | **09:10:00**, `CLOCK_SKEW_NOT_CORRECTED` |

Without the correction `evt-11` would sit at 07:00:30, *before* the newsletter visit, and
become Otto's first touch with `(none) / (none) / (none)`. Corrected, it is one second after
`evt-07` and is internal navigation.

## Stitching (decision #5)

| anonymousId | Identified as | Anonymous page views | Result |
|---|---|---|---|
| `anon-li-1` | `con-nw-li` (`evt-02`, 08:14) | `evt-01` at 08:10, before the identify | **Stitched** to `con-nw-li`: the landing view with the UTMs now reaches her. (M2: `ANONYMOUS`, lost.) |
| `anon-shared` | `con-nw-ana` (`evt-15`) **and** `con-nw-raj` (`evt-16`) | `evt-14` | `AMBIGUOUS_IDENTITY`: a shared browser, linked to nobody. |

## Visits (decision #5)

Per contact, in time order (ties by messageId). A view starts a visit if it is the contact's
first, comes more than 30 minutes after the previous view, carries a new campaign, or arrives
from a new external site. Visit starts and campaign-carrying views are touchpoints.

| Contact | View | Time (UTC) | Campaign / referrer host | Gap | Rule | Touchpoint? |
|---|---|---|---|---|---|---|
| `con-nw-li` | `evt-01` (stitched) | 09-02 08:10:00 | google / cpc / fall-search · google.com | — | `FIRST_VISIT` | yes |
| | `evt-03` | 08:15:00 | same campaign · google.com (same) | 5 min | `CAMPAIGN_DATA` | yes |
| | `evt-05` | 08:20:00 | none · own site | 5 min | `INTERNAL_NAVIGATION` | **no** (M2: yes) |
| | `evt-10` | 08:20:00 | linkedin / paid-social / fall-abm | 0 | `NEW_CAMPAIGN` | yes |
| | `evt-13` | 09:00:00 | none · none | 40 min | `INACTIVITY` | yes |
| `con-ke-otto` | `evt-07` | 09-03 09:00:01 | newsletter / email / sept-digest · none | — | `FIRST_VISIT` | yes |
| | `evt-11` | 09:00:02 | none · own site | 1 s | `INTERNAL_NAVIGATION` | no |
| | `evt-12` | 09:10:00 | none · duckduckgo.com (new) | 9 min 58 s | `NEW_REFERRER` | yes |

## Touchpoints (contracts/touchpoints.py)

Ordered by (time in UTC, messageId):

| Order | Touchpoint | Contact | Time (UTC) | Source / medium / campaign | Rule |
|---|---|---|---|---|---|
| 1 | `evt-01` | `con-nw-li` | 2026-09-02 08:10:00 | google / cpc / fall-search, content `ad-b`, term `revenue attribution` | `FIRST_VISIT`, stitched from `anon-li-1` |
| 2 | `evt-03` | `con-nw-li` | 2026-09-02 08:15:00 | google / cpc / fall-search (10:15+02:00 = 08:15Z) | `CAMPAIGN_DATA` |
| 3 | `evt-10` | `con-nw-li` | 2026-09-02 08:20:00 | linkedin / paid-social / fall-abm | `NEW_CAMPAIGN` |
| 4 | `evt-13` | `con-nw-li` | 2026-09-02 09:00:00 | (none) / (none) / (none) | `INACTIVITY` |
| 5 | `evt-07` | `con-ke-otto` | 2026-09-03 09:00:01 | newsletter / email / sept-digest | `FIRST_VISIT` |
| 6 | `evt-12` | `con-ke-otto` | 2026-09-03 09:10:00 | (none) / (none) / (none) | `NEW_REFERRER` |

Not touchpoints (accepted events are kept):

| Event | Reason |
|---|---|
| `evt-02`, `evt-04`, `evt-15`, `evt-16` | `NOT_A_PAGE_VIEW` (identify, track) |
| `evt-05`, `evt-11` | `INTERNAL_NAVIGATION` (shown in the contact's journey) |
| `evt-06` | `CONTACT_NOT_IMPORTED`: `con-unknown` is not in contacts.csv. |
| `evt-14` | `AMBIGUOUS_IDENTITY` |

## What moved since M2

| Number | M2 | M3 | Why |
|---|---|---|---|
| Events received / accepted | 10 / 8 | 16 / 14 | Six events added for the M3 cases (`evt-11` to `evt-16`). The original ten keep their outcomes. |
| Touchpoints from the original ten events | 4: `evt-03`, `evt-05`, `evt-10`, `evt-07` | 4: `evt-01`, `evt-03`, `evt-10`, `evt-07` | `evt-01` is now stitched (16); `evt-05` is now internal navigation (17). |
| `con-nw-li`'s first touch | `evt-03` at 08:15 | `evt-01` at 08:10 | The stitched landing view is earlier. Same campaign, so a first-touch credit would not change campaign. |
| `evt-07` event time | 09:00:00 | 09:00:01 | Skew-corrected by receivedAt − sentAt = 1 s (19). |
| Touchpoints in total | 4 | 6 | Plus `evt-13` (inactivity) and `evt-12` (new referrer). |

The demo report (`sample_data/demo/expected/first_touch.json`) does not move: its touchpoints
come from touchpoints.csv, which the visit rules don't touch, and every event is dated after
every demo conversion.
