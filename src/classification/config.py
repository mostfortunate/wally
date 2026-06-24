"""Load classification rules (categories + exclusions) from a TOML file.

Mirrors the budget-config pattern: a pure `parse_rules` over an already-parsed mapping
plus a `load_rules` file wrapper. Patterns are normalized once here, at load time, so
the hot path in `classify` only normalizes each transaction description.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ClassificationError(Exception):
    """Raised on an invalid rules file or an ambiguous classification."""


def normalize(text: str) -> str:
    """Lowercase and strip ALL whitespace, so spacing/case never affect a match."""
    return "".join(text.split()).lower()


@dataclass(frozen=True)
class ClassificationRules:
    """Normalized rules. Keys are display names; values are normalized match patterns."""

    categories: dict[str, tuple[str, ...]]  # category name -> patterns
    exclusions: dict[str, tuple[str, ...]]  # exclusion reason -> patterns


def _parse_section(section: object, name: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(section, dict):
        raise ClassificationError(
            f"[{name}] must be a table of key = [patterns]; got {type(section).__name__}"
        )
    result: dict[str, tuple[str, ...]] = {}
    for key, patterns in section.items():
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ClassificationError(
                f"{name}.{key!r} must be a list of strings; got {patterns!r}"
            )
        normalized: list[str] = []
        for pattern in patterns:
            token = normalize(pattern)
            if not token:
                raise ClassificationError(
                    f"{name}.{key!r} has an empty/whitespace-only pattern {pattern!r} "
                    f"that would match everything"
                )
            normalized.append(token)
        result[key] = tuple(normalized)
    return result


def parse_rules(data: dict) -> ClassificationRules:
    """Validate and normalize a parsed-TOML mapping into `ClassificationRules`. Pure."""
    return ClassificationRules(
        categories=_parse_section(data.get("categories", {}), "categories"),
        exclusions=_parse_section(data.get("exclude", {}), "exclude"),
    )


def load_rules(path: str | Path) -> ClassificationRules:
    """Read and parse the classification rules at `path`."""
    with Path(path).open("rb") as fh:
        data = tomllib.load(fh)
    return parse_rules(data)


__all__ = [
    "ClassificationError",
    "ClassificationRules",
    "load_rules",
    "normalize",
    "parse_rules",
]
