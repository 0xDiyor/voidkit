"""Module contract v1: the base class, option system, and Result schema.

This package is the load-bearing interface between the framework core and
drop-in modules. Everything a module author needs is importable from here::

    from voidkit.contract import ModuleBase, ModuleOptions, Result, RunContext, option, record

See CONTRIBUTING.md for the authoring guide.
"""

from voidkit.contract.base import ModuleBase, RunContext
from voidkit.contract.options import (
    InvalidOptionValueError,
    ModuleOptions,
    OptionError,
    OptionSpec,
    OptionValidationError,
    UnknownOptionError,
    option,
)
from voidkit.contract.result import (
    JSONValue,
    Record,
    Result,
    ResultError,
    ResultStatus,
    record,
    utc_now,
)

__all__ = [
    "InvalidOptionValueError",
    "JSONValue",
    "ModuleBase",
    "ModuleOptions",
    "OptionError",
    "OptionSpec",
    "OptionValidationError",
    "Record",
    "Result",
    "ResultError",
    "ResultStatus",
    "RunContext",
    "UnknownOptionError",
    "option",
    "record",
    "utc_now",
]
