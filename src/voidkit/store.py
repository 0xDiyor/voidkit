"""In-memory result store: the backing for ``show results`` and, later, chaining.

Every module run in the shell produces a :class:`~voidkit.contract.Result`; the
store keeps them in run order and indexes them by their (already-unique) ``id``
so ``show results`` can list them and later phases can look one up to chain from
or persist. This is deliberately just an ordered, id-indexed collection over the
Phase 1 schema. Persistence (Phase 4) serializes these Results verbatim.
"""

from __future__ import annotations

import structlog

from voidkit.contract import Result

__all__ = ["ResultStore"]

_log = structlog.get_logger("voidkit.store")


class ResultStore:
    """Ordered, id-indexed collection of :class:`Result` objects for one session."""

    def __init__(self) -> None:
        self._results: list[Result] = []
        self._by_id: dict[str, Result] = {}

    def add_result(self, result: Result) -> str:
        """Store a result and return its id. A duplicate id replaces the prior entry."""
        if result.id in self._by_id:
            existing = self._by_id[result.id]
            self._results = [r if r.id != result.id else result for r in self._results]
            self._by_id[result.id] = result
            _log.warning("store.replaced", id=result.id, module=existing.module_path)
            return result.id
        self._results.append(result)
        self._by_id[result.id] = result
        _log.info("store.added", id=result.id, module=result.module_path, status=result.status.value)
        return result.id

    def list_results(self) -> list[Result]:
        """All stored results, in the order they were added (a copy; safe to mutate)."""
        return list(self._results)

    def get_result(self, result_id: str) -> Result | None:
        """The result with this id, or ``None`` if it was never stored."""
        return self._by_id.get(result_id)

    def clear(self) -> None:
        """Drop all stored results."""
        count = len(self._results)
        self._results.clear()
        self._by_id.clear()
        _log.info("store.cleared", removed=count)

    def __len__(self) -> int:
        return len(self._results)

    def __bool__(self) -> bool:
        return bool(self._results)
