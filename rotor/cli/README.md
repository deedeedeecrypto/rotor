# CLI Package

Defines the installed `rotor` command.

Files:

- `__init__.py`: short package-level command overview.
- `main.py`: argparse parser and handler for `rotor mm vl`.

CLI handlers should stay thin: parse command-line values, unlock the wallet when
needed, then delegate real work to the VL runner.
