"""Core data model + the parser interface both banks implement.

This is the foundation: both reconciliation gates and the disposition split depend
on these types, so they are pinned down before anything else.

Money is `Decimal`, never `float`, everywhere. Parse amount strings straight into
`Decimal` — a float-rounding penny will trip a reconciliation gate that exists to
catch *real* errors, and you won't be able to tell the two apart.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum, auto


class Direction(Enum):
    """Which way money moved on the account."""

    WITHDRAWAL = auto()
    DEPOSIT = auto()


class Disposition(Enum):
    """How a parsed transaction is accounted for in the budget.

    EXCLUDED means *not spending* (money that moved or is counted elsewhere).
    UNCATEGORIZED means *spending we can't label* — never silently dropped.
    Keep the two distinct: they are different claims about the same dollars.
    """

    CATEGORIZED = auto()
    EXCLUDED = auto()
    UNCATEGORIZED = auto()


@dataclass
class Transaction:
    """One line item extracted from a statement.

    `amount` is always a positive magnitude; `direction` carries the sign meaning.
    """

    raw_description: str
    amount: Decimal
    direction: Direction
    # RBC dates are "sticky" (inherited on continuation rows). For audit/ordering only —
    # never used for budget-month attribution. May be None for banks that omit it.
    date: date | None = None
    # RBC running balance; feeds the balance gate. None when the layout has no balance column.
    balance: Decimal | None = None


@dataclass
class Classified:
    """A transaction plus the disposition the classification engine assigned it."""

    txn: Transaction
    disposition: Disposition
    category: str | None = None  # set iff CATEGORIZED
    reason: str | None = None  # set iff EXCLUDED (e.g. "CIBC card payment")


@dataclass
class Statement:
    """A fully parsed statement. The statement *is* the budget scope."""

    bank: str
    transactions: list[Transaction] = field(default_factory=list)
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None


class Parser(ABC):
    """Interface every bank parser implements.

    A parser turns the raw word geometry of one statement PDF into a `Statement`.
    It must not classify, aggregate, or attribute dates to months — that is all
    downstream, bank-agnostic work.
    """

    #: Human-readable bank label written onto the resulting `Statement.bank`.
    bank: str

    @abstractmethod
    def parse(self, pdf_path: str) -> Statement:
        """Extract every transaction from `pdf_path` into a `Statement`."""
        raise NotImplementedError
