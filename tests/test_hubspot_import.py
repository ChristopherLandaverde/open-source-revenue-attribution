"""import_hubspot: read-only HubSpot import through the existing import contract.

All HubSpot responses here are SYNTHETIC: hand-written records in the documented CRM v3 shapes
(tests/fixtures/hubspot/portal.json), served by a fake `urlopen`. No test touches the network.
The fake fails any request that is not a GET to api.hubapi.com.
"""

import copy
import io
import json
import re
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.management import CommandError, call_command

from collection.models import CollectedEvent, Workspace
from reports import hubspot
from reports.models import Account, Contact, ImportRun, Opportunity, Touchpoint

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_data" / "demo"
PORTAL = json.loads((ROOT / "tests" / "fixtures" / "hubspot" / "portal.json").read_text())
TOKEN = "pat-na1-SYNTHETIC-0000-not-a-real-token"

# Sample CSV IDs -> the synthetic HubSpot record IDs in portal.json.
ID_MAP = {
    "acc-northwind": "5001",
    "acc-umbra": "5002",
    "acc-kestrel": "5003",
    "acc-sakura": "5004",
    "acc-missing": "5099",
    "con-nw-ana": "7001",
    "con-nw-raj": "7002",
    "con-nw-li": "7003",
    "con-um-eve": "7004",
    "con-um-sam": "7005",
    "con-ke-otto": "7006",
    "con-sk-yui": "7007",
    "con-ghost": "7099",
    **{f"opp-1{n:02d}": f"91{n:02d}" for n in range(1, 10)},
}
# CSV rows HubSpot cannot produce: an ID with a space, an exact duplicate row, and a lowercase
# currency code (HubSpot only stores valid codes). Everything else has a HubSpot equivalent.
NOT_IN_HUBSPOT = {"accounts.csv": ["acc beta"], "opportunities.csv": ["opp-110"]}


# --- Fake HubSpot ---------------------------------------------------------------------


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeHubSpot:
    """Serves portal records page by page; records every request; refuses anything but GET."""

    def __init__(self, portal=None, page_size=2, failures=None, token=TOKEN):
        self.portal = copy.deepcopy(portal or PORTAL)
        self.page_size = page_size
        self.failures = list(failures or [])  # (status, headers, body) served before successes
        self.token = token
        self.requests = []
        self.v4 = {}  # (from_type, id, to_type) -> v4 association rows

    def __call__(self, request, timeout=None):
        url = urlsplit(request.full_url)
        method = request.get_method()
        self.requests.append((method, request.full_url))
        assert method == "GET", f"non-GET request to HubSpot: {method} {request.full_url}"
        assert request.data is None, "a request body was sent"
        assert url.scheme == "https" and url.hostname == "api.hubapi.com", request.full_url
        assert timeout, "no timeout"
        if self.failures:
            status, headers, body = self.failures.pop(0)
            raise urllib.error.HTTPError(
                request.full_url, status, "error", headers, io.BytesIO(json.dumps(body).encode())
            )
        assert request.get_header("Authorization") == f"Bearer {self.token}"
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if m := re.fullmatch(r"/crm/v3/objects/(companies|contacts|deals)", url.path):
            return self._page(self.portal[m.group(1)], query, inline=True)
        if m := re.fullmatch(r"/crm/v4/objects/(\w+)/(\d+)/associations/(\w+)", url.path):
            return self._page(self.v4[m.groups()], query, inline=False)
        raise AssertionError(f"unexpected path {url.path}")

    def _page(self, records, query, inline):
        assert int(query["limit"]) <= 500
        start = int(query.get("after", 0))
        size = self.page_size if inline else 1
        body = {"results": records[start : start + size]}
        if start + size < len(records):
            after = str(start + size)
            body["paging"] = {"next": {"after": after, "link": f"?after={after}"}}
        return FakeResponse(json.dumps(body).encode())


@pytest.fixture
def fake(monkeypatch):
    server = FakeHubSpot()
    monkeypatch.setattr(hubspot, "urlopen", server)
    monkeypatch.setenv("HUBSPOT_TOKEN", TOKEN)
    monkeypatch.setattr(hubspot.time, "sleep", lambda s: pytest.fail("sleep without a 429"))
    return server


def run(*args, **options):
    out, err = io.StringIO(), io.StringIO()
    call_command("import_hubspot", *args, stdout=out, stderr=err, **options)
    return out.getvalue(), err.getvalue()


# --- Equivalence with the CSV import ----------------------------------------------------


def translate(text: str) -> str:
    return re.sub(r"[A-Za-z0-9._:-]+", lambda m: ID_MAP.get(m.group(), m.group()), text)


