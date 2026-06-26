"""RBC statement downloader.

DOM-specific implementation is not yet filled in — requires inspection of
the RBC online banking statements page (Angular SPA) to identify selectors
and download triggers.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from .base import BankDownloader, StatementEntry


class RBCDownloader:
    bank = "RBC"
    statements_url = "https://www.rbcroyalbank.com/ways-to-bank/online-banking/index.html"

    def is_authenticated(self, page: Page) -> bool:
        raise NotImplementedError("RBC: fill in the authenticated-page selector")

    def list_statements(self, page: Page) -> list[StatementEntry]:
        raise NotImplementedError("RBC: fill in statement list scraping")

    def download(self, page: Page, entry: StatementEntry, dest_dir: Path) -> Path:
        raise NotImplementedError("RBC: fill in download trigger and file save")


# Satisfy the BankDownloader protocol at type-check time.
_: BankDownloader = RBCDownloader()
