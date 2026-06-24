"""Unit tests for the two reconciliation gates."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.parsers.base import Classified, Direction, Disposition, Statement, Transaction
from src.reconciliation import ReconciliationError, check_balance, check_partition


def _txn(amount: str, direction: Direction) -> Transaction:
    return Transaction(raw_description="x", amount=Decimal(amount), direction=direction)


def _balanced_statement() -> Statement:
    # 100 opening + 50 deposit - 30 withdrawal = 120 closing.
    return Statement(
        bank="RBC",
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("120.00"),
        transactions=[
            _txn("50.00", Direction.DEPOSIT),
            _txn("30.00", Direction.WITHDRAWAL),
        ],
    )


class TestBalanceGate:
    def test_passes_when_identity_holds(self) -> None:
        check_balance(_balanced_statement())  # no raise

    def test_fails_on_mis_signed_withdrawal(self) -> None:
        stmt = _balanced_statement()
        # Flip the withdrawal to a deposit — closing no longer ties out.
        stmt.transactions[1].direction = Direction.DEPOSIT
        with pytest.raises(ReconciliationError, match="balance gate failed"):
            check_balance(stmt)

    def test_fails_on_dropped_transaction(self) -> None:
        stmt = _balanced_statement()
        stmt.transactions.pop()  # drop the withdrawal
        with pytest.raises(ReconciliationError):
            check_balance(stmt)

    def test_requires_balances(self) -> None:
        stmt = _balanced_statement()
        stmt.closing_balance = None
        with pytest.raises(ValueError):
            check_balance(stmt)


class TestPartitionGate:
    def test_passes_when_every_txn_accounted_once(self) -> None:
        txns = [_txn("30.00", Direction.WITHDRAWAL), _txn("12.00", Direction.WITHDRAWAL)]
        classified = [
            Classified(txns[0], Disposition.CATEGORIZED, category="gas"),
            Classified(txns[1], Disposition.UNCATEGORIZED),
        ]
        check_partition(txns, classified)  # no raise

    def test_fails_when_a_txn_is_dropped(self) -> None:
        txns = [_txn("30.00", Direction.WITHDRAWAL), _txn("12.00", Direction.WITHDRAWAL)]
        classified = [Classified(txns[0], Disposition.CATEGORIZED, category="gas")]
        with pytest.raises(ReconciliationError, match="partition gate failed"):
            check_partition(txns, classified)
