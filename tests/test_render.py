"""Tests for src/report.py — render output via render_to_str (no capsys needed)."""

from __future__ import annotations

from decimal import Decimal

from src.budget import CategoryReport, Status
from src.parsers.base import Classified, Direction, Disposition, Transaction
from src.report import render_to_str

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
    return Classified(txn=_txn(amount), disposition=Disposition.EXCLUDED, reason=reason)


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
# Status labels — categories are uppercased; labels use ✓/↓/↑ prefix
# ---------------------------------------------------------------------------


def test_within_appears_in_output() -> None:
    out = render_to_str([_report("takeout", "45.20", "60.00", Status.WITHIN)], [])
    assert "WITHIN" in out
    assert "TAKEOUT" in out
    assert "$45.20" in out
    assert "$60.00" in out


def test_under_appears_in_output() -> None:
    out = render_to_str([_report("groceries", "12.00", "80.00", Status.UNDER)], [])
    assert "UNDER" in out
    assert "GROCERIES" in out
    assert "$12.00" in out
    assert "$80.00" in out


def test_over_appears_in_output() -> None:
    out = render_to_str([_report("gas", "210.50", "200.00", Status.OVER)], [])
    assert "OVER" in out
    assert "GAS" in out
    assert "$210.50" in out
    assert "$200.00" in out


# ---------------------------------------------------------------------------
# No-limit category: shows "-" in LIMIT/USED/STATUS columns, no status token
# ---------------------------------------------------------------------------


def test_no_limit_shows_dash() -> None:
    out = render_to_str([_report("pets", "40.00", None, None)], [])
    assert "PETS" in out
    assert "$40.00" in out
    assert "WITHIN" not in out
    assert "UNDER" not in out
    assert "OVER" not in out


# ---------------------------------------------------------------------------
# Alphabetical ordering (uppercase names)
# ---------------------------------------------------------------------------


def test_categories_sorted_alphabetically() -> None:
    reports = [
        _report("takeout", "45.00", "60.00", Status.WITHIN),
        _report("gas", "100.00", "200.00", Status.UNDER),
        _report("groceries", "80.00", "80.00", Status.WITHIN),
    ]
    out = render_to_str(reports, [])
    assert out.index("GAS") < out.index("GROCERIES") < out.index("TAKEOUT")


# ---------------------------------------------------------------------------
# Uncategorized warning: uses ⚠ prefix, deposits omitted when zero
# ---------------------------------------------------------------------------


def test_uncategorized_warning_printed() -> None:
    classified = [
        _uncategorized("50.00", Direction.WITHDRAWAL),
        _uncategorized("20.00", Direction.WITHDRAWAL),
        _uncategorized("5.00", Direction.DEPOSIT),
    ]
    out = render_to_str([], classified)
    assert "uncategorized" in out
    assert "3 uncategorized transaction(s)" in out
    assert "$70.00" in out  # withdrawals total
    assert "$5.00" in out  # deposits total


def test_uncategorized_warning_withdrawal_only() -> None:
    out = render_to_str([], [_uncategorized("87.40", Direction.WITHDRAWAL)])
    assert "uncategorized" in out
    assert "$87.40" in out
    # Deposits are omitted from the line when zero
    assert "deposits" not in out


def test_uncategorized_warning_deposit_only() -> None:
    out = render_to_str([], [_uncategorized("15.00", Direction.DEPOSIT)])
    assert "uncategorized" in out
    assert "$15.00" in out


# ---------------------------------------------------------------------------
# No uncategorized → no warning line at all
# ---------------------------------------------------------------------------


def test_zero_uncategorized_no_warning() -> None:
    classified = [
        _categorized("30.00", "takeout"),
        _excluded("100.00", "CIBC card payment"),
    ]
    out = render_to_str([], classified)
    assert "uncategorized" not in out.lower()


def test_empty_classified_no_warning() -> None:
    out = render_to_str([], [])
    assert "uncategorized" not in out.lower()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_reports_no_crash() -> None:
    render_to_str([], [])  # must not raise


def test_mixed_dispositions_only_uncategorized_warned() -> None:
    classified = [
        _categorized("30.00", "food"),
        _excluded("200.00", "card payment"),
        _uncategorized("42.00"),
    ]
    out = render_to_str([], classified)
    assert "1 uncategorized transaction(s)" in out


# ---------------------------------------------------------------------------
# Period / latest badge in title
# ---------------------------------------------------------------------------


def test_no_period_shows_plain_report_title() -> None:
    out = render_to_str([_report("gas", "50.00", "300.00", Status.WITHIN)], [])
    assert "Report" in out
    assert "·" not in out
    assert "(latest)" not in out


def test_period_appears_in_title() -> None:
    out = render_to_str([_report("gas", "50.00", "300.00", Status.WITHIN)], [], period="June 2026")
    assert "June 2026" in out
    assert "(latest)" not in out


def test_period_with_is_latest_shows_badge() -> None:
    out = render_to_str(
        [_report("gas", "50.00", "300.00", Status.WITHIN)],
        [],
        period="June 2026",
        is_latest=True,
    )
    assert "June 2026" in out
    assert "(latest)" in out


def test_is_latest_without_period_no_badge() -> None:
    out = render_to_str([_report("gas", "50.00", "300.00", Status.WITHIN)], [], is_latest=True)
    assert "(latest)" not in out
    assert "·" not in out


# ---------------------------------------------------------------------------
# Timing line
# ---------------------------------------------------------------------------


def test_timing_line_always_present() -> None:
    out = render_to_str([_report("gas", "50.00", "300.00", Status.WITHIN)], [])
    assert "Ran in " in out


def test_timing_line_after_uncategorized_warning() -> None:
    classified = [_uncategorized("30.00", Direction.WITHDRAWAL)]
    out = render_to_str([], classified)
    assert out.index("uncategorized") < out.index("Ran in ")


def test_timing_line_shows_elapsed_ms() -> None:
    out = render_to_str([], [], elapsed_ms=142.0)
    assert "Ran in 142ms." in out
