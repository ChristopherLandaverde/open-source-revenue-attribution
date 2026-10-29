"""CSV import contract: accounts, contacts, opportunities, touchpoints (docs/contract.md).

`validate_import` takes raw rows and returns an `ImportReport`: typed accepted records,
rejected rows with reason codes, and warnings. It never loads anything; callers load only
`report.accepted`.
"""

import csv
import io
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from attribution import DEFAULT_LOOKBACK_DAYS, Conversion, Touchpoint, eligible_touchpoints
from contracts.codes import RejectReason, WarningCode
from contracts.fields import (
    fits_currency,
    parse_amount,
    parse_currency,
    parse_email,
    parse_id,
    parse_timestamp,
)

R, W = RejectReason, WarningCode


@dataclass(frozen=True)
class Column:
    name: str
    required: bool = False
    max_length: int | None = None


TEXT, LONG_TEXT = 200, 500

# Column order here is the documented order and the order issues are reported in.
SCHEMAS: dict[str, tuple[Column, ...]] = {
    "accounts": (
        Column("account_id", required=True),
        Column("name", max_length=TEXT),
        Column("domain", max_length=TEXT),
    ),
    "contacts": (
        Column("contact_id", required=True),
        Column("account_id", required=True),
        Column("email", max_length=254),
    ),
    "opportunities": (
        Column("opportunity_id", required=True),
        Column("account_id", required=True),
        Column("contact_id"),
        Column("name", max_length=TEXT),
        Column("amount", required=True),
        Column("currency", required=True),
        Column("stage", required=True),
        Column("created_at", required=True),
        Column("won_at"),
    ),
    "touchpoints": (
        Column("touchpoint_id", required=True),
        Column("contact_id", required=True),
        Column("occurred_at", required=True),
        Column("utm_source", max_length=TEXT),
        Column("utm_medium", max_length=TEXT),
        Column("utm_campaign", max_length=TEXT),
        Column("utm_content", max_length=TEXT),
        Column("utm_term", max_length=TEXT),
        Column("landing_page", max_length=LONG_TEXT),
        Column("referrer", max_length=LONG_TEXT),
    ),
}
ENTITIES = tuple(SCHEMAS)  # validation order: parents before children
STAGES = ("open", "won")
CAMPAIGN_COLUMNS = ("utm_source", "utm_medium", "utm_campaign")


def id_column(entity: str) -> str:
    return SCHEMAS[entity][0].name


# --- input -------------------------------------------------------------------


@dataclass(frozen=True)
class Table:
    """One import file: its header and its data rows (raw strings)."""

    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]

    def without_column(self, name: str) -> "Table":
        return Table(
            columns=tuple(c for c in self.columns if c != name),
            rows=tuple({k: v for k, v in row.items() if k != name} for row in self.rows),
        )


@dataclass
class ImportBatch:
    """The files of one import. An entity missing from `tables` is a missing file."""

    tables: dict[str, Table]

    @classmethod
    def from_rows(cls, **rows_by_entity: list[dict[str, str]]) -> "ImportBatch":
        tables = {}
        for entity, rows in rows_by_entity.items():
            columns = list(dict.fromkeys(key for row in rows for key in row))
            if not rows:  # header-only file
                columns = [c.name for c in SCHEMAS[entity]]
            tables[entity] = Table(tuple(columns), tuple(rows))
        return cls(tables)

    @classmethod
    def from_csv_dir(cls, path: Path) -> "ImportBatch":
        """Read `<entity>.csv` files (UTF-8, header row) from a directory."""
        texts = {}
        for entity in ENTITIES:
            file = Path(path) / f"{entity}.csv"
            if file.exists():
                texts[entity] = file.read_bytes().decode("utf-8-sig")  # keep \r\n as-is
        return cls.from_csv_texts(texts)

    @classmethod
    def from_csv_texts(cls, texts: dict[str, str]) -> "ImportBatch":
        """Build a batch from each file's decoded text, keyed by entity. Absent = missing file."""
        tables = {}
        for entity in ENTITIES:
            if entity not in texts:
                continue
            reader = csv.DictReader(io.StringIO(texts[entity].removeprefix("\ufeff"), newline=""))
            columns = tuple((name or "").strip() for name in reader.fieldnames or ())
            rows = tuple(
                {(k or "").strip(): v for k, v in row.items() if k is not None} for row in reader
            )
            tables[entity] = Table(columns, rows)
        return cls(tables)


# --- accepted records --------------------------------------------------------


@dataclass(frozen=True)
class AccountRecord:
    account_id: str
    name: str
    domain: str
    row: int


@dataclass(frozen=True)
class ContactRecord:
    contact_id: str
    account_id: str
    email: str
    row: int


