# RudderStack: pointing the SDK at this server, and forwarding from an existing setup

Researched 2026-10-30 from primary sources only: rudderstack.com docs and RudderStack's own
code (rudder-server, rudder-transformer, and the vendored SDK). Sources are listed at the end.
Tests: `tests/test_rudderstack_forwarding.py` (forwarding) and `tests/test_security.py` (CORS).

Two questions:

1. How does a site point the RudderStack JavaScript SDK at a data plane that isn't
   RudderStack's, and do our docs say it correctly?
2. How does someone who already runs RudderStack (Cloud, or self-hosted `rudder-server`) forward
   events to a third-party HTTP endpoint, and does `/v1/` accept that as is?

## Answers in short

- **SDK: `load(writeKey, dataPlaneUrl)` alone does not work against this server.** The SDK
  first fetches its source config from RudderStack's control plane (`configUrl`, default
  `https://api.rudderstack.com`). Our write keys are unknown there, so the fetch fails and the
  SDK stops before sending anything. RudderStack's documented option for this is
  `getSourceConfig`, which "returns custom configuration data to use instead of making a request
  to the control plane". Our SDK demo page already used it; `docs/self-hosting.md` didn't
  say so. It does now.
- **SDK from another site was blocked by our CORS preflight.** SDK 3.35.0 sends `SentAt` on
  every request and `Rsa-Retry-*` / `Rsa-Since-*` headers on retries. `/v1/` allowed only
  `Authorization, Content-Type, AnonymousId`, so the browser blocked each event before sending
  it. rudder-server allows any request header. `/v1/` now does the same: the preflight echoes
  the requested header names (fixed in the same PR as this note).
- **Forwarding works as is for one event per request:** the **Webhook** destination (POST),
  and the **HTTP Webhook** destination with batching off. Put the write key in a Basic
  `Authorization` header (Webhook) or in Basic Auth's Username (HTTP Webhook). Event time comes
  from the `timestamp` that rudder-server sets, used as is.
