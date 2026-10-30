# M5 research: how open-source analytics tools ship self-hosting

How Plausible Community Edition, Umami, PostHog (hobby) and Matomo package a self-hosted
install, protect the admin UI, guard the collection endpoint, and handle backups, upgrades
and release notes. Read 2026-10-29 from each project's docs, and from source code where the
docs are silent (CORS is never documented by the first three). Quotes are short excerpts;
check the page before reusing them publicly.

## 1. Packaging and configuration

| | Plausible CE | Umami | PostHog hobby | Matomo |
|---|---|---|---|---|
| Install | `git clone -b v3.2.1`, `.env`, `docker compose up -d` | Compose file: app + Postgres | `deploy-hobby` script | PHP app + web installer |
| Data stores | Postgres 16 + ClickHouse 24.12 | Postgres (>= 12.14) | Postgres, ClickHouse, Kafka, Redis and ~40 services | MySQL |
| TLS | Built in (Let's Encrypt) or your own proxy | Your own proxy | Bundled Caddy, Let's Encrypt | Your own web server |
| Required config | `BASE_URL`, `SECRET_KEY_BASE` | `DATABASE_URL` (+ `APP_SECRET`) | `SECRET_KEY`, `SITE_URL`, `DATABASE_URL` | `config.ini.php` written by installer |

**Plausible CE.** The [README](https://github.com/plausible/community-edition) clones a pinned
tag, writes `BASE_URL` and `SECRET_KEY_BASE` (generated with `openssl rand -base64 48`) to a
`.env`, and runs `docker compose up -d`. "Setting HTTP_PORT=80 and HTTPS_PORT=443 enables
automatic Let's Encrypt TLS certificate issuance." The [compose file](https://github.com/plausible/community-edition/blob/v3.2.1/compose.yml)
has three services (`plausible_db`, `plausible_events_db`, `plausible`) and pins every image
(`ghcr.io/plausible/community-edition:v3.2.1`). The [Configuration](https://github.com/plausible/community-edition/wiki/Configuration)
page: `BASE_URL` has no default and feeds link generation and WebSocket origin checks;
`SECRET_KEY_BASE` must be at least 64 bytes. The [Reverse Proxy](https://github.com/plausible/community-edition/wiki/Reverse-Proxy)
page covers Caddy, Nginx and Apache (bind `127.0.0.1:8000`, forward `X-Forwarded-For`). It says
that since 2.1.2 a proxy is "no longer necessary", and that the Nginx and Apache configs "have
not been tested by the maintainers".

**Umami.** "Umami ships with a Docker Compose file that contains the application and a
PostgreSQL database" ([install](https://docs.umami.is/docs/install)). The
[compose file](https://github.com/umami-software/umami/blob/master/docker-compose.yml) sets
`DATABASE_URL`, `APP_SECRET: replace-me-with-a-random-string` and a 2FA key inline, publishes
port 3000, and uses the `:latest` image. `DATABASE_URL` is "the only required variable";
`APP_SECRET` is "a random string used to secure authentication tokens"
([environment variables](https://docs.umami.is/docs/environment-variables)). No TLS: "You will
need to either proxy requests from your web server or change the port" ([install](https://docs.umami.is/docs/install)).

**PostHog hobby.** A curl-piped [`deploy-hobby`](https://posthog.com/docs/self-host) script asks
for a tag and a domain. It needs a 4 vCPU / 16 GB VM, and "PostHog will automatically create an
SSL certificate for your domain using LetsEncrypt" through a `proxy` (Caddy) service
([compose](https://github.com/PostHog/posthog/blob/master/docker-compose.hobby.yml)).
Self-hosting is "officially unsupported". [Env vars](https://posthog.com/docs/self-host/configure/environment-variables):
`SECRET_KEY` ("required in production"), `SITE_URL`, `DATABASE_URL`, plus `IS_BEHIND_PROXY` and
`TRUSTED_PROXIES` for running behind your own proxy.

**Matomo.** A PHP app installed through a web wizard. The installer checks the system, takes
MySQL credentials, then "Matomo will add the necessary tables to your database"
([installing](https://matomo.org/faq/on-premise/installing-matomo/)).

## 2. Admin UI and the first admin

| Tool | First admin | Locking down registration |
|---|---|---|
| Plausible CE | Sign-up form on first visit to `BASE_URL` | `DISABLE_REGISTRATION` = `true` / `false` / `invite_only` (default `invite_only`) |
| Umami | Default account `admin` / `umami` created with the tables | No sign-up page; `DISABLE_LOGIN` hides login entirely |
| PostHog | First sign-up becomes staff | No signup toggle in the env var or instance settings pages |
| Matomo | Superuser step in the web installer | Single superuser; others are added by the superuser |

- **Plausible:** "visit `$BASE_URL` and create the first user" ([README](https://github.com/plausible/community-edition));
  registration modes are on the [Configuration](https://github.com/plausible/community-edition/wiki/Configuration)
  page. Because the default is `invite_only`, only the first user can sign up uninvited.
- **Umami:** "a default administrator account with the username admin and the password umami";
  "The first thing you will want to do is log in and change your password" ([login](https://docs.umami.is/docs/login)).
  Default credentials are the one weak spot in this survey: the instance is open until someone
  changes them.
- **PostHog:** "As of PostHog 1.32.0, the first user in any instance is a staff user"
  ([instance settings](https://posthog.com/docs/self-host/configure/instance-settings)).
- **Matomo:** "The superuser is the user that you create when you install Matomo"; "There is
  only one super user in each Matomo installation" ([installing](https://matomo.org/faq/on-premise/installing-matomo/)).

None of the four documents a CLI command for the first admin. The "first visitor claims the
instance" pattern (Plausible, PostHog, Matomo) has a race window between `up` and the first
visit; none of the docs read call it out.

## 3. Collection endpoint: CORS and site keys

| Tool | Endpoint | Site identifier | Secret? | CORS on collection |
|---|---|---|---|---|
| Plausible | `POST /api/event` | `domain` field | Public, no auth | Any origin (`CORSPlug` defaults) |
| Umami | `POST /api/send` | `website` UUID | Public | `Access-Control-Allow-Origin: *` on `/api/*` |
| PostHog | `/capture`, `/batch` | Project token `phc_...` | Public by design | Mirrors any request origin, with credentials |
| Matomo | `matomo.php` (Tracking API) | `idsite` | Public; `token_auth` secret for privileged params | `cors_domains[]` allowlist; `*` "not recommended" |

**Plausible.** The [Events API](https://plausible.io/docs/events-api) requires `domain`, `name`,
`url` and a `User-Agent`; it documents no authentication. The domain must be "the domain name
you used when you added your site". CORS is not documented; the [endpoint source](https://github.com/plausible/analytics/blob/master/lib/plausible_web/endpoint.ex)
applies `CORSPlug.init([])` (library defaults) to everything except the OAuth authorize path.
Per-site control is server-side, not CORS: events are dropped by Shields checks such as
`hostname_allowed?`, IP, page and country blocks ([ingestion source](https://github.com/plausible/analytics/blob/master/lib/plausible/ingestion/event.ex)).

**Umami.** The [`next.config.ts`](https://github.com/umami-software/umami/blob/master/next.config.ts)
sets `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Headers: *` on `/api/:path*`;
the only CORS knob is `CORS_MAX_AGE` ([env vars](https://docs.umami.is/docs/environment-variables)).
The [send route](https://github.com/umami-software/umami/blob/master/src/app/api/send/route.ts)
validates the `website` UUID and returns "Website not found." otherwise. `data-domains` on the
script only makes the tracker run on listed hostnames, matched against `window.location.hostname`
([tracker configuration](https://docs.umami.is/docs/tracker-configuration)); it is client-side.

**PostHog.** Capture and batch are "POST-only public endpoints that use your project token"
([capture API](https://posthog.com/docs/api/capture)). "It is ok for your project token
(starts with phc_) to be public" ([privacy](https://posthog.com/docs/privacy)); personal API
keys (`phx_`) must stay secret. The capture service's legacy routes use a "Very permissive CORS
policy": `AllowOrigin::mirror_request()` with credentials allowed ([router source](https://github.com/PostHog/posthog/blob/master/rust/capture/src/router.rs)).

**Matomo** is the exception. `idsite` is required on every hit; `token_auth` (a "32 character
authorization key") is needed only for privileged parameters such as `cip` or a `cdt` older than
24 hours, and Matomo suggests a dedicated write-only user for it ([Tracking API](https://developer.matomo.org/api-reference/tracking-api)).
CORS is an explicit allowlist (`cors_domains[] = "http://example.com"` in `config.ini.php` or
the admin UI); "Using a wildcard (`*`) for CORS in Matomo is not recommended" because it makes
the Administration and Analytics API "accessible from any website" ([CORS FAQ](https://matomo.org/faq/how-to/faq_18694/)).
The FAQ's concern is the authenticated API, not tracking, and it does not say whether the
setting covers `matomo.php`.

## 4. Backups, upgrades, migrations

| Tool | Migrations | Version pinning | Backup docs |
|---|---|---|---|
| Plausible CE | On container start (`db createdb && db migrate && run`) | Pin patch tag ("Recommended") | None official |
| Umami | On container start (`check-db.js` runs `prisma migrate deploy`) | `:latest` in compose | None |
| PostHog | Web container runs them on start | No tagged self-host releases; "always on the latest image" | "back up all your data" before upgrading, no procedure |
| Matomo | Browser update screen or `console core:update` | Download latest build | Back up `config.ini.php` and the database |

- **Plausible.** Migrations run in the compose `command` ([compose](https://github.com/plausible/community-edition/blob/v3.2.1/compose.yml)).
  The [Upgrade](https://github.com/plausible/community-edition/wiki/Upgrade) page says each
  release "contains specific instructions on how to upgrade", to "Always review the specific
  upgrade instructions provided in the release notes" for majors, calls patch pinning
  "Recommended", and warns that fixes are not backported. Minor upgrade: `git pull` the new tag,
  `docker compose up -d`. There is no backup guide; in [issue #203](https://github.com/plausible/community-edition/issues/203)
  a contributor suggests `pg_dump` plus ClickHouse's own backup docs and warns against copying a
  running database's volume. CE is released "twice per year" and "community supported only"
  ([self-hosting](https://plausible.io/docs/self-hosting)).
- **Umami.** The image's [`start-docker.sh`](https://github.com/umami-software/umami/blob/master/scripts/start-docker.sh)
  runs `check-db.js` ("the one-shot DB check/migration") before the server, and
  `SKIP_DB_MIGRATION` opts out ([env vars](https://docs.umami.is/docs/environment-variables)).
  Update: `docker compose pull` then `up --force-recreate -d`; run `ANALYZE;` after a major
  ([updates](https://docs.umami.is/docs/updates)). No backup guidance.
- **PostHog.** `upgrade-hobby` script; "Before upgrading, make sure you have created back-ups of
  all your data!"; no tagged releases for self-host, run it "the way we run PostHog Cloud: always
  on the latest image" ([upgrading](https://posthog.com/docs/runbook/upgrading-posthog)).
- **Matomo.** "Please back up your Matomo configuration file"; restore also needs a full database
  backup. After replacing files, open Matomo to run the database update, or run
  `./console core:update`, which is "highly recommended" for busy sites, with tracking paused
  ([update FAQ](https://matomo.org/faq/on-premise/update-matomo/)).

## 5. Release notes and changelogs

- **Plausible:** `vMAJOR.MINOR.PATCH` tags with `-rc.N` pre-releases. v3.2.0's notes have a
  summary, an **Upgrade** section with commands, and a **Changelog** split into Added / Changed /
  Fixed; v3.2.1 is a security note with "Who is affected?" and "Mitigation" ([releases](https://github.com/plausible/analytics/releases)).
  [`CHANGELOG.md`](https://github.com/plausible/analytics/blob/master/CHANGELOG.md) uses an
  `## Unreleased` section with `### Added` / `### Removed` headings, in the Keep a Changelog style
  (it does not cite the spec). The CE repo has no GitHub releases of its own ([CE releases](https://github.com/plausible/community-edition/releases)).
- **Umami:** `vMAJOR.MINOR.PATCH` (v3.4.1 is "mainly a security hotfix"). Headings are New
  features / Security / **Migrations** / Fixes / Updates, plus a "Full Changelog" compare link.
  "Migrations" lists schema changes or "None."; there is no "Breaking changes" heading
  ([releases](https://github.com/umami-software/umami/releases)).
- **PostHog:** a product changelog at posthog.com/changelog; no self-host release notes
  ([upgrading](https://posthog.com/docs/runbook/upgrading-posthog)).

## Common pattern

1. **Packaging:** one `compose.yml` with app + Postgres (plus ClickHouse at scale), secrets and
   the public URL in `.env` or the compose file. Two of three Docker-first tools bundle TLS
   (Plausible built-in, PostHog Caddy); Umami and Matomo leave TLS to your proxy. Plausible
   documents both paths.
2. **Required config:** a random secret (`SECRET_KEY_BASE` / `APP_SECRET` / `SECRET_KEY`), the
   public URL, and the database URL.
3. **First admin:** created in the browser. Three of four let the first visitor claim the
   instance; Umami ships default credentials. None uses a CLI. Plausible is the only one with a
   documented registration switch, defaulting to invite-only.
4. **Collection CORS:** open. Plausible, Umami and PostHog accept any origin (`*` or mirrored).
   The site key is public by design and per-site filtering (hostname shields, unknown-site
   rejection) happens server-side after the request is accepted. Matomo alone uses an origin
   allowlist and warns against `*`, but its warning targets the authenticated API.
5. **Migrations:** run automatically on container start (Plausible, Umami, PostHog), with an
   opt-out in Umami. Matomo is the manual outlier, and recommends the CLI for large installs.
6. **Upgrades:** pin a tag, read the release notes, pull, `up -d`. Backups are mostly
   undocumented beyond "back up first"; `pg_dump` is the informal answer.
7. **Release notes:** semver tags, a security patch release when needed, an explicit
   upgrade/migrations section. Plausible's CHANGELOG follows Keep a Changelog headings.

## Implications for OSRA

**CORS default-deny deviates from the standard.** Every Docker-first tool in this survey
accepts browser events from any origin; only Matomo allowlists, and it does so to protect its
cookie-authenticated API. Default-deny until `ALLOWED_ORIGINS` is set is still defensible for
us, for three reasons:

- Our write key is as public as a `phc_` token or Umami website id: it ships in browser JS.
  CORS does not hide it, and server-to-server or `curl` callers ignore CORS entirely. So the
  allowlist is not authentication. Say this in the docs.
- What the allowlist does buy is that a random third-party page cannot make visitors' browsers
  post junk into a workspace that holds B2B pipeline data, where polluted touches skew revenue
  credit. That is cheap to configure because a B2B customer has a handful of domains, unlike a
  publisher-scale analytics tool.
- The cost is first-run friction: events silently fail in the browser until the variable is
  set. Mitigate with a clear startup log line and a dashboard warning when `ALLOWED_ORIGINS` is
  empty, and consider a per-workspace allowlist (closer to Plausible's per-site hostname shield)
  rather than only a global env var.

Never send `Access-Control-Allow-Credentials` on `/v1/batch`: Basic auth with the write key
goes in a header the SDK sets, so cookies are not needed, and Matomo's warning shows why
credentials plus a wildcard is the dangerous combination.

**First admin: `createsuperuser` is safer than the norm.** It avoids Umami's default password
and the first-visitor race of Plausible, PostHog and Matomo. Django supports a non-interactive
variant: `createsuperuser --noinput` reads `DJANGO_SUPERUSER_PASSWORD` and
`DJANGO_SUPERUSER_<FIELD>` such as `DJANGO_SUPERUSER_EMAIL` ([django-admin](https://docs.djangoproject.com/en/5.2/ref/django-admin/)).
If we add an env-var bootstrap, make it idempotent (skip if any superuser exists) and tell users
to remove the password from `.env` afterwards. Have no public sign-up, like Umami.

**Migrations on container start matches the standard** (Plausible, Umami, PostHog). Run
`migrate` in the entrypoint before the server, offer a `SKIP_MIGRATIONS` opt-out like Umami's
`SKIP_DB_MIGRATION`, and say in each release's notes whether it contains migrations.

**Reverse proxy: bring your own, with a documented Caddy example.** Bundled TLS is common
(Plausible, PostHog), but Plausible itself documents both paths and Umami ships none. For a
small Django app, document a two-line Caddyfile plus an nginx snippet, require
`X-Forwarded-For`/`X-Forwarded-Proto` handling (Plausible's proxy configs forward
`X-Forwarded-For`; PostHog has `IS_BEHIND_PROXY` and `TRUSTED_PROXIES`), and leave a bundled Caddy profile as an optional later addition.

**Releases:** semver tags, a pinned image tag in the sample compose (not `:latest`), and a
Keep a Changelog `CHANGELOG.md` whose release entries carry "Upgrade" and "Migrations" notes in
the style of Plausible and Umami. Document `pg_dump`/`pg_restore`, since none of the four tools
does this well.
