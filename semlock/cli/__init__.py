"""SEMLock command-line interface (S5-owned).

Contract (frozen early; changes need an ADR):

    semlock check REFA REFB [--repo PATH] [--json | --sarif]
                  [--config PATH] [--inject-fixtures SCENARIO]
    semlock graph REF [--repo PATH] [-o FILE]
    semlock version

Exit codes: 0 = clean, 1 = conflicts found, 2 = error (bad ref, bad args,
unavailable stage, I/O failure). argparse usage errors also exit 2.

Run as a module until the console-script entry point lands in pyproject
(S1-owned): `python -m semlock.cli.main check A B`.
"""
from __future__ import annotations
