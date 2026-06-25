"""Tests for src/init_cmd.py — pure helpers only (no interactive prompts)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from src.init_cmd import CATEGORIES, build_toml


class TestBuildToml:
    def test_writes_section_header(self) -> None:
        out = build_toml({"groceries": Decimal("100.00")})
        assert "[budget.limits]" in out

    def test_formats_amount_as_quoted_string(self) -> None:
        out = build_toml({"takeout": Decimal("50")})
        assert 'takeout = "50.00"' in out

    def test_multiple_categories(self) -> None:
        out = build_toml({"gas": Decimal("250"), "groceries": Decimal("100")})
        assert 'gas = "250.00"' in out
        assert 'groceries = "100.00"' in out

    def test_output_is_valid_toml_readable(self, tmp_path: Path) -> None:
        import tomllib

        content = build_toml({"groceries": Decimal("100.00"), "gas": Decimal("250.00")})
        f = tmp_path / "out.toml"
        f.write_text(content)
        data = tomllib.loads(f.read_text())
        assert data["budget"]["limits"]["groceries"] == "100.00"
        assert data["budget"]["limits"]["gas"] == "250.00"


class TestCategories:
    def test_all_keys_are_valid_toml_identifiers(self) -> None:
        for key, _ in CATEGORIES:
            assert key.replace("_", "").isalnum(), f"{key!r} is not a valid TOML key"

    def test_no_duplicate_keys(self) -> None:
        keys = [k for k, _ in CATEGORIES]
        assert len(keys) == len(set(keys))
