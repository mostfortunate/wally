"""Unit tests for the within/under/over verdict."""

from __future__ import annotations

from decimal import Decimal

from src.budget import Status, status_for


def test_over_when_spend_exceeds_limit() -> None:
    assert status_for(Decimal("120"), Decimal("100")) is Status.OVER


def test_under_when_spend_below_threshold() -> None:
    # 40 < 100 * 0.5 -> meaningfully underspending.
    assert status_for(Decimal("40"), Decimal("100")) is Status.UNDER


def test_within_when_between_threshold_and_limit() -> None:
    assert status_for(Decimal("80"), Decimal("100")) is Status.WITHIN


def test_at_limit_is_within_not_over() -> None:
    assert status_for(Decimal("100"), Decimal("100")) is Status.WITHIN


def test_zero_limit_never_underspends() -> None:
    assert status_for(Decimal("0"), Decimal("0")) is Status.WITHIN
