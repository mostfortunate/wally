"""Aggregate classified transactions against per-category monthly limits.

Budgets care about withdrawals (spend). The within/under/over verdict is a pure
function of spent-vs-limit; aggregation groups CATEGORIZED spend by category and
sums it. UNCATEGORIZED spend is reported separately as a warning, never folded into
"underspending."
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto

from src.parsers.base import Classified, Direction, Disposition

ZERO = Decimal("0")

#: Per-category monthly spending limits, e.g. {"takeout": Decimal("100"), "gas": Decimal("300")}.
BudgetLimits = dict[str, Decimal]


class Status(Enum):
    """Where a category landed relative to its limit."""

    WITHIN = auto()
    UNDER = auto()
    OVER = auto()


def status_for(
    spent: Decimal, limit: Decimal, *, under_threshold: Decimal = Decimal("0.5")
) -> Status:
    """Classify spend against a limit.

    OVER when spend exceeds the limit; UNDER when spend is below `under_threshold` of
    the limit (meaningfully underspending); WITHIN otherwise. Pure function.
    """
    if spent > limit:
        return Status.OVER
    if limit > ZERO and spent < limit * under_threshold:
        return Status.UNDER
    return Status.WITHIN


@dataclass
class CategoryReport:
    category: str
    spent: Decimal
    limit: Decimal | None
    status: Status | None  # None when there is no limit to measure against


def _net_spend(txns: list[Classified]) -> Decimal:
    """Net spend for a group: withdrawals are spend, deposits (e.g. refunds) offset it."""
    total = ZERO
    for c in txns:
        if c.txn.direction is Direction.WITHDRAWAL:
            total += c.txn.amount
        else:
            total -= c.txn.amount
    return total


def aggregate(classified: list[Classified], limits: BudgetLimits) -> list[CategoryReport]:
    """Sum CATEGORIZED spend per category and assign a within/under/over status.

    Reports every category that has either a configured limit or some spend, so a
    budgeted category with no activity still shows (as underspending). A category with
    spend but no limit surfaces with `limit`/`status` of None — spend we can't measure.
    Refunds (CATEGORIZED deposits) net against their category. EXCLUDED and
    UNCATEGORIZED are intentionally not folded in here.
    """
    spend_by_category: dict[str, list[Classified]] = {}
    for c in classified:
        if c.disposition is Disposition.CATEGORIZED and c.category is not None:
            spend_by_category.setdefault(c.category, []).append(c)

    reports: list[CategoryReport] = []
    for category in sorted(limits.keys() | spend_by_category.keys()):
        spent = _net_spend(spend_by_category.get(category, []))
        limit = limits.get(category)
        status = status_for(spent, limit) if limit is not None else None
        reports.append(CategoryReport(category=category, spent=spent, limit=limit, status=status))
    return reports


__all__ = ["BudgetLimits", "CategoryReport", "Status", "aggregate", "status_for"]
