"""The Result schema: the machine-consumable output contract for Void Kit modules.

Every module run produces exactly one :class:`Result`. The schema is strictly
JSON-serializable (enforced by the :data:`JSONValue` type) because three later
phases consume it verbatim:

- the result store (``show results``, Phase 2),
- session save/load to JSON (Phase 4), via :meth:`Result.to_dict` / :meth:`Result.from_dict`,
- module chaining (Phase 4), via typed :class:`Record` entries and the ``keys`` mapping.

Chaining model: a module emits its findings as records, each with a snake_case
``type`` naming the kind of thing found (``"host"``, ``"port"``, ``"domain"``) and a
flat ``fields`` mapping. A downstream module selects what it needs with
:meth:`Result.records_of` or :meth:`Result.values`, e.g. feeding ``port_scan``
hosts into ``dns_enum``::

    addresses = upstream.values("host", "address")

``keys`` carries scalar, run-level outputs (counts, derived values) that don't
belong to any single record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypeAliasType

__all__ = [
    "JSONValue",
    "Record",
    "Result",
    "ResultError",
    "ResultStatus",
    "record",
    "utc_now",
]

# Strictly-JSON value type: anything a Result carries must survive a JSON round
# trip, so session files and chained reads never meet a non-serializable object.
JSONValue = TypeAliasType(
    "JSONValue",
    "str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ResultStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    PARTIAL = "partial"


class Record(BaseModel):
    """One typed finding: the unit of module chaining.

    ``type`` is a snake_case kind ("host", "port", "ioc"); ``fields`` holds the
    finding's data under stable, documented field names.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    fields: dict[str, JSONValue] = Field(default_factory=dict)


def record(record_type: str, **fields: Any) -> Record:
    """Convenience constructor: ``record("host", address="10.0.0.1", state="up")``."""
    return Record(type=record_type, fields=fields)


class ResultError(BaseModel):
    """One failure attached to an error or partial result."""

    model_config = ConfigDict(extra="forbid")

    message: str
    kind: str = "error"
    detail: dict[str, JSONValue] = Field(default_factory=dict)


class Result(BaseModel):
    """The output of one module run. See the module docstring for the chaining model."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: int = 1
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    module: str
    category: str
    status: ResultStatus
    started_at: datetime
    finished_at: datetime | None = None
    summary: str = ""
    options: dict[str, JSONValue] = Field(default_factory=dict)
    keys: dict[str, JSONValue] = Field(default_factory=dict)
    records: list[Record] = Field(default_factory=list)
    errors: list[ResultError] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_matches_errors(self) -> Self:
        if self.status is ResultStatus.OK and self.errors:
            raise ValueError("an 'ok' result must not carry errors; use 'partial' or 'error'")
        if self.status is not ResultStatus.OK and not self.errors:
            raise ValueError(
                f"a '{self.status.value}' result must carry at least one error explaining it"
            )
        return self

    @property
    def module_path(self) -> str:
        """The category/module_name address, e.g. ``recon/port_scan``."""
        return f"{self.category}/{self.module}"

    def records_of(self, record_type: str) -> list[Record]:
        """All records of the given type; the coarse chaining selector."""
        return [rec for rec in self.records if rec.type == record_type]

    def values(self, record_type: str, field_name: str) -> list[Any]:
        """One field across all records of a type; records lacking the field are skipped.

        This is the fine-grained chaining read: ``values("host", "address")``
        yields the list a downstream module consumes.
        """
        return [
            rec.fields[field_name]
            for rec in self.records_of(record_type)
            if field_name in rec.fields
        ]

    def to_dict(self) -> dict[str, Any]:
        """Dump to plain JSON-compatible types (datetimes become ISO 8601 strings)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> Self:
        return cls.model_validate_json(data)
