"""MCP server (mcp-server/osra_mcp): a real MCP client session against a live OSRA server.

Each test starts Django's live server with the bundled sample data and a real API token,
connects an in-process MCP client to the server, and checks that every tool returns exactly
what the JSON API returns for the same request.
"""

import json
import os
import shutil
from pathlib import Path

import anyio
import httpx2
import pytest
from django.core.management import call_command
from mcp import Client, StdioServerParameters, stdio_client
from mcp.client.session import ClientSession
from osra_mcp import server as osra_mcp

from api.models import ApiToken
from api.views import JOURNEY_MEANING, READINESS_MEANING, REPORT_MEANING

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.anyio]
ROOT = Path(__file__).resolve().parent.parent
TOOLS = {"get_attribution", "get_journey", "get_readiness"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def osra(live_server, django_user_model):
    """A live OSRA instance with the sample data, and the env an agent would give the server."""
    call_command("load_sample_data", verbosity=0)
    user = django_user_model.objects.create_user(username="agent-owner", password="x-pw-12345")
    token = ApiToken.issue(user, "mcp")[1]
    return {"OSRA_URL": live_server.url, "OSRA_TOKEN": token}


def api(env, path, **params):
    """The JSON API's own response, fetched directly with the same token."""
    response = httpx2.get(
        env["OSRA_URL"] + path,
        params=params,
        headers={"Authorization": f"Bearer {env['OSRA_TOKEN']}"},
    )
    return response.status_code, response.json()


async def call(env, tool, arguments=None, transport=None):
    async with Client(osra_mcp.create_server(env=env, transport=transport)) as client:
        return await client.call_tool(tool, arguments or {})


def payload(result):
    """The tool's JSON: structured content, and the identical text block."""
    (block,) = result.content
    assert json.loads(block.text) == result.structured_content
    return result.structured_content


# --- Tools are listed, read-only and carry the meaning sentence ----------------------


async def test_lists_three_read_only_tools_with_the_meaning(osra):
    async with Client(osra_mcp.create_server(env=osra)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == TOOLS
    meanings = {
        "get_attribution": REPORT_MEANING,
        "get_journey": JOURNEY_MEANING,
        "get_readiness": READINESS_MEANING,
    }
    for name, tool in tools.items():
        assert meanings[name] in tool.description
        assert "association under" in tool.description and "not causal impact" in tool.description
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
    assert tools["get_journey"].input_schema["required"] == ["id"]
    metric = tools["get_attribution"].input_schema["properties"]["metric"]
    assert metric["enum"] == ["pipeline", "won"]


def test_meaning_sentences_are_the_apis():
    assert osra_mcp.REPORT_MEANING == REPORT_MEANING
    assert osra_mcp.JOURNEY_MEANING == JOURNEY_MEANING
    assert osra_mcp.READINESS_MEANING == READINESS_MEANING


# --- Results equal the API's responses -----------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "path", "params"),
    [
        ("get_attribution", {}, "/api/v1/attribution", {"metric": "pipeline"}),
        ("get_attribution", {"metric": "won"}, "/api/v1/attribution", {"metric": "won"}),
        (
            "get_attribution",
            {"model": "linear"},
            "/api/v1/attribution",
            {"metric": "pipeline", "model": "linear"},
        ),
        ("get_journey", {"id": "opp-101"}, "/api/v1/journeys/opp-101", {"metric": "pipeline"}),
        (
            "get_journey",
            {"id": "acc-umbra", "metric": "won", "model": "first-touch"},
            "/api/v1/journeys/acc-umbra",
            {"metric": "won", "model": "first-touch"},
        ),
        ("get_readiness", {}, "/api/v1/readiness", {"metric": "pipeline"}),
        ("get_readiness", {"metric": "won"}, "/api/v1/readiness", {"metric": "won"}),
    ],
)
async def test_tool_result_equals_the_api_response(osra, tool, arguments, path, params):
    result = await call(osra, tool, arguments)
    status, expected = await anyio.to_thread.run_sync(lambda: api(osra, path, **params))
    assert status == 200
    assert result.is_error is False
    assert payload(result) == expected
    assert payload(result)["schemaVersion"] == "1"


async def test_api_errors_pass_through_as_tool_errors(osra):
    result = await call(osra, "get_journey", {"id": "opp-999"})
    assert result.is_error is True
    status, expected = await anyio.to_thread.run_sync(
        lambda: api(osra, "/api/v1/journeys/opp-999", metric="pipeline")
    )
    assert status == 404
    assert payload(result) == expected
    assert expected["error"]["code"] == "not_found"

    result = await call(osra, "get_attribution", {"model": "data-driven"})
    assert result.is_error is True
    assert payload(result)["error"]["code"] == "unknown_model"


# --- Auth: missing or invalid token is a structured error, never data -----------------


async def test_invalid_token_is_the_apis_401(osra):
    env = {**osra, "OSRA_TOKEN": "osra_not-a-real-token"}
    for tool, arguments in [
        ("get_attribution", {}),
        ("get_journey", {"id": "opp-101"}),
        ("get_readiness", {}),
    ]:
        result = await call(env, tool, arguments)
        assert result.is_error is True
        data = payload(result)
        assert set(data) == {"schemaVersion", "error"}  # no data
        assert data["error"]["code"] == "not_authenticated"
        assert "osra_not-a-real-token" not in result.content[0].text


@pytest.mark.parametrize(
    ("env", "code"),
    [
        ({"OSRA_URL": "http://127.0.0.1:9"}, "missing_token"),
        ({"OSRA_URL": "http://127.0.0.1:9", "OSRA_TOKEN": "  "}, "missing_token"),
        ({"OSRA_TOKEN": "osra_x"}, "missing_url"),
        ({"OSRA_URL": "ftp://osra.example", "OSRA_TOKEN": "osra_x"}, "invalid_url"),
        ({"OSRA_URL": "https://u:p@osra.example", "OSRA_TOKEN": "osra_x"}, "invalid_url"),
        ({"OSRA_URL": "https://osra.example/?x=1", "OSRA_TOKEN": "osra_x"}, "invalid_url"),
        ({"OSRA_URL": "http://osra.example", "OSRA_TOKEN": "osra_x"}, "insecure_url"),
        ({"OSRA_URL": "http://10.0.0.5:8000", "OSRA_TOKEN": "osra_x"}, "insecure_url"),
        ({"OSRA_URL": "http://localhost.evil.example", "OSRA_TOKEN": "osra_x"}, "insecure_url"),
    ],
)
async def test_missing_settings_are_structured_errors_without_a_request(env, code):
    sent = []
    transport = httpx2.MockTransport(lambda request: sent.append(request))
    result = await call(env, "get_readiness", transport=transport)
    assert result.is_error is True
    assert payload(result)["error"]["code"] == code
    assert sent == []


async def test_reads_os_environ_by_default(osra, monkeypatch):
    monkeypatch.setenv("OSRA_URL", osra["OSRA_URL"])
    monkeypatch.delenv("OSRA_TOKEN", raising=False)
    async with Client(osra_mcp.create_server()) as client:
        missing = await client.call_tool("get_readiness", {})
        monkeypatch.setenv("OSRA_TOKEN", osra["OSRA_TOKEN"])
        found = await client.call_tool("get_readiness", {})
    assert payload(missing)["error"]["code"] == "missing_token"
    assert found.is_error is False and payload(found)["verdict"] == "fix_data_first"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://127.0.0.1:8000/",
        "http://[::1]:8000",
        "https://osra.example",
    ],
)
async def test_plain_http_is_allowed_only_for_this_machine(url):
    sent = []

    def respond(request):
        sent.append(request)
        return httpx2.Response(200, json={"schemaVersion": "1"})

    env = {"OSRA_URL": url, "OSRA_TOKEN": "osra_tok"}
    result = await call(env, "get_readiness", transport=httpx2.MockTransport(respond))
    assert result.is_error is False and len(sent) == 1


