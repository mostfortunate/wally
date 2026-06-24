"""Unit tests for the classification engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.classification import ClassificationError, classify
from src.classification.config import parse_rules
from src.parsers.base import Direction, Disposition, Transaction


def _txn(description: str) -> Transaction:
    return Transaction(description, Decimal("10.00"), Direction.WITHDRAWAL)


RULES = parse_rules(
    {
        "categories": {
            "takeout": ["tim hortons", "uber eats"],
            "gas": ["petro"],
        },
        "exclude": {"CIBC card payment": ["payment thank you"]},
    }
)


def test_single_category_match() -> None:
    [result] = classify([_txn("TIM HORTONS #42 VANCOUVER BC")], RULES)
    assert result.disposition is Disposition.CATEGORIZED
    assert result.category == "takeout"


def test_exclusion_is_checked_first() -> None:
    # Matches the exclusion; must be EXCLUDED with a reason, never categorized.
    [result] = classify([_txn("PAYMENT THANK YOU / PAIEMENT MERCI")], RULES)
    assert result.disposition is Disposition.EXCLUDED
    assert result.reason == "CIBC card payment"
    assert result.category is None


def test_exclusion_wins_over_a_category_match() -> None:
    rules = parse_rules(
        {
            "categories": {"gas": ["petro"]},
            "exclude": {"transfer": ["petro"]},  # contrived overlap, exclude-first
        }
    )
    [result] = classify([_txn("PETRO CANADA")], rules)
    assert result.disposition is Disposition.EXCLUDED
    assert result.reason == "transfer"


def test_no_match_is_uncategorized() -> None:
    [result] = classify([_txn("SOME UNKNOWN MERCHANT")], RULES)
    assert result.disposition is Disposition.UNCATEGORIZED
    assert result.category is None
    assert result.reason is None


def test_ambiguous_categories_raise() -> None:
    rules = parse_rules(
        {"categories": {"takeout": ["amazon"], "shopping": ["amazon"]}}
    )
    with pytest.raises(ClassificationError, match="multiple categories"):
        classify([_txn("AMAZON* PURCHASE")], rules)


def test_ambiguous_exclusions_raise() -> None:
    rules = parse_rules(
        {"exclude": {"reason a": ["payment"], "reason b": ["payment"]}}
    )
    with pytest.raises(ClassificationError, match="multiple exclusion reasons"):
        classify([_txn("PAYMENT RECEIVED")], rules)


def test_one_classified_per_transaction() -> None:
    txns = [_txn("TIM HORTONS"), _txn("PETRO"), _txn("MYSTERY")]
    results = classify(txns, RULES)
    assert len(results) == len(txns)
    assert [r.txn for r in results] == txns
