"""Orchestration layer for wally download.

Launches a persistent Chrome context (reusing the user's existing session),
navigates to each bank's statements page, lists available statements, and
downloads any that are not already present on disk.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from .base import BankDownloader

# Pause between downloads to match human pacing and avoid triggering bank anti-bot systems.
# The download itself takes 1–3 s (network + file write); this is the additional wait after
# each one completes. 2 s puts the total rhythm at ~3–5 s per statement — clearly human.
_INTER_DOWNLOAD_DELAY_S = 2.0

_CHROME_PROFILE_MACOS = (
    Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "Default"
)


def _prompt_login(bank: str) -> None:
    try:
        input(
            f"\n  [{bank}] Session expired — complete login in the browser window, "
            "then press Enter to continue..."
        )
    except KeyboardInterrupt:
        raise


def run_download(
    downloaders: list[BankDownloader],
    statements_dir: Path,
    *,
    chrome_profile: Path | None = None,
) -> int:
    """Run all downloaders and return a process exit code."""
    profile = chrome_profile or _CHROME_PROFILE_MACOS
    if not profile.exists():
        print(
            f"Chrome profile not found at {profile}\n"
            "Is Google Chrome installed? Run Chrome at least once to create a profile.",
            file=sys.stderr,
        )
        return 1

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

            print(f"\n[{downloader.bank}] Navigating to statements page...")
            page.goto(downloader.statements_url)

            if not downloader.is_authenticated(page):
                _prompt_login(downloader.bank)
                page.goto(downloader.statements_url)

            entries = downloader.list_statements(page)
            print(f"[{downloader.bank}] Found {len(entries)} statement(s).")

            skipped = downloaded = 0
            for entry in entries:
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

        ctx.close()

    return 0