def equivalent_csvs(directory: Path) -> Path:
    """The sample CSVs with HubSpot IDs, minus the rows HubSpot cannot produce."""
    directory.mkdir()
    for name in ["accounts.csv", "contacts.csv", "opportunities.csv", "touchpoints.csv"]:
        lines, seen = [], set()
        for line in (SAMPLE / name).read_text().splitlines():
            first = line.split(",")[0]
            if first in NOT_IN_HUBSPOT.get(name, []) or line in seen:
                continue  # also drops the exact duplicate contact row
            seen.add(line)
            lines.append(translate(line))
        (directory / name).write_text("\n".join(lines) + "\n")
    return directory


def records():
    return {
        "accounts": sorted(Account.objects.values_list("external_id", "name", "domain")),
        "contacts": sorted(
            Contact.objects.values_list("external_id", "account__external_id", "email")
        ),
        "opportunities": sorted(
            Opportunity.objects.values_list(
                "external_id",
                "account__external_id",
                "contact__external_id",
                "name",
                "amount",
                "currency",
                "stage",
                "created_at",
                "won_at",
            )
        ),
        "touchpoints": sorted(
            Touchpoint.objects.values_list(
                "external_id",
                "origin",
                "contact__external_id",
                "occurred_at",
                "source",
                "medium",
                "campaign",
                "content",
                "term",
                "landing_page",
                "referrer",
            )
        ),
    }


def report_summary(run_):
    report = run_.report
    return {
        "counts": report["counts"],
        "accepted_ids": report["accepted_ids"],
        "rejected": [
            (r["entity"], r["row"], r["record_id"], [i["code"] for i in r["issues"]])
            for r in report["rejected"]
        ],
        "warnings": [
            (w["entity"], w["row"], w["record_id"], w["code"]) for w in report["warnings"]
        ],
    }


def api_numbers(client):
    """Every API response the reports give: attribution, readiness and each journey."""
    data = {}
    for metric in ["pipeline", "won"]:
        data[f"attribution {metric}"] = client.get("/api/v1/attribution", {"metric": metric}).json()
        data[f"readiness {metric}"] = client.get("/api/v1/readiness", {"metric": metric}).json()
        for opp in Opportunity.objects.order_by("external_id"):
            path = f"/api/v1/journeys/{opp.external_id}"
            data[f"journey {opp.external_id} {metric}"] = client.get(
                path, {"metric": metric}
            ).json()
    return data


def wipe():
    for model in [Touchpoint, Opportunity, Contact, Account, ImportRun]:
        model.objects.all().delete()


def test_hubspot_equals_the_equivalent_csv_import(client, fake, tmp_path):
    csvs = equivalent_csvs(tmp_path / "csv")
    call_command(
        "load_sample_data", "--path", str(csvs), stdout=io.StringIO(), stderr=io.StringIO()
    )
    from_csv = records(), report_summary(ImportRun.objects.get()), api_numbers(client)
    wipe()

    out, err = run(touchpoints=csvs / "touchpoints.csv")
    from_hubspot = records(), report_summary(ImportRun.objects.get()), api_numbers(client)

    assert from_hubspot[0] == from_csv[0]  # identical imported records
    assert from_hubspot[1] == from_csv[1]  # identical validation outcome
    assert from_hubspot[2] == from_csv[2]  # identical report numbers, journeys and readiness
    # The comparison is not vacuous: the demo's numbers are there.
    assert len(from_csv[0]["opportunities"]) == 6 and len(from_csv[0]["touchpoints"]) == 15
    usd = next(
        c for c in from_hubspot[2]["attribution pipeline"]["currencies"] if c["currency"] == "USD"
    )
    assert usd["total"] == "54000.00"
    assert ImportRun.objects.get().source == "HubSpot (api.hubapi.com)"
    assert "Read 4 companies, 8 contacts and 9 deals from api.hubapi.com" in out
    assert "9107" in err and "AMOUNT_PRECISION" in err


# --- Read-only: no write request, ever ------------------------------------------------


def test_only_get_requests_are_sent(fake, tmp_path):
    """The fake fails the test on any non-GET request or request body (see FakeHubSpot)."""
    run(touchpoints=equivalent_csvs(tmp_path / "csv") / "touchpoints.csv")
    assert fake.requests and {m for m, _ in fake.requests} == {"GET"}
    for _, url in fake.requests:
        assert urlsplit(url).hostname == "api.hubapi.com"
        assert urlsplit(url).path.startswith(("/crm/v3/objects/", "/crm/v4/objects/"))


def test_the_client_has_no_write_method():
    public = {n for n in dir(hubspot.HubSpotClient) if not n.startswith("_")}
    assert public == {"get", "list_objects", "associations"}
    source = (ROOT / "reports" / "hubspot.py").read_text()
    assert 'method="GET"' in source
    assert not re.search(r"\b(POST|PUT|PATCH|DELETE)\b", source.replace("# ", ""))


