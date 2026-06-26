"""Tests for the CIBC parser: pure column/row helpers + a golden-file oracle."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from src.parsers.base import Direction
from src.parsers.cibc import (
    CibcParser,
    _Columns,
    _section_columns,
    cluster_rows,
    parse_amount,
    parse_transaction_row,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "cibc-sample-statement.pdf"
COLUMNS = _Columns(description_left=110.0, category_left=325.4, amount_left=504.5)


def _w(text: str, x0: float, top: float, x1: float | None = None) -> dict:
    return {"text": text, "x0": x0, "x1": x1 if x1 is not None else x0 + 10, "top": top}


class TestParseAmount:
    def test_plain_and_dollar_amounts(self) -> None:
        assert parse_amount("30.52") == Decimal("30.52")
        assert parse_amount("$567.35") == Decimal("567.35")
        assert parse_amount("1,234.00") == Decimal("1234.00")

    def test_trailing_minus_is_a_credit(self) -> None:
        assert parse_amount("12.00-") == Decimal("-12.00")
        assert parse_amount("-12.00") == Decimal("-12.00")

    def test_non_money_is_none(self) -> None:
        assert parse_amount("BC") is None
        assert parse_amount("905-209-8911") is None  # phone, not money
        assert parse_amount("ON") is None


class TestClusterRows:
    def test_groups_by_top_within_tolerance(self) -> None:
        # 100.0 and 100.5 share a line; 108 is a new line (tol=2).
        words = [_w("b", 80, 100.5), _w("a", 40, 100.0), _w("c", 40, 108.0)]
        rows = cluster_rows(words, tol=2.0)
        assert [[w["text"] for w in r] for r in rows] == [["a", "b"], ["c"]]

    def test_each_row_sorted_left_to_right(self) -> None:
        rows = cluster_rows([_w("z", 300, 50), _w("a", 40, 50)])
        assert [w["text"] for w in rows[0]] == ["a", "z"]


class TestParseTransactionRow:
    def _amazon_row(self) -> list[dict]:
        return [
            _w("Apr", 36.7, 196),
            _w("26", 51.1, 196),
            _w("Apr", 78.7, 196),
            _w("27", 93.1, 196),
            _w("AMAZON*", 122.8, 196, 159),
            _w("VANCOUVER", 219.3, 196, 263),
            _w("BC", 272.1, 196, 281),
            _w("Personal", 341.5, 196, 369),
            _w("Expenses", 424.0, 196, 453),
            _w("30.52", 520.0, 196, 539),
        ]

    def test_extracts_merchant_amount_and_date(self) -> None:
        txn = parse_transaction_row(self._amazon_row(), COLUMNS, year=2026)
        assert txn is not None
        assert txn.amount == Decimal("30.52")
        assert txn.direction is Direction.WITHDRAWAL
        assert txn.raw_description == "AMAZON* VANCOUVER BC"  # no category, no dates
        assert txn.date is not None and txn.date.isoformat() == "2026-04-26"
        assert txn.bank_category == "Personal Expenses"

    def test_credit_row_is_a_deposit(self) -> None:
        row = self._amazon_row()[:-1] + [_w("12.00-", 520.0, 196, 539)]
        txn = parse_transaction_row(row, COLUMNS, year=2026)
        assert txn is not None
        assert txn.direction is Direction.DEPOSIT
        assert txn.amount == Decimal("12.00")

    def test_glyph_only_row_is_skipped(self) -> None:
        assert parse_transaction_row([_w("Ý", 109.0, 205)], COLUMNS, year=2026) is None

    def test_amount_outside_amount_column_is_not_a_transaction(self) -> None:
        # A money-looking token sitting in the description column must not count.
        row = [
            _w("May", 36.7, 50),
            _w("15", 51.1, 50),
            _w("CASHBACK", 122.8, 50, 180),
            _w("70.00", 200.0, 50, 220),
        ]
        assert parse_transaction_row(row, COLUMNS, year=2026) is None


class TestSectionColumns:
    def _header(self) -> list[dict]:
        return [
            _w("Trans", 36, 150),
            _w("date", 55, 150),
            _w("Post", 78, 150),
            _w("date", 95, 150),
            _w("Description", 118, 150),
            _w("Spend", 330, 150),
            _w("Categories", 365, 150),
            _w("Amount($)", 505, 150),
        ]

    def test_anchors_columns_on_the_header_tokens(self) -> None:
        cols = _section_columns([self._header()])
        assert cols.description_left == 118
        assert cols.category_left == 330
        assert cols.amount_left == 505

    def test_falls_back_when_no_header_row(self) -> None:
        cols = _section_columns([[_w("just", 10, 10), _w("words", 40, 10)]])
        assert cols.description_left == 110.0  # _DESC_LEFT_FALLBACK


@pytest.mark.skipif(not FIXTURE.exists(), reason="PII fixture not present (never committed)")
class TestGoldenFile:
    def test_charges_sum_to_the_hand_keyed_oracle(self) -> None:
        stmt = CibcParser().parse(str(FIXTURE))
        withdrawals = sum(
            (t.amount for t in stmt.transactions if t.direction is Direction.WITHDRAWAL),
            Decimal("0"),
        )
        assert len(stmt.transactions) == 9
        assert withdrawals == Decimal("567.35")  # hand-keyed from the statement

    def test_gate_one_ties_out(self) -> None:
        # parse() runs the Total-for tie-out internally; a clean parse means it held.
        stmt = CibcParser().parse(str(FIXTURE))
        assert stmt.bank == "CIBC"
        assert all(t.amount > 0 for t in stmt.transactions)

    def test_bank_category_populated(self) -> None:
        """CIBC transactions carry the bank's own category label."""
        stmt = CibcParser().parse(str(FIXTURE))
        categories = [t.bank_category for t in stmt.transactions if t.bank_category is not None]
        assert len(categories) > 0
