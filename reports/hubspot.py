"""Read-only HubSpot import: companies, contacts and deals mapped to the CSV import contract.

`fetch` reads the three CRM objects and their associations from HubSpot's CRM v3 API with
GET requests only; `to_batch` maps them to the same `ImportBatch` the CSV import builds, so the
existing validation and load path (`reports.imports.run_import`) decides what is accepted.
Mapping and sources: docs/decisions.md ("Read-only HubSpot import").

The token comes from the caller (the `HUBSPOT_TOKEN` environment variable in the management
command). It is sent only to api.hubapi.com, in the Authorization header, and never logged,
stored or put in an error message.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlencode

from contracts import ImportBatch, Table
from contracts.fields import parse_timestamp

API_HOST = "api.hubapi.com"
API = f"https://{API_HOST}"
# Read scopes only. Nothing here can write: the client has a GET method and no other.
SCOPES = ("crm.objects.companies.read", "crm.objects.contacts.read", "crm.objects.deals.read")
PAGE_SIZE = 100  # HubSpot's maximum page size for the CRM object list endpoints
MAX_RETRIES = 5  # for 429 and 5xx, with backoff
MAX_BACKOFF = 30.0
TIMEOUT = 30

COMPANY_PROPERTIES = ("name", "domain")
CONTACT_PROPERTIES = ("email", "createdate")
DEAL_PROPERTIES = (
    "dealname",
    "amount",
    "deal_currency_code",
    "dealstage",
    "pipeline",
    "hs_createdate",
    "createdate",
    "closedate",
    "hs_is_closed_won",
    "hs_is_closed_lost",
)

urlopen = urllib.request.urlopen  # module attribute, so tests can replace the network


class HubSpotError(Exception):
    """A HubSpot request failed. The message never contains the token."""


class HubSpotClient:
    """GET-only client for api.hubapi.com with pagination and 429/5xx backoff."""

    def __init__(self, token: str, sleep: Callable[[float], None] | None = None):
        if not token:
            raise HubSpotError("No HubSpot token.")
        self._token = token
        self._sleep = sleep or (lambda seconds: time.sleep(seconds))
        self.requests = 0

    def get(self, path: str, params: dict[str, str] | None = None) -> dict:
        """GET a CRM path on api.hubapi.com and return its JSON body."""
        if not path.startswith("/crm/"):
            raise HubSpotError(f"Refusing to read {path!r}: only /crm/ paths are read.")
        url = f"{API}{path}" + (f"?{urlencode(params)}" if params else "")
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "User-Agent": "osra-import-hubspot",
            },
        )
        for attempt in range(MAX_RETRIES + 1):
            self.requests += 1
            try:
                with urlopen(request, timeout=TIMEOUT) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                status, body = exc.code, _error_message(exc)
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
            except urllib.error.URLError as exc:
                raise HubSpotError(f"Could not reach {API_HOST}: {exc.reason}.") from None
            if (status == 429 or status >= 500) and attempt < MAX_RETRIES:
                self._sleep(_backoff(attempt, retry_after))
                continue
            raise HubSpotError(_explain(status, body, path)) from None
        raise AssertionError("unreachable")  # pragma: no cover

    def list_objects(
        self, object_type: str, properties: tuple[str, ...], associations: tuple[str, ...] = ()
    ) -> list[dict]:
        """Every record of a CRM object type, following `paging.next.after`."""
        params = {"limit": str(PAGE_SIZE), "properties": ",".join(properties), "archived": "false"}
        if associations:
            params["associations"] = ",".join(associations)
        records, after = [], None
        while True:
            page = self.get(
                f"/crm/v3/objects/{object_type}", {**params, **({"after": after} if after else {})}
            )
            records.extend(page.get("results", []))
            after = ((page.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                return records

    def associations(self, from_type: str, object_id: str, to_type: str) -> list[dict]:
        """All of one record's associations to `to_type` (CRM associations v4, GET)."""
        results, after = [], None
        while True:
            params = {"limit": "500", **({"after": after} if after else {})}
            page = self.get(
                f"/crm/v4/objects/{from_type}/{object_id}/associations/{to_type}", params
            )
            results.extend(page.get("results", []))
            after = ((page.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                return results


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), MAX_BACKOFF)
        except ValueError:
            pass
    # HubSpot's burst window is 10 seconds; 1, 2, 4, 8, 16 s covers it more than once.
    return min(2.0**attempt, MAX_BACKOFF)


