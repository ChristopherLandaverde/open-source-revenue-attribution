---
type: project-plan
status: active
domain: [focosys, analytics, attribution, open-source]
tags: [revenue-attribution, project-management, quality]
created: 2026-10-28
---

# Project Management Plan: Open Source Revenue Attribution

Up: [Open Source Revenue Attribution](../README.md)
Spec: [PRD](prd.md)

## 1. Project outcome

Deliver a small, runnable, open-source demo that takes campaign touchpoints and a sample B2B lead/opportunity funnel through to transparent pipeline and revenue attribution reports. Optimize for correctness, inspectability, and an easy local setup before adding integrations.

The PRD is the product scope. This plan is the source of truth for delivery sequence, progress evidence, and quality gates. Once a code repository exists, implementation issues, source code, migrations, and CI results live there; keep this note as the project overview and link to the repository.

## 2. Delivery principles

1. Ship a thin end-to-end slice before broadening scope.
2. Keep the sample dataset and expected results as executable, reviewable product evidence.
3. Make one change at a time with an explicit acceptance condition and regression test.
4. Treat tracking, identity, and attribution as contracts, not incidental implementation details.
5. Keep the product honest: reports explain modeled credit and do not claim causal lift.
6. Do not add an integration until the core event-to-revenue workflow is useful without it.
7. Let the agent carry each well-scoped task from implementation through its required verification and evidence record; ask the user only for decisions or access that cannot be safely inferred from project defaults.

## 3. Selected implementation and test frameworks

The project stack is Django + HTMX, selected on 2026-10-28. Use these as the M0 baseline, pin compatible versions in the dependency lockfile, and confirm the clean local setup before expanding scope.

| Area | Recommended choice | Why |
|---|---|---|
| Web app | Django + Django templates + HTMX; Python for server logic | Server-rendered app with partial-page interactions and no React app or Vite build pipeline. Prefer the supported Django LTS release available at repository bootstrap. |
| Styling and browser code | Plain CSS/design tokens; HTMX and RudderStack browser SDK as pinned static assets | Avoid a frontend build system. Keep browser JavaScript small and focused on tracking and chart behavior. |
| Database/backend | Django ORM and Django migrations; PostgreSQL locally; Supabase as an optional managed PostgreSQL host | Django owns app auth, permissions, and schema migrations; the same app can run against ordinary self-hosted PostgreSQL. Do not create competing Django/Supabase migrations for the same tables. |
| Event collection | RudderStack JavaScript SDK and a documented event contract | Use a standard event pipeline; validate PostgreSQL delivery/freshness behavior during M0. |
| Domain and web tests | pytest + pytest-django + Django test client | Exercise pure attribution rules, views, imports, and database behavior with isolated synthetic fixtures. |
| Automated browser tests | Playwright for Python with pytest | Repeatable end-to-end flow in CI; Chromium on each PR, Firefox/WebKit coverage before release. |
| Real UI acceptance | CUA live walkthroughs | Operate the running app, inspect visual results, and attach screenshots/observations to each user-facing slice and release. |
| Continuous integration | GitHub Actions once the repository is connected to GitHub | Run Ruff, Django system checks, migration checks, pytest, and browser gates on proposed changes. |

Use the supported Django LTS release available at repository bootstrap and pin dependencies. Keep attribution calculations in pure Python modules, not templates. Use HTMX endpoints that return HTML fragments for interactions. Avoid adding a Node frontend toolchain or separate API framework unless a later vertical slice proves one is needed. Django owns application authentication, permissions, and schema migrations; Supabase is an optional managed PostgreSQL host, not a second migration or authorization layer. Apply tenant authorization at the server and database boundaries before enabling multi-workspace use.

## 4. Work tracking

### Issue statuses

`Backlog → Ready → In Progress → Review → Done`; use `Blocked` when progress depends on a decision, access, or external service. Every blocked item names the blocker, owner/next action, and date to revisit.

### Work item requirements

Every implementation item includes:

