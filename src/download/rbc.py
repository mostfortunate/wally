"""RBC statement downloader."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Page

from .base import BankDownloader, StatementEntry

_TABLE_TIMEOUT_MS = 8_000


class RBCDownloader:
    bank = "RBC"
    statements_url = "https://www.rbcroyalbank.com/personal.html"

    def list_statements(self, page: Page) -> list[StatementEntry]:
        page.wait_for_selector("rbc-data-table table tbody tr", timeout=_TABLE_TIMEOUT_MS)
        rows = page.locator("rbc-data-table table tbody tr").all()
        entries: list[StatementEntry] = []
        for row in rows:
            link = row.locator(
                "td div.document-meta a[data-testid='desktop-document-download-link']"
            )
            if not link.count():
                continue
            aria_label = link.get_attribute("aria-label") or ""
            try:
                stmt_date = _parse_aria_date(aria_label)
            except ValueError:
                continue
            entries.append(
                StatementEntry(
                    filename=f"{stmt_date.year}-{stmt_date.month:02d}.pdf",
                    date=stmt_date,
                )
            )
        return entries

    def download(self, page: Page, entry: StatementEntry, dest_dir: Path) -> Path:
        selector = (
            "[data-testid='desktop-document-download-link']"
            f"[aria-label*='Download {entry.date.strftime('%B')} {entry.date.day}, {entry.date.year}']"
        )
        dest = dest_dir / entry.filename
        with page.expect_download() as dl:
            page.locator(selector).click()
        dl.value.save_as(str(dest))
        return dest


def _parse_aria_date(aria_label: str) -> date:
    m = re.search(r"Download (\w+ \d+, \d{4})", aria_label)
    if not m:
        raise ValueError(f"Cannot parse date from aria-label: {aria_label!r}")
    return datetime.strptime(m.group(1), "%B %d, %Y").date()


# Satisfy the BankDownloader protocol at type-check time.
_: BankDownloader = RBCDownloader()
