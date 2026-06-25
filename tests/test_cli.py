"""Unit tests for CLI helpers."""

from __future__ import annotations

from src.cli import _period_label


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
