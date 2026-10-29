---
type: product-spec
status: draft
domain: [focosys, analytics, attribution, open-source]
tags: [revenue-attribution, rudderstack, supabase, prd]
created: 2026-10-28
---

# Product Requirements: Open Source Revenue Attribution

Up: [Open Source Revenue Attribution](../README.md)
Related: [Project Management Plan](project-management-plan.md)

## 1. Product summary

Build an open-source, self-hostable product that helps a small B2B team see which marketing touchpoints are associated with qualified pipeline and closed revenue. The first release makes the event-to-revenue path visible and the attribution math inspectable.

**Working product description:** A focused, transparent alternative in the problem space served by Dreamdata, built first for a runnable demo and small teams that can provide a lightweight lead and opportunity dataset.

**Core question:** Which campaigns and channels bring in leads that become customers, and how much pipeline or revenue should each receive under a clearly stated attribution rule?

The product reports association under selected attribution models. It does not claim that attribution proves causal impact or incrementality.

## 2. Target user and job

### Initial user hypothesis

- A marketer, founder, or agency analyst at a small B2B SaaS company.
- They can add a tracking snippet and provide a simple lead/opportunity export, but do not want to buy or configure a large marketing-data platform.
- They need a report they can explain to a teammate or client.

This is a hypothesis to validate during the demo; the initial buyer focus (SaaS teams, agencies, or both) remains open.

### Job to be done

When a campaign produces activity across several visits and later becomes a lead, opportunity, or customer, help me inspect that journey and understand how the selected attribution model assigns pipeline and revenue.

## 3. Goals and success measures

### MVP goals

1. Capture campaign and website activity with a documented event contract.
2. Connect anonymous activity to a known lead only through an explicit identify event and documented consent/identity rules.
3. Record or import a minimal lead and opportunity funnel without requiring a full CRM integration.
4. Join contacts to accounts using explicit, stable IDs and show an inspectable account/contact journey.
5. Show campaign-level lead, qualified-pipeline, and won-revenue totals, with attributed credit kept distinct from overlapping influence.
6. Compare first-touch, last-touch, and linear credit for the same sample funnel.
7. Show basic tracking/import readiness so missing and rejected data are visible beside the reports.
8. Provide a clean setup path that another developer can run locally from the repository documentation.

### Demo acceptance measures

- A fresh local setup can load the included sample dataset and render the report using the documented steps.
- For the fixed fixture, all three attribution models match hand-calculated expected results; credits reconcile to the opportunity amount without unexplained loss or duplication.
- A user can move from a campaign summary to the underlying opportunity and touchpoints, and can see which model/window produced the displayed amount.
- Replaying the same event fixture does not silently inflate event or revenue totals.
- The demo communicates that attribution is a reporting model, not a causal-lift estimate.

## 4. MVP user journey

1. Start the app and load a supplied B2B sample dataset.
2. Review the workspace's event and identity settings, including the attribution window.
3. Collect website events through RudderStack and route them to the Supabase/Postgres analytics schema, or use the included fixture when external services are not configured.
4. Import or enter leads and opportunities with stage history and revenue.
5. Link contacts to accounts with explicit account IDs; do not infer account matches.
6. Inspect an account or contact's campaign touches, lead creation, qualification, opportunity, and close.
7. Compare first-touch, last-touch, and linear attribution side by side.
8. Review pipeline and closed revenue by campaign, inspect the records and rule behind any total, and check data coverage/import errors.

## 5. Functional requirements

### Event collection and campaign context

- Capture page views and named conversion events with event ID, event name, event timestamp, anonymous ID, optional known user/contact ID, page URL, referrer, landing page, and available UTM fields (`utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`).
- Preserve original event time and source context; do not replace missing campaign values with guessed values.
- Validate the event contract and reject or quarantine invalid records with a useful diagnostic.
- Deduplicate on a stable event ID so retries are safe.
- Support the milestones `Demo Requested`, `Lead Qualified`, `Opportunity Created`, and `Opportunity Won` in the sample funnel.

### Identity and privacy

