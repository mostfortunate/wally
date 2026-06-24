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

from src.parsers.base import Classified

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


def aggregate(classified: list[Classified], limits: BudgetLimits) -> list[CategoryReport]:
    """Sum CATEGORIZED spend per category and assign a within/under/over status.

    Phase 0 stub — implemented in the Phase 1 vertical slice once classification lands.
    """
    raise NotImplementedError("budget aggregation — Phase 1")


__all__ = ["BudgetLimits", "CategoryReport", "Status", "aggregate", "status_for"]