@dataclass(frozen=True)
class OpportunityRecord:
    opportunity_id: str
    account_id: str
    contact_id: str  # "" when the opportunity has no contact
    name: str
    amount: Decimal
    currency: str
    stage: str
    created_at: datetime  # UTC
    won_at: datetime | None  # UTC
    row: int


@dataclass(frozen=True)
class TouchpointRecord:
    touchpoint_id: str
    contact_id: str
    occurred_at: datetime  # UTC
    source: str
    medium: str
    campaign: str
    content: str
    term: str
    landing_page: str
    referrer: str
    row: int


# --- report ------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    entity: str
    row: int  # header is row 1, so the first data row is row 2; 1 means the file itself
    record_id: str
    code: RejectReason | WarningCode
    field: str
    message: str

    @property
    def file(self) -> str:
        return f"{self.entity}.csv"

    def to_dict(self) -> dict:
        return {**asdict(self), "code": str(self.code), "file": self.file}


@dataclass(frozen=True)
class RejectedRow:
    entity: str
    row: int
    record_id: str
    values: dict[str, str]
    issues: tuple[Issue, ...]

    def to_dict(self) -> dict:
        return {
            "entity": self.entity,
            "file": f"{self.entity}.csv",
            "row": self.row,
            "record_id": self.record_id,
            "values": self.values,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class ImportReport:
    lookback_days: int
    accepted: dict[str, list] = field(default_factory=lambda: {e: [] for e in ENTITIES})
    rejected: list[RejectedRow] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    file_errors: list[Issue] = field(default_factory=list)
    received: dict[str, int] = field(default_factory=lambda: dict.fromkeys(ENTITIES, 0))

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.file_errors

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        counts = {}
        for entity in ENTITIES:
            accepted = len(self.accepted[entity])
            rejected = sum(1 for r in self.rejected if r.entity == entity)
            counts[entity] = {
                "received": self.received[entity],
                "accepted": accepted,
                "rejected": rejected,
                "duplicates": self.received[entity] - accepted - rejected,
            }
        return counts

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "lookback_days": self.lookback_days,
            "counts": self.counts,
            "file_errors": [issue.to_dict() for issue in self.file_errors],
            "rejected": [row.to_dict() for row in self.rejected],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "accepted_ids": {
                entity: [getattr(rec, id_column(entity)) for rec in records]
                for entity, records in self.accepted.items()
            },
        }


# --- validation --------------------------------------------------------------


