# Self-hosting

Run Open Source Revenue Attribution on your own server: the Django app (gunicorn, static files
served by WhiteNoise) and PostgreSQL 17, from `compose.production.yml`, behind a reverse proxy
that terminates TLS.

How this compares with Plausible, Umami, PostHog and Matomo, with sources:
[research/m5-self-hosting.md](research/m5-self-hosting.md). Where we differ:
[decisions.md](decisions.md) (M5).

**Verified 2026-10-29** on Docker 28 with Compose v2 and Caddy 2 (`tls internal` on
localhost): build, start, migrations on PostgreSQL 17, first admin, sign-in over HTTPS, demo
import, every page, events from an allowed and a refused origin, `pg_dump` backup and restore.
Not yet tried on a public domain with a real Let's Encrypt certificate.

## Contents

1. [Requirements](#requirements)
2. [Install](#install)
3. [Create the first admin](#create-the-first-admin)
4. [Reverse proxy and TLS](#reverse-proxy-and-tls)
5. [Send events from your site](#send-events-from-your-site)
6. [Forward from an existing RudderStack setup](#forward-from-an-existing-rudderstack-setup)
7. [Configuration reference](#configuration-reference)
8. [Security checklist](#security-checklist)
9. [Backups and restore](#backups-and-restore)
10. [Upgrades and migrations](#upgrades-and-migrations)
11. [Troubleshooting](#troubleshooting)

## Requirements

- A Linux host with Docker Engine and the Compose v2 plugin (`docker compose version`).
- 1 GB RAM is enough for the demo data. Touchpoints are recomputed from all events on each
  collection request, so the app is not tuned for large event volumes yet.
- A domain name pointing at the host, and ports 80 and 443 open, for automatic HTTPS.

## Install

```sh
git clone https://github.com/ChristopherLandaverde/open-source-revenue-attribution.git
cd open-source-revenue-attribution
git checkout v0.1.0            # a release tag; see CHANGELOG.md (not tagged yet: use main)
cp .env.example .env
```

Edit `.env`. These are the values a server needs; every other setting is optional and listed
in `.env.example`:

```sh
DEBUG=false
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_urlsafe(50))">
POSTGRES_PASSWORD=<python3 -c "import secrets; print(secrets.token_hex(24))">
ALLOWED_HOSTS=attribution.acme.example
CSRF_TRUSTED_ORIGINS=https://attribution.acme.example
BEHIND_PROXY=true
SECURE_HSTS_SECONDS=3600
# Optional: accept browser events only from your own sites (see "Send events from your site").
# COLLECT_ALLOWED_ORIGINS=https://www.acme.example
```

Use letters and digits only for `POSTGRES_PASSWORD`: the stack puts it in a database URL.

Build and start:

```sh
docker compose -f compose.production.yml up -d --build --wait
docker compose -f compose.production.yml exec app python manage.py check --deploy
```

`--wait` returns once PostgreSQL and the app pass their health checks. The app container runs
`migrate` before gunicorn starts. It listens on `127.0.0.1:8000` only (change with `APP_PORT`),
so nothing is public until the reverse proxy is set up. `check --deploy` should print
no warnings or errors (two checks are silenced, as explained in [decisions.md](decisions.md)).
With the default `COLLECT_ALLOWED_ORIGINS` it also prints one info line, `osra.I001`, which
says browser events are accepted from any site.

## Create the first admin

Every page except the event endpoint needs a signed-in user. There is no public sign-up and no
default password. Create the first account from the server:

```sh
docker compose -f compose.production.yml exec app python manage.py createsuperuser
```

It asks for a username, an email address and a password. Without a terminal (provisioning
scripts), pass the password in the environment and remove it afterwards:

```sh
docker compose -f compose.production.yml exec -e DJANGO_SUPERUSER_PASSWORD='<password>' app \
  python manage.py createsuperuser --noinput --username admin --email admin@acme.example
```

`--noinput` fails if the username exists, so running it twice changes nothing. Sign in at
`https://<your domain>/accounts/login/`. Add more people, or reset a password, in Django admin
at `/admin/` (superusers only). Every signed-in user sees all data: there are no roles or
per-workspace permissions yet.

### API tokens for agents and scripts

The read-only JSON API at `/api/v1/` (fields and examples in the
[README](../README.md#use-it-from-an-agent--api)) takes a per-user Bearer token:

```sh
docker compose -f compose.production.yml exec app python manage.py createapitoken admin --name agent
curl -H "Authorization: Bearer <token>" https://<your domain>/api/v1/readiness
```

The token is printed once and only its SHA-256 hash is stored. It reads everything its user
can see and cannot write. Revoke it in Django admin under API tokens (delete it); deactivating
the user also stops its tokens.

### Try it with the demo data

```sh
docker compose -f compose.production.yml exec app python manage.py load_sample_data
```

This loads the synthetic demo accounts, contacts, opportunities and touchpoints into the same
dataset your real data goes in, and there is no command to remove them again. Try it on a
throwaway stack, then wipe it with `docker compose -f compose.production.yml down -v` (deletes
the database volume) before importing real data.

## Reverse proxy and TLS

Bring your own proxy, as with Umami and Matomo. Plausible also documents this route. The proxy
must:

- terminate TLS and forward to `127.0.0.1:8000`;
- set (overwrite, never append) `X-Forwarded-Proto`. With `BEHIND_PROXY=true`, Django trusts
  that header to know the request was HTTPS. That is only safe because the app port is bound to
  127.0.0.1 and only the proxy can reach it;
- pass the `Host` header through, or list the public origin in `CSRF_TRUSTED_ORIGINS`.

**Caddy** (gets and renews a Let's Encrypt certificate itself):
[`deploy/Caddyfile.example`](../deploy/Caddyfile.example)

```caddy
attribution.acme.example {
	encode zstd gzip
	reverse_proxy 127.0.0.1:8000
}
```

**nginx** with certbot certificates:
[`deploy/nginx.conf.example`](../deploy/nginx.conf.example). Raise `client_max_body_size` if
your CSV uploads are larger than 20 MB.

With `DEBUG=false`, plain HTTP requests are redirected to HTTPS, session and CSRF cookies are
`Secure`, and `SECURE_HSTS_SECONDS` sends HSTS. Start at 3600 and raise it to 31536000 once
HTTPS works. Browsers remember HSTS, so a mistake cannot be undone quickly.
`includeSubDomains` and `preload` stay off unless you set them, because they bind your whole
parent domain. A plain-HTTP deployment on a private network needs `HTTPS=false`, and
`check --deploy` will warn about it.

## Send events from your site

```sh
docker compose -f compose.production.yml exec app python manage.py create_workspace website
# Write key: <key>
```

Load the RudderStack JavaScript SDK (3.35.0, the version in `static/vendor/`) on your site with
that write key and your server's URL as the data plane URL:

```html
<script src="https://cdn.jsdelivr.net/npm/@rudderstack/analytics-js@3.35.0/dist/npm/modern/bundled/umd/index.js"></script>
<script>
  const osra = new window.rudderanalytics.RudderAnalytics();
  osra.load("<write key>", "https://attribution.acme.example", {
    // This server is not a RudderStack control plane: give the SDK its source config here.
    getSourceConfig: () => ({
      source: { id: "osra", name: "OSRA", enabled: true, config: {}, destinations: [] },
    }),
  });
  osra.page();
</script>
```

Keep `getSourceConfig`. Without it the SDK first fetches its configuration from
`https://api.rudderstack.com` with your write key, gets an error, and sends nothing. The script
URL is the same file as `static/vendor/rudderstack-analytics-js-3.35.0.bundled.umd.js`
(SHA-256 in `static/vendor/README.md`); you can serve your own copy instead. When a visitor
becomes a known contact, call `osra.identify("<contact_id>")`: only an identify
links earlier anonymous page views to a contact.

Events go to `/v1/page`, `/v1/track` and `/v1/identify` (or `/v1/batch`). The rules for what
is accepted are in [contract.md](contract.md), section 3. Checked 2026-10-30 with this snippet
on a page served from another origin: the page view was accepted
([research](research/rudderstack-forwarding.md#1-the-javascript-sdk-and-a-custom-data-plane)).

**Allowed origins.** By default, `/v1/` accepts browser events from pages on any site, as
Plausible, Umami and PostHog do (`COLLECT_ALLOWED_ORIGINS=*`). Your site works with no extra
setting. To accept browser events only from your own sites, list their origins as scheme and
host, comma-separated, with no path:

```sh
COLLECT_ALLOWED_ORIGINS=https://www.acme.example,https://app.acme.example
```

Then a browser request from any other origin gets `403` on the preflight and on the POST, and
nothing is stored. This server's own pages are always allowed. So are requests without an
`Origin` header (your backend, `curl`, a RudderStack server forwarding events), which need only
the write key.

Neither setting is **authentication**. The write key is visible in your pages' JavaScript,
and a non-browser client can send any `Origin` header it likes. A list only stops other
websites from making their visitors' browsers post events into your revenue data. The
**Events** page shows the current setting. Reasons: [decisions.md](decisions.md).

Check from the server:

```sh
curl -si -X OPTIONS https://attribution.acme.example/v1/batch \
  -H 'Origin: https://www.acme.example' -H 'Access-Control-Request-Method: POST' | head -1
# HTTP/2 204    (allowed)      HTTP/2 403    (a list is set and this origin is not on it)
```

## Forward from an existing RudderStack setup

If your site already sends events to RudderStack (RudderStack Cloud or a self-hosted
`rudder-server`), you can forward them here with a destination instead of adding a second SDK.
These steps follow RudderStack's destination docs and code, and the documented payloads are
tested against this server (`tests/test_rudderstack_forwarding.py`). They have **not yet been
run from a live RudderStack workspace**. Research and sources:
[research/rudderstack-forwarding.md](research/rudderstack-forwarding.md).

1. Create a workspace for RudderStack and encode its write key for a Basic auth header:

   ```sh
   docker compose -f compose.production.yml exec app python manage.py create_workspace rudderstack
   # Write key: <key>
   printf '%s:' '<key>' | base64       # the key, a colon, nothing after it
   ```

2. In RudderStack, connect your source to a new **Webhook** destination:

   | Setting | Value |
   |---|---|
   | Webhook URL | `https://attribution.acme.example/v1/track` |
   | URL Method | `POST` |
   | Headers | Key `Authorization`, value `Basic <the base64 from step 1>` |

   Or use the **HTTP Webhook** destination: Base URL as above, Authentication **Basic Auth**
   with Username = the write key (not base64; the password is ignored), Method `POST`, Body Format
   `JSON`, and **Send the event payload as is** on. **Enable Batching** may be on or off; batched
   delivery sends a bare JSON array accepted by `/v1/batch`.

3. Send a few events, then open **Events**. Delivery errors show in the destination's
   **Live Events** tab in RudderStack.

What to expect:

- One URL takes every event type: the event's own `type` decides, not the path, so `/v1/track`
  also takes page and identify events.
- Event time is the `timestamp` RudderStack sets on every event, used as is.
- `userId` is read as a `contact_id`. One that isn't a valid ID, such as an email address, is
  refused with `INVALID_ID`. A valid ID that isn't an imported contact is kept and becomes a
  touchpoint after the import that adds it ([contract §3](contract.md#3-events-rudderstack)).
- `COLLECT_ALLOWED_ORIGINS` doesn't apply: RudderStack's servers send no `Origin` header, so
  only the write key is checked.
- Each request carries one event, and every request recomputes touchpoints (README, Known
  limits). That is fine at small volumes.

## Configuration reference

Every setting, with its default and production value, is in
[`.env.example`](../.env.example). A test fails if a setting is read in `config/settings.py`
without being listed there. The ones specific to the Docker stack:

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_PASSWORD` | required | Database password; the stack builds `DATABASE_URL` from it |
| `MIGRATE_ON_START` | `true` | Run `migrate` when the app container starts |
| `WEB_CONCURRENCY` | `2` | gunicorn worker processes |
| `APP_PORT` | `8000` | Port on 127.0.0.1 the proxy forwards to |
| `OSRA_VERSION` | `local` | Tag for the built image, e.g. `0.1.0` |
| `OSRA_ENV_FILE` | `.env` | The env file the app container reads |

## Security checklist

`manage.py check --deploy` checks these. Run it after every configuration change; CI runs it
with production-like settings.

| Check | How | Checked by |
|---|---|---|
| `DEBUG` off | `DEBUG=false` (forced in the compose file) | Django `security.W018` |
| Long random `SECRET_KEY` | 50+ random characters | Django `security.W009` |
| `ALLOWED_HOSTS` is your domain | never `*` | `osra.W001` |
| HTTPS redirect, `Secure` cookies | on by default when `DEBUG=false` | Django `security.W008`, `W012`, `W016`, and `osra.W005` |
| HSTS | `SECURE_HSTS_SECONDS` > 0 | Django `security.W004` |
| Proxy header trusted only behind the proxy | `BEHIND_PROXY=true`, app bound to 127.0.0.1 | this guide |
| Form posts from your domain | `CSRF_TRUSTED_ORIGINS=https://<domain>` | sign-in fails with 403 if wrong |
| Browser events only from your sites (optional) | `COLLECT_ALLOWED_ORIGINS` lists origins instead of the default `*` | `osra.I001` (info: unrestricted), `osra.W006` (malformed entry) |
| SDK demo page off | leave `COLLECT_DEMO_PAGE` unset | `osra.W003` |
| PostgreSQL, not SQLite | the compose stack | `osra.W004` |
| Admin accounts | strong passwords, Django's validators enforce length and common-password rules | `createsuperuser` |
| API tokens | one per agent or script, deleted in the admin when no longer used; sent only over HTTPS | `createapitoken` |

The database port is not published, the app runs as a non-root user, and `.env` is excluded
from the image (`.dockerignore`).

## Backups and restore

Everything (records, events, users, write keys) is in PostgreSQL. Back it up with `pg_dump`,
and copy the dump off the host:

```sh
docker compose -f compose.production.yml exec -T db \
  pg_dump -U osra -d osra --format=custom > osra-$(date +%F).dump
```

Keep `.env` too (in a password manager, not in git). Without the same `SECRET_KEY`, every
user's session ends, but no data is lost.

Restore into a running stack, replacing the current data:

```sh
docker compose -f compose.production.yml stop app
docker compose -f compose.production.yml exec -T db psql -U osra -d postgres \
  -c "DROP DATABASE osra" -c "CREATE DATABASE osra OWNER osra"
docker compose -f compose.production.yml exec -T db \
  pg_restore -U osra -d osra --no-owner < osra-2026-10-29.dump
docker compose -f compose.production.yml start app
```

Test a restore once before you rely on the backups.

## Upgrades and migrations

1. Read the release's entry in [CHANGELOG.md](../CHANGELOG.md). Every release says whether it
   has database migrations and whether anything must be done by hand.
2. Back up (above).
3. Switch to the new release and rebuild:

   ```sh
   git fetch --tags && git checkout v0.2.0
   OSRA_VERSION=0.2.0 docker compose -f compose.production.yml up -d --build --wait
   docker compose -f compose.production.yml logs app | grep -A20 "Running migrations"
   ```

   The new container applies migrations before it serves requests (as Plausible, Umami and
   PostHog do). To run them yourself instead, set `MIGRATE_ON_START=false` and run
   `docker compose -f compose.production.yml run --rm app python manage.py migrate` before
   `up`.
4. Check `/healthz`, sign in, and open the model comparison.

**Rolling back:** migrations are not reversed automatically. Check out the previous tag and
restore the backup you made in step 2.

PostgreSQL major upgrades (17 to 18, for example) need a dump and restore into a new volume.
The `postgres` image cannot upgrade a data directory in place.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Set POSTGRES_PASSWORD in .env` when starting | Add `POSTGRES_PASSWORD` to `.env` |
| `ImproperlyConfigured: Set the SECRET_KEY environment variable` | Add `SECRET_KEY` to `.env` |
| `400 Bad Request` on every page | The domain is not in `ALLOWED_HOSTS` |
| Redirect loop | The proxy does not send `X-Forwarded-Proto: https`, or `BEHIND_PROXY` is not `true` |
| `403 CSRF verification failed` when signing in | Add `https://<domain>` to `CSRF_TRUSTED_ORIGINS` |
| Browser console: CORS error on `/v1/batch`; response `403 Origin ... is not allowed` | `COLLECT_ALLOWED_ORIGINS` lists origins and this page's isn't one of them. Add it, or remove the setting, and restart the app |
| `401` from `/v1/` | Missing or wrong write key (`create_workspace <name>` prints it again) |
| Unstyled pages | The image was built without `collectstatic`. Rebuild with `--build` |

Logs: `docker compose -f compose.production.yml logs -f app`. Health: `GET /healthz` returns
`{"status": "ok"}` when the app can reach the database.
