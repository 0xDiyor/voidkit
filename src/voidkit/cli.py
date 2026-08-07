"""Command-line entry point for Void Kit.

``voidkit`` (no arguments) prints the banner and starts the interactive
``use``/``set``/``run`` shell (Phase 2). ``--version`` and ``--help`` keep the
Phase 0 behavior. ``--modules-dir`` points discovery at a modules directory;
it defaults to ``$VOIDKIT_MODULES_DIR`` or ``./modules``.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.console import Console

from voidkit import __version__
from voidkit.loader import ModuleLoader
from voidkit.log_config import configure_logging
from voidkit.shell import Shell

DEFAULT_MODULES_DIR = "modules"

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
    parser.add_argument(
        "--modules-dir",
        default=os.environ.get("VOIDKIT_MODULES_DIR", DEFAULT_MODULES_DIR),
        help="Directory to discover modules from (default: $VOIDKIT_MODULES_DIR or ./modules).",
    )
    return parser


def print_banner(console: Console) -> None:
    console.print(BANNER, style="bold cyan", markup=False, highlight=False)
    console.print(f"Void Kit {__version__}, pre-alpha", markup=False, highlight=False)
    console.print(
        "For authorized security testing and defensive operations only.",
        markup=False,
        highlight=False,
    )
    console.print()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    configure_logging()
    console = Console()
    print_banner(console)

    loader = ModuleLoader(Path(args.modules_dir))
    Shell(loader=loader, console=console).run()
    return 0
