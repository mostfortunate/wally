"""CIBC credit-card parser — block-delimited, coordinate-based.

Transactions live in the "YOUR NEW CHARGES AND CREDITS" section, between a
`Card number [snipped]` line and a `Total for [card]` line — those are the block
delimiters. The `Total for` line is the Gate-1 anchor: within each card block the
charges minus credits must tie out to it, or `parse` aborts with a diff.

We read word geometry with `pdfplumber.extract_words()` (never flattened text) and
bucket each row by column using the section header's x-anchors:

    Trans date | Post date | Description | Spend Categories | Amount($)

The amount is the right-aligned money token; the CIBC category label sits in its own
column to the left of it and is not part of the merchant description. Stray "Ý" cash-
back glyphs land on their own rows (no amount) and are skipped, as is the separate
"Your payments" section (it carries no `Card number` delimiter).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pdfplumber

from src.parsers.base import Direction, Parser, Statement, Transaction

# A money token: optional leading $, thousands separators, two decimals, optional
# trailing/leading minus for credits (e.g. "30.52", "$567.35", "12.00-").
_MONEY_RE = re.compile(r"^\$?-?[\d,]+\.\d{2}-?$")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Fallback column x-anchors (used only if the section header can't be located).
_CATEGORY_LEFT_FALLBACK = 325.0
_AMOUNT_LEFT_FALLBACK = 500.0
_ROW_TOL = 2.0  # rows whose `top` differ by <= this belong to the same line
_DESC_LEFT = 110.0  # description words start right of the two date columns


@dataclass(frozen=True)
class _Columns:
    """Left x-edges of the Spend-Categories and Amount columns for a page section."""

    category_left: float
    amount_left: float


def parse_amount(text: str) -> Decimal | None:
    """Parse a money token into a signed `Decimal`, or None if it isn't money.

    Charges are positive; a leading or trailing minus marks a credit (negative).
    """
    if not _MONEY_RE.match(text):
        return None
    negative = text.startswith("-") or text.endswith("-")
    cleaned = text.replace("$", "").replace(",", "").replace("-", "")
    value = Decimal(cleaned)
    return -value if negative else value


def cluster_rows(words: list[dict], tol: float = _ROW_TOL) -> list[list[dict]]:
    """Group words into rows by shared `top` baseline; sort each row left to right."""
    rows: list[list[dict]] = []
    for word in sorted(words, key=lambda w: w["top"]):
        if rows and abs(word["top"] - rows[-1][0]["top"]) <= tol:
            rows[-1].append(word)
        else:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    return rows


def _row_text(row: list[dict]) -> str:
    return " ".join(w["text"] for w in row)


def _leading_date(row: list[dict], year: int | None) -> date | None:
    """The transaction date — first month-abbrev + day pair at the row's left edge."""
    if len(row) < 2 or year is None:
        return None
    month = row[0]["text"].lower().rstrip(".")
    if month not in _MONTHS or not row[1]["text"].isdigit():
        return None
    return date(year, _MONTHS[month], int(row[1]["text"]))


def _starts_with_date(row: list[dict]) -> bool:
    return (
        len(row) >= 2
        and row[0]["text"].lower().rstrip(".") in _MONTHS
        and row[1]["text"].isdigit()
    )


def parse_transaction_row(
    row: list[dict], columns: _Columns, year: int | None
) -> Transaction | None:
    """Turn one clustered row into a Transaction, or None if it isn't one.

    A transaction row has a leading month+day date and a trailing money amount in the
    Amount column. Description = words left of the Spend-Categories column (after the
    date columns); the category label and dates are excluded.
    """
    if not _starts_with_date(row):
        return None
    last = row[-1]
    amount = parse_amount(last["text"])
    if amount is None or last["x0"] < columns.amount_left - 30:
        return None

    description = " ".join(
        w["text"]
        for w in row
        if _DESC_LEFT <= w["x0"] < columns.category_left and w is not last
    )
    if not description:
        return None

    direction = Direction.DEPOSIT if amount < 0 else Direction.WITHDRAWAL
    return Transaction(
        raw_description=description,
        amount=abs(amount),
        direction=direction,
        date=_leading_date(row, year),
    )


def _section_columns(rows: list[list[dict]]) -> _Columns:
    """Find the charges-section header to anchor the category and amount columns."""
    for row in rows:
        texts = {w["text"] for w in row}
        if "Amount($)" in texts and ("Spend" in texts or "Categories" in texts):
            amount_left = next(w["x0"] for w in row if w["text"] == "Amount($)")
            spend = [w for w in row if w["text"] in ("Spend", "Categories")]
            category_left = min(w["x0"] for w in spend)
            return _Columns(category_left=category_left, amount_left=amount_left)
    return _Columns(_CATEGORY_LEFT_FALLBACK, _AMOUNT_LEFT_FALLBACK)


def _statement_year(pdf: pdfplumber.PDF) -> int | None:
    """Pull the statement year from the first page (e.g. 'May 24, 2026')."""
    text = pdf.pages[0].extract_text() or ""
    match = re.search(r"[A-Z][a-z]{2,8}\s+\d{1,2},\s+(\d{4})", text)
    return int(match.group(1)) if match else None


def _verify_card_total(
    transactions: list[Transaction], total: Decimal, card: str
) -> None:
    """Gate 1 (CIBC): charges minus credits must equal the card's 'Total for' line."""
    zero = Decimal("0")
    charges = sum(
        (t.amount for t in transactions if t.direction is Direction.WITHDRAWAL), zero
    )
    credits = sum(
        (t.amount for t in transactions if t.direction is Direction.DEPOSIT), zero
    )
    net = charges - credits
    if net != total:
        raise AssertionError(
            f"CIBC Gate-1 failed for card {card}:\n"
            f"  charges   {charges}\n"
            f"  - credits {credits}\n"
            f"  = net     {net}\n"
            f"  Total for {total}\n"
            f"  drift     {total - net}"
        )


class CibcParser(Parser):
    bank = "CIBC"

    def parse(self, pdf_path: str) -> Statement:
        transactions: list[Transaction] = []
        with pdfplumber.open(pdf_path) as pdf:
            year = _statement_year(pdf)
            for page in pdf.pages:
                rows = cluster_rows(page.extract_words(use_text_flow=False))
                columns = _section_columns(rows)
                self._collect_page(rows, columns, year, transactions)
        return Statement(bank=self.bank, transactions=transactions)

    def _collect_page(
        self,
        rows: list[list[dict]],
        columns: _Columns,
        year: int | None,
        transactions: list[Transaction],
    ) -> None:
        """Walk a page, parsing each Card number → Total for block and tying it out."""
        card: str | None = None
        block: list[Transaction] = []
        for row in rows:
            text = _row_text(row)
            if text.startswith("Card number"):
                card = text.removeprefix("Card number").strip()
                block = []
            elif text.startswith("Total for") and card is not None:
                total = parse_amount(row[-1]["text"])
                if total is not None:
                    _verify_card_total(block, total, card)
                transactions.extend(block)
                card = None
            elif card is not None:
                txn = parse_transaction_row(row, columns, year)
                if txn is not None:
                    block.append(txn)