# --- Network: only GET requests to OSRA_URL's /api/v1/ --------------------------------


async def test_requests_go_only_to_osra_url(osra):
    sent = []

    def respond(request):
        sent.append(request)
        return httpx2.Response(200, json={"schemaVersion": "1"})

    env = {"OSRA_URL": "https://attribution.example.com/osra/", "OSRA_TOKEN": "osra_tok"}
    transport = httpx2.MockTransport(respond)
    calls = [
        ("get_attribution", {"model": "linear"}),
        ("get_journey", {"id": "acc-umbra"}),
        ("get_readiness", {"metric": "won"}),
    ]
    for tool, arguments in calls:
        assert (await call(env, tool, arguments, transport)).is_error is False
    # IDs that could leave the API path or the host are refused before any request.
    for bad in ["../admin", "..", "https://evil.example/x", "a/b", "a?b", "", "x" * 65]:
        result = await call(env, "get_journey", {"id": bad}, transport)
        assert result.is_error is True and payload(result)["error"]["code"] == "invalid_id"
    assert len(sent) == len(calls)
    for request in sent:
        assert request.method == "GET"
        assert request.url.scheme == "https" and request.url.host == "attribution.example.com"
        assert request.url.path.startswith("/osra/api/v1/")
        assert request.headers["Authorization"] == "Bearer osra_tok"
    assert [r.url.path for r in sent] == [
        "/osra/api/v1/attribution",
        "/osra/api/v1/journeys/acc-umbra",
        "/osra/api/v1/readiness",
    ]


async def test_redirects_are_not_followed(osra):
    sent = []

    def respond(request):
        sent.append(request)
        return httpx2.Response(301, headers={"Location": "https://elsewhere.example/"})

    env = {"OSRA_URL": "https://attribution.example.com", "OSRA_TOKEN": "osra_tok"}
    result = await call(env, "get_readiness", transport=httpx2.MockTransport(respond))
    assert len(sent) == 1
    error = payload(result)["error"]
    assert result.is_error is True
    assert error["code"] == "unexpected_response" and error["status"] == 301
    assert "osra_tok" not in result.content[0].text


async def test_unreachable_server_is_a_structured_error():
    def fail(request):
        raise httpx2.ConnectError("refused", request=request)

    env = {"OSRA_URL": "http://127.0.0.1:9", "OSRA_TOKEN": "osra_secret"}
    result = await call(env, "get_readiness", transport=httpx2.MockTransport(fail))
    assert result.is_error is True
    assert payload(result)["error"]["code"] == "unreachable"
    assert "osra_secret" not in result.content[0].text


# --- The installed entry point speaks MCP over stdio ----------------------------------


async def test_osra_mcp_entry_point_over_stdio(osra):
    command = shutil.which("osra-mcp")
    assert command, "the osra-mcp entry point is not installed (uv sync installs the mcp group)"
    params = StdioServerParameters(
        command=command, env={"PATH": os.environ.get("PATH", ""), **osra}
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        assert {t.name for t in (await session.list_tools()).tools} == TOOLS
        result = await session.call_tool("get_readiness", {})
    status, expected = await anyio.to_thread.run_sync(lambda: api(osra, "/api/v1/readiness"))
    assert result.is_error is False
    assert payload(result) == expected
