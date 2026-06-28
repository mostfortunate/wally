"""Orchestration layer for wally download.

Launches a persistent Chrome context (reusing the user's existing session),
navigates to each bank's statements page, lists available statements, and
downloads any that are not already present on disk.
"""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from .base import BankDownloader

# Pause between downloads to match human pacing and avoid triggering bank anti-bot systems.
# The download itself takes 1–3 s (network + file write); this is the additional wait after
# each one completes. 2 s puts the total rhythm at ~3–5 s per statement — clearly human.
_INTER_DOWNLOAD_DELAY_S = 2.0

_DEFAULT_PROFILE = Path.home() / ".local" / "share" / "wally" / "browser-profile"


def run_download(
    downloaders: list[BankDownloader],
    statements_dir: Path,
    *,
    chrome_profile: Path | None = None,
    month: str | None = None,
) -> int:
    """Run all downloaders and return a process exit code."""
    profile = chrome_profile or _DEFAULT_PROFILE
    profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            accept_downloads=True,
        )
        page = ctx.new_page()

        for downloader in downloaders:
            dest_dir = statements_dir / downloader.bank.lower()
            dest_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n[{downloader.bank}] Opening browser...")
            page.goto(downloader.statements_url)
            input(
                f"  [{downloader.bank}] Sign in, navigate to your statements page, "
                "and select the right account — then press Enter..."
            )
            skipped = downloaded = 0
            for batch in downloader.statements_by_year(page):
                if month:
                    batch = [e for e in batch if e.filename.startswith(month)]
                for entry in batch:
                    dest = dest_dir / entry.filename
                    if dest.exists():
                        print(f"  skip  {entry.filename}")
                        skipped += 1
                        continue
                    print(f"  down  {entry.filename} ...", end="", flush=True)
                    downloader.download(page, entry, dest_dir)
                    print(" done")
                    downloaded += 1
                    time.sleep(_INTER_DOWNLOAD_DELAY_S)

            print(f"[{downloader.bank}] {downloaded} downloaded, {skipped} already present.")

        input("\nAll done. Press Enter to close the browser...")
        ctx.close()

    return 0
