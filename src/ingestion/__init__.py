"""Load an uploaded PDF, detect which bank produced it, and dispatch to its parser.

Detection is the only place bank identity is inferred; once a `Parser` is chosen the
rest of the pipeline is bank-agnostic.
"""

from __future__ import annotations

from src.parsers.base import Parser, Statement
from src.parsers.cibc import CibcParser
from src.parsers.rbc import RbcParser


def detect_parser(pdf_path: str) -> Parser:
    """Inspect the PDF and return the matching bank parser.

    Phase 0 stub: real detection keys off a bank fingerprint in the document text
    (e.g. RBC's column header row vs. CIBC's "YOUR NEW CHARGES AND CREDITS" section).
    """
    raise NotImplementedError("bank detection — Phase 1")


def ingest(pdf_path: str) -> Statement:
    """Detect the bank and parse the statement into a `Statement`."""
    return detect_parser(pdf_path).parse(pdf_path)


__all__ = ["CibcParser", "RbcParser", "detect_parser", "ingest"]
