"""Transaction → disposition. Configurable, extensible rule engine.

Every transaction is parsed first, then classified into exactly one disposition:
  - CATEGORIZED   — maps to a real budget category (merchant-specific, extensible).
  - EXCLUDED      — money that moved or is counted elsewhere; always carries a reason
                    (inter-account transfers, the CIBC card payment). Not spending.
  - UNCATEGORIZED — real spend we couldn't attribute. Never silently dropped; surfaces
                    in the report as a warning.

Matching is deterministic: normalize the description (lowercase; keep only letters,
digits, '#', '$') and test each normalized pattern as a substring. Decisions, in order:
  1. Exclusions are checked FIRST — a card payment must never be miscategorized.
  2. A description matching two or more distinct categories (or exclusion reasons) is a
     config error, not first-match-wins. Silent miscategorization is unacceptable in a
     reconciliation system, so we raise rather than guess.
  3. No match → UNCATEGORIZED.
"""

from __future__ import annotations

from src.classification.config import (
    ClassificationError,
    ClassificationRules,
    load_rules,
    normalize,
    parse_rules,
)
from src.parsers.base import Classified, Disposition, Transaction


def _matches(description: str, rules: dict[str, tuple[str, ...]]) -> list[str]:
    """Keys whose patterns appear in the normalized description."""
    return [key for key, patterns in rules.items() if any(p in description for p in patterns)]


def _classify_one(txn: Transaction, rules: ClassificationRules) -> Classified:
    description = normalize(txn.raw_description)

    reasons = _matches(description, rules.exclusions)
    if len(reasons) > 1:
        raise ClassificationError(
            f"{txn.raw_description!r} matches multiple exclusion reasons {reasons}; "
            f"disambiguate the rules"
        )
    if reasons:
        return Classified(txn, Disposition.EXCLUDED, reason=reasons[0])

    categories = _matches(description, rules.categories)
    if len(categories) > 1:
        raise ClassificationError(
            f"{txn.raw_description!r} matches multiple categories {categories}; "
            f"disambiguate the rules"
        )
    if categories:
        return Classified(txn, Disposition.CATEGORIZED, category=categories[0])

    return Classified(txn, Disposition.UNCATEGORIZED)


def classify(transactions: list[Transaction], rules: ClassificationRules) -> list[Classified]:
    """Assign a disposition (and category/reason) to every transaction.

    Returns exactly one `Classified` per input transaction so the partition gate holds.
    """
    return [_classify_one(txn, rules) for txn in transactions]


__all__ = [
    "ClassificationError",
    "ClassificationRules",
    "classify",
    "load_rules",
    "normalize",
    "parse_rules",
]
