"""Unit tests for the terminal budget report."""

from __future__ import annotations

from decimal import Decimal

from src.budget import CategoryReport, Status
from src.cli import render


def test_renders_each_status_with_symbol(capsys) -> None:
    reports = [
        CategoryReport("takeout", Decimal("90.00"), Decimal("60.00"), Status.OVER),
        CategoryReport("groceries", Decimal("40.00"), Decimal("80.00"), Status.WITHIN),
        CategoryReport("gas", Decimal("0"), Decimal("200.00"), Status.UNDER),
    ]
    render(reports)
    out = capsys.readouterr().out

    assert "takeout" in out
    assert "$90.00 > $60.00  OVER" in out
    assert "$40.00 = $80.00  WITHIN" in out
    assert "$0.00 < $200.00  UNDER" in out


def test_unbudgeted_category_has_no_verdict(capsys) -> None:
    render([CategoryReport("pets", Decimal("40.00"), None, None)])
    out = capsys.readouterr().out
    assert "pets" in out
    assert "unbudgeted" in out
    assert "OVER" not in out and "UNDER" not in out


def test_empty_reports_is_handled(capsys) -> None:
    render([])
    assert "No categories" in capsys.readouterr().out
