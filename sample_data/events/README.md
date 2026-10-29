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
`evt-07` and is a later page view of `evt-07`'s session.

## Stitching (decision #5)

| anonymousId | Identified as | Anonymous page views | Result |
|---|---|---|---|
| `anon-li-1` | `con-nw-li` (`evt-02`, 08:14) | `evt-01` at 08:10, before the identify | **Stitched** to `con-nw-li`: the landing view with the UTMs now reaches her. (M2: `ANONYMOUS`, lost.) |
| `anon-shared` | `con-nw-ana` (`evt-15`) **and** `con-nw-raj` (`evt-16`) | `evt-14` | `AMBIGUOUS_IDENTITY`: a shared browser, linked to nobody. |

## Sessions (decision #7)

Per contact **and browser** (`anonymousId`), all of the contact's events (page, track,
identify) in time order, ties by messageId. An event less than 30 minutes after the browser's
previous event stays in the session; 30 minutes or more starts a new one. A new campaign or
referrer does not. Each session is one touchpoint: its first page view.

| Contact · browser | Event | Time (UTC) | Type · campaign / referrer host | Gap to previous event | Session | Touchpoint? |
|---|---|---|---|---|---|---|
| `con-nw-li` · `anon-li-1` | `evt-01` (stitched) | 09-02 08:10:00 | page · google / cpc / fall-search · google.com | — | **S1** starts | **yes**, `FIRST_SESSION` |
| | `evt-02` | 08:14:00 | identify | 4 min | S1 | — (not a page view) |
| | `evt-03` | 08:15:00 | page · same campaign · google.com | 1 min | S1 | no, `SAME_SESSION` (M3: yes, `CAMPAIGN_DATA`) |
| | `evt-04` | 08:18:00 | track `Demo Requested` | 3 min | S1 | — (not a page view) |
| | `evt-05` | 08:20:00 | page · none · own site | 2 min | S1 | no, `SAME_SESSION` |
| | `evt-13` | 09:00:00 | page · none · none | 40 min (≥ 30) | **S3** starts | **yes**, `INACTIVITY` |
| `con-nw-li` · `anon-li-2` | `evt-10` | 09-02 08:20:00 | page · linkedin / paid-social / fall-abm | — (first event of this browser) | **S2** starts | **yes**, `NEW_DEVICE` (M3: `NEW_CAMPAIGN`) |
| `con-ke-otto` · `anon-otto-1` | `evt-07` | 09-03 09:00:01 | page · newsletter / email / sept-digest · none | — | **S1** starts | **yes**, `FIRST_SESSION` |
| | `evt-11` | 09:00:02 | page · none · own site | 1 s | S1 | no, `SAME_SESSION` |
| | `evt-12` | 09:10:00 | page · none · duckduckgo.com | 9 min 58 s (< 30) | S1 | no, `SAME_SESSION` (M3: yes, `NEW_REFERRER`) |

Li's sessions in order of start: S1 08:10 (`anon-li-1`, her first: `FIRST_SESSION`), S2 08:20
(`anon-li-2`, a browser not seen before: `NEW_DEVICE`), S3 09:00 (`anon-li-1` again after
40 minutes: `INACTIVITY`). S2 overlaps S1 in time but is a separate session because it is
another browser (GA4 scopes sessions per browser). No session's first page view lacks UTMs
while having an external referrer, so the referral rule does not fire here: `evt-13` has
neither and stays `(none) / (none) / (none)`.

## Touchpoints (contracts/touchpoints.py)

Ordered by (time in UTC, messageId). `session_id` = the touchpoint's own messageId:

