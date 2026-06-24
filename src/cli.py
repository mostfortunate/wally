"""Entry point + terminal report.

Pipeline: ingest (detect bank → parse) → balance gate → classify → partition gate →
aggregate against budget limits → print report. A failed gate aborts here with a diff
and a non-zero exit; no report is emitted on a failed reconciliation.

Run:  uv run python -m src.cli <statement.pdf>
"""

from __future__ import annotations

import argparse
import sys

from src.budget import aggregate
from src.classification import classify
from src.ingestion import ingest
from src.reconciliation import ReconciliationError, check_balance, check_partition

# Per-category monthly limits live in config; hardcoded empty until the human provides them.
BUDGET_LIMITS: dict = {}


def run(pdf_path: str) -> int:
    """Run the full pipeline for one statement. Returns a process exit code."""
    statement = ingest(pdf_path)
    check_balance(statement)

    classified = classify(statement.transactions)
    check_partition(statement.transactions, classified)

    reports = aggregate(classified, BUDGET_LIMITS)
    render(reports)
    return 0


def render(reports: list) -> None:
    """Print the within/under/over report to stdout. Phase 1."""
    raise NotImplementedError("terminal report — Phase 1")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wally", description="Budget reconciliation from a bank statement PDF."
    )
    parser.add_argument("statement", help="path to a statement PDF")
    args = parser.parse_args(argv)

    try:
        return run(args.statement)
    except ReconciliationError as exc:
        print(f"Reconciliation aborted — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
