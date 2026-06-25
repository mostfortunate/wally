"""Locate the latest uploaded statement PDF for a given bank directory.

Files must be named YYYY-MM.pdf (e.g. 2026-05.pdf). Alphabetical sort == chronological
sort for ISO-formatted stems, so we take the last glob match.
"""

from __future__ import annotations

from pathlib import Path


def find_latest(bank_dir: Path) -> Path | None:
    """Return the most recent YYYY-MM.pdf in bank_dir, or None if the dir is empty."""
    pdfs = sorted(bank_dir.glob("*.pdf"))
    # Filter to files whose stem looks like YYYY-MM (4 digits, dash, 2 digits).
    valid = [
        p
        for p in pdfs
        if len(p.stem) == 7 and p.stem[4] == "-" and p.stem[:4].isdigit() and p.stem[5:].isdigit()
    ]
    return valid[-1] if valid else None
