"""CIBC statement downloader."""

from __future__ import annotations

import re
from collections.abc import Generator
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .base import BankDownloader, StatementEntry

_PANE_SELECTOR = "ui-collapsible-pane"
_TITLE_SELECTOR = ".ui-dynamic-header .ui-title"
_BUTTON_SELECTOR = "ui-button[role='button'][aria-label*='Download this PDF']"
_EXPAND_TIMEOUT_MS = 8_000


class CIBCDownloader:
    bank = "CIBC"
    statements_url = "https://www.cibc.com/en/personal-banking/online-banking.html"

    def statements_by_year(self, page: Page) -> Generator[list[StatementEntry]]:
        for pane in page.locator(_PANE_SELECTOR).all():
            title = pane.locator(_TITLE_SELECTOR)
            if title.get_attribute("aria-expanded") == "false":
                title.click()
                try:
                    # Wait for the actual buttons to be visible — unambiguous and
                    # avoids [aria-hidden='false'] matching unrelated elements early.
                    pane.locator(_BUTTON_SELECTOR).first.wait_for(
                        state="visible", timeout=_EXPAND_TIMEOUT_MS
                    )
                except PlaywrightTimeoutError:
                    continue
            entries = _scrape_pane(pane)
            if entries:
                yield entries

    def download(self, page: Page, entry: StatementEntry, dest_dir: Path) -> Path:
        dest = dest_dir / entry.filename
        with page.expect_download() as dl:
            page.get_by_role("button", name=entry.aria_label, exact=True).click()
        dl.value.save_as(str(dest))
        return dest


def _scrape_pane(pane: Locator) -> list[StatementEntry]:
    entries: list[StatementEntry] = []
    for btn in pane.locator(_BUTTON_SELECTOR).all():
        aria_label = btn.get_attribute("aria-label") or ""
        try:
            stmt_date = _parse_start_date(aria_label)
        except ValueError:
            print(f"  warn  cibc: could not parse date from aria-label: {aria_label!r}")
            continue
        entries.append(
            StatementEntry(
                filename=f"{stmt_date.year}-{stmt_date.month:02d}.pdf",
                date=stmt_date,
                aria_label=aria_label,
            )
        )
    return entries


def _parse_start_date(aria_label: str) -> date:
    # "December 25 to January 26, 2026. Download this PDF."
    # Year appears only with the end date; infer start year from month ordering.
    m = re.search(r"(\w+) (\d+) to (\w+) \d+, (\d{4})\.", aria_label)
    if not m:
        raise ValueError(f"Cannot parse date from aria-label: {aria_label!r}")
    start_month = datetime.strptime(m.group(1), "%B").month
    start_day = int(m.group(2))
    end_month = datetime.strptime(m.group(3), "%B").month
    end_year = int(m.group(4))
    start_year = end_year - 1 if start_month > end_month else end_year
    return date(start_year, start_month, start_day)


# Satisfy the BankDownloader protocol at type-check time.
_: BankDownloader = CIBCDownloader()