def _error_message(exc: urllib.error.HTTPError) -> str:
    """HubSpot's own error message from the body, if any (bodies never echo the token)."""
    try:
        data = json.loads(exc.read().decode("utf-8"))
    except (ValueError, OSError, UnicodeDecodeError):
        return ""
    return str(data.get("message", ""))[:300] if isinstance(data, dict) else ""


def _explain(status: int, message: str, path: str) -> str:
    detail = f" HubSpot said: {message}" if message else ""
    if status == 401:
        return (
            "HubSpot refused the token (401). Check HUBSPOT_TOKEN: it must be a service key or "
            f"private app access token for this portal.{detail}"
        )
    if status == 403:
        return (
            f"HubSpot refused access to {path} (403). The token needs the read scopes "
            f"{', '.join(SCOPES)}.{detail}"
        )
    if status == 429:
        return f"HubSpot kept rate-limiting the import (429) after {MAX_RETRIES} retries.{detail}"
    return f"HubSpot answered {status} for {path}.{detail}"


# --- Reading ---------------------------------------------------------------------------


@dataclass
class HubSpotData:
    companies: list[dict]
    contacts: list[dict]
    deals: list[dict]
    requests: int = 0


def fetch(client: HubSpotClient) -> HubSpotData:
    """Read companies, contacts (with their companies) and deals (with companies and contacts)."""
    companies = client.list_objects("companies", COMPANY_PROPERTIES)
    contacts = client.list_objects("contacts", CONTACT_PROPERTIES, ("companies",))
    deals = client.list_objects("deals", DEAL_PROPERTIES, ("companies", "contacts"))
    for record, from_type in [(c, "contacts") for c in contacts] + [(d, "deals") for d in deals]:
        for to_type, block in list((record.get("associations") or {}).items()):
            if ((block.get("paging") or {}).get("next") or {}).get("after"):
                # More associations than fit inline: read them all from the v4 endpoint.
                target = _target_type(to_type, block)
                full = client.associations(from_type, record["id"], target)
                record["associations"][to_type] = {"results": _from_v4(from_type, target, full)}
    return HubSpotData(companies, contacts, deals, client.requests)


def _target_type(key: str, block: dict) -> str:
    if key in ("companies", "contacts"):
        return key
    kinds = {r.get("type", "") for r in block.get("results", [])}
    return "companies" if any("to_company" in k for k in kinds | {key}) else "contacts"


def _from_v4(from_type: str, to_type: str, results: list[dict]) -> list[dict]:
    """v4 association rows to the v3 inline shape: primary company rows as `<a>_to_company`."""
    single = {"companies": "company", "contacts": "contact", "deals": "deal"}
    base = f"{single[from_type]}_to_{single[to_type]}"
    rows = []
    for row in results:
        object_id = str(row.get("toObjectId", ""))
        labels = [t.get("label") or "" for t in row.get("associationTypes", [])]
        rows.append({"id": object_id, "type": f"{base}_unlabeled"})
        if "Primary" in labels:
            rows.append({"id": object_id, "type": base})
    return rows


# --- Mapping to the import contract ------------------------------------------------------


@dataclass
class Mapping:
    """The import batch plus what the mapping chose, for the command to report."""

    batch: ImportBatch
    notes: list[str] = field(default_factory=list)


def _associated(record: dict, kind: str) -> tuple[list[str], list[str]]:
    """(primary IDs, all IDs) of a record's associated `kind` ("company" or "contact").

    v3 lists each association as `<from>_to_<kind>_unlabeled`, and the primary one once more
    as `<from>_to_<kind>`. Custom labels repeat an ID already listed as unlabeled.
    """
    primary, every = [], []
    for block in (record.get("associations") or {}).values():
        for row in block.get("results", []):
            row_type, object_id = row.get("type", ""), str(row.get("id", ""))
            if f"_to_{kind}" not in row_type or not object_id:
                continue
            if row_type.endswith(f"_to_{kind}") and object_id not in primary:
                primary.append(object_id)
            if object_id not in every:
                every.append(object_id)
    return primary, every


