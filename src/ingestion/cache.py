"""Statement parse cache: SHA-256-keyed JSON blobs stored in ~/.cache/wally/statements/.

Cache key is the SHA-256 of the PDF bytes, not the filename — a renamed or overwritten file
produces a different hash and correctly misses the cache. Amounts are stored as decimal strings
(never float) so the reconciliation gates are equally strict on cached and fresh data.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from platformdirs import user_cache_dir

from src.parsers.base import Direction, Parser, Statement, Transaction

CACHE_VERSION = 2
_CACHE_ROOT = Path(user_cache_dir("wally")) / "statements"


def cached_parse(pdf_path: str, parser: Parser, *, no_cache: bool = False) -> Statement:
    """Return a parsed Statement, reading from cache when possible.

    On a cache miss the parser runs and the result is written to the cache.
    Pass no_cache=True to force a fresh parse, skipping both cache read and write.
    """
    if no_cache:
        return parser.parse(pdf_path)

    pdf_bytes = Path(pdf_path).read_bytes()
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    cache_file = _CACHE_ROOT / f"sha256-{sha256}.json"

    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            if data.get("cache_version") == CACHE_VERSION:
                return _from_json(data)
        except KeyError, ValueError, InvalidOperation, TypeError:
            pass  # corrupt or unreadable cache entry — fall through to re-parse

    stmt = parser.parse(pdf_path)
    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(_to_json(stmt, sha256), indent=2))
    return stmt


def clear() -> int:
    """Delete all cached statement parses. Returns the number of entries removed."""
    if not _CACHE_ROOT.exists():
        return 0
    entries = list(_CACHE_ROOT.glob("sha256-*.json"))
    shutil.rmtree(_CACHE_ROOT)
    return len(entries)


def _to_json(stmt: Statement, pdf_sha256: str) -> dict[str, object]:
    return {
        "cache_version": CACHE_VERSION,
        "pdf_sha256": pdf_sha256,
        "bank": stmt.bank,
        "opening_balance": str(stmt.opening_balance) if stmt.opening_balance is not None else None,
        "closing_balance": str(stmt.closing_balance) if stmt.closing_balance is not None else None,
        "transactions": [_txn_to_json(t) for t in stmt.transactions],
    }


def _txn_to_json(txn: Transaction) -> dict[str, object]:
    return {
        "raw_description": txn.raw_description,
        "amount": str(txn.amount),
        "direction": txn.direction.name,
        "date": txn.date.isoformat() if txn.date is not None else None,
        "balance": str(txn.balance) if txn.balance is not None else None,
        "bank_category": txn.bank_category,
    }


def _from_json(data: dict[str, object]) -> Statement:
    ob = data["opening_balance"]
    cb = data["closing_balance"]
    return Statement(
        bank=str(data["bank"]),
        opening_balance=Decimal(str(ob)) if ob is not None else None,
        closing_balance=Decimal(str(cb)) if cb is not None else None,
        transactions=[_txn_from_json(t) for t in data["transactions"]],  # type: ignore[arg-type]
    )


def _txn_from_json(data: dict[str, object]) -> Transaction:
    raw_date = data["date"]
    raw_balance = data["balance"]
    return Transaction(
        raw_description=str(data["raw_description"]),
        amount=Decimal(str(data["amount"])),
        direction=Direction[str(data["direction"])],
        date=date.fromisoformat(str(raw_date)) if raw_date is not None else None,
        balance=Decimal(str(raw_balance)) if raw_balance is not None else None,
        bank_category=str(data["bank_category"])
        if data.get("bank_category") is not None
        else None,
    )
