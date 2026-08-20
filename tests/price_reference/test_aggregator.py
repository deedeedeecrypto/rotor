"""Tests for freshness enforcement in the reference-price oracle."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

import pytest

from rotor.price_reference.aggregator import ReferencePriceOracle, ReferenceUnavailable
from rotor.price_reference.models import PriceObservation


@dataclass
class StaticSource:
    name: str = "wise"
    rate: Decimal = Decimal("0.7400")
    age_s: float = 0.0

    def quote(self, base: str, quote: str, *, amount=None) -> PriceObservation:
        return PriceObservation(
            source=self.name,
            pair=f"{base}/{quote}",
            rate=self.rate,
            ts=time.time() - self.age_s,
        )


def test_reference_oracle_returns_fresh_wise_quote():
    ref = ReferencePriceOracle(StaticSource(rate=Decimal("0.7415"))).get("SGD", "USD")

    assert ref.pair == "SGD/USD"
    assert ref.rate == Decimal("0.7415")
    assert ref.source == "wise"


def test_reference_oracle_rejects_stale_quote():
    oracle = ReferencePriceOracle(StaticSource(age_s=999), max_age_s=10)
    with pytest.raises(ReferenceUnavailable, match="stale"):
        oracle.get("SGD", "USD")
