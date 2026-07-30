"""Pydantic-based option declaration and validation for Void Kit modules.

Module authors declare options by subclassing :class:`ModuleOptions` and
annotating fields with :func:`option`::

    class ScanOptions(ModuleOptions):
        target: str = option(description="Target host or CIDR range.")
        port: int = option(80, description="TCP port to probe.", ge=1, le=65535)
        timing: Literal["slow", "normal", "fast"] = option(
            "normal", description="Scan timing profile."
        )

Omitting the default makes an option required. Enum and ``Literal`` annotations
give choice-style options; pydantic validates membership and :meth:`ModuleOptions.specs`
surfaces the allowed values for the shell's ``show options``.

Values arrive from the shell as strings (``set port 443``), so validation runs in
pydantic's lax mode: ``"443"`` coerces to ``443``, ``"yes"`` to ``True``, and enum
values match by value. :meth:`ModuleOptions.validate_value` checks a single option
at ``set`` time; :meth:`ModuleOptions.build` validates the full set (including
required options) just before ``run``.
"""

from __future__ import annotations

import enum
import typing
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from pydantic_core import PydanticUndefined

__all__ = [
    "InvalidOptionValueError",
    "ModuleOptions",
    "OptionError",
    "OptionSpec",
    "OptionValidationError",
    "UnknownOptionError",
    "option",
]


def option(default: Any = PydanticUndefined, *, description: str, **constraints: Any) -> Any:
    """Declare a module option field.

    Omit *default* to make the option required. *description* is mandatory: it is
    what the operator sees in ``show options``. Extra keyword arguments (``ge``,
    ``le``, ``min_length``, ...) pass through to :func:`pydantic.Field`.
    """
    return Field(default, description=description, **constraints)


class OptionError(ValueError):
    """Base class for option-related errors."""


class UnknownOptionError(OptionError):
    """Raised when setting an option name the module does not declare."""

    def __init__(self, name: str, valid_names: typing.Iterable[str]) -> None:
        self.name = name
        self.valid_names = tuple(valid_names)
        hint = ", ".join(self.valid_names) or "<none>"
        super().__init__(f"unknown option '{name}' (valid options: {hint})")


class InvalidOptionValueError(OptionError):
    """Raised when a single option value fails validation at ``set`` time."""

    def __init__(self, name: str, value: Any, reason: str) -> None:
        self.name = name
        self.value = value
        self.reason = reason
        super().__init__(f"invalid value for option '{name}': {reason}")


class OptionValidationError(OptionError):
    """Raised when the full option set fails validation before ``run``.

    ``problems`` holds one user-friendly message per failing option.
    """

    def __init__(self, problems: typing.Iterable[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class OptionSpec:
    """Shell-facing description of one option, for ``show options``."""

    name: str
    type: str
    required: bool
    default: Any
    description: str
    choices: tuple[Any, ...] | None = None


def _choices_for(annotation: Any) -> tuple[Any, ...] | None:
    if typing.get_origin(annotation) is Literal:
        return typing.get_args(annotation)
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return tuple(member.value for member in annotation)
    return None


def _type_name(annotation: Any) -> str:
    if _choices_for(annotation) is not None:
        return "choice"
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


# Single-field TypeAdapters are expensive to build; cache them per (model, field).
_ADAPTERS: dict[tuple[type, str], TypeAdapter[Any]] = {}


class ModuleOptions(BaseModel):
    """Base class for a module's option set. Subclass and declare fields with option()."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @classmethod
    def option_names(cls) -> tuple[str, ...]:
        return tuple(cls.model_fields)

    @classmethod
    def required_options(cls) -> tuple[str, ...]:
        return tuple(name for name, field in cls.model_fields.items() if field.is_required())

    @classmethod
    def specs(cls) -> tuple[OptionSpec, ...]:
        specs = []
        for name, field in cls.model_fields.items():
            default = field.get_default(call_default_factory=True)
            specs.append(
                OptionSpec(
                    name=name,
                    type=_type_name(field.annotation),
                    required=field.is_required(),
                    default=None if default is PydanticUndefined else default,
                    description=field.description or "",
                    choices=_choices_for(field.annotation),
                )
            )
        return tuple(specs)

    @classmethod
    def validate_value(cls, name: str, value: Any) -> Any:
        """Validate and coerce a single option value; the shell calls this on ``set``."""
        field = cls.model_fields.get(name)
        if field is None:
            raise UnknownOptionError(name, cls.option_names())
        key = (cls, name)
        adapter = _ADAPTERS.get(key)
        if adapter is None:
            annotation = field.annotation
            for meta in field.metadata:  # re-attach Field constraints (ge, le, ...)
                annotation = Annotated[annotation, meta]
            adapter = _ADAPTERS[key] = TypeAdapter(annotation)
        try:
            return adapter.validate_python(value)
        except ValidationError as exc:
            raise InvalidOptionValueError(name, value, exc.errors()[0]["msg"]) from exc

    @classmethod
    def build(cls, values: dict[str, Any]) -> Self:
        """Validate the full option set, raising OptionValidationError with friendly messages."""
        try:
            return cls.model_validate(dict(values))
        except ValidationError as exc:
            problems = []
            for err in exc.errors():
                loc = ".".join(str(part) for part in err["loc"]) or "<options>"
                top = str(err["loc"][0]) if err["loc"] else ""
                field = cls.model_fields.get(top)
                if err["type"] == "missing":
                    description = field.description if field is not None else ""
                    suffix = f" ({description})" if description else ""
                    problems.append(f"missing required option '{loc}'{suffix}")
                else:
                    problems.append(f"invalid value for option '{loc}': {err['msg']}")
            raise OptionValidationError(problems) from exc
