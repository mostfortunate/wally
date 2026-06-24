"""RBC chequing/debit parser — coordinate-based.

Layout: columns `Date | Description | Withdrawals($) | Deposits($) | Balance($)`,
borderless. Withdrawal-vs-deposit is encoded as horizontal position, so we read word
geometry with `pdfplumber.extract_words()` and bucket amounts by column x-band — never
flatten to markdown, which is exactly the step that throws that signal away.

The fiddly, deterministic pieces (each a testable unit):
  - column-bucketing of money tokens by x-coordinate (anchored on right-aligned headers);
  - sticky-date inheritance (continuation rows inherit the date above);
  - wrapped-description stitching (cluster tokens by shared `top` baseline);
  - orphaned type tokens (Contactless Interac purchase/refund, Online transfer received).

First/last rows carry OpeningBalance / closing balance — feed Gate 1.
"""

from __future__ import annotations

from src.parsers.base import Parser, Statement


class RbcParser(Parser):
    bank = "RBC"

    def parse(self, pdf_path: str) -> Statement:  # noqa: D102 — see Parser.parse
        raise NotImplementedError("RBC parser — Phase 2")
