# Notifications Package

This package contains optional outbound notifications for market-maker runs.

Files:

- `__init__.py`: re-exports `TelegramNotifier`.
- `telegram.py`: synchronous-safe Telegram notifier with normal, important, and
  debug/heartbeat channels.

Notifications must not crash trading loops. The Telegram notifier uses debug
dry-run logs when tokens, chat IDs, or the optional `python-telegram-bot`
dependency are missing.
