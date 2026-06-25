"""Unit tests for src.ingestion.cache."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.ingestion import cache as cache_module
from src.ingestion.cache import CACHE_VERSION, cached_parse, clear
from src.parsers.base import Direction, Parser, Statement, Transaction

_SAMPLE_STMT = Statement(
    bank="TestBank",
    opening_balance=Decimal("1000.00"),
    closing_balance=Decimal("500.00"),
    transactions=[
        Transaction(
            raw_description="Some Merchant",
            amount=Decimal("50.00"),
            direction=Direction.WITHDRAWAL,
            date=date(2026, 5, 1),
            balance=Decimal("950.00"),
        ),
        Transaction(
            raw_description="Payroll",
            amount=Decimal("200.00"),
            direction=Direction.DEPOSIT,
            date=date(2026, 5, 15),
            balance=None,
        ),
    ],
)


class _MockParser(Parser):
    bank = "TestBank"

    def __init__(self) -> None:
        self.call_count = 0

    def parse(self, pdf_path: str) -> Statement:
        self.call_count += 1
        return _SAMPLE_STMT


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "wally" / "statements"
    monkeypatch.setattr(cache_module, "_CACHE_ROOT", d)
    return d


@pytest.fixture
def fake_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "2026-05.pdf"
    p.write_bytes(b"fake-pdf-bytes")
    return p


class TestCachedParse:
    def test_cache_miss_calls_parser(self, cache_dir: Path, fake_pdf: Path) -> None:
        parser = _MockParser()
        cached_parse(str(fake_pdf), parser)
        assert parser.call_count == 1

    def test_cache_miss_writes_json_file(self, cache_dir: Path, fake_pdf: Path) -> None:
        cached_parse(str(fake_pdf), _MockParser())
        assert len(list(cache_dir.glob("sha256-*.json"))) == 1

    def test_cache_hit_skips_parser(self, cache_dir: Path, fake_pdf: Path) -> None:
        parser = _MockParser()
        cached_parse(str(fake_pdf), parser)
        cached_parse(str(fake_pdf), parser)
        assert parser.call_count == 1

    def test_no_cache_always_calls_parser(self, cache_dir: Path, fake_pdf: Path) -> None:
        parser = _MockParser()
        cached_parse(str(fake_pdf), parser, no_cache=True)
        cached_parse(str(fake_pdf), parser, no_cache=True)
        assert parser.call_count == 2

    def test_no_cache_does_not_write_cache_file(self, cache_dir: Path, fake_pdf: Path) -> None:
        cached_parse(str(fake_pdf), _MockParser(), no_cache=True)
        assert not cache_dir.exists()

    def test_changed_pdf_content_misses_cache(self, cache_dir: Path, tmp_path: Path) -> None:
        pdf = tmp_path / "stmt.pdf"
        pdf.write_bytes(b"original-content")
        parser = _MockParser()
        cached_parse(str(pdf), parser)
        pdf.write_bytes(b"amended-content")
        cached_parse(str(pdf), parser)
        assert parser.call_count == 2

    def test_version_mismatch_triggers_re_parse(self, cache_dir: Path, fake_pdf: Path) -> None:
        cache_dir.mkdir(parents=True)
        sha = hashlib.sha256(fake_pdf.read_bytes()).hexdigest()
        stale = {
            "cache_version": CACHE_VERSION - 1,
            "pdf_sha256": sha,
            "bank": "TestBank",
            "opening_balance": None,
            "closing_balance": None,
            "transactions": [],
        }
        (cache_dir / f"sha256-{sha}.json").write_text(json.dumps(stale))
        parser = _MockParser()
        cached_parse(str(fake_pdf), parser)
        assert parser.call_count == 1

    def test_roundtrip_preserves_decimal_precision(self, cache_dir: Path, fake_pdf: Path) -> None:
        cached_parse(str(fake_pdf), _MockParser())
        result = cached_parse(str(fake_pdf), _MockParser())
        assert result.opening_balance == Decimal("1000.00")
        assert result.closing_balance == Decimal("500.00")
        assert result.transactions[0].amount == Decimal("50.00")
        assert result.transactions[0].balance == Decimal("950.00")

    def test_roundtrip_preserves_none_balance(self, cache_dir: Path, fake_pdf: Path) -> None:
        cached_parse(str(fake_pdf), _MockParser())
        result = cached_parse(str(fake_pdf), _MockParser())
        assert result.transactions[1].balance is None

    def test_roundtrip_preserves_date(self, cache_dir: Path, fake_pdf: Path) -> None:
        cached_parse(str(fake_pdf), _MockParser())
        result = cached_parse(str(fake_pdf), _MockParser())
        assert result.transactions[0].date == date(2026, 5, 1)
        assert result.transactions[1].date == date(2026, 5, 15)

    def test_roundtrip_preserves_direction(self, cache_dir: Path, fake_pdf: Path) -> None:
        cached_parse(str(fake_pdf), _MockParser())
        result = cached_parse(str(fake_pdf), _MockParser())
        assert result.transactions[0].direction is Direction.WITHDRAWAL
        assert result.transactions[1].direction is Direction.DEPOSIT

    def test_roundtrip_preserves_bank(self, cache_dir: Path, fake_pdf: Path) -> None:
        cached_parse(str(fake_pdf), _MockParser())
        result = cached_parse(str(fake_pdf), _MockParser())
        assert result.bank == "TestBank"

    def test_cache_key_is_content_not_filename(self, cache_dir: Path, tmp_path: Path) -> None:
        content = b"identical-content"
        pdf_a = tmp_path / "2026-05.pdf"
        pdf_b = tmp_path / "2026-06.pdf"
        pdf_a.write_bytes(content)
        pdf_b.write_bytes(content)
        parser = _MockParser()
        cached_parse(str(pdf_a), parser)
        cached_parse(str(pdf_b), parser)
        assert parser.call_count == 1  # same bytes → same hash → cache hit
        assert len(list(cache_dir.glob("sha256-*.json"))) == 1


class TestClear:
    def test_clear_returns_zero_when_cache_absent(self, cache_dir: Path) -> None:
        assert clear() == 0

    def test_clear_returns_count_and_removes_dir(self, cache_dir: Path, fake_pdf: Path) -> None:
        cached_parse(str(fake_pdf), _MockParser())
        assert clear() == 1
        assert not cache_dir.exists()

    def test_clear_multiple_entries(self, cache_dir: Path, tmp_path: Path) -> None:
        for i in range(3):
            pdf = tmp_path / f"stmt{i}.pdf"
            pdf.write_bytes(f"content-{i}".encode())
            cached_parse(str(pdf), _MockParser())
        assert clear() == 3
        assert not cache_dir.exists()

    def test_clear_is_idempotent(self, cache_dir: Path) -> None:
        assert clear() == 0
        assert clear() == 0
