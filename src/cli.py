"""Wally CLI — budget reconciliation from bank statement PDFs.

Pipeline: parse (CIBC and/or RBC) → balance gate (RBC only; CIBC's runs inside the
parser) → classify combined transactions → partition gate → aggregate → print report.
A failed gate aborts with a diff and a non-zero exit; no report is emitted.

Subcommands / usage:
    wally init                                            # scaffold wally.toml interactively
    wally cache clear                                     # delete cached statement parses
    wally annotate --cibc 2026-06 --rbc 2026-06          # label uncategorized transactions
    wally annotate list                                   # show annotation status per statement
    wally                                                 # auto-discover latest from statements/
    wally --cibc <statement.pdf> --rbc <statement.pdf>   # combine both explicitly
    wally --cibc 2026-06                            # CIBC only, resolved from statements/cibc/
    wally --rbc  2026-06                            # RBC only, resolved from statements/rbc/

When no --cibc/--rbc flags are given, wally looks for the most recent YYYY-MM.pdf
in statements/cibc/ and statements/rbc/ (or the directory given by --statements-dir).
--cibc/--rbc accept either a full file path or a bare YYYY-MM date stem.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

from src.budget import BudgetLimits, aggregate
from src.budget.config import load_budget_limits
from src.classification import ClassificationRules, classify, load_rules
from src.ingestion.cache import cached_parse
from src.ingestion.cache import clear as cache_clear
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


def _resolve_pdf_path(value: str, bank_dir: Path, parser: argparse.ArgumentParser) -> str:
    """Accept a full path or a bare YYYY-MM stem, resolving stems against bank_dir."""
    if Path(value).exists():
        return value
    candidate = bank_dir / f"{value}.pdf"
    if candidate.exists():
        return str(candidate)
    parser.error(f"cannot find PDF {value!r} — tried {candidate}")


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
    no_cache: bool = False,
) -> int:
    """Run the full pipeline. Returns a process exit code."""
    start = time.perf_counter()
    all_transactions: list[Transaction] = []

    if cibc_path:
        cibc_stmt = cached_parse(cibc_path, CibcParser(), no_cache=no_cache)
        # CIBC Gate-1 runs inside the parser per-card block; no statement-level balances.
        all_transactions.extend(cibc_stmt.transactions)

    if rbc_path:
        rbc_stmt = cached_parse(rbc_path, RbcParser(), no_cache=no_cache)
        check_balance(rbc_stmt)
        all_transactions.extend(rbc_stmt.transactions)

    classified = classify(all_transactions, rules)
    check_partition(all_transactions, classified)

    reports = aggregate(classified, limits)
    elapsed_ms = (time.perf_counter() - start) * 1000
    render(reports, classified, period=period, is_latest=is_latest, elapsed_ms=elapsed_ms)
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

    cache_p = subparsers.add_parser("cache", help="manage the statement parse cache")
    cache_sub = cache_p.add_subparsers(dest="cache_action", required=True)
    cache_sub.add_parser("clear", help="delete all cached statement parses (~/.cache/wally/)")

    annotate_p = subparsers.add_parser(
        "annotate",
        help="step through uncategorized transactions and grow classification.toml",
        description=(
            "Parses one or more statement PDFs, deduplicates uncategorized transactions "
            "by merchant, and prompts you to assign each to a category via a single-keypress "
            "menu. Writes patterns directly to classification.toml as production config. "
            "Note: tomli-w does not preserve hand-written comments in classification.toml."
        ),
    )
    annotate_p.add_argument(
        "--cibc",
        metavar="PDF",
        action="append",
        dest="cibc_pdfs",
        default=[],
        help="CIBC statement PDF or YYYY-MM stem (may be repeated)",
    )
    annotate_p.add_argument(
        "--rbc",
        metavar="PDF",
        action="append",
        dest="rbc_pdfs",
        default=[],
        help="RBC statement PDF or YYYY-MM stem (may be repeated)",
    )
    annotate_p.add_argument(
        "-r",
        "--rules",
        default=DEFAULT_RULES_CONFIG,
        dest="annotate_rules",
        help="classification rules TOML to update (default: classification.toml)",
    )
    annotate_p.add_argument(
        "--statements-dir",
        default=DEFAULT_STATEMENTS_DIR,
        metavar="DIR",
        dest="annotate_statements_dir",
        help="root folder for resolving YYYY-MM stems (default: statements/)",
    )
    annotate_sub = annotate_p.add_subparsers(dest="annotate_action")
    annotate_list_p = annotate_sub.add_parser(
        "list", help="show annotation status (done/remaining) per statement"
    )
    annotate_list_p.add_argument(
        "--statements-dir",
        default=DEFAULT_STATEMENTS_DIR,
        metavar="DIR",
        dest="list_statements_dir",
        help="root folder containing cibc/ and rbc/ subdirectories (default: statements/)",
    )
    annotate_list_p.add_argument(
        "--cibc",
        metavar="PDF",
        action="append",
        dest="list_cibc_pdfs",
        default=[],
        help="CIBC statement PDF (may be repeated; overrides auto-discovery)",
    )
    annotate_list_p.add_argument(
        "--rbc",
        metavar="PDF",
        action="append",
        dest="list_rbc_pdfs",
        default=[],
        help="RBC statement PDF (may be repeated; overrides auto-discovery)",
    )
    annotate_list_p.add_argument(
        "-r",
        "--rules",
        default=DEFAULT_RULES_CONFIG,
        dest="annotate_rules",
        help="classification rules TOML to read (default: classification.toml)",
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
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="re-parse from PDF, skipping the statement cache",
    )
    args = parser.parse_args(argv)

    if args.command == "init":
        return run_init(config_path=args.config)

    if args.command == "cache":
        if args.cache_action == "clear":
            n = cache_clear()
            if n == 0:
                print("Cache is already empty.")
            else:
                print(f"Cleared {n} cached statement parse(s).")
        return 0

    if args.command == "annotate":
        from src.annotate import run_annotate, run_annotate_list

        if args.annotate_action == "list":
            return run_annotate_list(
                rules_path=args.annotate_rules,
                statements_dir=args.list_statements_dir,
                cibc_paths=args.list_cibc_pdfs or None,
                rbc_paths=args.list_rbc_pdfs or None,
            )
        base = Path(args.annotate_statements_dir)
        cibc_pdfs = [_resolve_pdf_path(p, base / "cibc", parser) for p in args.cibc_pdfs]
        rbc_pdfs = [_resolve_pdf_path(p, base / "rbc", parser) for p in args.rbc_pdfs]
        return run_annotate(
            cibc_paths=cibc_pdfs,
            rbc_paths=rbc_pdfs,
            rules_path=args.annotate_rules,
        )

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

    if not Path(args.config).exists():
        parser.error(f"{args.config} not found — run `wally init` to set up your budget config")
    if not Path(args.rules).exists():
        parser.error(f"{args.rules} not found — create a classification rules file")

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
            no_cache=args.no_cache,
        )
    except ReconciliationError as exc:
        print(f"Reconciliation aborted — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
