# Changelog

All notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Before 1.0, a minor version
(0.x.0) may change report numbers, the data contract or settings. The entry says so when it
does. How releases are made: [docs/release.md](docs/release.md).

## [Unreleased]

## [0.1.0] - Unreleased (not tagged)

First release: milestones M0 to M5. Reports state association under a named model, never
causal impact.

### Added

- **Self-hosting (M5).** Production Docker image (gunicorn, WhiteNoise static files, non-root
  user, `/healthz`) and `compose.production.yml` with PostgreSQL 17. Caddy and nginx examples
  in `deploy/`. Guide: [docs/self-hosting.md](docs/self-hosting.md) covers install, first
  admin, TLS, backups, upgrades and the security checklist.
- **Sign-in (M5).** Every page needs a signed-in user (Django auth). The first admin is
  created with `manage.py createsuperuser`. There is no public sign-up and no default password.
- **CORS for `/v1/` (M5).** Browser events are accepted from any site by default, as in
  Plausible, Umami and PostHog. `COLLECT_ALLOWED_ORIGINS` can restrict them to a list of
  origins; other sites then get 403. Write-key auth is unchanged.
- **Deployment checks (M5).** `manage.py check --deploy` adds `osra.W001` and `osra.W003` to
  `osra.W006` (wildcard hosts, demo page on, SQLite, HTTPS off, malformed origins), plus the
  info message `osra.I001` (unrestricted origins).
  HTTPS-by-default settings apply when `DEBUG=false`.
- **Model comparison (M4).** First-touch, last-touch, linear, position-based (40/20/40) and
  time decay (7-day half-life), side by side per campaign and per opportunity, for pipeline
  (at creation) and won revenue (at close). No lookback cap by default, as in Dreamdata.
  `ATTRIBUTION_LOOKBACK_DAYS` sets an optional one. Every model column reconciles to the
  amount.
- **Attributed vs influenced (M4).** An overlapping Influenced column, never totalled
  (Dreamdata's definition).
- **Data readiness (M4).** `/readiness/` runs 7 checks with denominators, fixes and
  verification steps.
- **Journeys (M3).** `/opportunities/<id>/journey/`: every touch of the opportunity's contact,
  its eligibility, its session and each model's credit. Anonymous page views are stitched to
  a contact through identify (`anonymousId`), and browser clock skew is corrected. One
  touchpoint per session: 30 minutes of inactivity ends a session, as in Dreamdata and GA4
  (#7).
- **Event collection (M2).** RudderStack-compatible `POST /v1/batch`, `/v1/page`, `/v1/track`
  and `/v1/identify` with per-workspace write keys. Events are validated, deduplicated on
  `messageId`, and stored with their outcome. The Events page and an SDK demo page (DEBUG
  only) show the results.
- **CSV import (M1-M2).** The `load_sample_data --path` command and the Import CSV page take
  accounts, contacts, opportunities and touchpoints, in partial or strict mode. The
  validation page lists every refused row with its reason code and fix.
- **Data contract (M1).** [docs/contract.md](docs/contract.md) has 21 refusal codes and
  8 warning codes. A synthetic demo fixture comes with hand-calculated expected results.
- **Repository (M0).** Django 5.2 LTS + HTMX app with pure-Python `attribution/` and
  `contracts/` packages (a test enforces the boundary), CI, and the MIT license.

### Migrations

`collection.0001` and `reports.0001` to `reports.0005`. On a new install they run on first
start. There are no earlier releases to upgrade from.

### Upgrade notes

None (first release). Settings added in M5 that a server must set: `SECRET_KEY`,
`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `BEHIND_PROXY` and `POSTGRES_PASSWORD`. Optional:
`COLLECT_ALLOWED_ORIGINS` to restrict browser events to your sites. All are listed in
`.env.example`.

### Known limits

- One dataset: workspaces identify senders but do not isolate data, and every signed-in user
  sees everything.
- Journeys are per opportunity contact, not combined per account. Stages are `open` and `won`
  only. No W-shaped or data-driven model.
- Touchpoints are recomputed from all events on each collection request. This is not tuned
  for large volumes.

[Unreleased]: https://github.com/ChristopherLandaverde/open-source-revenue-attribution/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ChristopherLandaverde/open-source-revenue-attribution/releases/tag/v0.1.0
