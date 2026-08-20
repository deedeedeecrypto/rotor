"""Simple fixed-bps market-making algorithm.

Benchmark:
    The algo receives a quote-per-base reference rate for the day/tick,
    such as `SGD/USD` for `XSGD/USDC`. It treats that rate as the
    benchmark mid.

Quotes:
    Bid = benchmark * (1 - fixed_bps / 10_000)
    Ask = benchmark * (1 + fixed_bps / 10_000)

The algo also quantizes to Sera's price/amount grids and enforces the
market's published minimum sizes. It has no network access and no wallet
access, which keeps future algorithms easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from rotor.mm.exchange.client import MarketInfo

# One basis point is 1/10,000; keeping this as Decimal avoids float drift in
# financial arithmetic.
BPS = Decimal("10000")


@dataclass(frozen=True)
class SimpleMarketMakingConfig:
    """Configuration for fixed-bps quoting around a benchmark rate."""

    # Base-token amount requested for each side before exchange quantization.
    qty_base: Decimal
    # Distance from the benchmark mid price to each side, in basis points.
    fixed_bps: Decimal


@dataclass(frozen=True)
class QuoteSet:
    """The two-sided target emitted by a market-making algo."""

    # Reference quote-per-base rate that the algo used as the mid.
    benchmark_rate: Decimal
    # Limit bid price, or None when this algo intentionally does not quote bid.
    bid_price: Decimal | None
    # Limit ask price, or None when this algo intentionally does not quote ask.
    ask_price: Decimal | None
    # Base-token size after exchange amount-grid quantization.
    qty_base: Decimal
    # Effective spread setting used to produce the quote.
    fixed_bps: Decimal


class SimpleMarketMakingAlgo:
    """Quote one bid and one ask at fixed bps from the benchmark rate."""

    # Public name used by runners/config to dispatch algorithm-specific inputs.
    name = "simple_market_making"

    def __init__(self, config: SimpleMarketMakingConfig) -> None:
        """Store immutable quote parameters for later ticks."""
        self.config = config

    def quote(self, market: MarketInfo, benchmark_rate: Decimal) -> QuoteSet:
        """Build a valid two-sided quote for one Sera market."""
        # Normalize through `str` so caller-provided ints/floats do not leak
        # binary floating-point representation into Decimal math.
        fixed = Decimal(str(self.config.fixed_bps))
        # The algo applies the configured bps to each side of the mid.
        half = fixed / BPS
        # Bids round down so the maker never bids more aggressively than the
        # requested spread after exchange tick quantization.
        bid = _quantize_price(market, benchmark_rate * (Decimal("1") - half), "bid")
        # Asks round up for the symmetric reason: never sell cheaper than the
        # requested spread after tick quantization.
        ask = _quantize_price(market, benchmark_rate * (Decimal("1") + half), "ask")
        # Amounts round down so the bot never places a larger base size than
        # configured.
        qty = _quantize_qty(market, self.config.qty_base)
        # Fail fast before a runner signs or submits an invalid order.
        _validate_minimums(market, qty, bid, ask)
        return QuoteSet(
            benchmark_rate=benchmark_rate,
            bid_price=bid,
            ask_price=ask,
            qty_base=qty,
            fixed_bps=fixed,
        )


def _quantize_price(info: MarketInfo, value: Decimal, side: str) -> Decimal:
    """Snap a raw price onto Sera's price grid with side-aware rounding."""
    # Side-aware rounding preserves the maker's economic intent after snapping.
    rounding = ROUND_DOWN if side == "bid" else ROUND_UP
    return _quantize_step(value, info.price_step, info.tick_precision, rounding)


def _quantize_qty(info: MarketInfo, value: Decimal) -> Decimal:
    """Snap a raw base quantity onto Sera's amount grid."""
    # Quantities always round down to avoid overspending inventory.
    return _quantize_step(value, info.amount_step, info.quantity_precision, ROUND_DOWN)


def _quantize_step(
    value: Decimal,
    step: Decimal | None,
    precision: int,
    rounding,
) -> Decimal:
    """Snap `value` to an explicit step, or to precision-derived powers of ten."""
    # Newer market metadata can provide an exact step; older metadata may only
    # provide decimal precision, so derive a quantum like 0.01 from precision=2.
    quantum = step or Decimal("1").scaleb(-precision)
    # Divide by the grid, round to an integer grid count, then scale back.
    return (value / quantum).to_integral_value(rounding=rounding) * quantum


def _validate_minimums(info: MarketInfo, qty: Decimal, bid_px: Decimal, ask_px: Decimal) -> None:
    """Reject quotes that would violate basic local and Sera market constraints."""
    # A zero/negative amount after quantization cannot produce a valid order.
    if qty <= 0:
        raise ValueError("quantity rounds to zero")
    # Some derived algos may intentionally omit one side, but at least one side
    # must remain quoteable.
    if bid_px is None and ask_px is None:
        raise ValueError("no quoteable side")
    # Bid minimums are quote-token notional minimums: base size times bid price.
    if bid_px is not None and info.min_bid_quote_amount and qty * bid_px < info.min_bid_quote_amount:
        raise ValueError(
            f"bid notional {qty * bid_px} below Sera min {info.min_bid_quote_amount}"
        )
    # Ask minimums are base-token amount minimums.
    if ask_px is not None and info.min_ask_amount and qty < info.min_ask_amount:
        raise ValueError(f"ask qty {qty} below Sera min {info.min_ask_amount}")
    # A crossed quote is invalid and would invert maker economics.
    if bid_px is not None and ask_px is not None and bid_px >= ask_px:
        raise ValueError(f"bid {bid_px} must be below ask {ask_px}")
