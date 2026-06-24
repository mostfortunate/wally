"""Tests for the RBC parser: pure helper unit tests + a golden-file oracle."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.parsers.base import Direction
from src.parsers.rbc import (
    RbcParser,
    _Columns,
    _is_date_token,
    bucket_column,
    cluster_rows,
    extract_columns,
    inherit_date,
    parse_date_token,
    parse_money,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "rbc-sample-statement.pdf"


def _w(text: str, x0: float, top: float, x1: float | None = None) -> dict:
    return {"text": text, "x0": x0, "x1": x1 if x1 is not None else x0 + 10, "top": top}


# ---------------------------------------------------------------------------
# Helper: a representative set of column anchors (matches the odd-page layout)
# ---------------------------------------------------------------------------

_COLS = _Columns(
    withdrawals_x1=373.0,
    deposits_x1=464.9,
    balance_x1=593.1,
    description_x0=90.0,
    date_x0=44.9,
    header_top=445.7,
)


# ---------------------------------------------------------------------------
# TestParseMoneyRbc
# ---------------------------------------------------------------------------


class TestParseMoneyRbc:
    def test_plain_amount(self) -> None:
        assert parse_money("3.94") == Decimal("3.94")

    def test_thousands_separator(self) -> None:
        assert parse_money("1,000.00") == Decimal("1000.00")

    def test_leading_dollar_sign(self) -> None:
        assert parse_money("$16,467.03") == Decimal("16467.03")

    def test_non_money_returns_none(self) -> None:
        assert parse_money("DOLLARAMA#1201") is None
        assert parse_money("4May") is None
        assert parse_money("16,467.03-") is None  # trailing minus not a valid RBC token


# ---------------------------------------------------------------------------
# TestClusterRowsRbc
# ---------------------------------------------------------------------------


class TestClusterRowsRbc:
    def test_groups_words_within_tolerance(self) -> None:
        words = [_w("b", 80, 100.5), _w("a", 40, 100.0), _w("c", 40, 108.0)]
        rows = cluster_rows(words, tol=2.0)
        assert [[w["text"] for w in r] for r in rows] == [["a", "b"], ["c"]]

    def test_each_row_sorted_left_to_right(self) -> None:
        rows = cluster_rows([_w("z", 300, 50), _w("a", 40, 50)])
        assert [w["text"] for w in rows[0]] == ["a", "z"]

    def test_single_word(self) -> None:
        rows = cluster_rows([_w("x", 10, 10)])
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# TestBucketColumn — the critical deterministic piece
# ---------------------------------------------------------------------------


class TestBucketColumn:
    """Column x-band bucketing: amounts land in the right column by right-edge proximity."""

    def test_withdrawal_amount_right_edge_near_withdrawals_x1(self) -> None:
        # x1=373.6 is within 40 pts of withdrawals_x1=373.0 → WITHDRAWAL
        assert bucket_column(373.6, _COLS) is Direction.WITHDRAWAL

    def test_deposit_amount_right_edge_near_deposits_x1(self) -> None:
        # x1=465.5 is within 40 pts of deposits_x1=464.9 → DEPOSIT
        assert bucket_column(465.5, _COLS) is Direction.DEPOSIT

    def test_balance_amount_right_edge_near_balance_x1(self) -> None:
        # x1=593.8 is near balance_x1=593.1 → None (balance column)
        assert bucket_column(593.8, _COLS) is None

    def test_ambiguous_x1_picks_closest_column(self) -> None:
        # x1=393 is 20 pts from withdrawals_x1=373 and 71 pts from deposits_x1=464.9
        # → within the 40-pt tolerance for Withdrawals, not Deposits → WITHDRAWAL
        assert bucket_column(393.0, _COLS) is Direction.WITHDRAWAL

    def test_far_outside_all_columns_returns_none(self) -> None:
        # x1=10 is more than 40 pts from any column
        assert bucket_column(10.0, _COLS) is None

    def test_small_withdrawal_right_aligned_within_band(self) -> None:
        # Real observed x1 from fixture: 3.94 sits at x1=373.6 (within 1 pt of header)
        assert bucket_column(373.6, _COLS) is Direction.WITHDRAWAL

    def test_deposit_from_second_page_layout(self) -> None:
        # Page 2 has different column anchors (smaller x values)
        cols2 = _Columns(
            withdrawals_x1=344.9,
            deposits_x1=437.1,
            balance_x1=565.0,
            description_x0=61.9,
            date_x0=16.8,
            header_top=149.0,
        )
        # x1=437.7 → DEPOSIT on page 2
        assert bucket_column(437.7, cols2) is Direction.DEPOSIT
        # x1=345.5 → WITHDRAWAL on page 2
        assert bucket_column(345.5, cols2) is Direction.WITHDRAWAL


# ---------------------------------------------------------------------------
# TestParseDateToken
# ---------------------------------------------------------------------------


class TestParseDateToken:
    def test_single_digit_day(self) -> None:
        assert parse_date_token("4May", 2026) == date(2026, 5, 4)

    def test_double_digit_day(self) -> None:
        assert parse_date_token("12May", 2026) == date(2026, 5, 12)

    def test_june(self) -> None:
        assert parse_date_token("2Jun", 2026) == date(2026, 6, 2)

    def test_non_date_returns_none(self) -> None:
        assert parse_date_token("DOLLARAMA", 2026) is None
        assert parse_date_token("3.94", 2026) is None

    def test_is_date_token_helper(self) -> None:
        assert _is_date_token("4May") is True
        assert _is_date_token("2Jun") is True
        assert _is_date_token("TIMHORTONS#65") is False
        assert _is_date_token("3.94") is False


# ---------------------------------------------------------------------------
# TestInheritDate — sticky-date inheritance
# ---------------------------------------------------------------------------


class TestInheritDate:
    """A row with no date token inherits the date from the previous row."""

    def test_row_with_date_token_returns_that_date(self) -> None:
        row = [_w("4May", 44.9, 472.9), _w("Onlinetransfer", 90, 472.9)]
        result = inherit_date(row, None, 2026)
        assert result == date(2026, 5, 4)

    def test_row_without_date_inherits_current(self) -> None:
        row = [_w("DOLLARAMA#1201", 97.9, 530.8), _w("3.94", 355.9, 530.8)]
        inherited = date(2026, 5, 4)
        result = inherit_date(row, inherited, 2026)
        assert result == inherited

    def test_none_stays_none_when_no_date(self) -> None:
        row = [_w("DOLLARAMA#1201", 97.9, 530.8)]
        result = inherit_date(row, None, 2026)
        assert result is None

    def test_new_date_overrides_inherited(self) -> None:
        row = [_w("5May", 44.9, 616.9), _w("OnlineBanking", 90, 616.9)]
        result = inherit_date(row, date(2026, 5, 4), 2026)
        assert result == date(2026, 5, 5)


# ---------------------------------------------------------------------------
# TestExtractColumns
# ---------------------------------------------------------------------------


class TestExtractColumns:
    def _header(self, x_offset: float = 0.0) -> list[dict]:
        return [
            _w("Date", 44.9 + x_offset, 445.7),
            _w("Description", 90.0 + x_offset, 445.7),
            _w("Withdrawals($)", 318.7 + x_offset, 445.7, x1=373.0 + x_offset),
            _w("Deposits($)", 423.6 + x_offset, 445.7, x1=464.9 + x_offset),
            _w("Balance($)", 554.4 + x_offset, 445.7, x1=593.1 + x_offset),
        ]

    def test_extracts_x1_anchors_from_header(self) -> None:
        cols = extract_columns([self._header()])
        assert cols is not None
        assert cols.withdrawals_x1 == pytest.approx(373.0)
        assert cols.deposits_x1 == pytest.approx(464.9)
        assert cols.balance_x1 == pytest.approx(593.1)
        assert cols.description_x0 == pytest.approx(90.0)
        assert cols.header_top == pytest.approx(445.7)

    def test_returns_none_when_no_header(self) -> None:
        rows = [[_w("just", 10, 10), _w("words", 40, 10)]]
        assert extract_columns(rows) is None

    def test_skips_non_header_rows(self) -> None:
        non_header = [_w("some", 10, 10), _w("words", 40, 10)]
        cols = extract_columns([non_header, self._header()])
        assert cols is not None
        assert cols.withdrawals_x1 == pytest.approx(373.0)


# ---------------------------------------------------------------------------
# Golden-file oracle
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not FIXTURE.exists(), reason="PII fixture not present (never committed)")
class TestGoldenFile:
    """End-to-end parse of the real fixture PDF.

    Oracle numbers hand-verified against the statement's own summary section
    (YouropeningbalanceonMay1,2026 / TotalDeposits / TotalWithdrawals / Closing).
    """

    def test_statement_metadata(self) -> None:
        stmt = RbcParser().parse(str(FIXTURE))
        assert stmt.bank == "RBC"
        assert stmt.opening_balance == Decimal("16467.03")
        assert stmt.closing_balance == Decimal("28139.86")

    def test_transaction_count(self) -> None:
        stmt = RbcParser().parse(str(FIXTURE))
        assert len(stmt.transactions) == 74

    def test_withdrawal_total(self) -> None:
        stmt = RbcParser().parse(str(FIXTURE))
        total = sum(t.amount for t in stmt.transactions if t.direction is Direction.WITHDRAWAL)
        assert total == Decimal("3644.66")

    def test_deposit_total(self) -> None:
        stmt = RbcParser().parse(str(FIXTURE))
        total = sum(t.amount for t in stmt.transactions if t.direction is Direction.DEPOSIT)
        assert total == Decimal("15317.49")

    def test_gate_one_balance_identity(self) -> None:
        """opening + deposits - withdrawals == closing (Gate 1)."""
        stmt = RbcParser().parse(str(FIXTURE))
        deposits = sum(t.amount for t in stmt.transactions if t.direction is Direction.DEPOSIT)
        withdrawals = sum(
            t.amount for t in stmt.transactions if t.direction is Direction.WITHDRAWAL
        )
        assert stmt.opening_balance is not None
        assert stmt.closing_balance is not None
        assert stmt.opening_balance + deposits - withdrawals == stmt.closing_balance

    def test_all_amounts_positive(self) -> None:
        stmt = RbcParser().parse(str(FIXTURE))
        assert all(t.amount > 0 for t in stmt.transactions)

    def test_dates_are_set_on_all_transactions(self) -> None:
        stmt = RbcParser().parse(str(FIXTURE))
        assert all(t.date is not None for t in stmt.transactions)

    def test_date_range(self) -> None:
        """All transaction dates fall within the statement period (May–Jun 2026)."""
        import datetime

        stmt = RbcParser().parse(str(FIXTURE))
        dates = [t.date for t in stmt.transactions if t.date is not None]
        assert min(dates) >= datetime.date(2026, 5, 1)
        assert max(dates) <= datetime.date(2026, 6, 2)