def test_a_non_get_request_fails_the_guard(monkeypatch):
    """The guard itself works: a POST through it is a test failure."""
    import urllib.request

    guard = FakeHubSpot()
    request = urllib.request.Request(
        "https://api.hubapi.com/crm/v3/objects/deals", data=b"{}", method="POST"
    )
    with pytest.raises(AssertionError, match="non-GET"):
        guard(request, timeout=1)


def test_refuses_paths_outside_crm():
    with pytest.raises(hubspot.HubSpotError, match="only /crm/"):
        hubspot.HubSpotClient(TOKEN).get("/oauth/v1/refresh-tokens")


# --- Pagination, associations, rate limits ----------------------------------------------


@pytest.mark.parametrize("page_size", [1, 3, 100])
def test_pagination_reads_every_page(fake, page_size):
    fake.page_size = page_size
    out, _ = run(dry_run=True)
    assert "Read 4 companies, 8 contacts and 9 deals" in out
    lists = [u for _, u in fake.requests if "/crm/v3/objects/" in u]
    pages = sum(-(-len(PORTAL[t]) // page_size) for t in ["companies", "contacts", "deals"])
    assert len(lists) == pages
    afters = [parse_qs(urlsplit(u).query).get("after") for u in lists]
    assert afters.count(None) == 3  # each object type starts without a cursor
    assert all(parse_qs(urlsplit(u).query)["limit"] == ["100"] for u in lists)


def test_inline_association_paging_is_completed_from_v4(fake):
    deal = next(d for d in fake.portal["deals"] if d["id"] == "9102")
    deal["associations"]["contacts"]["paging"] = {"next": {"after": "1", "link": "?after=1"}}
    contact_row = {"toObjectId": 7002, "associationTypes": [{"typeId": 3, "label": None}]}
    other = {"toObjectId": 7003, "associationTypes": [{"typeId": 3, "label": None}]}
    fake.v4[("deals", "9102", "contacts")] = [other, contact_row]
    data = hubspot.fetch(hubspot.HubSpotClient(TOKEN))
    deal = next(d for d in data.deals if d["id"] == "9102")
    _, contacts = hubspot._associated(deal, "contact")
    assert contacts == ["7003", "7002"]
    v4 = [u for _, u in fake.requests if "/crm/v4/" in u]
    assert len(v4) == 2  # two pages of one row each


def test_429_backs_off_and_retries(fake, monkeypatch):
    slept = []
    monkeypatch.setattr(hubspot.time, "sleep", slept.append)
    rate_limited = {
        "status": "error",
        "errorType": "RATE_LIMIT",
        "policyName": "TEN_SECONDLY_ROLLING",
    }
    fake.failures = [
        (429, {"Retry-After": "3"}, rate_limited),
        (429, {}, rate_limited),
        (502, {}, {}),
    ]
    out, _ = run(dry_run=True)
    assert "Read 4 companies" in out
    assert slept == [3.0, 2.0, 4.0]  # Retry-After when sent, else 2^attempt


def test_persistent_429_is_a_clear_error_and_writes_nothing(fake, monkeypatch):
    monkeypatch.setattr(hubspot.time, "sleep", lambda s: None)
    fake.failures = [
        (429, {}, {"message": "You have reached your ten_secondly_rolling limit."})
    ] * 6
    with pytest.raises(CommandError, match=r"rate-limiting.*Nothing was written"):
        run()
    assert len(fake.requests) == hubspot.MAX_RETRIES + 1
    assert not Account.objects.exists() and not ImportRun.objects.exists()


# --- Token handling -------------------------------------------------------------------


def test_missing_token_is_a_clear_error(monkeypatch):
    sent = []
    monkeypatch.setattr(hubspot, "urlopen", lambda *a, **k: sent.append(a))
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    for value in [None, "", "   "]:
        if value is not None:
            monkeypatch.setenv("HUBSPOT_TOKEN", value)
        with pytest.raises(CommandError) as error:
            run()
        message = str(error.value)
        assert "HUBSPOT_TOKEN" in message and "crm.objects.deals.read" in message
        assert "Nothing was read or written" in message
    assert sent == [] and not ImportRun.objects.exists()


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "refused the token"), (403, "crm.objects.companies.read"), (404, "answered 404")],
)
def test_http_errors_are_clear_and_never_show_the_token(fake, status, expected, caplog):
    fake.failures = [(status, {}, {"message": "synthetic error", "category": "X"})]
    with pytest.raises(CommandError) as error:
        run()
    assert expected in str(error.value) and "synthetic error" in str(error.value)
    assert TOKEN not in str(error.value) and TOKEN not in caplog.text
    assert not ImportRun.objects.exists()


