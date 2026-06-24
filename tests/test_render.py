"""Tests for src/report.py — render() stdout output via capsys."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.budget import CategoryReport, Status
from src.parsers.base import Classified, Direction, Disposition, Transaction
from src.report import render

ZERO = Decimal("0")


def _txn(
    amount: str,
    direction: Direction = Direction.WITHDRAWAL,
    description: str = "desc",
) -> Transaction:
    return Transaction(raw_description=description, amount=Decimal(amount), direction=direction)


def _categorized(
    amount: str, category: str, direction: Direction = Direction.WITHDRAWAL
) -> Classified:
    return Classified(
        txn=_txn(amount, direction),
        disposition=Disposition.CATEGORIZED,
        category=category,
    )


def _uncategorized(amount: str, direction: Direction = Direction.WITHDRAWAL) -> Classified:
    return Classified(txn=_txn(amount, direction), disposition=Disposition.UNCATEGORIZED)


def _excluded(amount: str, reason: str = "transfer") -> Classified:
    return Classified(
        txn=_txn(amount),
        disposition=Disposition.EXCLUDED,
        reason=reason,
    )


def _report(
    category: str,
    spent: str,
    limit: str | None,
    status: Status | None,
) -> CategoryReport:
    return CategoryReport(
        category=category,
        spent=Decimal(spent),
        limit=Decimal(limit) if limit is not None else None,
        status=status,
    )


# ---------------------------------------------------------------------------
# Status labels
# ---------------------------------------------------------------------------


def test_within_appears_in_output(capsys: pytest.CaptureFixture[str]) -> None:
    reports = [_report("takeout", "45.20", "60.00", Status.WITHIN)]
    render(reports, [])
    out = capsys.readouterr().out
    assert "WITHIN" in out
    assert "takeout" in out
    assert "$45.20" in out
    assert "$60.00" in out


def test_under_appears_in_output(capsys: pytest.CaptureFixture[str]) -> None:
    reports = [_report("groceries", "12.00", "80.00", Status.UNDER)]
    render(reports, [])
    out = capsys.readouterr().out
    assert "UNDER" in out
    assert "groceries" in out
    assert "$12.00" in out
    assert "$80.00" in out


def test_over_appears_in_output(capsys: pytest.CaptureFixture[str]) -> None:
    reports = [_report("gas", "210.50", "200.00", Status.OVER)]
    render(reports, [])
    out = capsys.readouterr().out
    assert "OVER" in out
    assert "gas" in out
    assert "$210.50" in out
    assert "$200.00" in out


# ---------------------------------------------------------------------------
# No-limit category
# ---------------------------------------------------------------------------


def test_no_limit_shows_no_limit_label(capsys: pytest.CaptureFixture[str]) -> None:
    reports = [_report("pets", "40.00", None, None)]
    render(reports, [])
    out = capsys.readouterr().out
    assert "no limit" in out
    assert "pets" in out
    assert "$40.00" in out
    # Must NOT show a status token when there is no limit
    assert "WITHIN" not in out
    assert "UNDER" not in out
    assert "OVER" not in out


# ---------------------------------------------------------------------------
# Alphabetical ordering
# ---------------------------------------------------------------------------


def test_categories_sorted_alphabetically(capsys: pytest.CaptureFixture[str]) -> None:
    reports = [
        _report("takeout", "45.00", "60.00", Status.WITHIN),
        _report("gas", "100.00", "200.00", Status.UNDER),
        _report("groceries", "80.00", "80.00", Status.WITHIN),
    ]
    render(reports, [])
    out = capsys.readouterr().out
    gas_pos = out.index("gas")
    groceries_pos = out.index("groceries")
    takeout_pos = out.index("takeout")
    assert gas_pos < groceries_pos < takeout_pos


# ---------------------------------------------------------------------------
# Uncategorized warning
# ---------------------------------------------------------------------------


def test_uncategorized_warning_printed(capsys: pytest.CaptureFixture[str]) -> None:
    classified = [
        _uncategorized("50.00", Direction.WITHDRAWAL),
        _uncategorized("20.00", Direction.WITHDRAWAL),
        _uncategorized("5.00", Direction.DEPOSIT),
    ]
    render([], classified)
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "3 uncategorized transaction(s)" in out
    assert "$70.00" in out  # withdrawals total
    assert "$5.00" in out  # deposits total


def test_uncategorized_warning_withdrawal_only(capsys: pytest.CaptureFixture[str]) -> None:
    classified = [_uncategorized("87.40", Direction.WITHDRAWAL)]
    render([], classified)
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "$87.40" in out
    assert "$0.00" in out


def test_uncategorized_warning_deposit_only(capsys: pytest.CaptureFixture[str]) -> None:
    classified = [_uncategorized("15.00", Direction.DEPOSIT)]
    render([], classified)
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "$0.00" in out  # withdrawals
    assert "$15.00" in out  # deposits


# ---------------------------------------------------------------------------
# No uncategorized → no warning
# ---------------------------------------------------------------------------


def test_zero_uncategorized_no_warning(capsys: pytest.CaptureFixture[str]) -> None:
    classified = [
        _categorized("30.00", "takeout"),
        _excluded("100.00", "CIBC card payment"),
    ]
    render([], classified)
    out = capsys.readouterr().out
    assert "WARNING" not in out
    assert "uncategorized" not in out.lower()


def test_empty_classified_no_warning(capsys: pytest.CaptureFixture[str]) -> None:
    render([], [])
    out = capsys.readouterr().out
    assert "WARNING" not in out


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_reports_no_crash(capsys: pytest.CaptureFixture[str]) -> None:
    render([], [])
    # Should not raise; output may be empty or minimal
    capsys.readouterr()


def test_mixed_dispositions_only_uncategorized_warned(capsys: pytest.CaptureFixture[str]) -> None:
    classified = [
        _categorized("30.00", "food"),
        _excluded("200.00", "card payment"),
        _uncategorized("42.00"),
    ]
    render([], classified)
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "1 uncategorized transaction(s)" in out
    assert "$42.00" in out
