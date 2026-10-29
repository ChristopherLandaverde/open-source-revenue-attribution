---
type: research
status: current-snapshot
domain: [focosys, analytics, attribution, open-source]
tags: [revenue-attribution, competitors, swot, research]
researched: 2026-10-28
---

# Market Research and SWOT: Open Source Revenue Attribution

Up: [Open Source Revenue Attribution](../README.md)
Spec: [PRD](prd.md)
Plan: [Project Management Plan](project-management-plan.md)

> Research snapshot: 2026-10-28. Product capabilities below are based on current public company product pages and documentation. Vendor pages describe vendor capabilities; they do not independently prove performance or attribution accuracy.

## Executive summary

Dreamdata and adjacent B2B revenue-intelligence products aim to unify activity across marketing, sales, product, and CRM systems, connect contacts to accounts and opportunities, and report the buyer journey through pipeline and revenue. Stronger products go beyond a single credit score: they support stage-specific journeys, explainable touchpoints, model comparisons, data-quality and identity handling, and activation or lift analysis.

The project should not compete on connector count or AI features. A credible opening is a small, self-hostable, warehouse-friendly tool that makes every mapping, input record, attribution assumption, and calculation inspectable. Make setup and data trust the product advantage.

## What similar products do

| Product | Publicly described approach | What that means for our product |
|---|---|---|
| **Dreamdata** | B2B account/contact/deal journeys; stage-based pipeline and revenue reporting; campaign/channel/landing-page and referrer breakdowns; attribution models; audience activation and benchmarks. Its current Free plan advertises web analytics, cookieless tracking, company identification, audience building, and ad-spend reporting, with limits shown on its pricing page. | The strongest direct reference. A tiny three-model dashboard alone is not a durable differentiator. Keep the MVP honest about scope and win on inspectability, portability, and a frictionless synthetic/CSV demo. |
| **HockeyStack** | Unified online/offline GTM data, buyer journeys, configurable multi-touch attribution, custom reports, lift/incrementality reports, source-system syncing, and AI recommendations/analysis. | Do not race it on breadth. Make a clean path from inputs to explainable results first; treat causal lift as a different analysis with a different evidence standard. |
| **Factors.ai** | Visitor/account analytics and report building; attribution for conversion goals with first/last-touch, non-direct variants, linear, U-shaped, and time-decay models; supports touchpoints such as paid media, referrals, content, email, and offline events. | Keep model definitions visible. Design the event and touchpoint contract so offline activity can be added later without letting the first release turn into an integration project. |
| **CaliberMind** | Enterprise GTM data warehouse and transformations; multi-touch attribution, account scoring, buyer journeys/sales signals, and marketing mix modeling. | Data normalization and account identity are first-class product work. Do not build enterprise data operations into v1, but keep raw inputs and mappings inspectable and exportable. |
| **Attribution Studio (open-source adjacent)** | A public GitHub project describes CSV upload against a canonical schema, a dbt/Postgres pipeline, and comparison across first/last, linear, time-decay, position-based, and Markov models. | There is open-source overlap in general model comparison. Our distinct scope must be B2B funnel/account journeys, reproducibility, and an operable self-hosted demo—not merely more attribution formulas. |

## Market patterns and product implications

1. **The unit of analysis is often the account and the pipeline stage.** Multiple people and activities can influence one opportunity. Include deterministic contact-to-account relationships in the sample data; defer fuzzy company recognition and probabilistic identity stitching.
2. **Attribution and influence answer different questions.** Attributed credit is fractionally allocated and should reconcile to the opportunity amount. Influence records a touchpoint's presence and can count one deal in several channels. Label these metrics separately.
3. **The data model and joins are the hard part.** Contacts, companies/accounts, opportunities, stage definitions, session/touchpoint data, and campaign data have to line up. Build import preview, validation errors, stable IDs, and source traceability before adding many integrations.
4. **Stage models matter before closed-won.** Show qualified pipeline and opportunity creation as well as won revenue; early-stage projects cannot wait through a full B2B sales cycle to see whether tracking works.
5. **Model comparison is more informative than model proliferation.** Start with first-touch, last-touch, and linear, but allow the same fixture to compare all three and show the underlying journey. Expand only when a user has a decision that another model can support.
6. **Causal lift is not another attribution model.** Observational touchpoint credit cannot establish incremental effect by itself. Defer lift/holdout analysis until there is a credible experiment design and adequate data.
7. **Current competition includes free entry tiers.** Dreamdata's current public pricing page lists a $0 Free plan with product limits. Open-source alone will not beat a capable free plan; self-hosting, data ownership, explainability, and the right setup experience need to be tangible.

## Recommended product improvements

### Add to the first useful demo

- **Account-aware, deterministic sample model:** accounts own opportunities; contacts belong to accounts; account journeys combine explicitly linked contacts and company-level activity. Require imported account IDs for the demo; no fuzzy matching.
- **Model comparison view:** compare first-touch, last-touch, and linear for the same funnel and show which records moved credit.
- **Separate attributed from influenced metrics:** attributed values reconcile; influence counts are labeled as overlapping and are never added together as if exclusive.
- **Data readiness panel:** show counts/percentages of valid events, missing campaign fields, unattributed conversions, duplicate/rejected events, unlinked contacts, and import errors. Show the denominator and sample period for each rate.
- **Import preview and error report:** accept the sample CSV, validate before write, show row-level failures, and make repeat imports safe.
- **Evidence trail on every report:** expose stage definition, conversion timestamp/value/currency, model, lookback, contributing touchpoints, and calculation version.

