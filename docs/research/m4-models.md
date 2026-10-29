# M4 research: attribution models, influence, data readiness

How Dreamdata (the product we are an open alternative to), GA4 and HockeyStack define the
models, the lookback window, "influenced" vs "attributed", and data-quality signals. Read
2026-10-29 from each vendor's own documentation. Quotes are short excerpts; check the page
before reusing them publicly. Where we depart from the standard, `docs/decisions.md` says why.

## 1. Models

### Dreamdata

Source: [Attribution models](https://docs.dreamdata.io/article/tycc6odb2v-attribution-model).
Six models: first touch, last touch, linear, U-shaped, W-shaped (rule-based) and data-driven.

| Model | Dreamdata definition |
|---|---|
| First touch | "The very first touchpoint receives 100% of the credit." |
| Last touch | "The very last touchpoint receives 100% of the credit." |
| Linear | "Every touch is assigned an equal amount of credit" (five touches: 20% each). |
| U-shaped | "40% of the credit is given to the first touch and 40% to the last touch." "The remaining 20% is divided among the remaining middle touches." |
| W-shaped | "30% of the credit is given to the first touch, 30% to the last touch, and 30% to the touch containing the conversion." The remaining 10% goes to the middle touches. |
| Data-driven | A Markov-chain model that credits by "removal effect" ("what would happen if this touchpoint did not exist?"). It moves toward linear "when the number of journeys are below 50" ([data-driven attribution](https://docs.dreamdata.io/article/m3fdrit0vt-data-driven-attribution)). |

- **Not documented:** what U- and W-shaped do with one or two touches, and which milestone
  "the touch containing the conversion" means (lead creation, opportunity creation).
- **No time-decay model** appears in Dreamdata's docs.
- **Custom models** ([custom attribution models](https://docs.dreamdata.io/article/6lh24wdj9v-custom-attribution-models)):
  weighted groups of touches with include and exclude rules (for example, exclude `direct`).
  Weight left over is spread by a fallback model.
- **Credit grain:** "Attribution is calculated for each stage journey" and one row is one
  session in one stage journey ([warehouse: attribution](https://developer.dreamdata.io/data-warehouse/description/attribution)).
  That matches our one touch per session (decision #7).

### GA4

Source: [Get started with attribution](https://support.google.com/analytics/answer/10596866).
- **Today:** data-driven and last click (paid and organic, or Google paid channels only).
- "The first click, linear, time decay, and position-based attribution models are no longer
  available as of November 2023."
- **Legacy definitions** ([MCF attribution models](https://support.google.com/analytics/answer/1665189)):
  - **Time decay:** "a default half-life of 7 days, meaning that a touchpoint occurring 7
    days prior to a conversion" gets half the credit of a touch on the conversion day.
  - **Position-based:** "40% credit each to the first interaction and last interaction" and
    "20% credit to the interactions in the middle".
- **Direct visits:** GA4 models "exclude direct visits from receiving attribution credit"
  unless the whole path is direct. Dreamdata does not.

### HockeyStack

Source: [Attribution models](https://docs.hockeystack.com/documentation/reports/attribution-models).
- First touch, last touch and linear, as above.
- **Position-based:** first and last get 40% each; the rest goes to the middle touches.
- **Time decay:** value halves every 7 days.
- **Uniform:** the full value goes to every touch, so totals do not add up. It is
  influence under another name.
- **Predictive:** a proprietary machine-learning model.

### What we adopt

| Model | Ours | Matches |
|---|---|---|
| First-touch | 100% to the earliest eligible touch | Dreamdata, HockeyStack, GA4 legacy |
| Last-touch | 100% to the latest eligible touch | Dreamdata, HockeyStack, GA4 last click (except direct handling) |
| Linear | equal split | Dreamdata, HockeyStack |
| Position-based (U-shaped) | 40 / 20 / 40; one touch 100%; two touches 50 / 50 | Dreamdata U-shaped, GA4 legacy, HockeyStack (one- and two-touch cases are our reading) |
| Time decay | weight 2^(−age / 7 days), age measured back from the conversion, normalised so credits sum to the amount | GA4 legacy, HockeyStack; Dreamdata has none |
| W-shaped | **not built**: we do not store the milestone it needs | see decisions |
| Data-driven | **not built** | see below |

Data-driven is skipped on purpose. Dreamdata's own version falls back toward linear below 50
journeys, so a small self-hosted dataset would mostly get linear with extra steps. A
removal-effect credit also can't be checked by hand per opportunity, and the project's
promise is that every number traces to source records and a named rule.

## 2. Lookback windows

- **Dreamdata** has no fixed day-based lookback in its docs. The journey runs from the first
  interaction up to the stage date: "We will always calculate the value from the first
  interaction up to the stage you selected" ([attribution models](https://docs.dreamdata.io/article/tycc6odb2v-attribution-model)).
  Activity after the stage timestamp is excluded ([stage models](https://docs.dreamdata.io/article/qndrelwriy-stage-models-kpi-customization)).
- **GA4:** key events default to a 90-day window (30 or 60 selectable); acquisition events
  default to 30 days. The window "applies to all attribution models"
  ([attribution settings](https://support.google.com/analytics/answer/16291704)).
- **HockeyStack:** time-based (days or months before the goal), goal-based, or none, per report
  or as a workspace default ([attribution lookback](https://docs.hockeystack.com/marketing-intelligence/reports/attribution-lookback)).
- **Ours:** a 90-day inclusive window measured back from the conversion (PRD section 6), the
  same for every model and for influence. It is GA4's default. Dreamdata's unbounded journey is
  a deviation (decisions).

## 3. Attributed vs influenced

Source: [Revenue attribution](https://docs.dreamdata.io/article/8v75km9zu3-revenue-attribution).

- **Influenced:** "the number of deals/opps/leads that were influenced by the channel." "The
  same deal/opp/lead can be counted fully multiple times." "If you add up all the numbers in
  these columns they will sum to more than actual number of deals/opps/leads and value."
- **Attributed:** "a deal/opp/lead is broken into fractions and split according to the
  attribution model." "If you add up all the fractions of a deal it will always add up to 1 and
  the full amount on the deal."
- **Attributable deals:** only deals "where we have a recorded history of sessions."

**Ours:**
- A campaign's influenced amount is the full amount of every opportunity with at least one
  eligible touch from it. "Eligible" uses the same window as the models.
- The column is labelled as overlapping and is never totalled.
- Attributed columns reconcile to the amount per currency.
- Opportunities with no eligible touch stay visible as an Unattributed row, where Dreamdata
  would drop them as not attributable (decisions).

## 4. Data readiness

Neither Dreamdata nor HockeyStack documents a coverage dashboard publicly. Dreamdata's
data-quality signals are labels inside its reports:

- **"No Tracking":** "we have not tracked any events or touch points for that company,
  contact or deal" ([No tracking](https://docs.dreamdata.io/article/vh72ayqv6e-some-of-my-deals-are-flagged-with-no-tracking-what-does-it-mean)).
- **"Unknown":** no tracking activity before the stage, and no CRM source to fall back on
  ([Unknown](https://docs.dreamdata.io/article/9qa2ormsm8-some-of-my-deals-are-flagged-with-unknown-what-does-it-mean)).
- **"Unspecified":** the group-by doesn't apply to that source
  ([Unspecified](https://docs.dreamdata.io/article/4a8v2helup-understanding-unspecified)).
- **Attributable deals:** deals with session history (section 3).
- **Tracking status** under Integrations, plus a validation walkthrough
  ([How to validate your data](https://docs.dreamdata.io/article/mosflcr0rm-how-to-validate-your-data);
  the checklist itself is in a slideshow we could not read).
- **Direct:** a session with no `utm_source`, `utm_medium` or referrer
  ([UTMs and paid defaults](https://docs.dreamdata.io/article/02dp7owlbl-understanding-utms-and-paid-defaults)).
  Direct still gets credit in the standard models.

**Ours** turns those labels into counted checks with denominators (PRD section 5 asks for
this):

| Check | Dreamdata equivalent |
|---|---|
| Opportunities have a contact | contactless deals (Dreamdata would fall back to the company; we don't, decision #3) |
| Contacts have tracked touches | No Tracking |
| Touches fall inside the lookback window | attributable deals |
| Touches carry source, medium and campaign | Unknown / direct |
| The last import loaded every row | CRM sync health |
| Collected events were accepted | tracking status |
| Collected page views reach a contact | anonymous traffic left unmatched |

Each check gives a fix and a way to verify it. A check without data shows "Not checked" with
the reason.

## 5. Account-level journeys (unchanged)

Dreamdata journeys default to company level for most objects. Opportunity-level journeys use
the opportunity's contacts and fall back to company level when there are none. Anonymous
company traffic gets credit too ([stage models](https://docs.dreamdata.io/article/qndrelwriy-stage-models-kpi-customization),
[anonymous traffic](https://docs.dreamdata.io/article/2l49qhyqbz-attribution-of-anonymous-traffic)).
We stay contact-level, as decided in M1 (#3). An account-level option is still a candidate for
later.
