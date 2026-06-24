"""The two reconciliation gates, run as runtime invariants on every parse.

These are not just tests: a failed gate **aborts the run with a diff** and produces
no report. It never silently emits a wrong budget.

Gate 1 — Balance gate: did we parse *every* transaction?
    opening_balance + Σ(deposits) − Σ(withdrawals) == closing_balance
A missed or mis-signed amount breaks this identity. (CIBC's analogous anchor is the
per-card "Total for [card]" line; that variant lands with the CIBC parser.)

Gate 2 — Partition gate: did we *account for* every parsed transaction?
    Σ(categorized) + Σ(excluded) + Σ(uncategorized) == Σ(all transactions)
Every classified transaction lands in exactly one disposition, and they sum back to
the whole. Gate 1 proves nothing fell out of parsing; Gate 2 proves nothing fell out
of budgeting. Together: nothing leaks.
"""

from __future__ import annotations

from decimal import Decimal

from src.parsers.base import Classified, Direction, Disposition, Statement, Transaction

ZERO = Decimal("0")


class ReconciliationError(AssertionError):
    """Raised when a gate fails. Carries a human-readable diff; aborts the run."""


def check_balance(statement: Statement) -> None:
    """Gate 1. Verify the running-balance identity ties out to the penny.

    Requires both opening and closing balances. Raises `ValueError` if they are
    absent (the statement has no balance anchor to verify against) and
    `ReconciliationError` if the identity does not hold.
    """
    if statement.opening_balance is None or statement.closing_balance is None:
        raise ValueError(
            f"{statement.bank}: balance gate needs opening and closing balances; "
            f"got opening={statement.opening_balance!r} closing={statement.closing_balance!r}"
        )

    deposits = sum(
        (t.amount for t in statement.transactions if t.direction is Direction.DEPOSIT),
        ZERO,
    )
    withdrawals = sum(
        (t.amount for t in statement.transactions if t.direction is Direction.WITHDRAWAL),
        ZERO,
    )
    expected_closing = statement.opening_balance + deposits - withdrawals

    if expected_closing != statement.closing_balance:
        drift = statement.closing_balance - expected_closing
        raise ReconciliationError(
            f"{statement.bank} balance gate failed:\n"
            f"  opening      {statement.opening_balance}\n"
            f"  + deposits   {deposits}\n"
            f"  - withdrawals {withdrawals}\n"
            f"  = expected   {expected_closing}\n"
            f"  statement    {statement.closing_balance}\n"
            f"  drift        {drift}"
        )


def check_partition(transactions: list[Transaction], classified: list[Classified]) -> None:
    """Gate 2. Verify the classified set accounts for exactly the parsed transactions.

    Every parsed transaction must appear in exactly one disposition, and the
    per-disposition sums must add back to the total over `transactions`.
    """
    total = sum((t.amount for t in transactions), ZERO)
    by_disposition: dict[Disposition, Decimal] = {d: ZERO for d in Disposition}
    for c in classified:
        by_disposition[c.disposition] += c.txn.amount
    accounted = sum(by_disposition.values(), ZERO)

    if accounted != total or len(classified) != len(transactions):
        raise ReconciliationError(
            "partition gate failed:\n"
            f"  parsed transactions   {len(transactions)} totalling {total}\n"
            f"  classified            {len(classified)} totalling {accounted}\n"
            f"  categorized           {by_disposition[Disposition.CATEGORIZED]}\n"
            f"  excluded              {by_disposition[Disposition.EXCLUDED]}\n"
            f"  uncategorized         {by_disposition[Disposition.UNCATEGORIZED]}\n"
            f"  leak                  {total - accounted}"
        )


__all__ = ["ReconciliationError", "check_balance", "check_partition"]
