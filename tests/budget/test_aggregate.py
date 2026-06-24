"""Unit tests for budget aggregation."""

from __future__ import annotations

from decimal import Decimal

from src.budget import Status, aggregate
from src.parsers.base import Classified, Direction, Disposition, Transaction


def _cat(amount: str, category: str, direction: Direction = Direction.WITHDRAWAL) -> Classified:
    txn = Transaction(raw_description=category, amount=Decimal(amount), direction=direction)
    return Classified(txn, Disposition.CATEGORIZED, category=category)


def test_sums_spend_per_category_with_status() -> None:
    classified = [
        _cat("30.00", "gas"),
        _cat("25.00", "gas"),
        _cat("90.00", "takeout"),
    ]
    limits = {"gas": Decimal("200.00"), "takeout": Decimal("60.00")}
    reports = {r.category: r for r in aggregate(classified, limits)}

    assert reports["gas"].spent == Decimal("55.00")
    assert reports["gas"].status is Status.UNDER  # 55 < 200*0.5
    assert reports["takeout"].spent == Decimal("90.00")
    assert reports["takeout"].status is Status.OVER  # 90 > 60


def test_refund_nets_against_its_category() -> None:
    classified = [
        _cat("80.00", "groceries"),
        _cat("20.00", "groceries", direction=Direction.DEPOSIT),  # refund
    ]
    reports = {r.category: r for r in aggregate(classified, {"groceries": Decimal("80.00")})}
    assert reports["groceries"].spent == Decimal("60.00")
    assert reports["groceries"].status is Status.WITHIN


def test_budgeted_category_with_no_activity_shows_as_underspending() -> None:
    reports = {r.category: r for r in aggregate([], {"gas": Decimal("200.00")})}
    assert reports["gas"].spent == Decimal("0")
    assert reports["gas"].status is Status.UNDER


def test_spend_without_a_limit_surfaces_with_no_status() -> None:
    reports = {r.category: r for r in aggregate([_cat("40.00", "pets")], {})}
    assert reports["pets"].spent == Decimal("40.00")
    assert reports["pets"].limit is None
    assert reports["pets"].status is None


def test_excluded_and_uncategorized_are_not_aggregated() -> None:
    txn = Transaction("x", Decimal("500.00"), Direction.WITHDRAWAL)
    classified = [
        Classified(txn, Disposition.EXCLUDED, reason="CIBC card payment"),
        Classified(txn, Disposition.UNCATEGORIZED),
    ]
    assert aggregate(classified, {"gas": Decimal("200.00")}) == [
        # only the budgeted category, with zero spend
        aggregate([], {"gas": Decimal("200.00")})[0]
    ]
