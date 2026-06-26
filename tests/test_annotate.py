"""Unit tests for src.annotate — pure function tests only.

No PDF I/O, no terminal interaction, no live filesystem except tmp_path.
"""

from __future__ import annotations

import tomllib
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console as RichConsole

from src.annotate import (
    _append_rule,
    _default_pattern,
    _delete_session,
    _guess_category,
    _load_session,
    _save_session,
    _unique_uncategorized,
    run_annotate_list,
)
from src.classification.config import ClassificationRules
from src.parsers.base import Classified, Direction, Disposition, Statement, Transaction

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_rules(
    categories: dict[str, list[str]],
    exclusions: dict[str, list[str]] | None = None,
) -> ClassificationRules:
    """Build a ClassificationRules with pre-normalized patterns."""
    return ClassificationRules(
        categories={k: tuple(v) for k, v in categories.items()},
        exclusions={k: tuple(v) for k, v in (exclusions or {}).items()},
    )


def _make_txn(description: str, amount: str = "10.00") -> Transaction:
    return Transaction(
        raw_description=description,
        amount=Decimal(amount),
        direction=Direction.WITHDRAWAL,
    )


def _make_classified(
    description: str,
    disposition: Disposition,
    amount: str = "10.00",
) -> Classified:
    txn = _make_txn(description, amount)
    return Classified(txn=txn, disposition=disposition)


def _make_statement(bank: str, transactions: list[Transaction]) -> Statement:
    return Statement(bank=bank, transactions=transactions)


# ---------------------------------------------------------------------------
# _guess_category tests
# ---------------------------------------------------------------------------


class TestGuessCategory:
    def test_guess_known_merchant(self) -> None:
        """Single pattern match returns correct category."""
        rules = _make_rules({"coffee": ["timhortons"], "groceries": ["loblaws"]})
        assert _guess_category("timhortons#2813", rules) == "coffee"

    def test_guess_no_match(self) -> None:
        """No matching pattern returns None."""
        rules = _make_rules({"coffee": ["timhortons"]})
        assert _guess_category("walmart", rules) is None

    def test_guess_ambiguous(self) -> None:
        """Two categories match returns None (ambiguous)."""
        rules = _make_rules({"coffee": ["amazon"], "shopping": ["amazon"]})
        assert _guess_category("amazonby8ue6y60", rules) is None


# ---------------------------------------------------------------------------
# _default_pattern tests
# ---------------------------------------------------------------------------


class TestDefaultPattern:
    def test_default_pattern_strips_store_code(self) -> None:
        """'timhortons#2813' -> 'timhortons'"""
        assert _default_pattern("timhortons#2813") == "timhortons"

    def test_default_pattern_strips_suffix_digits(self) -> None:
        """'amazonby8ue6y60' -> 'amazonby': letters-only prefix before first digit."""
        assert _default_pattern("amazonby8ue6y60") == "amazonby"

    def test_default_pattern_short_merchant(self) -> None:
        """Short name with no digits returned as-is."""
        assert _default_pattern("bp") == "bp"

    def test_default_pattern_dollarama(self) -> None:
        """'dollarama#1201' -> 'dollarama'"""
        assert _default_pattern("dollarama#1201") == "dollarama"


# ---------------------------------------------------------------------------
# _append_rule tests
# ---------------------------------------------------------------------------


class TestAppendRule:
    def test_append_rule_creates_file(self, tmp_path: Path) -> None:
        """Non-existent path is created with the new category."""
        rules_path = tmp_path / "classification.toml"
        assert not rules_path.exists()
        _append_rule(rules_path, "coffee", "timhortons")
        assert rules_path.exists()

    def test_append_rule_creates_category(self, tmp_path: Path) -> None:
        """An empty TOML file gets the category and pattern added."""
        rules_path = tmp_path / "classification.toml"
        rules_path.write_bytes(b"")
        _append_rule(rules_path, "coffee", "timhortons")
        with rules_path.open("rb") as fh:
            data = tomllib.load(fh)
        assert data["categories"]["coffee"] == ["timhortons"]

    def test_append_rule_extends_existing(self, tmp_path: Path) -> None:
        """Appending to an existing category adds the new pattern."""
        rules_path = tmp_path / "classification.toml"
        _append_rule(rules_path, "coffee", "timhortons")
        _append_rule(rules_path, "coffee", "starbucks")
        with rules_path.open("rb") as fh:
            data = tomllib.load(fh)
        assert data["categories"]["coffee"] == ["timhortons", "starbucks"]

    def test_append_rule_idempotent(self, tmp_path: Path) -> None:
        """Appending the same pattern twice produces no duplicate."""
        rules_path = tmp_path / "classification.toml"
        _append_rule(rules_path, "coffee", "timhortons")
        _append_rule(rules_path, "coffee", "timhortons")
        with rules_path.open("rb") as fh:
            data = tomllib.load(fh)
        assert data["categories"]["coffee"] == ["timhortons"]


