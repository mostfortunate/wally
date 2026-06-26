"""Locate the latest uploaded statement PDF for a given bank directory.

Files must be named YYYY-MM.pdf (e.g. 2026-05.pdf). Alphabetical sort == chronological
sort for ISO-formatted stems, so we take the last glob match.
"""

from __future__ import annotations

from pathlib import Path


def _is_valid_stem(p: Path) -> bool:
    """Return True iff the file stem matches YYYY-MM format."""
    return len(p.stem) == 7 and p.stem[4] == "-" and p.stem[:4].isdigit() and p.stem[5:].isdigit()


def find_latest(bank_dir: Path) -> Path | None:
    """Return the most recent YYYY-MM.pdf in bank_dir, or None if the dir is empty."""
    pdfs = sorted(bank_dir.glob("*.pdf"))
    # Filter to files whose stem looks like YYYY-MM (4 digits, dash, 2 digits).
    valid = [p for p in pdfs if _is_valid_stem(p)]
    return valid[-1] if valid else None


def find_all(directory: Path) -> list[Path]:
    """Return all YYYY-MM.pdf files in directory, sorted by name. Returns [] if absent."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.pdf") if _is_valid_stem(p))


__all__ = ["find_all", "find_latest"]
