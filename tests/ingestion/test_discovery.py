"""Unit tests for src.ingestion.discovery.find_latest."""

from __future__ import annotations

from pathlib import Path

from src.ingestion.discovery import find_latest


class TestFindLatest:
    def test_returns_none_when_dir_is_empty(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "cibc"
        bank_dir.mkdir()
        assert find_latest(bank_dir) is None

    def test_returns_single_pdf_when_only_one_present(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "rbc"
        bank_dir.mkdir()
        pdf = bank_dir / "2026-05.pdf"
        pdf.touch()
        assert find_latest(bank_dir) == pdf

    def test_returns_latest_of_multiple_pdfs(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "cibc"
        bank_dir.mkdir()
        (bank_dir / "2026-03.pdf").touch()
        (bank_dir / "2026-04.pdf").touch()
        assert find_latest(bank_dir) == bank_dir / "2026-04.pdf"

    def test_ignores_files_without_yyyy_mm_naming(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "rbc"
        bank_dir.mkdir()
        (bank_dir / "statement.pdf").touch()
        (bank_dir / "notes.txt").touch()
        (bank_dir / "2026-04.pdf").touch()
        assert find_latest(bank_dir) == bank_dir / "2026-04.pdf"

    def test_ignores_statement_pdf_with_non_numeric_year(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "cibc"
        bank_dir.mkdir()
        (bank_dir / "abcd-01.pdf").touch()
        assert find_latest(bank_dir) is None

    def test_ignores_statement_pdf_with_non_numeric_month(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "cibc"
        bank_dir.mkdir()
        (bank_dir / "2026-ab.pdf").touch()
        assert find_latest(bank_dir) is None

    def test_ignores_stem_of_wrong_length(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "rbc"
        bank_dir.mkdir()
        (bank_dir / "2026-5.pdf").touch()  # too short (6 chars)
        (bank_dir / "2026-045.pdf").touch()  # too long (8 chars)
        assert find_latest(bank_dir) is None

    def test_returns_none_for_empty_dir_with_only_txt_files(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "rbc"
        bank_dir.mkdir()
        (bank_dir / "notes.txt").touch()
        assert find_latest(bank_dir) is None

    def test_chronological_order_across_years(self, tmp_path: Path) -> None:
        bank_dir = tmp_path / "rbc"
        bank_dir.mkdir()
        (bank_dir / "2025-12.pdf").touch()
        (bank_dir / "2026-01.pdf").touch()
        (bank_dir / "2026-02.pdf").touch()
        assert find_latest(bank_dir) == bank_dir / "2026-02.pdf"
