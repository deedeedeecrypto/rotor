"""Canonical Order struct construction — server signing parity.

`eip712.build_order_struct` must reproduce, bit for bit, the struct that
the Sera server derives on its side.
Rotor signs that struct; the server rebuilds it from the same inputs and
recovers the signer. Any divergence — a different rounding mode, a different
Decimal precision, a swapped token role — yields a digest the server cannot
verify, and every order is rejected.

`order_struct_vectors.json` holds golden vectors captured from a live Sera
deployment's own `POST /orders/preview` response, so these are the server's
actual outputs rather than a re-derivation of Rotor's own logic. Regenerate
them only against a real deployment, never by hand.
"""

from __future__ import annotations

import decimal
import json
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path

import pytest

from rotor.mm.exchange import eip712

# Golden vectors live beside this test so a regeneration is a visible diff.
_VECTORS = json.loads(
    (Path(__file__).parent / "order_struct_vectors.json").read_text()
)


def _ids(vectors: list[dict]) -> list[str]:
    """Readable pytest ids: market + side + amount@price."""
    return [f"{v['symbol']}-{v['side']}-{v['amount']}@{v['price']}" for v in vectors]


@pytest.mark.parametrize("vector", _VECTORS, ids=_ids(_VECTORS))
def test_local_struct_matches_server_preview(vector: dict) -> None:
    """The locally built struct equals the server's own preview output."""
    struct = eip712.build_order_struct(
        owner_address=vector["owner_address"],
        side=vector["side"],
        amount=Decimal(vector["amount"]),
        price=Decimal(vector["price"]),
        base_address=vector["base_address"],
        quote_address=vector["quote_address"],
        base_decimals=vector["base_decimals"],
        quote_decimals=vector["quote_decimals"],
        uuid_int=int(vector["uuid_int"]),
        expiration=vector["expiration"],
    )
    # The server serializes uint fields as strings; compare on a common form
    # so a type difference cannot mask a value difference.
    actual = {key: str(value).lower() for key, value in struct.items()}
    expected = {key: str(value).lower() for key, value in vector["expected_struct"].items()}
    assert actual == expected


def test_bid_and_ask_swap_token_roles() -> None:
    """A bid spends quote to receive base; an ask does the reverse."""
    common = dict(
        owner_address="0x1111111111111111111111111111111111111111",
        amount=Decimal("1000"),
        price=Decimal("1.25"),
        base_address="0xAAA0000000000000000000000000000000000001",
        quote_address="0xBBB0000000000000000000000000000000000002",
        base_decimals=18,
        quote_decimals=6,
        uuid_int=7,
        expiration=1800000000,
    )
    bid = eip712.build_order_struct(side="bid", **common)
    ask = eip712.build_order_struct(side="ask", **common)

    # Token roles mirror each other across the two sides.
    assert bid["fromToken"] == ask["toToken"] == common["quote_address"].lower()
    assert bid["toToken"] == ask["fromToken"] == common["base_address"].lower()
    # 1000 base at 1.25 => 1250 quote, each scaled by its own token decimals.
    assert bid["fromAmount"] == ask["toAmount"] == 1250 * 10**6
    assert bid["toAmount"] == ask["fromAmount"] == 1000 * 10**18


def test_quote_amount_is_floored_not_rounded() -> None:
    """Sub-unit remainders truncate toward zero, matching the server."""
    struct = eip712.build_order_struct(
        owner_address="0x1111111111111111111111111111111111111111",
        side="ask",
        # 3 * 0.3333335 = 1.0000005 quote; at 6 decimals the trailing 5 must
        # be dropped, not rounded up to 1000001.
        amount=Decimal("3"),
        price=Decimal("0.3333335"),
        base_address="0xAAA0000000000000000000000000000000000001",
        quote_address="0xBBB0000000000000000000000000000000000002",
        base_decimals=6,
        quote_decimals=6,
        uuid_int=1,
        expiration=1800000000,
    )
    assert struct["toAmount"] == 1000000


def test_uses_server_decimal_precision() -> None:
    """Amounts are derived under the server's 50-digit Decimal context.

    Python defaults to 28 significant digits. With a 30-digit price the
    default context would round `amount * price` before flooring and produce a
    different raw amount than the server.
    """
    assert eip712.SERVER_DECIMAL_PREC == 50
    price = Decimal("1.00000000000000000000000000001")  # 30 significant digits
    struct = eip712.build_order_struct(
        owner_address="0x1111111111111111111111111111111111111111",
        side="ask",
        amount=Decimal("1000000000000"),
        price=price,
        base_address="0xAAA0000000000000000000000000000000000001",
        quote_address="0xBBB0000000000000000000000000000000000002",
        base_decimals=6,
        quote_decimals=18,
        uuid_int=1,
        expiration=1800000000,
    )
    # Computed at 50 digits the 1e-29 tail survives into the 18-decimal
    # scaling; at Python's default 28 digits it would be rounded away and the
    # amount would collapse to exactly 1e30.
    with decimal.localcontext() as ctx:
        ctx.prec = eip712.SERVER_DECIMAL_PREC
        expected = int(
            (Decimal("1000000000000") * price * Decimal(10**18)).quantize(
                Decimal(1), rounding=ROUND_FLOOR
            )
        )
    assert struct["toAmount"] == expected
    assert struct["toAmount"] != 10**30


def test_rejects_unknown_side() -> None:
    """Only bid/ask are valid; anything else is a programming error."""
    with pytest.raises(ValueError, match="Invalid side"):
        eip712.build_order_struct(
            owner_address="0x1111111111111111111111111111111111111111",
            side="buy",
            amount=Decimal("1"),
            price=Decimal("1"),
            base_address="0xAAA0000000000000000000000000000000000001",
            quote_address="0xBBB0000000000000000000000000000000000002",
            base_decimals=6,
            quote_decimals=6,
            uuid_int=1,
            expiration=1800000000,
        )


def test_raw_amount_rejects_oversized_amounts() -> None:
    """Absurd amounts raise a clear ValueError, never a raw InvalidOperation.

    At 10**60 base units the scaled value needs ~79 significant digits, more
    than the 50-digit context can quantize. The server hits the same wall —
    its own uint256 ceiling check sits after the quantize and is
    unreachable here — so the request would fail server-side regardless.
    Rotor refuses locally instead of signing and sending it.
    """
    with pytest.raises(ValueError, match="too large to represent"):
        eip712.raw_amount(Decimal(10) ** 60, 18)


@pytest.mark.parametrize("exponent", [51, 60, 78, 90])
def test_raw_amount_rejects_every_oversized_scale(exponent: int) -> None:
    """Oversized amounts are always refused, never silently wrapped.

    Note the uint256 ceiling (~1.16e77, 78 digits) sits above the 50-digit
    context, so a value large enough to overflow uint256 can never be
    quantized in the first place. The explicit `exceeds uint256` guard is
    therefore unreachable in both Rotor and the server; it is kept only as
    defence in depth should the precision ever be raised.
    """
    with pytest.raises(ValueError):
        eip712.raw_amount(Decimal(10) ** exponent, 18)


def test_raw_amount_rejects_negative() -> None:
    """Negative amounts can never appear in a signed order."""
    with pytest.raises(ValueError, match="non-negative"):
        eip712.raw_amount(Decimal("-1"), 6)
