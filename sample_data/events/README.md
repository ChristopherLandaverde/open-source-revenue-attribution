# Events fixture (synthetic)

`batch.json` is a RudderStack `/v1/batch` body: ten events, all dated September 2026, which is
after every demo opportunity's conversion, so posting them does not change the demo report.
Contacts are the demo fixture's (`sample_data/demo/contacts.csv`). Expected results are written
by hand in [`expected/touchpoints.json`](expected/touchpoints.json) and checked by
`tests/test_event_touchpoints.py` and `tests/test_collection.py`.

```sh
uv run python manage.py create_workspace demo        # prints the write key
curl -u '<write key>:' -H 'Content-Type: application/json' \
  --data @sample_data/events/batch.json http://127.0.0.1:8000/v1/batch
```

## Validation (event contract, docs/contract.md section 3)

| # | messageId | Event | Outcome | Why |
|---|---|---|---|---|
| 1 | `evt-01` | page, anonymous, google / cpc / fall-search | accepted | Has `anonymousId`. |
| 2 | `evt-02` | identify `con-nw-li` | accepted | |
| 3 | `evt-03` | page `con-nw-li`, `timestamp` 10:15 **+02:00** | accepted | |
| 4 | `evt-04` | track `Demo Requested` | accepted | A funnel milestone, so no warning. |
| 5 | `evt-05` | page `con-nw-li`, empty `context.campaign` | accepted, `MISSING_CAMPAIGN_FIELDS` | |
| 6 | `evt-06` | page `con-unknown` | accepted | Valid ID; the contract does not check it against contacts. |
| 7 | `evt-07` | page `con-ke-otto`, URL in `properties.url`, **no `timestamp`** | accepted | Falls back to `originalTimestamp`. |
| 8 | `evt-03` | same content as #3, different `sentAt` | duplicate, `DUPLICATE_ROW` | `sentAt` is ignored; counted once. |
| 9 | `evt-09` | page, `timestamp` `2026-09-04T10:00:00` | refused, `TIMESTAMP_WITHOUT_TIMEZONE` | No offset; not assumed UTC. |
| 10 | `evt-10` | page `con-nw-li`, linkedin / paid-social / fall-abm | accepted | Same instant as `evt-05`. |

Received 10 · accepted 8 · duplicates 1 · refused 1.

## Touchpoints (contracts/touchpoints.py)

Only page events with a `userId` that is an imported contact become touchpoints. Output is
ordered by (time in UTC, messageId).

| Order | Touchpoint | Contact | Time (UTC) | Source / medium / campaign | Why |
|---|---|---|---|---|---|
| 1 | `evt-03` | `con-nw-li` | 2026-09-02 08:15:00 | google / cpc / fall-search, content `ad-b`, term `revenue attribution` | 10:15+02:00 = 08:15Z. |
| 2 | `evt-05` | `con-nw-li` | 2026-09-02 08:20:00 | (none) / (none) / (none) | Blank UTMs stay blank; not taken from the URL. |
| 3 | `evt-10` | `con-nw-li` | 2026-09-02 08:20:00 | linkedin / paid-social / fall-abm | Ties with `evt-05`; `evt-05` < `evt-10` by ID. |
| 4 | `evt-07` | `con-ke-otto` | 2026-09-03 09:00:00 | newsletter / email / sept-digest | Time from `originalTimestamp`; URL from `properties.url`. |

Not touchpoints (accepted events are kept):

| Event | Reason |
|---|---|
| `evt-01` | `ANONYMOUS`: no `userId`. The identify at 08:14 (`evt-02`) does not link it back. |
| `evt-02` | `NOT_A_PAGE_VIEW` (identify) |
| `evt-04` | `NOT_A_PAGE_VIEW` (track) |
| `evt-06` | `CONTACT_NOT_IMPORTED`: `con-unknown` is not in contacts.csv. |
