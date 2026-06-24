"""Entry point + terminal report.

Pipeline: ingest (detect bank → parse) → balance gate (RBC only; CIBC's runs inside
the parser) → classify → partition gate → aggregate → print report. A failed gate
aborts with a diff and a non-zero exit; no report is emitted on a failed reconciliation.

Run:  uv run python -m src.cli <statement.pdf>
"""

from __future__ import annotations

import argparse
import sys

from src.budget import BudgetLimits, aggregate
from src.budget.config import load_budget_limits
from src.classification import ClassificationRules, classify, load_rules
from src.ingestion import ingest
from src.reconciliation import ReconciliationError, check_balance, check_partition
from src.report import render

DEFAULT_BUDGET_CONFIG = "wally.toml"
DEFAULT_RULES_CONFIG = "classification.toml"


def run(pdf_path: str, limits: BudgetLimits, rules: ClassificationRules) -> int:
    """Run the full pipeline for one statement. Returns a process exit code."""
    statement = ingest(pdf_path)

    # CIBC's Gate-1 runs inside the parser (per-card block tie-out). Only run the
    # statement-level balance gate for banks that populate opening/closing balances.
    if statement.opening_balance is not None or statement.closing_balance is not None:
        check_balance(statement)

    classified = classify(statement.transactions, rules)
    check_partition(statement.transactions, classified)

    reports = aggregate(classified, limits)
    render(reports, classified)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wally", description="Budget reconciliation from a bank statement PDF."
    )
    parser.add_argument("statement", help="path to a statement PDF")
    parser.add_argument(
        "-c", "--config", default=DEFAULT_BUDGET_CONFIG, help="path to budget config TOML"
    )
    parser.add_argument(
        "-r", "--rules", default=DEFAULT_RULES_CONFIG, help="path to classification rules TOML"
    )
    args = parser.parse_args(argv)

    limits = load_budget_limits(args.config)
    rules = load_rules(args.rules)
    try:
        return run(args.statement, limits, rules)
    except ReconciliationError as exc:
        print(f"Reconciliation aborted — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
