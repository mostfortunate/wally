"""Load an uploaded PDF, detect which bank produced it, and dispatch to its parser.

Detection is the only place bank identity is inferred; once a `Parser` is chosen the
rest of the pipeline is bank-agnostic.
"""

from __future__ import annotations

import pdfplumber

from src.parsers.base import Parser, Statement
from src.parsers.cibc import CibcParser
from src.parsers.rbc import RbcParser

# Fingerprints are anchored on section headers that appear on page 0 of each bank's PDF.
_CIBC_FINGERPRINT = "YOUR NEW CHARGES AND CREDITS"
_RBC_FINGERPRINT = "Withdrawals($)"


def detect_parser(pdf_path: str) -> Parser:
    """Inspect page 0 text and return the matching bank parser."""
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    if _CIBC_FINGERPRINT in text:
        return CibcParser()
    if _RBC_FINGERPRINT in text:
        return RbcParser()
    raise ValueError(f"Could not detect bank from {pdf_path!r}. Expected a CIBC or RBC statement.")


def ingest(pdf_path: str) -> Statement:
    """Detect the bank and parse the statement into a `Statement`."""
    return detect_parser(pdf_path).parse(pdf_path)


__all__ = ["CibcParser", "RbcParser", "detect_parser", "ingest"]
