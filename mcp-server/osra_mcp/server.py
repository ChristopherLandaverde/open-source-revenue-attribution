"""OSRA MCP server: three read-only tools over a self-hosted instance's JSON API.

The server is a thin client. Each tool makes one GET request to `/api/v1/` on the instance
named by `OSRA_URL`, with the user's own token from `OSRA_TOKEN` (`manage.py createapitoken`),
and returns the API's JSON unchanged. It computes nothing: the API is the single source of
numbers and of auth. It sends requests to `OSRA_URL` only, and never logs or returns the token.

Run it as a local stdio server from an agent (Claude Code, Claude Desktop, Cursor):
`OSRA_URL=https://attribution.example.com OSRA_TOKEN=osra_... osra-mcp`.
"""

import json
import os
import re
from collections.abc import Mapping
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from osra_mcp import __version__

# The API's own `meaning` sentences (api/views.py; a test keeps them identical).
REPORT_MEANING = (
    "Each column applies one named rule to the same touches. The numbers show association "
    "under that rule, not causal impact: no column shows that a campaign caused a deal. A gap "
    "between columns is the rules' difference, not a measured lift."
)
JOURNEY_MEANING = (
    "Every touch of this opportunity's contact, in time order, with why it is or isn't "
    "eligible and the credit each named model gives it. This is association under a named "
    "rule, not causal impact."
)
READINESS_MEANING = (
    "What to fix in your data before you trust the model comparison. "
    "This is association under a named rule, not causal impact."
)

INSTRUCTIONS = (
    "Read-only tools over the user's own Open Source Revenue Attribution (OSRA) instance. "
    "The numbers come from OSRA's engine: quote them from the tool results, never compute "
    "or estimate credit yourself. Always name the model and the lookback window next to a "
    "number. Credit is association under a named model, never causal impact: do not say a "
    "campaign caused, drove or generated revenue. To explain an opportunity's credit, cite "
    "its journey (get_journey): each touch, its status and the credit per model. Before "
    "trusting a comparison, check get_readiness."
)

# The import contract's ID rule (docs/contract.md section 1), minus the path segments . and ..
ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
TIMEOUT = httpx2.Timeout(30.0, connect=10.0)
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
USER_AGENT = f"osra-mcp/{__version__}"

Metric = Annotated[
    Literal["pipeline", "won"],
    Field(
        description="pipeline: credited at opportunity creation. won: credited when the "
        "opportunity was won (open opportunities are left out)."
    ),
]
Model = Annotated[
    str | None,
    Field(
        description="One model's ID or name, e.g. first-touch, last-touch, linear, "
        "position-based-u-shaped, time-decay. Omit for every model side by side."
    ),
]

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


