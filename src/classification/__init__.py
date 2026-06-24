"""Transaction → disposition. Configurable, extensible rule engine.

Every transaction is parsed first, then classified into exactly one disposition:
  - CATEGORIZED   — maps to a real budget category (merchant-specific, extensible).
  - EXCLUDED      — money that moved or is counted elsewhere; always carries a reason
                    (inter-account transfers, the CIBC card payment). Not spending.
  - UNCATEGORIZED — real spend we couldn't attribute. Never silently dropped; surfaces
                    in the report as a warning.

Data-driven exclusions to wire here (inputs from the human, not guesses):
  - The CIBC card-payment line on the RBC statement (grep one statement for the payment
    amount to get the exact description string) — EXCLUDED, reason "CIBC card payment".
"""

from __future__ import annotations

from src.parsers.base import Classified, Transaction


def classify(transactions: list[Transaction]) -> list[Classified]:
    """Assign a disposition (and category/reason) to every transaction.

    Phase 0 stub. Must return exactly one `Classified` per input transaction so the
    partition gate holds.
    """
    raise NotImplementedError("classification engine — Phase 1")


__all__ = ["classify"]
