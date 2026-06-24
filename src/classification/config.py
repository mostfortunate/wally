"""Load classification rules (categories + exclusions) from a TOML file.

Mirrors the budget-config pattern: a pure `parse_rules` over an already-parsed mapping
plus a `load_rules` file wrapper. Patterns are normalized once here, at load time, so
the hot path in `classify` only normalizes each transaction description.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# After lowercasing, keep ONLY ascii letters, digits, '#' and '$'; drop everything else
# (whitespace, punctuation, stray glyphs). ascii-only is deliberate: a glyph like "Ý"
# lowercases to "ý", which is alphanumeric to Python but is exactly the noise we drop.
_STRIP = re.compile(r"[^a-z0-9#$]")


class ClassificationError(Exception):
    """Raised on an invalid rules file or an ambiguous classification."""


def normalize(text: str) -> str:
    """Lowercase, then keep only letters, digits, '#' and '$'.

    Drops whitespace, punctuation, and stray glyphs so real statement descriptions like
    "AMAZON* BY8UE6Y60", "Ý TIM HORTONS #2813", or "UBER CANADA/UBERTRIP" reduce to
    "amazonby8ue6y60", "timhortons#2813", "ubercanadaubertrip" and substring patterns
    match cleanly. '#' and '$' are kept because they're meaningful (e.g. a store "#2813").
    """
    return _STRIP.sub("", text.lower())


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
