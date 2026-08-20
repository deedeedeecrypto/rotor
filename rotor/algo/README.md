# Algorithm Package

Pure fixed-spread quote generation. Algorithms do not fetch prices, place
orders, or sign anything.

Files:

- `__init__.py`: public exports.
- `simple_market_making.py`: fixed-bps two-sided quote generation with Sera
  tick/amount quantization and minimum-size checks.
