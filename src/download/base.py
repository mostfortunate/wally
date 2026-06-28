"""Shared contract for bank statement downloaders."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from playwright.sync_api import Page


@dataclass(frozen=True)
class StatementEntry:
    filename: str  # "2026-01.pdf" — used for dedup against existing files on disk
    date: date  # parsed date, for display
    aria_label: str = ""  # raw aria-label from the DOM; used to re-locate the link in download()


class BankDownloader(Protocol):
    """One implementation per bank.  All DOM-specific logic lives in the subclass."""

    bank: str  # display name, e.g. "CIBC" or "RBC"
    statements_url: str  # URL to navigate to for the statements list page

    def statements_by_year(self, page: Page) -> Generator[list[StatementEntry]]:
        """Yield one batch of entries per year.

        The runner downloads each batch before advancing to the next year, so
        the DOM is always in the correct state when download() is called.
        """
        ...

    def download(self, page: Page, entry: StatementEntry, dest_dir: Path) -> Path:
        """Trigger the download for *entry* and save it to dest_dir/entry.filename.

        Returns the path to the saved file.
        """
        ...
