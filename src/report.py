"""Terminal budget report renderer.

Prints a within/under/over summary per category, then an uncategorized warning
when any uncategorized transactions exist. Plain stdout — no colour dependency.
"""

from __future__ import annotations

from decimal import Decimal

from src.budget import CategoryReport, Status
from src.parsers.base import Classified, Direction, Disposition

ZERO = Decimal("0")

_STATUS_LABEL: dict[Status, str] = {
    Status.WITHIN: "WITHIN",
    Status.UNDER: "UNDER",
    Status.OVER: "OVER",
}


def _fmt_amount(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def render(reports: list[CategoryReport], classified: list[Classified]) -> None:
    """Print within/under/over budget report to stdout."""
    _render_category_rows(reports)
    _render_uncategorized_warning(classified)


def _render_category_rows(reports: list[CategoryReport]) -> None:
    if not reports:
        return

    sorted_reports = sorted(reports, key=lambda r: r.category)

    cat_width = max(len(r.category) for r in sorted_reports)
    spent_width = max(len(_fmt_amount(r.spent)) for r in sorted_reports)

    print()
    print("Budget Summary")
    print("-" * 50)

    for r in sorted_reports:
        cat_col = r.category.ljust(cat_width)
        spent_col = _fmt_amount(r.spent).rjust(spent_width)

        if r.limit is not None and r.status is not None:
            limit_col = f"/ {_fmt_amount(r.limit)}"
            status_col = _STATUS_LABEL[r.status]
            print(f"  {cat_col}  {spent_col}  {limit_col}  {status_col}")
        else:
            print(f"  {cat_col}  {spent_col}  (no limit)")

    print()


def _render_uncategorized_warning(classified: list[Classified]) -> None:
    uncategorized = [c for c in classified if c.disposition is Disposition.UNCATEGORIZED]
    if not uncategorized:
        return

    withdrawals = sum(
        (c.txn.amount for c in uncategorized if c.txn.direction is Direction.WITHDRAWAL),
        ZERO,
    )
    deposits = sum(
        (c.txn.amount for c in uncategorized if c.txn.direction is Direction.DEPOSIT),
        ZERO,
    )
    count = len(uncategorized)

    print(
        f"WARNING: {count} uncategorized transaction(s)"
        f" — {_fmt_amount(withdrawals)} in withdrawals,"
        f" {_fmt_amount(deposits)} in deposits"
    )
    print()


__all__ = ["render"]
