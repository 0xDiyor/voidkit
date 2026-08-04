"""Module loader: discovers drop-in :class:`ModuleBase` subclasses on disk.

On-disk layout
--------------

Modules live under a *modules directory* (``modules/`` by default), one file per
module, grouped into category subdirectories::

    modules/
        recon/
            port_scan.py      # defines a ModuleBase subclass, addressed recon/port_scan
            dns_enum.py
        analysis/
            log_parse.py

Each ``.py`` file defines exactly one concrete :class:`ModuleBase` subclass. The
address the shell uses (``category/name``) comes from the module's declared
``category`` and ``name`` class attributes, not from the file path. The directory
layout is a convention for humans, and the loader warns when a file sits in a
category directory whose name disagrees with the module's declared ``category``.

Dropping in a new module is therefore: create ``modules/<category>/<name>.py``,
subclass :class:`ModuleBase`, set ``name``/``category``/``description`` and an
``options_model``, implement ``run``. No registration step; discovery finds it.

Robustness
----------

Discovery never crashes on a bad module. A file that fails to import (syntax
error, bad dependency), defines no concrete module, or collides with an address
already claimed is skipped with a structlog warning; the rest still load.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path

import structlog

from voidkit.contract import ModuleBase

__all__ = [
    "LoaderError",
    "ModuleInfo",
    "ModuleLoader",
    "UnknownModuleError",
]

_log = structlog.get_logger("voidkit.loader")

# Files that are never modules: package plumbing and private/helper files.
_SKIP_PREFIXES = ("_", ".")


class LoaderError(Exception):
    """Base class for loader errors."""


class UnknownModuleError(LoaderError):
    """Raised by :meth:`ModuleLoader.get_module` for an address that was not discovered."""

    def __init__(self, address: str, known: list[str]) -> None:
        self.address = address
        self.known = known
        hint = ", ".join(known) or "<none discovered>"
        super().__init__(f"unknown module '{address}' (known modules: {hint})")


@dataclass(frozen=True)
class ModuleInfo:
    """One discovered module: its address, description, and the class to instantiate."""

    category: str
    name: str
    description: str
    cls: type[ModuleBase]

    @property
    def address(self) -> str:
        return f"{self.category}/{self.name}"


class ModuleLoader:
    """Discovers and addresses modules under a modules directory.

    Discovery is lazy and cached: the first call to :meth:`list_modules` or
    :meth:`get_module` scans the tree. Call :meth:`reload` to rescan (e.g. after
    dropping in a new module during a session).
    """

    def __init__(self, modules_dir: str | Path) -> None:
        self.modules_dir = Path(modules_dir)
        self._registry: dict[str, ModuleInfo] | None = None

    # -- discovery -------------------------------------------------------------

    def reload(self) -> None:
        """Discard the cache so the next access rescans the modules directory."""
        self._registry = None

    def _ensure_discovered(self) -> dict[str, ModuleInfo]:
        if self._registry is None:
            self._registry = self._discover()
        return self._registry

    def _discover(self) -> dict[str, ModuleInfo]:
        registry: dict[str, ModuleInfo] = {}
        if not self.modules_dir.is_dir():
            _log.warning("loader.modules_dir_missing", path=str(self.modules_dir))
            return registry

        for path in sorted(self.modules_dir.rglob("*.py")):
            if path.name.startswith(_SKIP_PREFIXES):
                continue
            self._load_file(path, registry)

        _log.info("loader.discovered", count=len(registry), path=str(self.modules_dir))
        return registry

    def _load_file(self, path: Path, registry: dict[str, ModuleInfo]) -> None:
        module = self._import_file(path)
        if module is None:
            return
        for cls in self._module_classes(module):
            self._register(cls, path, registry)

    def _import_file(self, path: Path):
        """Import a single file in isolation; return the module object or None on failure."""
        # A synthetic, path-derived module name keeps re-discovery idempotent and
        # avoids clobbering unrelated entries in sys.modules.
        try:
            rel = path.relative_to(self.modules_dir).with_suffix("")
            synthetic = "voidkit._loaded_modules." + ".".join(rel.parts)
        except ValueError:
            synthetic = "voidkit._loaded_modules." + path.stem

        spec = importlib.util.spec_from_file_location(synthetic, path)
        if spec is None or spec.loader is None:
            _log.warning("loader.unimportable", path=str(path))
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[synthetic] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 (one bad module must not break discovery)
            sys.modules.pop(synthetic, None)
            _log.warning(
                "loader.import_failed",
                path=str(path),
                error=str(exc),
                exception_type=type(exc).__name__,
            )
            return None
        return module

    @staticmethod
    def _module_classes(module) -> list[type[ModuleBase]]:
        """Concrete ModuleBase subclasses *defined in* this file (not imported ones)."""
        found = []
        for obj in vars(module).values():
            if not inspect.isclass(obj):
                continue
            if not issubclass(obj, ModuleBase) or obj is ModuleBase:
                continue
            if obj.__module__ != module.__name__:  # skip imported bases like ModuleBase
                continue
            if inspect.isabstract(obj):
                continue
            found.append(obj)
        return found

    def _register(
        self, cls: type[ModuleBase], path: Path, registry: dict[str, ModuleInfo]
    ) -> None:
        if not cls.name or not cls.category:
            _log.warning("loader.missing_address", path=str(path), cls=cls.__name__)
            return
        address = f"{cls.category}/{cls.name}"

        if address in registry:
            _log.warning(
                "loader.duplicate_address",
                address=address,
                kept=registry[address].cls.__name__,
                skipped=cls.__name__,
                path=str(path),
            )
            return

        declared_dir = path.parent.name
        if declared_dir != cls.category and path.parent != self.modules_dir:
            _log.warning(
                "loader.category_mismatch",
                address=address,
                directory=declared_dir,
                declared_category=cls.category,
                path=str(path),
            )

        registry[address] = ModuleInfo(
            category=cls.category,
            name=cls.name,
            description=cls.description,
            cls=cls,
        )

    # -- public API ------------------------------------------------------------

    def list_modules(self) -> list[tuple[str, str, str]]:
        """All discovered modules as ``(category, name, description)``, sorted by address."""
        registry = self._ensure_discovered()
        return [
            (info.category, info.name, info.description)
            for info in sorted(registry.values(), key=lambda i: i.address)
        ]

    def addresses(self) -> list[str]:
        """Every discovered ``category/name`` address, sorted (used by tab completion)."""
        return sorted(self._ensure_discovered())

    def get_info(self, address: str) -> ModuleInfo:
        """The :class:`ModuleInfo` for an address, or raise :class:`UnknownModuleError`."""
        registry = self._ensure_discovered()
        info = registry.get(address)
        if info is None:
            raise UnknownModuleError(address, sorted(registry))
        return info

    def get_module(self, address: str) -> type[ModuleBase]:
        """The module *class* for ``category/name`` (not an instance).

        Raises :class:`UnknownModuleError` if nothing was discovered at that address.
        """
        return self.get_info(address).cls
