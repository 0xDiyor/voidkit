"""Loader tests: discovery, addressing, and graceful handling of bad modules."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from conftest import ECHO_MODULE, SAMPLE_MODULE, write_module

from voidkit.contract import ModuleBase
from voidkit.loader import ModuleLoader, UnknownModuleError


class TestDiscovery:
    def test_list_modules_returns_sorted_triples(self, loader: ModuleLoader):
        assert loader.list_modules() == [
            ("analysis", "crash", "Always raises, to prove a module crash becomes an error Result."),
            ("analysis", "echo", "Echo a message back as a record."),
            ("recon", "sample", "Toy recon module (no network)."),
        ]

    def test_get_module_returns_the_class_not_an_instance(self, loader: ModuleLoader):
        cls = loader.get_module("recon/sample")
        assert isinstance(cls, type)
        assert issubclass(cls, ModuleBase)
        assert cls.name == "sample" and cls.category == "recon"
        # It is the class: the caller instantiates it.
        instance = cls()
        assert instance.full_name == "recon/sample"

    def test_addresses_lists_every_discovered_address(self, loader: ModuleLoader):
        assert loader.addresses() == ["analysis/crash", "analysis/echo", "recon/sample"]

    def test_unknown_module_raises_with_known_list(self, loader: ModuleLoader):
        with pytest.raises(UnknownModuleError) as excinfo:
            loader.get_module("recon/nope")
        assert "recon/nope" in str(excinfo.value)
        assert "recon/sample" in str(excinfo.value)

    def test_address_follows_declared_attributes_not_the_path(self, tmp_path: Path):
        # File lives under intel/ but the class declares category "recon".
        write_module(tmp_path, "intel", "misfiled", SAMPLE_MODULE)
        loader = ModuleLoader(tmp_path)
        assert loader.addresses() == ["recon/sample"]  # declared category wins


class TestResilience:
    def test_syntax_error_module_is_skipped_others_load(self, tmp_path: Path):
        write_module(tmp_path, "analysis", "echo", ECHO_MODULE)
        write_module(tmp_path, "recon", "broken", "def run(:\n  pass\n")
        loader = ModuleLoader(tmp_path)
        assert loader.addresses() == ["analysis/echo"]

    def test_import_error_module_is_skipped(self, tmp_path: Path):
        write_module(tmp_path, "analysis", "echo", ECHO_MODULE)
        write_module(tmp_path, "recon", "bad_import", "import a_package_that_does_not_exist\n")
        loader = ModuleLoader(tmp_path)
        assert loader.addresses() == ["analysis/echo"]

    def test_file_without_a_module_class_is_ignored(self, tmp_path: Path):
        write_module(tmp_path, "analysis", "echo", ECHO_MODULE)
        write_module(tmp_path, "misc", "helpers", "X = 1\n\ndef helper():\n    return X\n")
        loader = ModuleLoader(tmp_path)
        assert loader.addresses() == ["analysis/echo"]

    def test_abstract_subclass_is_not_registered(self, tmp_path: Path):
        source = """
            from voidkit.contract import ModuleBase

            class HalfBaked(ModuleBase):
                name = "half"
                category = "analysis"
                # no run() override -> still abstract, cannot be a real module
        """
        write_module(tmp_path, "analysis", "half", textwrap.dedent(source))
        loader = ModuleLoader(tmp_path)
        assert loader.addresses() == []

    def test_underscore_and_dot_files_are_skipped(self, tmp_path: Path):
        write_module(tmp_path, "analysis", "echo", ECHO_MODULE)
        # A private helper file that happens to define a module is not discovered.
        write_module(tmp_path, "analysis", "_private", ECHO_MODULE)
        loader = ModuleLoader(tmp_path)
        assert loader.addresses() == ["analysis/echo"]

    def test_imported_module_base_is_not_registered_as_a_module(self, tmp_path: Path):
        # ECHO_MODULE imports ModuleBase; the loader must not register the base class.
        write_module(tmp_path, "analysis", "echo", ECHO_MODULE)
        loader = ModuleLoader(tmp_path)
        addresses = loader.addresses()
        assert addresses == ["analysis/echo"]

    def test_duplicate_address_keeps_first_and_does_not_crash(self, tmp_path: Path):
        write_module(tmp_path, "recon", "sample", SAMPLE_MODULE)
        write_module(tmp_path, "recon", "sample_copy", SAMPLE_MODULE)  # same declared address
        loader = ModuleLoader(tmp_path)
        # Both files declare recon/sample; exactly one entry survives.
        assert loader.addresses() == ["recon/sample"]

    def test_missing_modules_dir_yields_no_modules(self, tmp_path: Path):
        loader = ModuleLoader(tmp_path / "does_not_exist")
        assert loader.list_modules() == []
        assert loader.addresses() == []


class TestReload:
    def test_reload_picks_up_a_newly_dropped_module(self, tmp_path: Path):
        write_module(tmp_path, "analysis", "echo", ECHO_MODULE)
        loader = ModuleLoader(tmp_path)
        assert loader.addresses() == ["analysis/echo"]

        write_module(tmp_path, "recon", "sample", SAMPLE_MODULE)
        assert loader.addresses() == ["analysis/echo"]  # cached until reload

        loader.reload()
        assert loader.addresses() == ["analysis/echo", "recon/sample"]

    def test_discovery_is_cached_between_calls(self, tmp_path: Path):
        write_module(tmp_path, "analysis", "echo", ECHO_MODULE)
        loader = ModuleLoader(tmp_path)
        first = loader.get_module("analysis/echo")
        second = loader.get_module("analysis/echo")
        assert first is second  # same class object, not re-imported each call
