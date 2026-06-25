"""Wally CLI — budget reconciliation from bank statement PDFs.

Pipeline: parse (CIBC and/or RBC) → balance gate (RBC only; CIBC's runs inside the
parser) → classify combined transactions → partition gate → aggregate → print report.
A failed gate aborts with a diff and a non-zero exit; no report is emitted.

Subcommands / usage:
    wally init                                            # scaffold wally.toml interactively
    wally                                                 # auto-discover latest from statements/
    wally --cibc <statement.pdf> --rbc <statement.pdf>   # combine both explicitly
    wally --cibc <statement.pdf>                          # CIBC only
    wally --rbc  <statement.pdf>                          # RBC only

When no --cibc/--rbc flags are given, wally looks for the most recent YYYY-MM.pdf
in statements/cibc/ and statements/rbc/ (or the directory given by --statements-dir).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from src.budget import BudgetLimits, aggregate
from src.budget.config import load_budget_limits
from src.classification import ClassificationRules, classify, load_rules
from src.ingestion.discovery import find_latest
from src.init_cmd import run_init
from src.parsers.base import Transaction
from src.parsers.cibc import CibcParser
from src.parsers.rbc import RbcParser
from src.reconciliation import ReconciliationError, check_balance, check_partition
from src.report import render


def _period_label(cibc_path: str | None, rbc_path: str | None) -> str | None:
    """Format a human-readable period from YYYY-MM PDF filenames, or None if unavailable."""
    months: set[str] = set()
    for path in (cibc_path, rbc_path):
        if path is None:
            continue
        stem = Path(path).stem
        if len(stem) == 7 and stem[4] == "-" and stem[:4].isdigit() and stem[5:].isdigit():
            months.add(stem)
    if not months:
        return None
    labels = [date(int(s[:4]), int(s[5:]), 1).strftime("%B %Y") for s in sorted(months)]
    return " – ".join(labels)


DEFAULT_BUDGET_CONFIG = "wally.toml"
DEFAULT_RULES_CONFIG = "classification.toml"
DEFAULT_STATEMENTS_DIR = "statements"


def run(
    limits: BudgetLimits,
    rules: ClassificationRules,
    cibc_path: str | None = None,
    rbc_path: str | None = None,
    *,
    period: str | None = None,
    is_latest: bool = False,
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
    render(reports, classified, period=period, is_latest=is_latest)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wally",
        description="Budget reconciliation from bank statement PDFs.",
        epilog=(
            "When no --cibc/--rbc flags are given, the latest YYYY-MM.pdf is "
            "auto-discovered from <statements-dir>/cibc/ and <statements-dir>/rbc/."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    init_p = subparsers.add_parser("init", help="scaffold wally.toml interactively")
    init_p.add_argument(
        "-c", "--config", default=DEFAULT_BUDGET_CONFIG, help="path to write (default: wally.toml)"
    )

    parser.add_argument("--cibc", metavar="PDF", help="path to CIBC credit card statement")
    parser.add_argument("--rbc", metavar="PDF", help="path to RBC chequing statement")
    parser.add_argument(
        "-c", "--config", default=DEFAULT_BUDGET_CONFIG, help="path to budget config TOML"
    )
    parser.add_argument(
        "-r", "--rules", default=DEFAULT_RULES_CONFIG, help="path to classification rules TOML"
    )
    parser.add_argument(
        "--statements-dir",
        default=DEFAULT_STATEMENTS_DIR,
        metavar="DIR",
        help="root folder containing cibc/ and rbc/ subdirectories (default: statements/)",
    )
    args = parser.parse_args(argv)

    if args.command == "init":
        return run_init(config_path=args.config)

    discovered = not args.cibc and not args.rbc
    if not args.cibc and not args.rbc:
        base = Path(args.statements_dir)
        cibc_path = find_latest(base / "cibc")
        rbc_path = find_latest(base / "rbc")
        if cibc_path is None and rbc_path is None:
            parser.error(
                f"no statements found in {base}/ — add YYYY-MM.pdf files to "
                f"{base}/cibc/ and {base}/rbc/"
            )
        if cibc_path is None:
            parser.error(
                f"no CIBC statement found in {base}/cibc/ — "
                f"run `wally --cibc <path>` to include one"
            )
        if rbc_path is None:
            parser.error(
                f"no RBC statement found in {base}/rbc/ — run `wally --rbc <path>` to include one"
            )
        args.cibc = str(cibc_path)
        args.rbc = str(rbc_path)

    limits = load_budget_limits(args.config)
    rules = load_rules(args.rules)
    period = _period_label(args.cibc, args.rbc)
    try:
        return run(
            limits,
            rules,
            cibc_path=args.cibc,
            rbc_path=args.rbc,
            period=period,
            is_latest=discovered,
        )
    except ReconciliationError as exc:
        print(f"Reconciliation aborted — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
