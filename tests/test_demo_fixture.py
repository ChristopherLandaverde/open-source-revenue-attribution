"""The demo fixture reproduces its hand-calculated expectations exactly.

Expectations live in sample_data/demo/expected/ and are derived in sample_data/demo/README.md.
"""

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command

from contracts import ImportBatch, validate_import
from reports.services import comparison_report, first_touch_report

DEMO = Path(__file__).resolve().parent.parent / "sample_data" / "demo"
EXPECTED_VALIDATION = json.loads((DEMO / "expected" / "validation.json").read_text())
EXPECTED_FIRST_TOUCH = json.loads((DEMO / "expected" / "first_touch.json").read_text())


@pytest.fixture(scope="module")
def report():
    return validate_import(ImportBatch.from_csv_dir(DEMO), lookback_days=90)


def test_counts_match(report):
    assert report.counts == EXPECTED_VALIDATION["counts"]
    assert report.ok is EXPECTED_VALIDATION["ok"]


def test_accepted_ids_match(report):
    assert report.to_dict()["accepted_ids"] == EXPECTED_VALIDATION["accepted_ids"]


def test_rejected_rows_and_reasons_match(report):
    got = [
        [issue.file, issue.row, issue.record_id, str(issue.code), issue.field]
        for row in report.rejected
        for issue in row.issues
    ]
    assert got == EXPECTED_VALIDATION["rejected"]
    assert report.file_errors == EXPECTED_VALIDATION["file_errors"] == []


def test_warnings_match(report):
    got = [[w.file, w.row, w.record_id, str(w.code), w.field] for w in report.warnings]
    assert got == EXPECTED_VALIDATION["warnings"]


def test_fixture_is_synthetic(report):
    for contact in report.accepted["contacts"]:
        assert contact.email.endswith(".example")


@pytest.mark.django_db
@pytest.mark.parametrize("metric", ["pipeline", "won"])
def test_first_touch_matches_hand_calculation(metric):
    call_command("load_sample_data", verbosity=0)
    result = first_touch_report(metric)
    expected = EXPECTED_FIRST_TOUCH[metric]

    got_opportunities = [
        [
            row.opportunity.external_id,
            row.credit.touchpoint_id,
            row.credit.campaign_key,
            row.credit.amount,
            row.credit.currency,
        ]
        for row in result.opportunity_rows
    ]
    assert got_opportunities == [
        [opp, tp, key, Decimal(amount), currency]
        for opp, tp, key, amount, currency in expected["opportunities"]
    ]
    assert result.campaign_rows == [
        (key, currency, Decimal(amount), count)
        for key, currency, amount, count in expected["campaigns"]
    ]

    totals = defaultdict(Decimal)
    for _, currency, amount, _ in result.campaign_rows:
        totals[currency] += amount
    assert dict(totals) == {c: Decimal(a) for c, a in expected["totals"].items()}


@pytest.mark.django_db
def test_credits_reconcile_to_opportunity_amounts():
    # Every accepted opportunity is credited exactly its amount, once per metric.
    call_command("load_sample_data", verbosity=0)
    for metric in ("pipeline", "won"):
        by_opportunity = defaultdict(Decimal)
        amounts = {}
        for row in first_touch_report(metric).opportunity_rows:
            by_opportunity[row.opportunity.external_id] += row.credit.amount
            amounts[row.opportunity.external_id] = row.opportunity.amount
        assert by_opportunity == amounts


EXPECTED_MODELS = json.loads((DEMO / "expected" / "models.json").read_text())


@pytest.mark.django_db
@pytest.mark.parametrize("metric", ["pipeline", "won"])
def test_model_comparison_matches_hand_calculation(metric):
    call_command("load_sample_data", verbosity=0)
    result = comparison_report(metric)
    assert [m.name for m in result.models] == EXPECTED_MODELS["models"]
    got = {
        block.currency: {
            "total": block.total,
            "rows": [
                [r.campaign_key, r.credits, r.influenced, r.influenced_opportunities]
                for r in block.rows
            ],
        }
        for block in result.blocks
    }
    expected = {
        currency: {
            "total": Decimal(block["total"]),
            "rows": [
                [key, [Decimal(a) for a in credits], Decimal(influenced), n]
                for key, credits, influenced, n in block["rows"]
            ],
        }
        for currency, block in EXPECTED_MODELS[metric].items()
    }
    assert got == expected
    # Every model's column reconciles to the currency's total; influence overlaps.
    for block in result.blocks:
        for i in range(len(result.models)):
            assert sum(r.credits[i] for r in block.rows) == block.total
