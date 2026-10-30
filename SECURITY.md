# Security policy

## Supported versions

| Version | Supported |
|---|---|
| `main` and the latest release (0.1.x, not yet tagged) | Yes |
| Anything older | No: upgrade first ([docs/self-hosting.md](docs/self-hosting.md#upgrades-and-migrations)) |

Security fixes are released on their own as a patch version, with a changelog entry under
**Security** ([docs/release.md](docs/release.md)).

## Reporting a vulnerability

Report it privately through GitHub's private vulnerability reporting: the repository's
**Security** tab → **Report a vulnerability**
([how it works](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)).
Don't open a public issue, and don't include real customer data. Say what is affected, how to
reproduce it on the synthetic demo data, and the version or commit. You'll get an
acknowledgement, and the fix and advisory will be coordinated with you before disclosure.

## Security model

What the app protects, and what it deliberately does not:

- **Sign-in on every page.** Reports, readiness, validation, CSV import, events, journeys and
  Django admin need a signed-in user (Django auth with its password validators). Only three
  paths are open without signing in: `/v1/` (event collection), the sign-in page and
  `/healthz` (returns `{"status": "ok"}` and nothing else). There is no public sign-up and no
  default password. The first admin is created on the server with
  `manage.py createsuperuser`.
- **One role, one dataset.** Every signed-in user can see and import everything. Workspaces
  identify event senders but do not isolate data. Give accounts only to people who may see
  all revenue data.
- **Write keys are public.** `/v1/` authenticates senders with a per-workspace write key sent
  as HTTP Basic auth. The key ships in your pages' JavaScript, so anyone can read it and send
  events with it. It authorizes writing events only, never reading data. Events still pass
  the data contract (validation, deduplication on `messageId`), and every refused payload is
  stored with its reason so that junk can be seen.
- **CORS.** By default `/v1/` accepts browser requests from any origin, as Plausible, Umami
  and PostHog do. It echoes the request's origin and never sends
  `Access-Control-Allow-Credentials`, because no cookies are used. Setting
  `COLLECT_ALLOWED_ORIGINS` to a list of origins makes `/v1/` refuse browser requests from
  any other origin with 403, before storing anything. Neither mode is authentication:
  non-browser clients can send any `Origin` header, or none.
- **Transport and cookies.** With `DEBUG=false`, HTTP redirects to HTTPS, session and CSRF
  cookies are `Secure`, and HSTS is sent when `SECURE_HSTS_SECONDS` is set. Run
  `manage.py check --deploy` to find unsafe settings
  ([checklist](docs/self-hosting.md#security-checklist)).
- **Secrets.** `SECRET_KEY` and the database password come from the environment (`.env`,
  which is never committed and is excluded from the Docker image). The database port is not
  published by the production compose file, and the app container runs as a non-root user.

Out of scope: denial of service by event volume (there is no rate limit; put one in your
proxy), and anything that requires shell or database access to the server.
