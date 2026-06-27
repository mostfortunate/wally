"""Shared contract for bank statement downloaders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from playwright.sync_api import Page


@dataclass(frozen=True)
class StatementEntry:
    filename: str  # "2026-01.pdf" — used for dedup against existing files on disk
    date: date  # parsed date, for display


class BankDownloader(Protocol):
    """One implementation per bank.  All DOM-specific logic lives in the subclass."""

    bank: str  # display name, e.g. "CIBC" or "RBC"
    statements_url: str  # URL to navigate to for the statements list page

    def is_authenticated(self, page: Page) -> bool:
        """Return True if the current page confirms an active session."""
        ...

    def list_statements(self, page: Page) -> list[StatementEntry]:
        """Return every available statement on the current page, newest first."""
        ...

    def download(self, page: Page, entry: StatementEntry, dest_dir: Path) -> Path:
        """Trigger the download for *entry* and save it to dest_dir/entry.filename.

        Returns the path to the saved file.
        """
        ...
