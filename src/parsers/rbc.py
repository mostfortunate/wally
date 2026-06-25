"""RBC chequing/debit parser — coordinate-based.

Layout: columns `Date | Description | Withdrawals($) | Deposits($) | Balance($)`,
borderless. Withdrawal-vs-deposit is encoded as horizontal position, so we read word
geometry with `pdfplumber.extract_words()` and bucket amounts by column x-band — never
flatten to markdown, which is exactly the step that throws that signal away.

The fiddly, deterministic pieces (each a testable unit):
  - column-bucketing of money tokens by x1-coordinate (anchored on right-aligned headers);
  - sticky-date inheritance (continuation rows inherit the date above);
  - wrapped-description stitching (cluster tokens by shared `top` baseline);
  - orphaned type tokens (Contactless Interac purchase/refund, Online transfer received).

First/last rows carry OpeningBalance / closing balance — feed Gate 1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import pdfplumber

from src.parsers.base import Direction, Parser, Statement, Transaction

# ---------------------------------------------------------------------------
# Money + date regexes
# ---------------------------------------------------------------------------

# Matches a plain money token (no leading $ for transaction amounts; balance
# tokens may have a leading $).  No sign — direction comes from column position.
_MONEY_RE = re.compile(r"^\$?[\d,]+\.\d{2}$")

# RBC date tokens: day-then-month fused into one word, e.g. "4May", "12May", "2Jun".
_DATE_RE = re.compile(r"^(\d{1,2})([A-Z][a-z]{2,8})$")

_MONTHS: dict[str, int] = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

# Year appears in the "FromMay1,2026toJune2,2026" token on page 1.
_YEAR_RE = re.compile(r",(\d{4})")

# Tolerance (points) for grouping words onto the same visual row.
_ROW_TOL = 2.0

# How close (points) a money token's right edge must be to a column header's
# right edge to be considered "in" that column.
_COL_TOL = 40.0


# ---------------------------------------------------------------------------
# Column anchor dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Columns:
    """Right x1-edges of the Withdrawals, Deposits, and Balance columns.

    RBC right-aligns all three money columns; anchoring on x1 (not x0) is the
    stable signal for bucketing variable-width dollar amounts.
    """

    withdrawals_x1: float
    deposits_x1: float
    balance_x1: float
    # Left x0 of the Description column (used to detect "type rows").
    description_x0: float
    # Left x0 of the Date column (used to detect sticky-date tokens).
    date_x0: float
    # Vertical top of the header row — rows above this are page chrome.
    header_top: float


# ---------------------------------------------------------------------------
# Pure helper functions (each unit-tested)
# ---------------------------------------------------------------------------


def cluster_rows(words: list[dict], tol: float = _ROW_TOL) -> list[list[dict]]:
    """Group words into visual rows by shared `top` baseline; sort each row left->right."""
    rows: list[list[dict]] = []
    for word in sorted(words, key=lambda w: w["top"]):
        if rows and abs(word["top"] - rows[-1][0]["top"]) <= tol:
            rows[-1].append(word)
        else:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    return rows


def parse_money(text: str) -> Decimal | None:
    """Parse a bare money token (e.g. "3.94", "1,000.00") into a Decimal, or None."""
    if not _MONEY_RE.match(text):
        return None
    try:
        return Decimal(text.replace("$", "").replace(",", ""))
    except InvalidOperation:
        return None


def bucket_column(x1: float, cols: _Columns) -> Direction | None:
    """Map a money token's right edge to WITHDRAWAL, DEPOSIT, or None (balance column).

    Compares the token x1 against the three header x1-anchors and returns the
    direction for the nearest column — or None when the nearest column is Balance,
    or when no column is within _COL_TOL points.
    """
    candidates: list[tuple[float, Direction | None]] = [
        (abs(x1 - cols.withdrawals_x1), Direction.WITHDRAWAL),
        (abs(x1 - cols.deposits_x1), Direction.DEPOSIT),
        (abs(x1 - cols.balance_x1), None),  # balance column — not a transaction amount
    ]
    dist, direction = min(candidates, key=lambda c: c[0])
    return direction if dist <= _COL_TOL else None


def parse_date_token(text: str, year: int) -> date | None:
    """Parse an RBC date token like "4May" or "2Jun" into a `date`, or None."""
    m = _DATE_RE.match(text)
    if not m:
        return None
    month = _MONTHS.get(m.group(2))
    if month is None:
        return None
    try:
        return date(year, month, int(m.group(1)))
    except ValueError:
        return None


def inherit_date(row: list[dict], current_date: date | None, year: int) -> date | None:
    """Return this row's date: a fresh one from the row if present, else the inherited one.

    RBC dates are sticky — blank on continuation rows — so we carry the last-seen
    date forward.
    """
    for word in row:
        candidate = parse_date_token(word["text"], year)
        if candidate is not None:
            return candidate
    return current_date


def _is_date_token(text: str) -> bool:
    m = _DATE_RE.match(text)
    return m is not None and _MONTHS.get(m.group(2)) is not None


def extract_columns(rows: list[list[dict]]) -> _Columns | None:
    """Locate the column header row and return its x1-anchors.

    Returns None when no header row is found (e.g. pages with no transaction table).
    """
    for row in rows:
        texts = {w["text"] for w in row}
        if "Withdrawals($)" in texts and "Deposits($)" in texts:
            col = {w["text"]: w for w in row}
            return _Columns(
                withdrawals_x1=col["Withdrawals($)"]["x1"],
                deposits_x1=col["Deposits($)"]["x1"],
                balance_x1=col["Balance($)"]["x1"],
                description_x0=col.get("Description", col["Withdrawals($)"])["x0"],
                date_x0=col.get("Date", row[0])["x0"],
                header_top=row[0]["top"],
            )
    return None


def _statement_year(pdf) -> int:
    """Extract the statement year from the "FromMay1,2026toJune2,2026" header token."""
    for page in pdf.pages[:2]:
        for word in page.extract_words(use_text_flow=False):
            m = _YEAR_RE.search(word["text"])
            if m:
                return int(m.group(1))
    from datetime import date as _date

    return _date.today().year


def _is_in_table(word: dict, cols: _Columns) -> bool:
    """True when the word sits within the horizontal span of the transaction table."""
    return word["x0"] < cols.balance_x1 + 20


# ---------------------------------------------------------------------------
# Page-level transaction extraction
# ---------------------------------------------------------------------------


def _extract_page_transactions(
    rows: list[list[dict]],
    cols: _Columns,
    year: int,
    current_date: date | None,
    opening_balance: Decimal | None,
    closing_balance: Decimal | None,
) -> tuple[list[Transaction], date | None, Decimal | None, Decimal | None]:
    """Walk one page's rows and emit Transactions.

    Returns (transactions, last_seen_date, opening_balance, closing_balance).
    opening/closing are passed in so multi-page statements accumulate correctly.
    """
    transactions: list[Transaction] = []

    # pending_type accumulates the description text from a "type row" (row A)
    # that carries no amount.  When the next "detail row" (row B) supplies the
    # amount we stitch them together.
    pending_type: str | None = None
    pending_date: date | None = current_date

    for row in rows:
        # Skip rows above (or at) the header — they are page chrome / summary section.
        if row[0]["top"] <= cols.header_top + 2:
            continue

        # Filter out words beyond the right edge of the table (page-number sidebars).
        table_row = [w for w in row if _is_in_table(w, cols)]
        if not table_row:
            continue

        row_texts = {w["text"] for w in table_row}
        row_texts_lower = {t.lower() for t in row_texts}

        # --- OpeningBalance row ---
        if "openingbalance" in row_texts_lower:
            for w in table_row:
                val = parse_money(w["text"])
                if val is not None and opening_balance is None:
                    opening_balance = val
            pending_type = None
            continue

        # --- ClosingBalance row ---
        if "closingbalance" in row_texts_lower:
            for w in table_row:
                val = parse_money(w["text"])
                if val is not None:
                    closing_balance = val
            pending_type = None
            continue

        # --- Skip rows entirely left of the description column (page chrome) ---
        if max(w["x1"] for w in table_row) < cols.description_x0 - 10:
            continue

        # --- Sticky date: update pending_date if this row carries a fresh date token ---
        has_fresh_date = any(_is_date_token(w["text"]) for w in table_row)
        if has_fresh_date:
            pending_date = inherit_date(table_row, pending_date, year)

        # --- Identify transaction-column money tokens on this row ---
        txn_money: list[tuple[Decimal, Direction]] = []
        balance_val: Decimal | None = None

        for w in table_row:
            val = parse_money(w["text"])
            if val is None:
                continue
            direction = bucket_column(w["x1"], cols)
            if direction is None:
                balance_val = val
            else:
                txn_money.append((val, direction))

        if not txn_money:
            # No transaction amount on this row — it is a "type row" (row A).
            # Save its description tokens for stitching with the next row.
            desc_tokens = [
                w["text"]
                for w in table_row
                if not _is_date_token(w["text"])
                and not _MONEY_RE.match(w["text"])
                and w["x0"] >= cols.description_x0 - 5
            ]
            if desc_tokens:
                pending_type = " ".join(desc_tokens)
            continue

        # --- We have a transaction amount: build the full description ---
        desc_tokens_b = [
            w["text"]
            for w in table_row
            if not _is_date_token(w["text"])
            and not _MONEY_RE.match(w["text"])
            and w["x0"] >= cols.description_x0 - 5
        ]
        desc_b = " ".join(desc_tokens_b)

        if pending_type and desc_b:
            description = f"{pending_type} {desc_b}"
        elif pending_type:
            description = pending_type
        else:
            description = desc_b

        description = description.strip()
        if not description:
            pending_type = None
            continue

        for amount, direction in txn_money:
            transactions.append(
                Transaction(
                    raw_description=description,
                    amount=amount,
                    direction=direction,
                    date=pending_date,
                    balance=balance_val,
                )
            )

        pending_type = None

    return transactions, pending_date, opening_balance, closing_balance


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------


class RbcParser(Parser):
    bank = "RBC"

    def parse(self, pdf_path: str) -> Statement:  # noqa: D102
        transactions: list[Transaction] = []
        opening_balance: Decimal | None = None
        closing_balance: Decimal | None = None

        with pdfplumber.open(pdf_path) as pdf:
            year = _statement_year(pdf)
            current_date: date | None = None

            for page in pdf.pages:
                words = page.extract_words(use_text_flow=False)
                rows = cluster_rows(words)
                cols = extract_columns(rows)
                if cols is None:
                    continue

                page_txns, current_date, opening_balance, closing_balance = (
                    _extract_page_transactions(
                        rows, cols, year, current_date, opening_balance, closing_balance
                    )
                )
                transactions.extend(page_txns)

        return Statement(
            bank=self.bank,
            transactions=transactions,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
        )