def _company(record: dict) -> str:
    """The primary company; else the only associated company; else '' (refused by the contract)."""
    primary, every = _associated(record, "company")
    if primary:
        return primary[0]
    return every[0] if len(every) == 1 else ""


def _flag(value) -> bool:
    return str(value or "").strip().lower() == "true"


def _stage(props: dict) -> str:
    if _flag(props.get("hs_is_closed_won")):
        return "won"
    if _flag(props.get("hs_is_closed_lost")):
        return "lost"  # the contract refuses lost for now (INVALID_STAGE), visibly
    return "open"


def to_batch(
    data: HubSpotData, touchpoints: Table | None = None, default_currency: str = ""
) -> Mapping:
    """Map HubSpot records to the CSV contract's rows (docs/contract.md section 2)."""
    notes: list[str] = []
    accounts = [
        {
            "account_id": str(c["id"]),
            "name": (c.get("properties") or {}).get("name") or "",
            "domain": (c.get("properties") or {}).get("domain") or "",
        }
        for c in data.companies
    ]
    contact_company, contact_created = {}, {}
    contacts = []
    for c in data.contacts:
        props = c.get("properties") or {}
        account = _company(c)
        contact_company[str(c["id"])] = account
        contact_created[str(c["id"])] = props.get("createdate") or c.get("createdAt") or ""
        contacts.append(
            {"contact_id": str(c["id"]), "account_id": account, "email": props.get("email") or ""}
        )
    opportunities, several, lost, defaulted = [], 0, 0, 0
    for d in data.deals:
        props = d.get("properties") or {}
        account = _company(d)
        _, deal_contacts = _associated(d, "contact")
        if len(deal_contacts) > 1:
            several += 1
        contact = _choose_contact(deal_contacts, account, contact_company, contact_created)
        stage = _stage(props)
        lost += stage == "lost"
        currency = (props.get("deal_currency_code") or "").strip()
        if not currency and default_currency:
            currency, defaulted = default_currency, defaulted + 1
        opportunities.append(
            {
                "opportunity_id": str(d["id"]),
                "account_id": account,
                "contact_id": contact,
                "name": props.get("dealname") or "",
                "amount": (props.get("amount") or "").strip(),
                "currency": currency,
                "stage": stage,
                "created_at": props.get("hs_createdate")
                or props.get("createdate")
                or d.get("createdAt")
                or "",
                # Close date is the won date only for a won deal; for an open deal it is the
                # expected close date, which is not a conversion.
                "won_at": (props.get("closedate") or "") if stage == "won" else "",
            }
        )
    if several:
        notes.append(
            f"{several} deals have more than one contact; each uses one contact (its company's "
            "contact first, then the earliest created). The others are not credited."
        )
    if lost:
        notes.append(
            f"{lost} closed-lost deals are passed on as stage 'lost', which the contract refuses "
            "for now (INVALID_STAGE)."
        )
    if defaulted:
        notes.append(f"{defaulted} deals had no currency and use --currency {default_currency}.")
    tables = ImportBatch.from_rows(
        accounts=accounts, contacts=contacts, opportunities=opportunities, touchpoints=[]
    ).tables
    if touchpoints is not None:
        tables["touchpoints"] = touchpoints
    return Mapping(ImportBatch(tables), notes)


def _choose_contact(
    contact_ids: list[str], account: str, company_of: dict[str, str], created: dict[str, str]
) -> str:
    """One contact per deal: one of the deal company's contacts first, then the earliest created,
    then the lowest ID. A deal with no contact stays contactless (fully Unattributed)."""
    if not contact_ids:
        return ""

    def key(contact_id: str):
        same_company = bool(account) and company_of.get(contact_id) == account
        numeric = int(contact_id) if contact_id.isdigit() else float("inf")
        when = parse_timestamp(created.get(contact_id) or "")[0]
        return (not same_company, when is None, when or 0, numeric, contact_id)

    return min(contact_ids, key=key)
