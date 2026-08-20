# Exchange Package

This package contains Sera-specific REST and signing payload helpers.

Files:

- `__init__.py`: package summary and module index.
- `client.py`: small Sera REST wrapper for config/health/markets, order preview,
  order placement, VL batch placement/cancel, open orders, and fills. Requires an
  `https://` base URL (except `localhost`), verifies each preview's
  owner/recipient/token-pair/amount against the intended order before signing,
  and paginates fills.
- `eip712.py`: EIP-712 type definitions plus Sera `uuid_int` bit packing for
  standalone and VL orders.
- `errors.py`: typed error envelopes for Sera HTTP responses, including cancel
  cooldown handling (classified by error code, with a message-substring fallback
  only when no code is present).

Keep Sera API shape changes isolated here so runners can stay focused on market
making decisions instead of wire-format details.