- user or operator outcome;
- scope and explicit non-goals;
- observable acceptance criteria;
- relevant tests or verification evidence;
- dependencies and data/security implications;
- a small reviewable change boundary.

Prefer tasks that can be completed and reviewed in one focused session. Split broad tasks until each one produces a visible result.

### Standard work item format

Use this structure for every issue or delegated task. If a field does not apply, state `None` rather than leaving ambiguity.

```markdown
## Outcome
What the user or operator can do when this is complete.

## Context and defaults
Relevant PRD section, architecture decision, existing behavior, and defaults to follow.

## Scope
Included changes and explicit non-goals.

## Acceptance criteria
- Observable behavior or result
- Error, empty, and boundary behavior where relevant

## Verification
- Automated checks to run
- CUA walkthrough needed: yes/no; scenario and viewport(s)
- Evidence to attach (test output, screenshots, or recording)

## Data, security, and side effects
Tables/migrations, permissions/privacy impact, external services, and any irreversible action.

## Dependencies and assumptions
Required access or decisions; assumptions the implementer can use without blocking.
```

### Autonomous execution agreement

- **Proceed without a check-in:** inspect relevant code and project notes; make reversible code, test, and documentation changes inside the agreed scope; run the checks specified in the issue and project quality plan; use CUA for the required live UI walkthrough; fix failures caused by the change; and report the result with links and evidence.
- **Use project defaults:** Django + HTMX; Python attribution logic; Django owns application auth and migrations; PostgreSQL is the database; Supabase is an optional managed PostgreSQL host. Prefer a local fixture path so work does not depend on external accounts.
- **Ask only when needed:** a missing product choice changes user-visible behavior or data meaning; required credentials/access are unavailable; a task would spend money, publish/release, change shared external state, or irreversibly delete data; or an acceptance criterion conflicts with the PRD or security boundary. Continue independent work while that decision is pending.
- **Close the loop:** summarize what changed, checks actually run and their results, CUA scenario/evidence for UI work, known limitations, and the next smallest task. Never claim a check passed unless it was run.

This agreement permits autonomous work within the repository and documented scope. It does not authorize publishing, contacting people, spending money, or changing production systems.

### Progress record

At the end of each work session, update the project board or this section with:

- completed outcome and link to the commit/PR/artifact;
- checks run and their results;
- next smallest task;
- blocker or decision needed, if any.

Progress is measured by accepted outcomes and evidence, not hours, lines changed, or tasks marked complete without verification.

## 5. Milestones and exit criteria

| Milestone | Status | Deliverables | Exit criteria |
|---|---|---|---|
| M0 — Project foundation | Ready | Repository, Django + HTMX app, README stub, license decision, local Postgres/sample-data path, CI skeleton, architecture and decision log; spike RudderStack deployment and Postgres freshness | Clean checkout runs a local sample without external service accounts; architecture decision records event freshness; formatting, lint, type-check, and test commands are defined; repo is the implementation source of truth |
| M1 — Event contract and demo fixture | Backlog | Event/property and CSV contracts, deterministic account/contact/opportunity fixture, hand-calculated model outputs, validation/error cases | Contract reviewed; fixture covers two campaigns, multiple contacts at one account, multiple journeys, and an unattributed case; outputs reconcile by hand; privacy-safe data only |
| M2 — Collection and persistence | Backlog | RudderStack source/configuration, Postgres analytics schema, Django-managed app migrations, event validation/deduplication | A sample event reaches the analytics schema; invalid events and retries have explicit behavior; integration test exercises the path |
| M3 — Funnel and identity | Backlog | Account/contact/opportunity import or entry, explicit identify flow, deterministic account mapping, stage history, journey query | Sample contacts connect to intended activity and account by explicit ID; account journey combines only intended contacts; duplicate imports/events do not inflate totals; identity behavior has tests and docs |
| M4 — Attribution and first report | Backlog | Pure calculation module, first/last/linear model comparison, attributed vs influenced views, campaign summary, account/contact journey, data-readiness panel | Expected fixtures pass for edge cases; attributed totals reconcile; influence is labeled as overlapping; model/window and source evidence are visible; data-quality counts match fixture truth |
| M5 — Usable demo and release | Backlog | Setup guide, synthetic demo flow, screenshots, limitations, license, tagged runnable release or public repo | New contributor follows setup; release checklist in the PRD passes; demo feedback and follow-up decisions are recorded |

