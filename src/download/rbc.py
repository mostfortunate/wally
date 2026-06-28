"""RBC statement downloader."""

from __future__ import annotations

import re
from collections.abc import Generator
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .base import BankDownloader, StatementEntry

_TABLE_TIMEOUT_MS = 8_000
_SHOW_DOCS_SELECTOR = "[data-testid='button-show-docs']"

# Month picker is the only rbc-select-input with an "All months" option (value="00").
# Year picker is targeted by its aria label — using option-value matching is ambiguous because
# the document-type picker (rbc-select-1) also has single-digit option values.
_MONTH_SELECT = "select.rbc-select-input:has(option[value='00'])"


class RBCDownloader:
    bank = "RBC"
    statements_url = "https://www.rbcroyalbank.com/personal.html"

    def statements_by_year(self, page: Page) -> Generator[list[StatementEntry]]:
        """Yield one batch of entries per year, newest first.

        Keeps the table in the correct state for download() — the runner must
        download each yielded batch before advancing to the next year.
        """
        year_select = page.get_by_label("Year")
        page.locator(_MONTH_SELECT).select_option(value="00")

        year_values = [
            v
            for el in year_select.locator("option:not([disabled])").all()
            if (v := el.get_attribute("value")) is not None
        ]

        for year_value in year_values:
            year_select.select_option(value=year_value)
            page.locator(_SHOW_DOCS_SELECTOR).click()
            try:
                page.wait_for_load_state("networkidle", timeout=_TABLE_TIMEOUT_MS)
                page.wait_for_selector("rbc-data-table table tbody tr", timeout=_TABLE_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                continue
            yield _scrape_rows(page)

    def list_statements(self, page: Page) -> list[StatementEntry]:
        return [entry for batch in self.statements_by_year(page) for entry in batch]

    def download(self, page: Page, entry: StatementEntry, dest_dir: Path) -> Path:
        selector = (
            f"[data-testid='desktop-document-download-link'][aria-label='{entry.aria_label}']"
        )
        dest = dest_dir / entry.filename
        with page.expect_download() as dl:
            page.locator(selector).click()
        dl.value.save_as(str(dest))
        return dest


def _scrape_rows(page: Page) -> list[StatementEntry]:
    entries: list[StatementEntry] = []
    for row in page.locator("rbc-data-table table tbody tr").all():
        link = row.locator("td div.document-meta a[data-testid='desktop-document-download-link']")
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
                aria_label=aria_label,
            )
        )
    return entries


def _parse_aria_date(aria_label: str) -> date:
    m = re.search(r"Download (\w+\.? \d+, \d{4})", aria_label)
    if not m:
        raise ValueError(f"Cannot parse date from aria-label: {aria_label!r}")
    date_str = m.group(1).replace(".", "")  # "Feb. 2, 2026" → "Feb 2, 2026"
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date from aria-label: {aria_label!r}")


# Satisfy the BankDownloader protocol at type-check time.
_: BankDownloader = RBCDownloader()
