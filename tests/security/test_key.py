"""Tests for wallet unlock, lock, address derivation, and typed-data signing."""

from __future__ import annotations

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from rotor.security import key as wallet_key


class TestUnlock:
    def test_unlock_loads_env_key_then_lock(
        self, known_keypair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pk, addr = known_keypair
        monkeypatch.setenv("SERA_PRIVATE_KEY", pk)

        wallet_key.unlock()
        assert wallet_key.is_unlocked()
        assert wallet_key.wallet_address() == addr

        wallet_key.lock()
        assert not wallet_key.is_unlocked()
        with pytest.raises(wallet_key.WalletLocked):
            wallet_key.wallet_address()

    def test_unlock_is_idempotent(
        self, known_keypair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pk, addr = known_keypair
        monkeypatch.setenv("SERA_PRIVATE_KEY", pk)
        wallet_key.unlock()
        wallet_key.unlock()
        assert wallet_key.wallet_address() == addr

    def test_unlock_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SERA_PRIVATE_KEY", raising=False)
        with pytest.raises(wallet_key.WalletNotInitialized):
            wallet_key.unlock()

    def test_unlock_malformed_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERA_PRIVATE_KEY", "not-a-key")
        with pytest.raises(wallet_key.InvalidPrivateKey):
            wallet_key.unlock()

    def test_unlock_rejects_zero_scalar_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Correct shape but a cryptographically invalid (zero) scalar that
        # eth-account would otherwise accept and derive a known address from.
        monkeypatch.setenv("SERA_PRIVATE_KEY", "0x" + "00" * 32)
        with pytest.raises(wallet_key.InvalidPrivateKey):
            wallet_key.unlock()

    def test_unlock_rejects_key_at_or_above_curve_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SERA_PRIVATE_KEY", "0x" + f"{wallet_key.SECP256K1_N:064x}")
        with pytest.raises(wallet_key.InvalidPrivateKey):
            wallet_key.unlock()


class TestTypedDataSigning:
    def test_sign_typed_data_raises_when_locked(self) -> None:
        with pytest.raises(wallet_key.WalletLocked):
            wallet_key.sign_typed_data({}, {}, {})

    def test_sign_typed_data_recovers_wallet_address(
        self, known_keypair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pk, addr = known_keypair
        domain = {
            "name": "Sera",
            "version": "1",
            "chainId": 1,
            "verifyingContract": "0x0000000000000000000000000000000000000001",
        }
        types = {
            "Ping": [
                {"name": "owner", "type": "address"},
                {"name": "nonce", "type": "uint256"},
            ],
        }
        message = {"owner": addr, "nonce": 1}

        monkeypatch.setenv("SERA_PRIVATE_KEY", pk)
        wallet_key.unlock()
        signature = wallet_key.sign_typed_data(domain, types, message)

        signable = encode_typed_data(
            domain_data=domain,
            message_types=types,
            message_data=message,
        )
        recovered = Account.recover_message(signable, signature=signature)
        assert recovered.lower() == addr.lower()