class _Refused(Exception):
    """A request this server will not send; carries the structured error for the tool result."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _error(code: str, message: str, status: int | None = None) -> CallToolResult:
    error = {"code": code, "message": message}
    if status is not None:
        error["status"] = status
    data = {"error": error}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data))],
        structured_content=data,
        is_error=True,
    )


def _base_url(env: Mapping[str, str]) -> str:
    raw = env.get("OSRA_URL", "").strip()
    if not raw:
        raise _Refused(
            "missing_url",
            "Set OSRA_URL to your OSRA instance, e.g. https://attribution.example.com "
            "(or http://127.0.0.1:8000 locally).",
        )
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _Refused("invalid_url", "OSRA_URL must be an http:// or https:// URL with a host.")
    if parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS:
        # The token travels in a header: plain HTTP is only for this machine.
        raise _Refused(
            "insecure_url",
            "OSRA_URL must use https:// unless it is this machine (localhost, 127.0.0.1 or "
            "[::1]); the token would otherwise cross the network unencrypted.",
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise _Refused(
            "invalid_url",
            "OSRA_URL must not contain credentials, a query or a fragment. Put the token in "
            "OSRA_TOKEN.",
        )
    return raw.rstrip("/")


def _token(env: Mapping[str, str]) -> str:
    token = env.get("OSRA_TOKEN", "").strip()
    if not token:
        raise _Refused(
            "missing_token",
            "Set OSRA_TOKEN to an API token from `manage.py createapitoken <username>` on the "
            "OSRA server.",
        )
    return token


def create_server(
    env: Mapping[str, str] | None = None,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> MCPServer:
    """The MCP server. `env` defaults to os.environ, read on each call; `transport` is for tests."""

    async def get(path: str, params: dict[str, str]) -> CallToolResult:
        source = os.environ if env is None else env
        try:
            url = _base_url(source) + path
            token = _token(source)
        except _Refused as refused:
            return _error(refused.code, refused.message)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            async with httpx2.AsyncClient(
                transport=transport, timeout=TIMEOUT, follow_redirects=False
            ) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx2.HTTPError as exc:
            # The exception text names the URL, never the headers, so the token stays out.
            return _error("unreachable", f"Could not reach OSRA_URL: {type(exc).__name__}.")
        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict) or "schemaVersion" not in data:
            hint = (
                " The server redirected; set OSRA_URL to the final URL (for example https://)."
                if response.is_redirect
                else " Check that OSRA_URL points at an OSRA instance."
            )
            return _error(
                "unexpected_response",
                f"OSRA_URL answered HTTP {response.status_code} without OSRA API JSON.{hint}",
                status=response.status_code,
            )
        # The API's JSON, unchanged: data on 200, its own {"error": {...}} otherwise.
        return CallToolResult(
            content=[TextContent(type="text", text=response.text)],
            structured_content=data,
            is_error=response.status_code != 200,
        )

    server = MCPServer(name="osra", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        title="Attribution by model",
        description=(
            "Credit per campaign under each named attribution model (first-touch, last-touch, "
            "linear, position-based-u-shaped, time-decay), the Influenced column beside it, per "
            "currency, and each opportunity's credits. Same numbers as OSRA's report page. "
            f"{REPORT_MEANING} Returns the JSON of GET /api/v1/attribution unchanged."
        ),
        annotations=READ_ONLY,
    )
    async def get_attribution(metric: Metric = "pipeline", model: Model = None) -> CallToolResult:
        params = {"metric": metric}
        if model:
            params["model"] = model
        return await get("/api/v1/attribution", params)

    @server.tool(
        title="Opportunity or account journey",
        description=(
            "The touches behind an opportunity's credit: each touch in time order, whether it "
            "is eligible and why, and the credit each named model gives it. An account ID "
            "returns each of its opportunities' journeys. Use it to explain why an opportunity "
            f"got its credit. {JOURNEY_MEANING} Returns the JSON of GET /api/v1/journeys/<id> "
            "unchanged."
        ),
        annotations=READ_ONLY,
    )
    async def get_journey(
        id: Annotated[str, Field(description="Opportunity or account ID, e.g. opp-101.")],
        metric: Metric = "pipeline",
        model: Model = None,
    ) -> CallToolResult:
        if not ID_PATTERN.fullmatch(id) or id in (".", ".."):
            return _error(
                "invalid_id", "IDs are 1-64 characters of A-Z a-z 0-9 . _ : - (docs/contract.md)."
            )
        params = {"metric": metric}
        if model:
            params["model"] = model
        return await get(f"/api/v1/journeys/{quote(id, safe='')}", params)

    @server.tool(
        title="Data readiness",
        description=(
            "OSRA's data checks before trusting the model comparison: each check's status, "
            "count, finding, fix and affected records, and a verdict. "
            f"{READINESS_MEANING} Returns the JSON of GET /api/v1/readiness unchanged."
        ),
        annotations=READ_ONLY,
    )
    async def get_readiness(metric: Metric = "pipeline") -> CallToolResult:
        return await get("/api/v1/readiness", {"metric": metric})

    return server


def main() -> None:
    create_server().run()  # stdio


if __name__ == "__main__":
    main()
