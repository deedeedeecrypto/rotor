"""Outbound notifications for the Sera market maker.

Public surface:
    TelegramNotifier: Three-channel Telegram notifier (normal, important,
        debug heartbeat) for market-maker lifecycle events.
"""

# Re-export the notifier so runners can import from `rotor.notifications`.
from rotor.notifications.telegram import TelegramNotifier  # noqa: F401

# Explicit public API for auditors and wildcard imports.
__all__ = ["TelegramNotifier"]