# ---------------------------------------------------------------------------
# Session helpers tests
# ---------------------------------------------------------------------------


class TestSessionHelpers:
    def test_session_round_trip(self, tmp_path: Path) -> None:
        """save + load returns same set of handled descriptions."""
        session_path = tmp_path / "classification.toml.session.json"
        _save_session(session_path, "timhortons")
        _save_session(session_path, "dollarama")
        loaded = _load_session(session_path)
        assert loaded == {"timhortons", "dollarama"}

    def test_load_session_missing_file(self, tmp_path: Path) -> None:
        """Missing session file returns empty set."""
        session_path = tmp_path / "nonexistent.session.json"
        assert _load_session(session_path) == set()

    def test_delete_session(self, tmp_path: Path) -> None:
        """_delete_session removes the file; calling again is a no-op."""
        session_path = tmp_path / "classification.toml.session.json"
        _save_session(session_path, "timhortons")
        assert session_path.exists()
        _delete_session(session_path)
        assert not session_path.exists()
        _delete_session(session_path)  # no-op, no error


# ---------------------------------------------------------------------------
# _unique_uncategorized tests
# ---------------------------------------------------------------------------


class TestUniqueUncategorized:
    def test_unique_uncategorized_deduplicates(self) -> None:
        """3 transactions with 2 unique descriptions -> 2 items returned."""
        classified = [
            _make_classified("TIM HORTONS #2813", Disposition.UNCATEGORIZED),
            _make_classified("TIM HORTONS #9001", Disposition.UNCATEGORIZED),  # same norm
            _make_classified("WALMART #123", Disposition.UNCATEGORIZED),
        ]
        result = _unique_uncategorized(classified)
        assert len(result) == 2
        assert result[0].raw_description == "TIM HORTONS #2813"
        assert result[1].raw_description == "WALMART #123"

    def test_unique_uncategorized_excludes_categorized(self) -> None:
        """CATEGORIZED and EXCLUDED transactions are not included."""
        classified = [
            _make_classified("STARBUCKS", Disposition.CATEGORIZED),
            _make_classified("CIBC PAYMENT", Disposition.EXCLUDED),
            _make_classified("UNKNOWN MERCHANT", Disposition.UNCATEGORIZED),
        ]
        result = _unique_uncategorized(classified)
        assert len(result) == 1
        assert result[0].raw_description == "UNKNOWN MERCHANT"


# ---------------------------------------------------------------------------
# run_annotate_list tests (monkeypatched cached_parse)
# ---------------------------------------------------------------------------


class TestRunAnnotateList:
    def test_list_all_categorized(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """All CATEGORIZED transactions -> Done column shows 0 uncategorized."""
        rules_path = tmp_path / "classification.toml"
        _append_rule(rules_path, "coffee", "timhortons")

        cibc_pdf = tmp_path / "2026-01.pdf"
        cibc_pdf.touch()

        stmt = _make_statement("CIBC", [_make_txn("TIM HORTONS #2813", "12.50")])

        import src.annotate as annotate_mod

        monkeypatch.setattr(annotate_mod, "cached_parse", lambda path, parser: stmt)

        buf = StringIO()
        monkeypatch.setattr(annotate_mod, "_console", RichConsole(file=buf, highlight=False))

        result = run_annotate_list(
            rules_path=str(rules_path),
            cibc_paths=[str(cibc_pdf)],
        )
        assert result == 0
        output = buf.getvalue()
        # 0 uncategorized transactions
        assert "0" in output

    def test_list_some_uncategorized(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Mixed dispositions -> correct uncategorized count in output."""
        rules_path = tmp_path / "classification.toml"
        _append_rule(rules_path, "coffee", "timhortons")

        cibc_pdf = tmp_path / "2026-01.pdf"
        cibc_pdf.touch()

        stmt = _make_statement(
            "CIBC",
            [
                _make_txn("TIM HORTONS #2813", "12.50"),  # will be categorized
                _make_txn("UNKNOWN MERCHANT XYZ", "5.00"),  # will be uncategorized
            ],
        )

        import src.annotate as annotate_mod

        monkeypatch.setattr(annotate_mod, "cached_parse", lambda path, parser: stmt)

        buf = StringIO()
        monkeypatch.setattr(annotate_mod, "_console", RichConsole(file=buf, highlight=False))

        result = run_annotate_list(
            rules_path=str(rules_path),
            cibc_paths=[str(cibc_pdf)],
        )
        assert result == 0
        output = buf.getvalue()
        # Should show 1 uncategorized transaction in the table
        assert "1" in output
