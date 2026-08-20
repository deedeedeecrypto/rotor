"""Token-symbol to ISO-currency mapping for simple FX market making."""

from __future__ import annotations

# Built-in mappings cover the token symbols the simple FX market maker expects
# to see most often.
DEFAULT_TOKEN_TO_ISO: dict[str, str] = {
    "USDC": "USD",
    "USDT": "USD",
    "USD": "USD",
    "XSGD": "SGD",
    "SGD": "SGD",
    "MYRC": "MYR",
    "MYRT": "MYR",
    "MYR": "MYR",
    "EURC": "EUR",
    "EURT": "EUR",
    "EUR": "EUR",
}


def parse_market_symbol(market: str) -> tuple[str, str]:
    """Split a Sera market symbol like `XSGD/USDC` into token symbols."""
    # Accept underscores as a forgiving input format, then normalize casing.
    parts = [p.strip().upper() for p in market.replace("_", "/").split("/")]
    # Reject missing sides or extra delimiters before downstream mapping.
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"market must look like BASE/QUOTE, got {market!r}")
    return parts[0], parts[1]


def market_to_iso_pair(
    market: str,
    token_to_iso: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Map a Sera token market into an ISO FX pair.

    Examples:
        `XSGD/USDC` -> (`SGD`, `USD`)
        `MYRT/USDT` -> (`MYR`, `USD`)
    """
    # User overrides win over built-ins so new stablecoin symbols can be added
    # without changing source.
    mapping = {**DEFAULT_TOKEN_TO_ISO, **(token_to_iso or {})}
    # Parse before mapping so the error for malformed market symbols is clear.
    base_token, quote_token = parse_market_symbol(market)
    try:
        # Return ISO currencies in the same base/quote order as the market.
        return mapping[base_token], mapping[quote_token]
    except KeyError as exc:
        # Missing token mappings are configuration issues, not provider issues.
        raise ValueError(
            f"no ISO mapping for token {exc.args[0]!r}; add PRICE_REFERENCE_TOKEN_TO_ISO"
        ) from exc
