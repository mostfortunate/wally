"""Unit tests for budget-config parsing — especially the Decimal-vs-float guard."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.budget.config import parse_budget_limits


def test_parses_string_amounts_to_decimal() -> None:
    data = {"budget": {"limits": {"takeout": "100.00", "gas": "300.50"}}}
    assert parse_budget_limits(data) == {
        "takeout": Decimal("100.00"),
        "gas": Decimal("300.50"),
    }


def test_rejects_float_amount_to_protect_precision() -> None:
    # A bare TOML number arrives as a float; reject it rather than lose a penny.
    data = {"budget": {"limits": {"gas": 300.10}}}
    with pytest.raises(ValueError, match="Decimal-exact"):
        parse_budget_limits(data)


def test_missing_section_is_empty() -> None:
    assert parse_budget_limits({}) == {}
    assert parse_budget_limits({"budget": {}}) == {}
