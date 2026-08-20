"""Sera market-making code.

Entry points:
    `rotor mm vl`: TOML-driven multi-pair Virtual Liquidity loop.
"""

# This package marker intentionally avoids imports so importing `rotor.mm` does
# not create HTTP clients, read wallet config, or start runtime side effects.
