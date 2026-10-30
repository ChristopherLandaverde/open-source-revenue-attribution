# Release process

How to cut a release of Open Source Revenue Attribution. Tagging, publishing a GitHub
release, publishing an image and making the repository public are Christopher's decisions
(portfolio `AGENTS.md`, Autonomy). An agent may prepare everything up to step 5 in a PR.

Modelled on Plausible's and Umami's release notes. Both use semver tags, give every release
an upgrade or migrations section, and ask self-hosters to pin a tag and read the notes before
upgrading ([research](research/m5-self-hosting.md#5-release-notes-and-changelogs)).

## Versioning

[Semantic Versioning](https://semver.org/spec/v2.0.0.html), tags `vMAJOR.MINOR.PATCH`. The
version lives in `pyproject.toml` and in `CHANGELOG.md`.

| Change | Before 1.0 | From 1.0 |
|---|---|---|
| Report numbers change for the same data (attribution math, eligibility, sessions) | minor | major |
| Data contract refuses something it accepted, or a setting is removed or renamed | minor | major |
| New feature, new reason code, new optional setting, new migration | minor | minor |
| Bug fix with no change to numbers or the contract | patch | patch |
| Security fix | patch, released on its own | patch, released on its own |

A change to report numbers always needs its decision in `docs/decisions.md` and a "Numbers
that moved" line in the changelog, as in M4.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Work lands
under `## [Unreleased]`. At release time that section becomes `## [x.y.z] - YYYY-MM-DD`
with these subsections (omit empty ones, except **Migrations**, which always says something):

- **Added / Changed / Fixed / Removed / Security**: user-visible changes, one line each, with
  the issue or PR number.
- **Numbers that moved**: which reports change for the same data, and the decision that
  changed them.
- **Migrations**: the migration names, or "None". Say whether any is slow on large tables or
  irreversible.
- **Upgrade notes**: settings to add or rename, and anything to do by hand before or after
  `up --build`.
- **Known limits**: anything newly known not to work.

## Checklist

### 1. Scope

- [ ] Every issue for the milestone is closed or moved; no open `needs-decision` blocks it.
- [ ] `docs/decisions.md` has every data-meaning change in the release.

### 2. Automated checks (record the output in the release PR)

```sh
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest                                         # SQLite
docker compose up -d --wait db                        # local PostgreSQL 17
TEST_DATABASE_URL=postgres://osra:osra@localhost:5432/osra uv run pytest
DEBUG=false SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))") \
  DATABASE_URL=postgres://u:p@db/x ALLOWED_HOSTS=attribution.example.com \
  CSRF_TRUSTED_ORIGINS=https://attribution.example.com BEHIND_PROXY=true \
  SECURE_HSTS_SECONDS=3600 uv run python manage.py check --deploy --fail-level WARNING
```

- [ ] All of the above pass, and CI is green on the release PR (both jobs: SQLite and
  PostgreSQL).

### 3. Self-hosted stack, end to end

On a clean clone of the release commit, with a production-like `.env`
([self-hosting.md](self-hosting.md#install)) and a TLS proxy in front (Caddy with
`tls internal` works on localhost):

- [ ] `docker compose -f compose.production.yml up -d --build --wait` → both containers healthy,
  migrations applied in the app log.
- [ ] `exec app python manage.py check --deploy` → no issues.
- [ ] Anonymous request to `/` → redirect to `/accounts/login/`. Plain HTTP → redirect to HTTPS.
- [ ] `createsuperuser` → sign in over HTTPS → session and CSRF cookies are `Secure`.
- [ ] `load_sample_data` → the model comparison, readiness, validation, events and a journey
  page all render. Numbers match `sample_data/demo/expected/`.
- [ ] `create_workspace` → with the default setting, an event POST with any `Origin` returns 200
  with `Access-Control-Allow-Origin`. With `COLLECT_ALLOWED_ORIGINS` set to a list, a listed
  origin gets 200 and an unlisted one gets 403 on preflight and POST.
- [ ] `pg_dump` → drop and recreate the database → `pg_restore` → row counts unchanged.
- [ ] **Upgrade path** (from the second release on): start the previous tag, load the demo,
  back up, check out the new tag, `up -d --build --wait`. Migrations apply and the demo data
  still reports the same numbers, or the numbers listed under "Numbers that moved".

### 4. Docs and UI

- [ ] README follows the `readme-standards` checklist: every count is checked against the
  code, every command has been run, and the status line is current.
- [ ] Screenshots in `docs/media/` show the release build on synthetic data.
- [ ] `ux-standards` review checklist for every changed page, with screenshots, in the PR.
- [ ] `.env.example` lists every setting (a test enforces this). `docs/self-hosting.md`
  matches the compose file.
- [ ] PRD section 11 (release acceptance checklist): mark each item done or explain the gap.

### 5. Prepare the release PR

- [ ] Bump `version` in `pyproject.toml` and run `uv lock`.
- [ ] Move `## [Unreleased]` to `## [x.y.z] - YYYY-MM-DD` and update the compare links.
- [ ] Open the PR labelled `needs-review` with the check output and the stack walkthrough.

### 6. Publish (Christopher only)

- [ ] Merge the release PR.
- [ ] `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.
- [ ] GitHub release from the tag, with the changelog entry as notes.
- [ ] Optional, later: publish a versioned image (never only `latest`), and make the
  repository public.

## After the release

- Collect feedback through the issue templates (`.github/ISSUE_TEMPLATE/`) before adding
  connectors (market research, M5).
- Append the release to `projects/open-source-revenue-attribution.md` in portfolio-ops.