| Order | Touchpoint | Contact | Time (UTC) | Source / medium / campaign | Rule |
|---|---|---|---|---|---|
| 1 | `evt-01` | `con-nw-li` | 2026-09-02 08:10:00 | google / cpc / fall-search, content `ad-b`, term `revenue attribution` | `FIRST_SESSION`, stitched from `anon-li-1` |
| 2 | `evt-10` | `con-nw-li` | 2026-09-02 08:20:00 | linkedin / paid-social / fall-abm | `NEW_DEVICE` |
| 3 | `evt-13` | `con-nw-li` | 2026-09-02 09:00:00 | (none) / (none) / (none) | `INACTIVITY` |
| 4 | `evt-07` | `con-ke-otto` | 2026-09-03 09:00:01 | newsletter / email / sept-digest | `FIRST_SESSION` |

Page views inside a session (`session_views`, shown in the journey, never counted):

| Page view | In the session started by |
|---|---|
| `evt-03` (08:15), `evt-05` (08:20) | `evt-01` |
| `evt-11` (09:00:02), `evt-12` (09:10) | `evt-07` |

Not touchpoints (accepted events are kept), in event order:

| Event | Reason |
|---|---|
| `evt-02`, `evt-04`, `evt-15`, `evt-16` | `NOT_A_PAGE_VIEW` (identify, track) |
| `evt-03`, `evt-05`, `evt-11`, `evt-12` | `SAME_SESSION` |
| `evt-06` | `CONTACT_NOT_IMPORTED`: `con-unknown` is not in contacts.csv. |
| `evt-14` | `AMBIGUOUS_IDENTITY` |

## What moved with decision #7 (sessions)

| Number | M3 | #7 | Why |
|---|---|---|---|
| Touchpoints in total | 6 | **4** | One per session. |
| `evt-03` | touchpoint, `CAMPAIGN_DATA` | in session `evt-01` | Same browser 5 min after `evt-01`; carrying the same campaign no longer counts it again. |
| `evt-12` | touchpoint, `NEW_REFERRER` | in session `evt-07` | 9 min 58 s after `evt-11`; a new referrer no longer splits a session. |
| `evt-10` rule | `NEW_CAMPAIGN` | `NEW_DEVICE` | Still a touchpoint, now because it is another browser (`anon-li-2`), not because of its campaign. |
| `evt-01`, `evt-07` rule | `FIRST_VISIT` | `FIRST_SESSION` | Renamed; same touchpoint. |
| `evt-13` | `INACTIVITY` | `INACTIVITY` | 40 min after `evt-05` on the same browser. |
| `evt-05`, `evt-11` | `INTERNAL_NAVIGATION` | `SAME_SESSION` | Renamed reason; still not touchpoints. |
| Validation, event times, stitching | — | unchanged | Decisions 16, 18, 19 are untouched. |

First-touch credit for any of these contacts would not move: each contact's earliest touch
(`evt-01`, `evt-07`) is unchanged. A multi-touch model would see Li's 4 M3 touches become 3.

## What moved since M2

| Number | M2 | M3 | Why |
|---|---|---|---|
| Events received / accepted | 10 / 8 | 16 / 14 | Six events added for the M3 cases (`evt-11` to `evt-16`). The original ten keep their outcomes. |
| Touchpoints from the original ten events | 4: `evt-03`, `evt-05`, `evt-10`, `evt-07` | 4: `evt-01`, `evt-03`, `evt-10`, `evt-07` | `evt-01` is now stitched (16); `evt-05` is now internal navigation (17). |
| `con-nw-li`'s first touch | `evt-03` at 08:15 | `evt-01` at 08:10 | The stitched landing view is earlier. Same campaign, so a first-touch credit would not change campaign. |
| `evt-07` event time | 09:00:00 | 09:00:01 | Skew-corrected by receivedAt − sentAt = 1 s (19). |
| Touchpoints in total | 4 | 6 | Plus `evt-13` (inactivity) and `evt-12` (new referrer). |

The demo report (`sample_data/demo/expected/first_touch.json`) does not move: its touchpoints
come from touchpoints.csv, which the session rules don't touch, and every event is dated after
every demo conversion.
