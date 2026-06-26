"""Unit tests for src.ingestion.discovery.find_latest and find_all."""

from __future__ import annotations

from pathlib import Path

from src.ingestion.discovery import find_all, find_latest


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


class TestFindAll:
    def test_find_all_returns_sorted_pdfs(self, tmp_path: Path) -> None:
        """find_all returns YYYY-MM.pdf files sorted; ignores non-matching names."""
        for name in ["2026-03.pdf", "2026-01.pdf", "2026-02.pdf", "notes.txt", "random.pdf"]:
            (tmp_path / name).touch()
        result = find_all(tmp_path)
        assert [p.name for p in result] == ["2026-01.pdf", "2026-02.pdf", "2026-03.pdf"]

    def test_find_all_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        """find_all returns [] for a directory that does not exist."""
        assert find_all(tmp_path / "nonexistent") == []

    def test_find_all_returns_empty_for_no_matching_files(self, tmp_path: Path) -> None:
        """find_all returns [] when dir exists but contains no YYYY-MM.pdf files."""
        (tmp_path / "notes.txt").touch()
        (tmp_path / "random.pdf").touch()
        assert find_all(tmp_path) == []
