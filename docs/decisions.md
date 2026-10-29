# Decisions

Product and data-meaning decisions, newest first. Each links the issue where it was made.

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