- Keep anonymous browsing activity anonymous until an explicit identify/lead-submission event connects it to a known contact.
- Document which fields can identify a person, what consent is expected from the deploying site, and how an operator can delete or unlink a contact's data.
- Do not collect sensitive personal data in the demo. Use synthetic data in fixtures and screenshots.
- Keep tracking and analytics data in a separate schema from app/auth tables. Use least-privilege credentials and database policies; never expose service-role credentials in browser code.

### Lead and opportunity records

- Allow a user to create or import an account, its contacts/leads, and an opportunity with source account/contact, amount, currency, current stage, and stage timestamps.
- The first demo may use a documented CSV format or seed data; native CRM synchronization is out of scope.
- Preserve record IDs and import provenance so repeat imports can be made idempotent or surfaced as conflicts.
- Support deterministic contact-to-account and contact/account-to-opportunity relationships using explicit IDs. Fuzzy company identification and probabilistic identity stitching are out of scope.

### Journey and reports

- Show a chronological, inspectable touchpoint journey for a contact and its opportunities.
- Show an account journey that combines explicitly linked contacts and account-level events, with a drill-down to each contact.
- Report leads, qualified opportunities/pipeline, and won revenue by source, medium, and campaign.
- Include the attribution model and window in every report context; expose the underlying touchpoints and credit amounts.
- Compare all three MVP models against the same opportunity/journey. Show `Attributed` (fractionally allocated and reconcilable) separately from `Influenced` (touchpoint present; overlapping counts/values).
- Implement first-touch (all eligible credit to the earliest eligible touchpoint), last-touch (all eligible credit to the latest eligible touchpoint), and linear (equal credit across eligible touchpoints).
- Make missing/unknown campaign attribution visible rather than dropping it from totals.
- Reconcile credited amounts to the selected opportunity value; specify currency handling and rounding behavior before reporting mixed-currency totals.
- Provide a compact data-readiness view with event/import counts, invalid or duplicate events, missing campaign fields, unlinked contacts, and unattributed conversions. Display denominators and the covered time period.

## 6. Proposed attribution contract

These defaults make the first demo testable. Confirm them in the decision log before implementation.

- Attribution is calculated per opportunity, with won revenue based on the opportunity's recorded value at the won stage.
- Eligible touchpoints are valid marketing touchpoints connected to that opportunity's contact and occurring no later than the conversion timestamp.
- Use a configurable lookback window, with **90 days as the initial demo default**. The window is measured backwards from the conversion timestamp.
- First-touch and last-touch use the earliest/latest eligible touchpoint. Linear splits the opportunity value evenly across eligible touchpoints.
- If there are no eligible touchpoints, assign the full amount to `Unattributed`.
- Round display values to the currency's minor unit; calculate with adequate precision and assign any rounding remainder deterministically so totals reconcile.
- Do not combine different currencies into one total unless a conversion rate and effective date are supplied. For the MVP, group totals by currency.
- The same opportunity, model, window, and input records must always produce the same result.

## 7. Initial data model

- **Workspace:** settings, attribution window, and display preferences. Initial deployment can be single-workspace; do not imply production-grade tenant isolation until it is designed and tested.
- **Account:** stable account ID, optional name/domain, and import provenance. In v1, an account is joined only through explicit IDs or reviewed import mapping.
- **Contact/Lead:** stable ID, account ID, optional email or external ID, lifecycle stage, created timestamp, and import provenance.
- **Session/Touchpoint:** contact or anonymous ID, event time, landing page, referrer, channel/campaign fields, and source record ID.
- **Event:** stable event ID, event name, event time, identity IDs, properties, received time, and validation/deduplication status.
- **Opportunity:** contact ID, amount, currency, stage, stage timestamps, and external/import ID.
- **Attribution result:** opportunity ID, model, lookback window, touchpoint/campaign key, credited amount, calculation version, and calculation timestamp.
- **Data-quality summary:** period, event/import totals, validation/deduplication status counts, coverage counts, and calculation timestamp.

