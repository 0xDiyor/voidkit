"""ModuleBase: the class every Void Kit module implements, plus its run context.

A minimal module::

    class PingOptions(ModuleOptions):
        target: str = option(description="Host to ping.")

    class Ping(ModuleBase):
        name = "ping"
        category = "recon"
        description = "ICMP reachability check."
        options_model = PingOptions

        def run(self, context: RunContext) -> Result:
            up = probe(self.opts.target)
            return self.ok(
                records=[record("host", address=self.opts.target, state="up" if up else "down")],
                summary=f"{self.opts.target} is {'up' if up else 'down'}",
            )

The shell drives the same lifecycle a test does: construct, ``set_option`` as the
operator types ``set``, then ``execute()``, which validates the full option set
(raising :class:`OptionValidationError` before any work happens), binds the
validated model to ``self.opts``, calls ``run``, and converts an uncaught
exception into an error :class:`Result` so a buggy module cannot crash the shell.

Modules log to the operator audit trail via ``self.log`` (structlog, bound to the
module address); user-facing shell output is rich's job, elsewhere. ``run`` never
prints.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

import structlog

from voidkit.contract.options import ModuleOptions, OptionSpec, UnknownOptionError
from voidkit.contract.result import Record, Result, ResultError, ResultStatus, utc_now

__all__ = ["ModuleBase", "RunContext"]

_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")


@dataclass
class RunContext:
    """Execution context handed to :meth:`ModuleBase.run`.

    ``upstream`` carries the previous module's :class:`Result` when running in a
    chain (Phase 4); standalone runs leave it ``None``. ``data`` is a scratch
    mapping for shell- or session-provided extras the contract does not model yet.
    """

    upstream: Result | None = None
    data: dict[str, Any] = field(default_factory=dict)
    logger: Any = None

    def __post_init__(self) -> None:
        if self.logger is None:
            self.logger = structlog.get_logger("voidkit.module")


class ModuleBase(ABC):
    """Base class for all Void Kit modules, addressed as ``category/name``."""

    name: ClassVar[str] = ""
    category: ClassVar[str] = ""
    description: ClassVar[str] = ""
    options_model: ClassVar[type[ModuleOptions]] = ModuleOptions

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for attr in ("name", "category"):
            value = getattr(cls, attr, "")
            if value and not _NAME_RE.fullmatch(value):
                raise TypeError(
                    f"{cls.__name__}.{attr} must be snake_case ([a-z][a-z0-9_]*), got {value!r}"
                )
        if not issubclass(cls.options_model, ModuleOptions):
            raise TypeError(f"{cls.__name__}.options_model must subclass ModuleOptions")

    def __init__(self, **options: Any) -> None:
        if not self.name or not self.category:
            raise TypeError(
                f"{type(self).__name__} must define non-empty 'name' and 'category' "
                "class attributes"
            )
        self._option_values: dict[str, Any] = {}
        self._started_at = None
        self.opts: ModuleOptions | None = None
        self.log = structlog.get_logger("voidkit.module").bind(module=self.full_name)
        for name, value in options.items():
            self.set_option(name, value)

    @property
    def full_name(self) -> str:
        """The ``category/module_name`` address, e.g. ``recon/port_scan``."""
        return f"{self.category}/{self.name}"

    # -- options ---------------------------------------------------------------

    def set_option(self, name: str, value: Any) -> None:
        """Set one option, validating and coercing immediately (shell ``set``)."""
        self._option_values[name] = self.options_model.validate_value(name, value)

    def unset_option(self, name: str) -> None:
        """Clear one option back to its default / unset state (shell ``unset``)."""
        if name not in self.options_model.model_fields:
            raise UnknownOptionError(name, self.options_model.option_names())
        self._option_values.pop(name, None)

    @property
    def option_values(self) -> dict[str, Any]:
        """A copy of the currently-set option values."""
        return dict(self._option_values)

    def validate_options(self) -> ModuleOptions:
        """Validate the full option set and bind it to ``self.opts``.

        Raises :class:`OptionValidationError` listing every missing or invalid option.
        """
        self.opts = self.options_model.build(self._option_values)
        return self.opts

    @classmethod
    def required_options(cls) -> tuple[str, ...]:
        return cls.options_model.required_options()

    @classmethod
    def option_specs(cls) -> tuple[OptionSpec, ...]:
        return cls.options_model.specs()

    # -- execution -------------------------------------------------------------

    @abstractmethod
    def run(self, context: RunContext) -> Result:
        """Do the module's work and return a Result.

        Called by :meth:`execute` with ``self.opts`` already validated. Build the
        return value with :meth:`ok`, :meth:`partial`, or :meth:`error` so the
        module address, timestamps, and options snapshot are filled in.
        """

    def execute(self, context: RunContext | None = None) -> Result:
        """Validate options, run the module, and guarantee a well-formed Result.

        Option problems raise :class:`OptionValidationError` before any work
        happens; an exception escaping ``run`` becomes an error Result instead
        of propagating.
        """
        options = self.validate_options()
        if context is None:
            context = RunContext(logger=self.log)
        self._started_at = utc_now()
        self.log.info(
            "module.started",
            category=self.category,
            options=options.model_dump(mode="json"),
        )
        try:
            result = self.run(context)
        except Exception as exc:  # noqa: BLE001 (a buggy module must not crash the shell)
            self.log.error(
                "module.crashed",
                error=str(exc),
                exception_type=type(exc).__name__,
            )
            return self.error(
                f"unhandled exception in {self.full_name}: {exc}",
                kind="exception",
                detail={"exception_type": type(exc).__name__},
            )
        if not isinstance(result, Result):
            raise TypeError(
                f"{self.full_name}.run() must return a Result, got {type(result).__name__}"
            )
        self.log.info(
            "module.finished",
            status=result.status.value,
            records=len(result.records),
        )
        return result

    # -- result builders -------------------------------------------------------

    def ok(
        self,
        *,
        records: Any = (),
        keys: dict[str, Any] | None = None,
        summary: str = "",
    ) -> Result:
        return self._build_result(
            ResultStatus.OK, records=records, keys=keys, summary=summary, errors=()
        )

    def partial(
        self,
        *,
        errors: Any,
        records: Any = (),
        keys: dict[str, Any] | None = None,
        summary: str = "",
    ) -> Result:
        return self._build_result(
            ResultStatus.PARTIAL, records=records, keys=keys, summary=summary, errors=errors
        )

    def error(
        self,
        message: str | None = None,
        *,
        errors: Any = (),
        kind: str = "error",
        detail: dict[str, Any] | None = None,
        summary: str = "",
    ) -> Result:
        errs = list(errors)
        if message is not None:
            errs.insert(0, ResultError(message=message, kind=kind, detail=detail or {}))
        return self._build_result(
            ResultStatus.ERROR, records=(), keys=None, summary=summary, errors=errs
        )

    def _build_result(
        self,
        status: ResultStatus,
        *,
        records: Any,
        keys: dict[str, Any] | None,
        summary: str,
        errors: Any,
    ) -> Result:
        now = utc_now()
        return Result(
            module=self.name,
            category=self.category,
            status=status,
            started_at=self._started_at or now,
            finished_at=now,
            summary=summary,
            options=self.opts.model_dump(mode="json") if self.opts is not None else {},
            keys=dict(keys or {}),
            records=[r if isinstance(r, Record) else Record.model_validate(r) for r in records],
            errors=[
                e if isinstance(e, ResultError) else ResultError.model_validate(e) for e in errors
            ],
        )
