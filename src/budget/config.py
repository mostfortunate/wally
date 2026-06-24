"""Load the user's budget config (categories + monthly limits) from a TOML file.

Amounts are quoted strings in the TOML on purpose: a bare TOML number parses as a
float, and money is Decimal, never float. We convert str -> Decimal and reject any
amount that isn't a string, so a stray bare number can't silently lose precision.
"""

from __future__ import annotations

import tomllib
from decimal import Decimal
from pathlib import Path

from src.budget import BudgetLimits


def parse_budget_limits(data: dict) -> BudgetLimits:
    """Turn a parsed-TOML mapping into Decimal limits. Pure; rejects float amounts."""
    raw = data.get("budget", {}).get("limits", {})
    limits: BudgetLimits = {}
    for category, amount in raw.items():
        if not isinstance(amount, str):
            raise ValueError(
                f"budget limit for {category!r} must be a quoted string to stay "
                f'Decimal-exact (e.g. "100.00"); got {type(amount).__name__} {amount!r}'
            )
        limits[category] = Decimal(amount)
    return limits


def load_budget_limits(path: str | Path) -> BudgetLimits:
    """Read and parse the budget config at `path`."""
    with Path(path).open("rb") as fh:
        data = tomllib.load(fh)
    return parse_budget_limits(data)


__all__ = ["load_budget_limits", "parse_budget_limits"]