Define the physical schema and constraints in versioned migrations after the event contract and identity decisions are approved. Prefer derived attribution results that can be recomputed from source records over opaque, manually edited totals.

## 8. Non-functional and quality requirements

- **Correctness:** event retries, identity linking, stage transitions, attribution, rounding, and currency grouping have deterministic tests.
- **Explainability:** every displayed total can be traced to source records and a named model/window.
- **Security:** secrets remain server-side; database access follows least privilege; schema boundaries and row-level policies are reviewed before any multi-user deployment.
- **Privacy:** use synthetic fixtures, minimize collected identifiers, and document retention/deletion behavior.
- **Reliability:** migrations and seed data can be applied repeatedly to a clean local environment; failures are visible and actionable.
- **Maintainability:** use typed boundaries, small cohesive modules, explicit data contracts, and versioned migrations. Avoid hidden attribution behavior and duplicated business rules.
- **Accessibility/usability:** reports have clear labels, keyboard-operable controls, readable empty/error states, and model/window context.
- **Self-hosting:** a new contributor can follow the setup guide without relying on undocumented local state.

## 9. Out of scope for the first release

- Reproducing all Dreamdata features or supporting enterprise-scale data volumes.
- Native CRM sync, ad-spend connectors, reverse ETL, or automated ad-platform actions.
- Machine-learning, position-based, or claimed causal/incrementality attribution.
- Automated account-level identity resolution or probabilistic identity stitching.
- Production multi-tenant SaaS guarantees, billing, and hosted operations.
- Broad customization of every event, report, and workflow before the default funnel works end to end.

## 10. Open decisions and validation

Record each decision and its evidence in the project's `Decisions` section or an ADR before the choice becomes difficult to change.

| Decision | Current proposal | Resolve by |
|---|---|---|
| Initial buyer | Validate small B2B SaaS vs agency focus | Before external demo feedback |
| App framework and language | **Selected:** Django + Django templates + HTMX, with Python for server and attribution logic; PostgreSQL locally and Supabase as an optional managed host | Confirm the clean local vertical slice in M0; revisit only if the slice exposes a concrete limitation |
| Local development topology | Decide whether Supabase local is required or a fixture-only mode is sufficient | Before database integration |
| RudderStack deployment | Hosted or self-hosted for the demo; keep setup instructions explicit | Before event-routing milestone |
| Import format | CSV for leads/opportunities is the simplest first path | Before funnel milestone |
| Consent and retention defaults | Document operator responsibilities and supported deletion behavior | Before real-site tracking |
| License and repository name | Choose before public release | Packaging milestone |

## 11. Release acceptance checklist

- [ ] New developer setup works from a clean checkout using the README.
- [ ] Sample events and funnel records load through documented seed/import steps.
- [ ] Unit tests cover first-touch, last-touch, linear, no-touch, repeated/retried events, lookback boundaries, rounding, and currency grouping.
- [ ] Integration tests cover migrations, constraints, deduplication, identity linking, and report queries against a disposable local database or equivalent fixture boundary.
- [ ] An end-to-end test follows the sample funnel from events through a report.
- [ ] An account journey correctly aggregates explicitly linked contacts and can drill back to their touchpoints.
- [ ] Model comparison distinguishes reconcilable attributed credit from overlapping influence counts/value.
- [ ] Data-readiness counts identify missing campaign data, rejected/retried events, unlinked contacts, and unattributed opportunities for the sample fixture.
- [ ] Lint, formatting, type-check, unit, integration, and production build gates pass.
- [ ] The actual release build passes the CUA walkthrough for clean install, sample import, account/opportunity journey, model comparison, data-readiness states, and responsive/keyboard-accessible UI; evidence is linked from the release PR.
- [ ] Reports reconcile to source opportunity values and expose model/window/source detail.
- [ ] No secrets or real personal data are committed; database access and schema boundaries are documented.
- [ ] README, architecture overview, event contract, import format, and known limitations are current.
- [ ] Demo screenshots use synthetic data and accurately represent the released code.

## Related

- [Open Source Revenue Attribution](../README.md)
- [Project Management Plan](project-management-plan.md)
