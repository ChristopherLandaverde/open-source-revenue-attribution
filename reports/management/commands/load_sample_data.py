"""Validate, then load, an import directory in the canonical CSV contract (docs/contract.md).

Defaults to the synthetic demo fixture in sample_data/demo/. Rows the validator rejects are
never loaded; each one is listed with its reason code. With --strict, any rejection refuses
the whole import. Idempotent: re-running updates rows by their IDs.
After a load, collected page events whose contact now exists become touchpoints.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from contracts import ImportBatch, ImportReport
from reports.imports import run_import

DEFAULT_PATH = Path(settings.BASE_DIR) / "sample_data" / "demo"


def display_path(path: Path) -> str:
    path = path.resolve()
    try:
        return str(path.relative_to(Path(settings.BASE_DIR).resolve()))
    except ValueError:
        return str(path)


class Command(BaseCommand):
    help = (
        "Validate and load accounts.csv, contacts.csv, opportunities.csv and touchpoints.csv "
        "from a directory (default: the synthetic demo fixture). Invalid rows are refused."
    )

    def add_arguments(self, parser):
        parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Refuse the whole import if any row or file fails validation.",
        )

    def handle(self, *args, path, strict, **options):
        if not path.is_dir():
            raise CommandError(f"{path} is not a directory of import CSV files.")
        source = display_path(path)
        result = run_import(ImportBatch.from_csv_dir(path), source=source, strict=strict)
        report = result.report
        self._describe(report, source)
        if not result.run.loaded:
            raise CommandError(
                f"Refused the whole import (--strict): {result.refused} rows or files "
                "failed validation. Nothing was loaded. Fix the rows listed above and re-run."
            )
        loaded = {e: len(r) for e, r in report.accepted.items()}
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {loaded['accounts']} accounts, {loaded['contacts']} contacts, "
                f"{loaded['opportunities']} opportunities, {loaded['touchpoints']} touchpoints "
                f"from {source}. Full validation report: /validation/"
            )
        )

    def _describe(self, report: ImportReport, source: str) -> None:
        counts = report.counts.values()
        received = sum(c["received"] for c in counts)
        accepted = sum(c["accepted"] for c in counts)
        duplicates = sum(c["duplicates"] for c in counts)
        self.stdout.write(
            f"Validated {source} ({report.lookback_days}-day lookback): {received} rows, "
            f"{accepted} accepted, {len(report.rejected)} refused, {duplicates} exact "
            f"duplicates ignored, {len(report.warnings)} warnings."
        )
        if report.file_errors:
            self.stderr.write(self.style.ERROR("File errors (file refused):"))
            for issue in report.file_errors:
                self.stderr.write(f"  {issue.file}: {issue.code} {issue.field} - {issue.message}")
        if report.rejected:
            self.stderr.write(self.style.WARNING("Refused rows (not loaded):"))
            for row in report.rejected:
                for issue in row.issues:
                    self.stderr.write(
                        f"  {issue.file} row {issue.row} [{row.record_id or 'no id'}]: "
                        f"{issue.code} {issue.field} - {issue.message}"
                    )
