# Decisions

Product and data-meaning decisions, newest first. Each links the issue where it was made.

## 2026-10-29 — Event identity, visits and time (M2 assumptions 16–21)

[#5](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/5)

- **Stitching (16):** an identify links the visitor's earlier `anonymousId` page views to its
  `userId` (the `contact_id`), so the visit that carried the UTMs reaches the contact.
- **Visits (17):** only page views that start a visit (30-minute inactivity gap, new campaign
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