def test_token_never_reaches_output_logs_or_the_database(fake, caplog, tmp_path):
    out, err = run(touchpoints=equivalent_csvs(tmp_path / "csv") / "touchpoints.csv")
    stored = json.dumps(list(ImportRun.objects.values()), default=str)
    for text in [out, err, caplog.text, stored]:
        assert TOKEN not in text
        assert "pat-na1" not in text


# --- Dry run ----------------------------------------------------------------------------


def test_dry_run_prints_the_report_and_writes_nothing(fake, tmp_path):
    Workspace.objects.create(name="demo", write_key="test-write-key-0123456789")
    models = [Account, Contact, Opportunity, Touchpoint, ImportRun, CollectedEvent, Workspace]
    before = {m.__name__: m.objects.count() for m in models}
    out, err = run(dry_run=True, touchpoints=equivalent_csvs(tmp_path / "csv") / "touchpoints.csv")
    assert {m.__name__: m.objects.count() for m in models} == before
    assert "Validated HubSpot (api.hubapi.com)" in out
    assert "Dry run: would load 4 accounts, 7 contacts, 6 opportunities, 15 touchpoints" in out
    assert "Nothing was written." in out
    assert "WON_AT_REQUIRED" in err and "CONTACT_ACCOUNT_MISMATCH" in err


# --- Mapping choices (docs/decisions.md) -------------------------------------------------


def mapped(portal, **kwargs):
    data = hubspot.HubSpotData(portal["companies"], portal["contacts"], portal["deals"])
    return hubspot.to_batch(data, **kwargs)


def rows(mapping, entity):
    return {r[next(iter(r))]: r for r in mapping.batch.tables[entity].rows}


def test_open_deal_close_date_is_not_a_won_date():
    deal = rows(mapped(PORTAL), "opportunities")["9102"]
    assert deal["stage"] == "open" and deal["won_at"] == ""
    won = rows(mapped(PORTAL), "opportunities")["9101"]
    assert won["stage"] == "won" and won["won_at"] == "2026-06-15T12:00:00.000Z"
    assert won["created_at"] == "2026-04-01T12:00:00.000Z"  # hs_createdate, as Dreamdata


def test_closed_lost_deal_is_refused_visibly(fake):
    lost = copy.deepcopy(fake.portal["deals"][1])
    lost["id"] = "9120"
    lost["properties"].update(dealstage="closedlost", hs_is_closed_lost="true")
    fake.portal["deals"].append(lost)
    out, err = run(dry_run=True)
    assert "1 closed-lost deals are passed on as stage 'lost'" in out
    assert "[9120]: INVALID_STAGE stage" in err


def test_a_deal_with_several_contacts_uses_its_companys_earliest_contact():
    portal = copy.deepcopy(PORTAL)
    deal = next(d for d in portal["deals"] if d["id"] == "9102")
    deal["associations"]["contacts"]["results"] = [
        {"id": i, "type": "deal_to_contact"} for i in ["7005", "7003", "7002"]
    ]  # 7005 belongs to another company; 7002 was created before 7003
    mapping = mapped(portal)
    assert rows(mapping, "opportunities")["9102"]["contact_id"] == "7002"
    assert any("1 deals have more than one contact" in n for n in mapping.notes)


def test_company_falls_back_to_the_only_association_and_otherwise_stays_blank():
    portal = copy.deepcopy(PORTAL)
    deals = {d["id"]: d for d in portal["deals"]}
    deals["9101"]["associations"]["companies"]["results"] = [
        {"id": "5001", "type": "deal_to_company_unlabeled"}
    ]
    deals["9102"]["associations"]["companies"]["results"] = [
        {"id": "5001", "type": "deal_to_company_unlabeled"},
        {"id": "5002", "type": "deal_to_company_unlabeled"},
    ]
    out = rows(mapped(portal), "opportunities")
    assert out["9101"]["account_id"] == "5001"
    assert out["9102"]["account_id"] == ""  # ambiguous: refused, not guessed


def test_missing_currency_uses_the_flag_or_is_refused():
    portal = copy.deepcopy(PORTAL)
    portal["deals"][0]["properties"]["deal_currency_code"] = None
    assert rows(mapped(portal), "opportunities")["9101"]["currency"] == ""
    mapping = mapped(portal, default_currency="USD")
    assert rows(mapping, "opportunities")["9101"]["currency"] == "USD"
    assert any("--currency USD" in n for n in mapping.notes)


def test_without_touchpoints_the_file_is_empty_not_missing(fake):
    out, err = run(dry_run=True)
    assert "MISSING_FILE" not in err
    assert "15 touchpoints" not in out and "0 touchpoints" in out
