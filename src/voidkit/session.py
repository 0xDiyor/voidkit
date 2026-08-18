"""Session persistence: save/load the shell's working state to JSON on disk.

Phase 4 makes an operator's work resumable. A :class:`Session` is a plain,
JSON-serializable snapshot of everything the shell needs to pick up where it left
off:

- the selected module's address and its currently-set options,
- the whole :class:`~voidkit.store.ResultStore` (every :class:`Result`, verbatim
  via the Phase 1 :meth:`Result.to_dict` / :meth:`Result.from_dict`),
- the chaining source (the id of the result feeding the next run's ``upstream``),
- an optional human name for the session.

The on-disk format is a single JSON object tagged with a version so a future
schema change can be detected rather than silently mis-read. Loading validates:
a missing file, non-JSON text, the wrong version, or a malformed :class:`Result`
all raise :class:`SessionError` with a clear message instead of crashing the shell.

The shell (``save <name>`` / ``load <name>``) maps itself to and from a
:class:`Session`; this module owns only the state container and its disk I/O, so
it stays decoupled from the REPL and is unit-testable on its own.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from voidkit.contract import Result

__all__ = ["SESSION_VERSION", "Session", "SessionError"]

_log = structlog.get_logger("voidkit.session")

# Bumped only on a breaking change to the session envelope (not the Result schema,
# which carries its own schema_version). Loading a mismatch is a clear error.
SESSION_VERSION = 1


class SessionError(Exception):
    """Raised when a session file cannot be read, parsed, or validated."""


def _jsonable(value: Any) -> Any:
    """Coerce option values to JSON-native types (enums -> their value, etc.).

    Option values arrive already validated/coerced by pydantic; the framework's
    own options are JSON scalars, but a module could declare an ``Enum`` option
    whose value is an enum member. Normalize those so ``to_state`` never hands
    ``json.dumps`` something it cannot serialize.
    """
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


@dataclass
class Session:
    """A JSON-serializable snapshot of shell state (Phase 4 save/load)."""

    name: str | None = None
    module: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    chain_from: str | None = None
    results: list[Result] = field(default_factory=list)

    # -- (de)serialization -----------------------------------------------------

    def to_state(self) -> dict[str, Any]:
        """Dump to a plain, JSON-compatible dict (the on-disk envelope)."""
        return {
            "voidkit_session_version": SESSION_VERSION,
            "name": self.name,
            "module": self.module,
            "options": _jsonable(self.options),
            "chain_from": self.chain_from,
            "results": [result.to_dict() for result in self.results],
        }

    @classmethod
    def from_state(cls, data: Any) -> Session:
        """Rebuild a :class:`Session` from a state dict, validating as we go.

        Raises :class:`SessionError` for anything that is not a well-formed
        session envelope: wrong top-level type, unknown version, mistyped
        fields, or a result that fails Phase 1 validation.
        """
        if not isinstance(data, dict):
            raise SessionError(
                f"session state must be a JSON object, got {type(data).__name__}"
            )

        version = data.get("voidkit_session_version")
        if version != SESSION_VERSION:
            raise SessionError(
                f"unsupported session version {version!r} (this build expects {SESSION_VERSION})"
            )

        name = _optional_str(data.get("name"), "name")
        module = _optional_str(data.get("module"), "module")
        chain_from = _optional_str(data.get("chain_from"), "chain_from")

        options = data.get("options", {})
        if not isinstance(options, dict):
            raise SessionError(f"'options' must be an object, got {type(options).__name__}")

        results_raw = data.get("results", [])
        if not isinstance(results_raw, list):
            raise SessionError(f"'results' must be a list, got {type(results_raw).__name__}")
        results: list[Result] = []
        for index, item in enumerate(results_raw):
            try:
                results.append(Result.from_dict(item))
            except Exception as exc:  # any parse/validation failure means a bad file
                raise SessionError(f"result #{index} is not a valid Result: {exc}") from exc

        return cls(
            name=name,
            module=module,
            options=dict(options),
            chain_from=chain_from,
            results=results,
        )

    # -- disk I/O --------------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        """Write the session as pretty-printed JSON, creating parent dirs."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_state(), indent=2)
        path.write_text(text, encoding="utf-8")
        _log.info("session.saved", path=str(path), results=len(self.results))
        return path

    @classmethod
    def load(cls, path: str | Path) -> Session:
        """Read and validate a session file, or raise :class:`SessionError`."""
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise SessionError(f"no session file at {path}") from exc
        except OSError as exc:
            raise SessionError(f"cannot read session file {path}: {exc}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SessionError(f"{path} is not valid JSON: {exc}") from exc
        return cls.from_state(data)


def _optional_str(value: Any, field_name: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise SessionError(f"'{field_name}' must be a string or null, got {type(value).__name__}")
