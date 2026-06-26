"""Unit tests for CLI helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from src.cli import _period_label, _resolve_pdf_path


class TestPeriodLabel:
    def test_returns_none_when_no_paths(self) -> None:
        assert _period_label(None, None) is None

    def test_returns_none_when_paths_have_no_yyyy_mm_stem(self) -> None:
        assert _period_label("statements/cibc/statement.pdf", None) is None

    def test_single_path_formats_month_year(self) -> None:
        assert _period_label("statements/cibc/2026-06.pdf", None) == "June 2026"

    def test_both_paths_same_month(self) -> None:
        result = _period_label("statements/cibc/2026-06.pdf", "statements/rbc/2026-06.pdf")
        assert result == "June 2026"

    def test_both_paths_different_months(self) -> None:
        label = _period_label("statements/cibc/2026-05.pdf", "statements/rbc/2026-06.pdf")
        assert label == "May 2026 – June 2026"

    def test_ignores_non_yyyy_mm_stem(self) -> None:
        assert _period_label("statements/cibc/2026-06.pdf", "other/statement.pdf") == "June 2026"


class TestResolvePdfPath:
    def test_full_path_that_exists_is_returned_as_is(self, tmp_path: Path) -> None:
        pdf = tmp_path / "2026-06.pdf"
        pdf.touch()
        p = argparse.ArgumentParser()
        assert _resolve_pdf_path(str(pdf), tmp_path / "cibc", p) == str(pdf)

    def test_date_stem_resolves_to_bank_dir_pdf(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "cibc"
        bank_dir.mkdir()
        (bank_dir / "2026-06.pdf").touch()
        p = argparse.ArgumentParser()
        assert _resolve_pdf_path("2026-06", bank_dir, p) == str(bank_dir / "2026-06.pdf")

    def test_raises_when_neither_path_nor_stem_resolves(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "cibc"
        bank_dir.mkdir()
        p = argparse.ArgumentParser()
        with pytest.raises(SystemExit):
            _resolve_pdf_path("2026-06", bank_dir, p)