Milestones are ordered gates, not calendar promises. Re-estimate after the repository and first technical spike exist. Do not start later integration work while an earlier milestone's exit criteria are failing.

## 6. Quality and clean-code standards

### Design and implementation

- Use Python type hints and validate external boundaries for events, imports, currencies, identity, and attribution results.
- Keep event parsing, identity linking, attribution calculations, persistence, Django views, and templates in clear modules with explicit inputs/outputs.
- Keep attribution formulas pure and deterministic; do not bury business logic in templates or provider-specific callbacks.
- Avoid untyped dictionaries at domain boundaries, broad exception swallowing, and silent fallback values.
- Use descriptive names, small cohesive functions, and comments that explain domain decisions rather than restating code.
- Avoid premature abstractions, duplicated formulas, unnecessary dependencies, and unrelated cleanup in feature changes.
- Version database changes as migrations. Add constraints and indexes for supported queries; make seed/import behavior repeatable.
- Keep secrets out of source control and browser bundles. Use environment examples with placeholders, never real credentials.

### Required automated gates

Before a change is marked done, run the relevant project scripts and record results. The default merge/release gate is:

1. formatter check;
2. lint;
3. static type-check;
4. unit and property/invariant tests for domain logic;
5. contract tests for event payloads and imports;
6. integration tests for migrations, persistence, authorization, and report queries;
7. production build;
8. automated end-to-end smoke tests for user-visible workflows.

CI should run the applicable automated gates on every pull request. A failing or skipped gate must be explained in the PR and tracked as follow-up work; do not treat a green build alone as proof of correctness.

### Test strategy and evidence

Use layered checks. Each test scenario records its preconditions/fixture, exact action, expected result, observed result, and evidence link. Use synthetic records only; never use live customer or personal data for routine tests.

- **Unit + invariants:** Pure attribution math and domain rules: all models, empty journeys, lookback boundaries, repeated touchpoints, duplicate event IDs, missing campaign fields, rounding remainders, currencies, stage timestamps, and invalid inputs. Assert invariants such as attributed credit equals the opportunity value, stable IDs never create duplicate events, and replaying the same inputs produces the same output.
- **Contract:** Validate RudderStack payloads and CSV import rows against versioned schemas; reject malformed/unknown data with actionable row/event diagnostics. Keep representative valid and invalid fixtures.
- **Integration:** Apply migrations to a disposable Supabase/Postgres instance or test database; verify constraints, least-privilege access, deduplication, explicit account/contact linking, identity unlink/delete behavior, and report queries. Include authorization-negative tests, not only happy paths.
- **End-to-end automation:** Seed the synthetic funnel, exercise import/collection, inspect account and contact journeys, compare models, and assert key totals and source details.
- **CUA live UI walkthrough (required for every user-facing slice):** Run the actual application in a browser, use CUA to interact with the rendered controls, capture the visible result, and verify the state after each meaningful action. Check normal and narrow viewport layouts, keyboard navigation, focus/labels, loading/empty/error/success states, readable tables, no clipped or overlapping content, and that displayed report totals match the synthetic fixture. A mocked component render or screenshot of a static mock does not satisfy this gate.
- **CUA release walkthrough (required before demo/release):** Start from the documented clean-install path; load the bundled synthetic data; complete the full path from import or tracked event through account/opportunity journey to the campaign report; exercise duplicate/invalid import and missing-UTM cases; inspect model/window explanations and data-readiness counts; refresh/reopen to check persistence; capture screenshots of the actual release build.
- **Regression:** Every fixed bug gets a deterministic automated regression that fails before the fix. UI bugs also get a CUA reproduction and post-fix walkthrough. Preserve expected fixture outputs as reviewed evidence when rules change.
- **Manual technical review:** Review migrations, access policies, logs/errors, browser console, and network requests for accidental secrets or unexpected data exposure. Review the clean-checkout setup before demo/release.

