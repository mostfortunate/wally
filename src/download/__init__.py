"""Statement auto-download via Playwright (persistent Chrome session)."""

from .base import BankDownloader, StatementEntry
from .runner import run_download

__all__ = ["BankDownloader", "StatementEntry", "run_download"]
