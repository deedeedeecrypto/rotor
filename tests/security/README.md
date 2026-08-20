# Security Tests

This folder tests wallet-key loading and EIP-712 signing.

Files:

- `conftest.py`: shared known-key fixtures and wallet cleanup.
- `test_key.py`: unlock/lock behavior, invalid-key handling (malformed, zero, and
  out-of-curve-range scalars), address derivation, and typed-data signing.
