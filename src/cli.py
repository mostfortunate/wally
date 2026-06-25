"""Wally CLI — budget reconciliation from bank statement PDFs.

Pipeline: parse (CIBC and/or RBC) → balance gate (RBC only; CIBC's runs inside the
parser) → classify combined transactions → partition gate → aggregate → print report.
A failed gate aborts with a diff and a non-zero exit; no report is emitted.

Usage:
    wally --cibc <statement.pdf> --rbc <statement.pdf>   # combine both (default use)
    wally --cibc <statement.pdf>                          # CIBC only
    wally --rbc  <statement.pdf>                          # RBC only
"""

from __future__ import annotations

import argparse
import sys

from src.budget import BudgetLimits, aggregate
from src.budget.config import load_budget_limits
from src.classification import ClassificationRules, classify, load_rules
from src.parsers.base import Transaction
from src.parsers.cibc import CibcParser
from src.parsers.rbc import RbcParser
from src.reconciliation import ReconciliationError, check_balance, check_partition
from src.report import render

DEFAULT_BUDGET_CONFIG = "wally.toml"
DEFAULT_RULES_CONFIG = "classification.toml"


def run(
    limits: BudgetLimits,
    rules: ClassificationRules,
    cibc_path: str | None = None,
    rbc_path: str | None = None,
) -> int:
    """Run the full pipeline. Returns a process exit code."""
    all_transactions: list[Transaction] = []

    if cibc_path:
        cibc_stmt = CibcParser().parse(cibc_path)
        # CIBC Gate-1 runs inside the parser per-card block; no statement-level balances.
        all_transactions.extend(cibc_stmt.transactions)

    if rbc_path:
        rbc_stmt = RbcParser().parse(rbc_path)
        check_balance(rbc_stmt)
        all_transactions.extend(rbc_stmt.transactions)

    classified = classify(all_transactions, rules)
    check_partition(all_transactions, classified)

    reports = aggregate(classified, limits)
    render(reports, classified)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wally",
        description="Budget reconciliation from bank statement PDFs.",
        epilog="At least one of --cibc or --rbc is required.",
    )
    parser.add_argument("--cibc", metavar="PDF", help="path to CIBC credit card statement")
    parser.add_argument("--rbc", metavar="PDF", help="path to RBC chequing statement")
    parser.add_argument(
        "-c", "--config", default=DEFAULT_BUDGET_CONFIG, help="path to budget config TOML"
    )
    parser.add_argument(
        "-r", "--rules", default=DEFAULT_RULES_CONFIG, help="path to classification rules TOML"
    )
    args = parser.parse_args(argv)

    if not args.cibc and not args.rbc:
        parser.error("at least one of --cibc or --rbc is required")

    limits = load_budget_limits(args.config)
    rules = load_rules(args.rules)
    try:
        return run(limits, rules, cibc_path=args.cibc, rbc_path=args.rbc)
    except ReconciliationError as exc:
        print(f"Reconciliation aborted — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
