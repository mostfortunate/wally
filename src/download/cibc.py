"""CIBC statement downloader.

DOM-specific implementation is not yet filled in — requires inspection of
the CIBC online banking statements page to identify selectors and download triggers.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from .base import BankDownloader, StatementEntry


class CIBCDownloader:
    bank = "CIBC"
    statements_url = "https://www.cibc.com/en/personal-banking/online-banking.html"

    def list_statements(self, page: Page) -> list[StatementEntry]:
        raise NotImplementedError("CIBC: fill in statement list scraping")

    def download(self, page: Page, entry: StatementEntry, dest_dir: Path) -> Path:
        raise NotImplementedError("CIBC: fill in download trigger and file save")


# Satisfy the BankDownloader protocol at type-check time.
_: BankDownloader = CIBCDownloader()