- **HTTP Webhook with batching on doesn't work:** it sends a bare JSON array, and `/v1/batch`
  takes only `{"batch": [...]}`. Changing that changes the collection contract, so it's
  [issue #16](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/16)
  (`needs-decision`). No code was changed for it.

## 1. The JavaScript SDK and a custom data plane

**What RudderStack documents** ([Load JavaScript SDK][load]):

- `rudderanalytics.load(WRITE_KEY, DATA_PLANE_URL, [loadOptions]);` The data plane URL is
  "the location where events are routed".
- `configUrl`: "The control plane endpoint serving your destination configurations. Default
  value: `https://api.rudderstack.com`." The SDK appends `/sourceConfig`.
- `getSourceConfig`: "Returns custom configuration data to use instead of making a request to
  the control plane." The doc's example passes it as a load option.

**What the vendored SDK 3.35.0 does** (`static/vendor/rudderstack-analytics-js-3.35.0.bundled.umd.js`,
byte-identical to the jsdelivr file `@rudderstack/analytics-js@3.35.0/dist/npm/modern/bundled/umd/index.js`,
SHA-256 `20a6f7fc…bbb5`, checked 2026-10-30):

- `ConfigManager.processConfig`: when the config response is missing, it reports
  `Failed to fetch the source config` and returns. The SDK never becomes ready and sends no events.
- Event requests go to `<dataPlaneUrl>/v1/<type>` (or `/v1/batch` when the queue batches),
  with `Authorization: Basic base64(<write key>:)`, `AnonymousId: base64(anonymousId)` and
  `SentAt` on every delivery. Retries also send `Rsa-Retry-Attempt`, `Rsa-Since-Last-Attempt`,
  `Rsa-Since-First-Attempt`, `Rsa-Retry-Reason`, and `Rsa-Recovered` for events reclaimed from
  storage.

**Checked in a browser** (Playwright 1.62 / Chromium). The page was served from
`http://127.0.0.1:8001` and loaded the jsdelivr 3.35.0 bundled build. The app ran on
`http://127.0.0.1:8000` (`DEBUG=true`, SQLite, demo data, a new workspace):

| Load call | What happened |
|---|---|
| `load(key, "http://127.0.0.1:8000")` | `GET https://api.rudderstack.com/sourceConfig/?…&writeKey=<our key>` returned `400`; console: `ConfigManager:: Failed to fetch the source config`. No request reached the app. Our write key was also sent to RudderStack. |
| the same, plus `getSourceConfig` (on `main` at `4d81528`) | No request to RudderStack. The preflight to `/v1/page` failed: "Request header field sentat is not allowed by Access-Control-Allow-Headers in preflight response", then the same for `rsa-since-last-attempt` on each retry. No event stored. |
| the same, after the CORS fix | `POST /v1/page` → `200`; one page event stored as `accepted`. |
| the exact snippet in `docs/self-hosting.md`, on a URL with UTM parameters, then `osra.identify("con-nw-li")` | `POST /v1/page` and `POST /v1/identify` → `200`, both accepted. The page view became a touchpoint for `con-nw-li` (`docs-check / sdk / snippet`, stitched from the browser's `anonymousId`, `FIRST_SESSION`). No request went anywhere but the page, jsdelivr and the app. |

Same-origin pages, such as our `/events/demo/`, send no preflight, so the demo page never hit
this.

**What rudder-server's CORS does** ([gateway/handle_lifecycle.go][gw-cors] at `ea33835`):
`cors.New(cors.Options{AllowOriginFunc: … true, AllowCredentials: true, AllowedHeaders: []string{"*"}, MaxAge: 900})`.
rs/cors v1.11.1 (the version in rudder-server's `go.mod`) answers `AllowedHeaders "*"` by
echoing the preflight's `Access-Control-Request-Headers` ([rs/cors cors.go][rscors]), and it
varies on `Origin, Access-Control-Request-Method, Access-Control-Request-Headers`.

**Adopted:** the preflight echoes every well-formed header name the browser asks for (an RFC
9110 token; anything else is dropped), with `Vary: Access-Control-Request-Headers`. The list
`Authorization, Content-Type, AnonymousId` is the fallback when none is asked for. Echoing the
names instead of keeping a list means a newer SDK, or RudderStack's CDN build on a customer
site, can add a header without breaking delivery. The M5 deviations stay as they were (see
[decisions.md](../decisions.md)): origins can be restricted with `COLLECT_ALLOWED_ORIGINS`,
the origin is echoed rather than `*`, and `Access-Control-Allow-Credentials` is never sent,
where rudder-server sends it. Header names don't widen access: `/v1/` reads only
`Authorization` and the body.

## 2. Forwarding from an existing RudderStack setup

RudderStack has two destinations for "send my events to an HTTP endpoint".

### Webhook destination

[Setup guide][wh-setup], connection settings:

- **Webhook URL**: "the endpoint where RudderStack sends the events". HTTP and HTTPS; HTTPS
  needs "a valid TLS certificate".
- **URL Method**: "By default, RudderStack uses the POST method."
- **Headers**: "Add custom headers for your events." RudderStack adds `user-agent: RudderLabs`
  and `content-type: application/json` to POST and PUT. There is no separate auth setting; a
  static `Authorization` header is set here.

[Cloud mode][wh-cloud], payload: for POST, PUT and PATCH, "RudderStack sends the whole event
payload (shown above) as the JSON body". GET and DELETE send properties or traits as query
parameters. The page shows identify, page and track samples: plain RudderStack events with
`type`, `messageId`, `anonymousId`, `userId`, `originalTimestamp`, `sentAt`, `context`,
`properties`, `integrations`.

**One event per request.** RudderStack's announcement of the newer destination says the Webhook
destination has "No native batching: You must send event to the endpoint individually"
([release note][http-release]). The transformer confirms it: `processEvent` sets
`response.body.JSON = message` for POST and merges the configured headers
([webhook/transform.js][wh-code]). It also copies `request_ip` to `context.ip`.

### HTTP Webhook destination

[Setup guide][http-setup]:

- **Base URL**, plus optional path and query parameters.
- **Authentication**: No Auth, **Basic Auth** (Username, Password), Bearer Token, API Key.
  rudder-transformer builds Basic Auth as `base64(`${username}:${password}`)`
  ([http/utils.ts][http-code]), so an unset password is encoded as the string `undefined`.
- **Method**: POST by default. **Body Format**: JSON, XML or FORM.
- **Request Body**: "The Send the event payload as is setting is toggled on by default, meaning
  the source event is sent to the webhook as is."
- **Enable Batching**: JSON only. "It sends the batched events in the JSON array format, for
  example, `[{Event1},{Event2},....{EventN}]`." At most 100 per batch, sent when full or after
  5 seconds. The transformer puts the merged events in `body.JSON_ARRAY.batch`.

### What rudder-server adds before any destination

[Common fields][common]: RudderStack sets `receivedAt` ("Time in UTC when RudderStack ingests
the event") and `timestamp`, which it "calculates … to account for any client-side clock skew
using the formula: timestamp = receivedAt - (sentAt - originalTimestamp)". The processor does
this in `enhanceWithTimeFields` ([processor.go][proc]): it keeps an existing `timestamp`,
otherwise it computes one, and writes all four times in RFC 3339 with milliseconds. It also sets
`request_ip`.

So forwarded events carry a server `timestamp`. Our contract (§3, event time rule 1) uses it as
is, with no second skew correction. The docs' samples, captured at the SDK, have no
`timestamp`. Sent to us like that, they would be corrected against our receive time, which
includes RudderStack's queueing delay. Real deliveries don't hit that case.

### Does `/v1/` accept it?

Tested with the docs' identify, page and track samples, field for field, as rudder-server
delivers them (plus `receivedAt`, `timestamp`, `request_ip`, `context.ip`). Values that look
like personal data were swapped for `*.example` ones.

| Setup | Result |
|---|---|
| Webhook, POST, URL `…/v1/track`, header `Authorization: Basic base64(<write key>:)` | **Accepted.** `/v1/page`, `/v1/track` and `/v1/identify` each take any event type: the event's `type` decides. Time from `timestamp`; the payload is stored verbatim. |
| HTTP Webhook, POST, JSON, payload as is, batching off, Basic Auth Username = write key | **Accepted.** We read only the username, so an empty, `undefined` or any other password works. Write key as the *password* with an empty username → `401`. |
| HTTP Webhook with **Enable Batching** | **Not accepted.** `/v1/batch` → `400`; a single-event path → `200` with the array refused (`MISSING_REQUIRED_FIELD`). Nothing stored. [Issue #16](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/16). |
| Webhook with GET or DELETE | Not supported: `/v1/` is POST only (`405`), and those methods send no event body. |
| Same event delivered twice (a retry) | Counted once (`duplicate`, `times_received = 2`). |
| `COLLECT_ALLOWED_ORIGINS` set to a list | Doesn't apply: server-to-server requests send no `Origin`. |
| The docs' page sample as is | Refused, `INVALID_ID` on `userId`: the sample's `userId` is an email address, and our `userId` must be a `contact_id`. This is the contract's identity rule, not the transport. With a `contact_id` it is accepted. |

Refused events still get `200`, as for the SDK (contract §3), so a refusal is not redelivered.
Bad or missing write keys get `401`. How RudderStack treats each status (retry or drop) was not
checked for this note.

**Volume.** One event per request means one touchpoint recompute per forwarded event (README,
Known limits). That is fine at demo volume and is part of the case for option A in issue #16.

## Not verified

- No RudderStack Cloud workspace or rudder-server instance was run. The payloads and headers
  come from RudderStack's docs and transformer code, not from a live delivery. A live run is
  still needed before the README claims more than "documented and tested against the
  documented payload".
- The HTTP Webhook dashboard's handling of an empty Basic Auth password wasn't seen. The code
  sends `undefined` when it is unset, and we accept either.

## Sources

[load]: https://www.rudderstack.com/docs/sources/event-streams/sdks/rudderstack-javascript-sdk/load-js-sdk/
[wh-setup]: https://www.rudderstack.com/docs/destinations/webhooks/setup-guide/
[wh-cloud]: https://www.rudderstack.com/docs/destinations/webhooks/cloud-mode/
[http-setup]: https://www.rudderstack.com/docs/destinations/http-webhook/setup-guide/
[http-release]: https://www.rudderstack.com/docs/releases/http-webhook-destination/
[common]: https://www.rudderstack.com/docs/event-spec/standard-events/common-fields/
[wh-code]: https://github.com/rudderlabs/rudder-transformer/blob/develop/src/v0/destinations/webhook/transform.js
[http-code]: https://github.com/rudderlabs/rudder-transformer/blob/develop/src/cdk/v2/destinations/http/utils.ts
[proc]: https://github.com/rudderlabs/rudder-server/blob/master/processor/processor.go
[gw-cors]: https://github.com/rudderlabs/rudder-server/blob/ea33835bf0c1b42a6a35e560eb35af3561c5b3c2/gateway/handle_lifecycle.go
[rscors]: https://github.com/rs/cors/blob/v1.11.1/cors.go

- RudderStack, Load JavaScript SDK: <https://www.rudderstack.com/docs/sources/event-streams/sdks/rudderstack-javascript-sdk/load-js-sdk/>
- RudderStack, Webhook setup guide: <https://www.rudderstack.com/docs/destinations/webhooks/setup-guide/>
- RudderStack, Webhook cloud mode: <https://www.rudderstack.com/docs/destinations/webhooks/cloud-mode/>
- RudderStack, HTTP Webhook setup guide: <https://www.rudderstack.com/docs/destinations/http-webhook/setup-guide/>
- RudderStack, HTTP Webhook release note: <https://www.rudderstack.com/docs/releases/http-webhook-destination/>
- RudderStack, Common fields: <https://www.rudderstack.com/docs/event-spec/standard-events/common-fields/>
- RudderStack, HTTP API (`/v1/batch` takes `{"batch": [...]}`; `curl -u <source_write_key>:`): <https://www.rudderstack.com/docs/api/http-api/>
- rudder-transformer, Webhook: <https://github.com/rudderlabs/rudder-transformer/blob/develop/src/v0/destinations/webhook/transform.js>
- rudder-transformer, HTTP Webhook: <https://github.com/rudderlabs/rudder-transformer/blob/develop/src/cdk/v2/destinations/http/utils.ts> and `rtWorkflow.yaml` in the same folder
- rudder-server, processor (`enhanceWithTimeFields`): <https://github.com/rudderlabs/rudder-server/blob/master/processor/processor.go>
- rudder-server, gateway CORS: <https://github.com/rudderlabs/rudder-server/blob/ea33835bf0c1b42a6a35e560eb35af3561c5b3c2/gateway/handle_lifecycle.go>
- rs/cors v1.11.1: <https://github.com/rs/cors/blob/v1.11.1/cors.go>
