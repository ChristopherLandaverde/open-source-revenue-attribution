# Vendored browser assets

Pinned copies, served by Django's static files. No Node toolchain. To upgrade, download the
new pinned file, rename it with its version, update references, and update this table.

| File | Package | Version | License | Source | SHA-256 |
|---|---|---|---|---|---|
| `htmx-2.0.4.min.js` | `htmx.org` | 2.0.4 | 0BSD | https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js | `e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447` |
| `fonts/dm-sans-5.1.0-latin-wght.woff2` | `@fontsource-variable/dm-sans` | 5.1.0 | OFL-1.1 (`fonts/OFL-dm-sans.txt`) | https://cdn.jsdelivr.net/npm/@fontsource-variable/dm-sans@5.1.0/files/dm-sans-latin-wght-normal.woff2 | `258f9f1b553bb57419619f41d3b1445226c7bc63d2a3409efef4a68426709e94` |
| `fonts/ibm-plex-mono-5.1.0-latin-400.woff2` | `@fontsource/ibm-plex-mono` | 5.1.0 | OFL-1.1 (`fonts/OFL-ibm-plex-mono.txt`) | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.1.0/files/ibm-plex-mono-latin-400-normal.woff2 | `3c5a451f9ec27a354b0c2bcca636c6ec17a651281aabf29f8427e210a1d31e85` |
| `fonts/ibm-plex-mono-5.1.0-latin-500.woff2` | `@fontsource/ibm-plex-mono` | 5.1.0 | OFL-1.1 (`fonts/OFL-ibm-plex-mono.txt`) | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.1.0/files/ibm-plex-mono-latin-500-normal.woff2 | `756026ff72eb76fd971ac4b7504cec55eef62109d2684c2cad8da32170b80b37` |
| `rudderstack-analytics-js-3.35.0.bundled.umd.js` | `@rudderstack/analytics-js` | 3.35.0 | MIT | https://cdn.jsdelivr.net/npm/@rudderstack/analytics-js@3.35.0/dist/npm/modern/bundled/umd/index.js | `20a6f7fc89d2706bc5cc440e3ed5e4730def89f1b3785d70d03e476fa183bbb5` |

The RudderStack SDK is the **bundled** build (plugins included), so it does not fetch plugin
code from RudderStack's CDN at runtime. It is loaded only by the SDK demo page
(`/events/demo/`, on when `DEBUG` or `COLLECT_DEMO_PAGE` is true), which passes a local
`getSourceConfig` and `polyfillIfRequired: false`, so the SDK makes no request to RudderStack
or any third party (checked with Playwright: every request went to the local server).

Fonts are the Focosys brand faces (DM Sans, IBM Plex Mono), served locally so the app makes no
font requests to Google.