def validate_import(batch: ImportBatch, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> ImportReport:
    report = ImportReport(lookback_days=lookback_days)
    for entity in ENTITIES:
        _validate_table(entity, batch.tables.get(entity), report)
    _warn_unreachable_touchpoints(report)
    report.warnings.sort(key=lambda w: (ENTITIES.index(w.entity), w.row))  # stable
    return report


class _RowCheck:
    """Collects issues for one row while its fields are parsed."""

    def __init__(self, entity: str, row: int, values: dict[str, str]):
        self.entity, self.row, self.values = entity, row, values
        self.record_id = values.get(id_column(entity), "")
        self.issues: list[Issue] = []

    def reject(self, code: RejectReason, column: str, message: str) -> None:
        self.issues.append(Issue(self.entity, self.row, self.record_id, code, column, message))

    def get(self, column: str) -> str:
        return self.values.get(column, "")

    def timestamp(self, column: str) -> datetime | None:
        value = self.get(column)
        if not value:
            return None
        parsed, reason = parse_timestamp(value)
        if reason:
            self.reject(reason, column, f"{value!r} must be ISO 8601 with a UTC offset.")
        return parsed

    def reference(self, column: str, known: set[str], code: RejectReason, parent: str) -> bool:
        value = self.get(column)
        if value and value not in known:
            self.reject(code, column, f"{value!r} is not an accepted {parent}.")
            return False
        return bool(value)


def _validate_table(entity: str, table: Table | None, report: ImportReport) -> None:
    schema = SCHEMAS[entity]
    if table is None:
        report.file_errors.append(
            Issue(entity, 1, "", R.MISSING_FILE, "", f"{entity}.csv was not provided.")
        )
        return
    report.received[entity] = len(table.rows)
    known = {c.name for c in schema}
    for column in table.columns:
        if column and column not in known:
            report.warnings.append(
                Issue(entity, 1, "", W.UNKNOWN_COLUMN, column, f"Column {column!r} was ignored.")
            )
    missing = [c.name for c in schema if c.required and c.name not in table.columns]
    if missing:
        errors = [
            Issue(entity, 1, "", R.MISSING_COLUMN, name, f"Required column {name!r} is absent.")
            for name in missing
        ]
        report.file_errors.extend(errors)
        for number, raw in enumerate(table.rows, start=2):
            values = _clean(raw, known)
            record_id = values.get(id_column(entity), "")
            issues = tuple(replace(e, row=number, record_id=record_id) for e in errors)
            report.rejected.append(RejectedRow(entity, number, record_id, values, issues))
        return

    rows = [(number, _clean(raw, known)) for number, raw in enumerate(table.rows, start=2)]
    contents_by_id: dict[str, set[tuple]] = defaultdict(set)
    for _, values in rows:
        if values[id_column(entity)]:
            contents_by_id[values[id_column(entity)]].add(tuple(sorted(values.items())))
    seen: set[str] = set()
    for number, values in rows:
        record_id = values[id_column(entity)]
        conflicting = len(contents_by_id.get(record_id, ())) > 1
        if record_id and not conflicting and record_id in seen:
            report.warnings.append(
                Issue(
                    entity,
                    number,
                    record_id,
                    W.DUPLICATE_ROW,
                    id_column(entity),
                    "Exact repeat of an earlier row; counted once.",
                )
            )
            continue
        seen.add(record_id)
        check = _RowCheck(entity, number, values)
        _check_common(check, schema)
        record = PARSERS[entity](check, report)
        if conflicting:
            check.reject(
                R.DUPLICATE_ID,
                id_column(entity),
                f"{record_id!r} appears more than once with different values.",
            )
        if check.issues:
            report.rejected.append(
                RejectedRow(entity, number, record_id, values, tuple(check.issues))
            )
        else:
            report.accepted[entity].append(record)
            report.warnings.extend(_row_warnings(entity, record))


def _clean(raw: dict[str, str | None], known: set[str]) -> dict[str, str]:
    """Contract columns only, each trimmed; absent or blank cells become ''."""
    return {name: (raw.get(name) or "").strip() for name in sorted(known)}


def _check_common(check: _RowCheck, schema: tuple[Column, ...]) -> None:
    for column in schema:
        value = check.get(column.name)
        if column.required and not value:
            check.reject(R.MISSING_REQUIRED_FIELD, column.name, f"{column.name} is required.")
        if column.max_length and len(value) > column.max_length:
            check.reject(
                R.VALUE_TOO_LONG,
                column.name,
                f"{column.name} is {len(value)} characters; the limit is {column.max_length}.",
            )
    id_name = schema[0].name
    if check.get(id_name) and parse_id(check.get(id_name))[1]:
        check.reject(
            R.INVALID_ID,
            id_name,
            f"{check.get(id_name)!r} must be 1-64 characters of A-Z a-z 0-9 . _ : -",
        )


def _account(check: _RowCheck, report: ImportReport) -> AccountRecord:
    return AccountRecord(check.get("account_id"), check.get("name"), check.get("domain"), check.row)


def _contact(check: _RowCheck, report: ImportReport) -> ContactRecord:
    accounts = {a.account_id for a in report.accepted["accounts"]}
    check.reference("account_id", accounts, R.UNKNOWN_ACCOUNT, "account")
    email = check.get("email")
    if email and parse_email(email)[1]:
        check.reject(R.INVALID_EMAIL, "email", f"{email!r} is not a valid email address.")
    return ContactRecord(check.get("contact_id"), check.get("account_id"), email, check.row)


def _opportunity(check: _RowCheck, report: ImportReport) -> OpportunityRecord | None:
    accounts = {a.account_id for a in report.accepted["accounts"]}
    contacts = {c.contact_id: c.account_id for c in report.accepted["contacts"]}
    has_account = check.reference("account_id", accounts, R.UNKNOWN_ACCOUNT, "account")
    has_contact = check.reference("contact_id", set(contacts), R.UNKNOWN_CONTACT, "contact")
    if has_account and has_contact and contacts[check.get("contact_id")] != check.get("account_id"):
        check.reject(
            R.CONTACT_ACCOUNT_MISMATCH,
            "contact_id",
            f"Contact {check.get('contact_id')!r} belongs to account "
            f"{contacts[check.get('contact_id')]!r}, not {check.get('account_id')!r}.",
        )

    amount = currency = None
    if raw := check.get("amount"):
        amount, reason = parse_amount(raw)
        if reason:
            check.reject(reason, "amount", f"{raw!r} must be a plain non-negative decimal.")
    if raw := check.get("currency"):
        currency, reason = parse_currency(raw)
        if reason:
            currency = None
            check.reject(reason, "currency", f"{raw!r} is not a supported uppercase ISO code.")
    if amount is not None and currency and not fits_currency(amount, currency):
        check.reject(
            R.AMOUNT_PRECISION,
            "amount",
            f"{check.get('amount')} has more decimal places than {currency} allows.",
        )

    stage = check.get("stage")
    if stage and stage not in STAGES:
        check.reject(R.INVALID_STAGE, "stage", f"{stage!r} must be one of {', '.join(STAGES)}.")
    created_at = check.timestamp("created_at")
    won_at = check.timestamp("won_at")
    if stage == "won" and not check.get("won_at"):
        check.reject(R.WON_AT_REQUIRED, "won_at", "A won opportunity needs won_at.")
    if stage == "open" and check.get("won_at"):
        check.reject(R.WON_AT_NOT_ALLOWED, "won_at", "An open opportunity cannot have won_at.")
    if created_at and won_at and won_at < created_at:
        check.reject(R.WON_BEFORE_CREATED, "won_at", "won_at is earlier than created_at.")
    if check.issues:
        return None
    return OpportunityRecord(
        opportunity_id=check.get("opportunity_id"),
        account_id=check.get("account_id"),
        contact_id=check.get("contact_id"),
        name=check.get("name"),
        amount=amount,
        currency=currency,
        stage=stage,
        created_at=created_at,
        won_at=won_at,
        row=check.row,
    )


def _touchpoint(check: _RowCheck, report: ImportReport) -> TouchpointRecord | None:
    contacts = {c.contact_id for c in report.accepted["contacts"]}
    check.reference("contact_id", contacts, R.UNKNOWN_CONTACT, "contact")
    occurred_at = check.timestamp("occurred_at")
    if check.issues:
        return None
    return TouchpointRecord(
        touchpoint_id=check.get("touchpoint_id"),
        contact_id=check.get("contact_id"),
        occurred_at=occurred_at,
        source=check.get("utm_source"),
        medium=check.get("utm_medium"),
        campaign=check.get("utm_campaign"),
        content=check.get("utm_content"),
        term=check.get("utm_term"),
        landing_page=check.get("landing_page"),
        referrer=check.get("referrer"),
        row=check.row,
    )


PARSERS = {
    "accounts": _account,
    "contacts": _contact,
    "opportunities": _opportunity,
    "touchpoints": _touchpoint,
}


def _row_warnings(entity: str, record) -> list[Issue]:
    warnings = []
    if entity == "opportunities":
        rid = record.opportunity_id
        if not record.contact_id:
            warnings.append(
                Issue(
                    entity,
                    record.row,
                    rid,
                    W.OPPORTUNITY_WITHOUT_CONTACT,
                    "contact_id",
                    "No contact: no touchpoints can be credited, so the full amount is "
                    "Unattributed.",
                )
            )
        if record.amount == 0:
            warnings.append(Issue(entity, record.row, rid, W.ZERO_AMOUNT, "amount", "Amount is 0."))
    if entity == "touchpoints":
        values = dict(
            zip(CAMPAIGN_COLUMNS, (record.source, record.medium, record.campaign), strict=True)
        )
        blank = [name for name, value in values.items() if not value]
        if blank:
            warnings.append(
                Issue(
                    entity,
                    record.row,
                    record.touchpoint_id,
                    W.MISSING_CAMPAIGN_FIELDS,
                    ", ".join(blank),
                    "Blank campaign fields are reported as (none), not guessed.",
                )
            )
    return warnings


def _warn_unreachable_touchpoints(report: ImportReport) -> None:
    """Warn about touchpoints that no opportunity's lookback window (pipeline or won) covers.

    Pipeline conversions happen at created_at and won conversions at won_at
    (docs/decisions.md). Window membership uses attribution.eligible_touchpoints so the
    rule has a single definition.
    """
    conversion_times: dict[str, list[datetime]] = defaultdict(list)
    for opp in report.accepted["opportunities"]:
        if opp.contact_id:
            conversion_times[opp.contact_id].append(opp.created_at)
            if opp.won_at:
                conversion_times[opp.contact_id].append(opp.won_at)
    for tp in report.accepted["touchpoints"]:
        times = conversion_times.get(tp.contact_id, [])
        touch = Touchpoint(id=tp.touchpoint_id, occurred_at=tp.occurred_at)
        reachable = any(
            eligible_touchpoints(
                Conversion("", Decimal(0), "", converted_at, (touch,)), report.lookback_days
            )
            for converted_at in times
        )
        if reachable:
            continue
        message = (
            f"Contact {tp.contact_id!r} has no opportunities."
            if not times
            else f"Outside every {report.lookback_days}-day lookback window of contact "
            f"{tp.contact_id!r}'s opportunities."
        )
        report.warnings.append(
            Issue(
                "touchpoints",
                tp.row,
                tp.touchpoint_id,
                W.TOUCHPOINT_OUTSIDE_LOOKBACK,
                "occurred_at",
                message,
            )
        )