### CUA walkthrough record

For a UI slice, attach a small test record to its issue/PR:

| Field | Record |
|---|---|
| Build | Commit/branch and app version tested |
| Environment | Browser, viewport, local services/fixture version |
| Scenario | User goal and seeded records |
| Steps | Ordered CUA actions actually performed |
| Expected | Visible state, key values, and navigation outcome |
| Observed | Pass/fail, actual values, console/network errors |
| Evidence | Timestamped screenshots or screen recording, linked from the issue/PR |
| Defects | Reproduction, severity, owner, and regression-test link |

Do not call a UI slice done if only automated tests pass but the live CUA path was not run. If CUA is unavailable or the application cannot be launched, mark the visual gate blocked and say why; do not silently substitute a static mock.

Do not chase a blanket line-coverage percentage. Protect critical calculations, contracts, and data boundaries with scenario-based tests. Add coverage reporting if it helps identify untested risk, but the test cases and reconciled outputs are the acceptance evidence.

## 7. Definition of Done

A work item is done only when:

- its acceptance criteria are met and the behavior is demonstrated;
- automated checks pass for the changed area and the default gate;
- user-facing behavior passes its required CUA walkthrough, with evidence linked from the issue/PR;
- tests cover the new behavior and relevant regression cases;
- migrations, event/import contracts, and docs are updated where needed;
- errors, loading, and empty states are understandable for user-facing changes;
- no credentials or real personal data were introduced;
- the change is reviewed and its commit/PR/evidence is linked from the tracker.

## 8. Risk and decision management

| Risk | Response |
|---|---|
| Event ingestion creates a misleading or incomplete source of truth | Keep raw events immutable where practical, validate contracts, preserve source IDs, and make reports traceable to source records |
| Anonymous-to-known identity rules create privacy or data-quality issues | Link only on explicit identify/submission; document consent assumptions and deletion/unlink behavior before real-site tracking |
| Supabase credentials or policies expose analytics data | Separate analytics schema, use least privilege, keep service credentials server-side, and test access boundaries before multi-user use |
| Attribution is mistaken for causal impact | Label model/window in reports and state the limitation in product copy and documentation |
| Scope expands into a full Dreamdata replacement | Revisit the PRD non-goals; require evidence from a user or demo before adding integrations |
| External service setup delays visible progress | Maintain a deterministic fixture/demo path and mark live-service work as a separate milestone dependency |
| Too much work is marked done without shipped evidence | Require acceptance evidence and update status only after review and checks |

Record consequential technical/product choices with date, context, options, decision, and revisit trigger. Keep unresolved questions visible rather than silently embedding assumptions in code.

## 9. First three work items

1. **Bootstrap the repository** — scaffold Django + HTMX, Python tooling, local Postgres run command, CI gates, and license; make the first run work from local sample data without external service accounts.
2. **Define the event and identity contract** — specify event names, required/optional properties, identify behavior, explicit contact-to-account mapping, deduplication key, and consent/deletion assumptions; add schema examples.
3. **Build the synthetic attribution fixture** — create two campaign journeys, multiple contacts in one account, lead/opportunity milestones, and hand-calculated expected first-touch, last-touch, and linear outputs, including unattributed, missing-data, and duplicate-event cases.

## 10. Current project status

- **Stage:** Planning; no dedicated attribution repository was found during this planning pass.
- **Product scope:** Draft PRD linked above.
- **Immediate next milestone:** M0 — Project foundation.
- **Next review point:** After M0 and the first event-contract proposal, revisit Supabase/Postgres hosting, RudderStack setup, buyer focus, and schedule estimates.
- **Progress rule:** Move a milestone out of `Ready`/`Backlog` only when its deliverables are underway; mark it complete only after its exit criteria have evidence linked here or in the repository.

## Related

- [Open Source Revenue Attribution](../README.md)
- [PRD](prd.md)
