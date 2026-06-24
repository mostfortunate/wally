"""Unit tests for classification-rules parsing and normalization."""

from __future__ import annotations

import pytest

from src.classification.config import (
    ClassificationError,
    normalize,
    parse_rules,
)


def test_normalize_lowercases_and_strips_all_whitespace() -> None:
    assert normalize("TIM HORTONS #1234") == "timhortons#1234"
    assert normalize("  Uber\tEats\n") == "ubereats"


def test_parse_rules_normalizes_patterns() -> None:
    data = {
        "categories": {"takeout": ["Tim Hortons", "UBER EATS"]},
        "exclude": {"CIBC card payment": ["Payment Thank You"]},
    }
    rules = parse_rules(data)
    assert rules.categories == {"takeout": ("timhortons", "ubereats")}
    assert rules.exclusions == {"CIBC card payment": ("paymentthankyou",)}


def test_parse_rules_empty_is_allowed() -> None:
    rules = parse_rules({})
    assert rules.categories == {}
    assert rules.exclusions == {}


def test_parse_rules_rejects_non_list_patterns() -> None:
    with pytest.raises(ClassificationError, match="must be a list of strings"):
        parse_rules({"categories": {"gas": "petro"}})


def test_parse_rules_rejects_non_string_pattern() -> None:
    with pytest.raises(ClassificationError, match="must be a list of strings"):
        parse_rules({"categories": {"gas": ["petro", 5]}})


def test_parse_rules_rejects_empty_pattern() -> None:
    with pytest.raises(ClassificationError, match="match everything"):
        parse_rules({"categories": {"gas": ["   "]}})


def test_parse_rules_rejects_non_table_section() -> None:
    with pytest.raises(ClassificationError, match=r"\[categories\] must be a table"):
        parse_rules({"categories": ["petro"]})
