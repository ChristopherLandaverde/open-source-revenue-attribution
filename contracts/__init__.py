"""Canonical import and event contracts, as pure Python (docs/contract.md).

Like attribution/, this package must not import Django or app code
(tests/test_architecture.py). The web app hands it raw rows and loads only what it accepts.
"""

from contracts.codes import RejectReason, WarningCode
from contracts.events import Event, EventReport, content_fingerprint, validate_events
from contracts.fields import CURRENCY_MINOR_UNITS
from contracts.imports import (
    ENTITIES,
    SCHEMAS,
    AccountRecord,
    ContactRecord,
    ImportBatch,
    ImportReport,
    Issue,
    OpportunityRecord,
    RejectedRow,
    Table,
    TouchpointRecord,
    validate_import,
)

__all__ = [
    "CURRENCY_MINOR_UNITS",
    "ENTITIES",
    "SCHEMAS",
    "AccountRecord",
    "ContactRecord",
    "Event",
    "EventReport",
    "ImportBatch",
    "ImportReport",
    "Issue",
    "OpportunityRecord",
    "RejectReason",
    "RejectedRow",
    "Table",
    "TouchpointRecord",
    "WarningCode",
    "content_fingerprint",
    "validate_events",
    "validate_import",
]
