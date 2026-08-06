"""Operator audit-log configuration for the interactive shell.

The contract keeps two output channels separate: ``rich`` writes user-facing shell
output to stdout, ``structlog`` writes the operator's audit trail. This module points
that trail at **stderr** so it never interleaves with the shell's stdout rendering,
and a piped ``voidkit`` run keeps its structured logs out of the captured output.

Only the CLI calls :func:`configure_logging`; importing the library (or running the
test suite) leaves structlog at its defaults, so nothing here changes Phase 1 behavior.
"""

from __future__ import annotations

import sys

import structlog

__all__ = ["configure_logging"]


class _LiveStderr:
    """Write to whatever ``sys.stderr`` is *now*, not whatever it was at config time.

    Binding ``sys.stderr`` eagerly into the logger factory would capture a transient
    stream (e.g. a test harness's captured buffer) and keep writing to it after it
    closes. Resolving it per write keeps logging robust across stream swaps.
    """

    def write(self, message: str) -> int:
        return sys.stderr.write(message)

    def flush(self) -> None:
        sys.stderr.flush()


def configure_logging() -> None:
    """Route structlog to stderr with timestamped, level-prefixed console lines."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=_LiveStderr()),
        cache_logger_on_first_use=True,
    )
