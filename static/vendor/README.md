# Vendored browser assets

Pinned copies, served by Django's static files. No Node toolchain. To upgrade, download the
new pinned file, rename it with its version, update references, and update this table.

| File | Package | Version | License | Source | SHA-256 |
|---|---|---|---|---|---|
| `htmx-2.0.4.min.js` | `htmx.org` | 2.0.4 | 0BSD | https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js | `e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447` |
| `rudderstack-analytics-js-3.35.0.bundled.umd.js` | `@rudderstack/analytics-js` | 3.35.0 | MIT | https://cdn.jsdelivr.net/npm/@rudderstack/analytics-js@3.35.0/dist/npm/modern/bundled/umd/index.js | `20a6f7fc89d2706bc5cc440e3ed5e4730def89f1b3785d70d03e476fa183bbb5` |

The RudderStack SDK is the **bundled** build (plugins included), so it does not fetch plugin
code from RudderStack's CDN at runtime. It is vendored for the M2 collection milestone and is
**not loaded by any page yet**; M0 has no live tracking and needs no write key.
