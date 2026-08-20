# Security Package

This package contains signing-key helpers for Sera order placement.

Files:

- `__init__.py`: re-exports key-management and signing helpers.
- `key.py`: loads `SERA_PRIVATE_KEY` (validating the 0x-prefixed shape and that
  it is a valid secp256k1 scalar in `[1, n)`, rejecting the zero key), exposes the
  unlocked wallet address, signs EIP-712 typed data, and allows the process to
  forget the key.

Private keys should come from the environment, a root `.env`, or an untracked
`rotor/secret.py`. Do not commit local key material.
