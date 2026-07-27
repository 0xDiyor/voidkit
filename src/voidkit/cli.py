"""Command-line entry point for Void Kit.

Phase 0 surface only: ``--version``, ``--help``, and a placeholder banner.
The interactive ``use``/``set``/``run`` shell arrives with the module loader
in Phase 2 (see ROADMAP.md).
"""

from __future__ import annotations

import argparse

from rich.console import Console

from voidkit import __version__

BANNER = r"""
             _     _ _    _ _
 __   _____ (_) __| | | _(_) |_
 \ \ / / _ \| |/ _` | |/ / | __|
  \ V / (_) | | (_| |   <| | |_
   \_/ \___/|_|\__,_|_|\_\_|\__|
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voidkit",
        description="A modular terminal framework for security and network operations.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Void Kit {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)

    console = Console()
    console.print(BANNER, style="bold cyan", markup=False, highlight=False)
    console.print(f"Void Kit {__version__}, pre-alpha", markup=False, highlight=False)
    console.print(
        "For authorized security testing and defensive operations only.",
        markup=False,
        highlight=False,
    )
    console.print()
    console.print(
        "voidkit > (interactive shell coming in Phase 2; see ROADMAP.md)",
        markup=False,
        highlight=False,
    )
    return 0
