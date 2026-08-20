"""Tests for fixed-bps quote generation, quantization, and minimum checks."""

from __future__ import annotations

from decimal import Decimal

import pytest

from rotor.algo import SimpleMarketMakingAlgo, SimpleMarketMakingConfig
from rotor.mm.exchange.client import MarketInfo


def _market() -> MarketInfo:
    return MarketInfo(
        symbol="XSGD/USDC",
        base_symbol="XSGD",
        quote_symbol="USDC",
        base_address="0xbase",
        quote_address="0xquote",
        base_decimals=6,
        quote_decimals=6,
        tick_precision=4,
        quantity_precision=2,
        price_step=Decimal("0.0001"),
        amount_step=Decimal("0.01"),
        min_bid_quote_amount=Decimal("8.80"),
        min_ask_amount=Decimal("1"),
    )


def test_simple_market_making_quotes_fixed_bps_from_benchmark():
    algo = SimpleMarketMakingAlgo(
        SimpleMarketMakingConfig(qty_base=Decimal("100.009"), fixed_bps=Decimal("8"))
    )
    quote = algo.quote(_market(), benchmark_rate=Decimal("0.74005"))

    assert quote.benchmark_rate == Decimal("0.74005")
    assert quote.fixed_bps == Decimal("8")
    assert quote.bid_price == Decimal("0.7394")
    assert quote.ask_price == Decimal("0.7407")
    assert quote.qty_base == Decimal("100.00")


def test_simple_market_making_rejects_too_small_bid_notional():
    algo = SimpleMarketMakingAlgo(
        SimpleMarketMakingConfig(qty_base=Decimal("1"), fixed_bps=Decimal("8"))
    )
    with pytest.raises(ValueError, match="bid notional"):
        algo.quote(_market(), benchmark_rate=Decimal("0.74005"))