### Defer until the first demo is useful

- Native CRM, ad platform, and marketing automation connectors.
- AI recommendations, account scoring, audience activation, and automated sales actions.
- Time-decay, U-shaped, Markov, or custom-weight models until a user decision requires them.
- MMM or causal-lift claims without a valid experimental/data design.
- Fuzzy account identification, broad multi-tenant SaaS guarantees, and enterprise implementation services.

## SWOT

### Strengths — internal/project choices

- The scope is a concrete marketing-engineering problem with an inspectable end-to-end demo.
- Postgres/Supabase and RudderStack offer familiar, composable building blocks; data can be designed for portability.
- The plan already favors deterministic sample data, explicit attribution rules, synthetic fixtures, and traceable outputs.
- Open-source/self-hosted intent can appeal to teams that want control over data and deployment—if packaging and maintenance are delivered well.

### Weaknesses — current gaps

- No dedicated repository or working product exists yet; the product idea and buyer focus remain unvalidated.
- Initial scope is contact-centric and only three simple models; B2B account identity, buying groups, and offline touchpoints need deliberate design.
- Requiring RudderStack and Supabase before a user sees value may make the first run too difficult.
- Attribution correctness depends on event coverage, CRM stage history, consistent campaign naming, consent, and identity mapping; current plan needs a visible way to expose these gaps.
- Open-source self-hosting adds setup, upgrades, security, backup, and support work.

### Opportunities — external openings

- Offer a local sample-data path and CSV import before live integrations, then let teams connect their own event pipeline when ready.
- Make data provenance, calculation replay, model sensitivity, and reconciliation the headline trust features.
- Serve technical small teams and agencies that want to inspect or adapt their attribution rules without buying an enterprise platform.
- Add an easy export or warehouse-first mode so users retain raw events and can verify results independently.
- Use the open-source repo, sample dataset, and benchmarkable tests as public proof-of-work and as an acquisition channel.

### Threats — external risks

- Dreamdata offers a free entry plan, while HockeyStack and Factors.ai advertise broad tracking, journey, attribution, and analysis capabilities.
- CaliberMind and similar enterprise tools combine attribution with managed data operations, expertise, integrations, and customization; a small OSS tool will not match that service layer.
- Browser privacy controls, consent requirements, ad-platform walled gardens, and missing CRM history can make journeys incomplete regardless of calculation quality.
- Users may read fractional attribution as causal proof and make bad budget decisions; product copy and reports must state limits clearly.
- Connector/API changes and deployment complexity can consume more time than the core product.

## Strategic recommendation

Position v1 as **“auditable B2B attribution you can run yourself”**. The core proof is not a big dashboard; it is a reproducible chain:

`source event / CSV row → validated record → account/contact/opportunity relationship → eligible journey → named model → reconciled credit`

Build order recommendation:

1. M0 foundation: repository, local sample mode, CI, architecture boundary, license, setup proof.
2. M1: canonical event/import contract, account-contact-opportunity fixture, hand-calculated expected outputs, and validation report.
3. M2–M3: collection/persistence and deterministic account/contact journey joins.
4. M4: side-by-side model results, attributed vs influenced distinction, and data readiness panel.
5. M5: self-hosting docs, release, and user feedback before adding connectors.

This keeps the project narrow while making its differentiator visible and testable.

## Sources

- [Dreamdata Revenue Attribution documentation](https://docs.dreamdata.io/article/8v75km9zu3-revenue-attribution) — report filters, stage metrics, attributed vs influenced columns.
- [Dreamdata developer data warehouse overview](https://developer.dreamdata.io/data-warehouse/intro/) — stages, journeys, session-level attribution, contact and company modeling.
- [Dreamdata pricing](https://dreamdata.io/pricing) — current public Free and Advanced plan positioning and limits.
- [Dreamdata guide to attribution reports](https://dreamdata.io/library/how-to-build-attribution-reports) — source data, CRM stage history, web tracking, ad spend, and journey validation.
- [HockeyStack product overview](https://www.hockeystack.com/) and [platform overview](https://www.hockeystack.com/platform-overview) — buyer journeys, attribution, lift reporting, data foundation, sync, and AI analysis.
- [Factors.ai multi-touch attribution documentation](https://help.factors.ai/en/articles/6280857-multi-touch-attribution) — goals, touchpoints, offline activity, and model options.
- [CaliberMind platform overview](https://calibermind.com/platform/) — warehouse, transformations, attribution, ABM, buyer journeys, and analytics.
- [Attribution Studio GitHub repository](https://github.com/Avanthi1990/attribution-studio) — public open-source adjacent implementation and model comparison.
- [RudderStack Open Source documentation](https://www.rudderstack.com/docs/get-started/rudderstack-open-source/) — self-hosted data plane/control plane and PostgreSQL dependency; useful for the M0 deployment decision.

## Related

- [Open Source Revenue Attribution](../README.md)
- [PRD](prd.md)
- [Project Management Plan](project-management-plan.md)
