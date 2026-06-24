"""CIBC credit-card parser — block-delimited.

Transactions sit between a `Card number [snipped]` line and a `Total for [card]`
line; use those as block delimiters. The `Total for` line is the Gate-1 anchor
(charges − credits must tie out). Section title: "YOUR NEW CHARGES AND CREDITS."

A line looks like:
    Apr 26   Apr 27   AMAZON* … VANCOUVER BC   Personal and Household Expenses   30.52
i.e. transaction date, posting date, merchant/description, CIBC's category label, amount.

Prefer `pdfplumber` here too — one extraction philosophy, one validation path.
"""

from __future__ import annotations

from src.parsers.base import Parser, Statement


class CibcParser(Parser):
    bank = "CIBC"

    def parse(self, pdf_path: str) -> Statement:  # noqa: D102 — see Parser.parse
        raise NotImplementedError("CIBC parser — Phase 1")
