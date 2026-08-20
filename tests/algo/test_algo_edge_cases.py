"""Extra deterministic edge coverage for fixed-spread quoting."""

from __future__ import annotations

from decimal import Decimal

import pytest

from rotor.algo import (
    SimpleMarketMakingAlgo,
    SimpleMarketMakingConfig,
)
from rotor.mm.exchange.client import MarketInfo


def _market(
    *,
    price_step: Decimal | None = Decimal("0.0001"),
    amount_step: Decimal | None = Decimal("0.01"),
    tick_precision: int = 4,
    quantity_precision: int = 2,
    min_bid_quote_amount: Decimal = Decimal("0"),
    min_ask_amount: Decimal = Decimal("0"),
) -> MarketInfo:
    return MarketInfo(
        symbol="XSGD/USDC",
        base_symbol="XSGD",
        quote_symbol="USDC",
        base_address="0xbase",
        quote_address="0xquote",
        base_decimals=6,
        quote_decimals=6,
        tick_precision=tick_precision,
        quantity_precision=quantity_precision,
        price_step=price_step,
        amount_step=amount_step,
        min_bid_quote_amount=min_bid_quote_amount,
        min_ask_amount=min_ask_amount,
    )


def test_simple_uses_precision_fallback_when_steps_are_absent():
    algo = SimpleMarketMakingAlgo(
        SimpleMarketMakingConfig(qty_base=Decimal("12.345"), fixed_bps=Decimal("10"))
    )

    quote = algo.quote(
        _market(price_step=None, amount_step=None, tick_precision=3, quantity_precision=1),
        Decimal("1.23456"),
    )

    assert quote.bid_price == Decimal("1.233")
    assert quote.ask_price == Decimal("1.236")
    assert quote.qty_base == Decimal("12.3")


def test_simple_rejects_too_small_ask_quantity():
    algo = SimpleMarketMakingAlgo(
        SimpleMarketMakingConfig(qty_base=Decimal("0.99"), fixed_bps=Decimal("8"))
    )

    with pytest.raises(ValueError, match="ask qty"):
        algo.quote(_market(min_ask_amount=Decimal("1")), Decimal("1"))


def test_simple_rejects_quantity_that_rounds_to_zero():
    algo = SimpleMarketMakingAlgo(
        SimpleMarketMakingConfig(qty_base=Decimal("0.009"), fixed_bps=Decimal("8"))
    )

    with pytest.raises(ValueError, match="quantity rounds to zero"):
        algo.quote(_market(amount_step=Decimal("0.01"), quantity_precision=2), Decimal("1"))


def test_simple_rejects_crossed_prices_after_quantization():
    algo = SimpleMarketMakingAlgo(
        SimpleMarketMakingConfig(qty_base=Decimal("10"), fixed_bps=Decimal("0"))
    )

    with pytest.raises(ValueError, match="must be below ask"):
        algo.quote(_market(price_step=Decimal("0.01"), tick_precision=2), Decimal("1"))
