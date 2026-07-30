"""Contract tests: option declaration, coercion, and validation."""

import enum
from typing import Literal

import pytest

from voidkit.contract import (
    InvalidOptionValueError,
    ModuleOptions,
    OptionValidationError,
    UnknownOptionError,
    option,
)


class Protocol(enum.Enum):
    TCP = "tcp"
    UDP = "udp"


class ScanOptions(ModuleOptions):
    target: str = option(description="Target host or CIDR range.")
    port: int = option(80, description="TCP port to probe.", ge=1, le=65535)
    verbose: bool = option(False, description="Emit per-host detail.")
    timing: Literal["slow", "normal", "fast"] = option("normal", description="Scan timing profile.")
    protocol: Protocol = option(Protocol.TCP, description="Transport protocol.")


class TestBuild:
    def test_defaults_apply_when_only_required_given(self):
        opts = ScanOptions.build({"target": "10.0.0.0/24"})
        assert opts.target == "10.0.0.0/24"
        assert opts.port == 80
        assert opts.verbose is False
        assert opts.timing == "normal"
        assert opts.protocol is Protocol.TCP

    def test_missing_required_option_fails_with_friendly_message(self):
        with pytest.raises(OptionValidationError) as excinfo:
            ScanOptions.build({})
        assert len(excinfo.value.problems) == 1
        message = excinfo.value.problems[0]
        assert "missing required option 'target'" in message
        assert "Target host or CIDR range." in message

    def test_all_problems_reported_at_once(self):
        with pytest.raises(OptionValidationError) as excinfo:
            ScanOptions.build({"port": "not_a_port", "timing": "warp"})
        joined = str(excinfo.value)
        assert "target" in joined
        assert "port" in joined
        assert "timing" in joined

    def test_unknown_option_rejected(self):
        with pytest.raises(OptionValidationError) as excinfo:
            ScanOptions.build({"target": "10.0.0.1", "threads": 4})
        assert "threads" in str(excinfo.value)

    def test_empty_options_model_builds_from_nothing(self):
        assert isinstance(ModuleOptions.build({}), ModuleOptions)


class TestSetTimeValidation:
    """validate_value backs the shell's `set <name> <value>`, so strings must coerce."""

    def test_string_coerces_to_int(self):
        assert ScanOptions.validate_value("port", "443") == 443

    def test_string_coerces_to_bool(self):
        assert ScanOptions.validate_value("verbose", "yes") is True
        assert ScanOptions.validate_value("verbose", "false") is False

    def test_enum_matches_by_value(self):
        assert ScanOptions.validate_value("protocol", "udp") is Protocol.UDP

    def test_literal_choice_accepted(self):
        assert ScanOptions.validate_value("timing", "fast") == "fast"

    def test_literal_choice_rejected(self):
        with pytest.raises(InvalidOptionValueError):
            ScanOptions.validate_value("timing", "warp")

    def test_bad_type_rejected_with_reason(self):
        with pytest.raises(InvalidOptionValueError) as excinfo:
            ScanOptions.validate_value("port", "http")
        assert excinfo.value.name == "port"
        assert excinfo.value.value == "http"

    def test_field_constraints_enforced_at_set_time(self):
        with pytest.raises(InvalidOptionValueError):
            ScanOptions.validate_value("port", 0)
        with pytest.raises(InvalidOptionValueError):
            ScanOptions.validate_value("port", 70000)

    def test_unknown_name_lists_valid_options(self):
        with pytest.raises(UnknownOptionError) as excinfo:
            ScanOptions.validate_value("prot", "tcp")
        assert excinfo.value.name == "prot"
        assert "protocol" in str(excinfo.value)


class TestIntrospection:
    def test_required_options(self):
        assert ScanOptions.required_options() == ("target",)

    def test_option_names_preserve_declaration_order(self):
        assert ScanOptions.option_names() == ("target", "port", "verbose", "timing", "protocol")

    def test_specs_expose_shell_facing_metadata(self):
        specs = {spec.name: spec for spec in ScanOptions.specs()}

        assert specs["target"].required is True
        assert specs["target"].default is None
        assert specs["target"].type == "str"
        assert specs["target"].description == "Target host or CIDR range."

        assert specs["port"].required is False
        assert specs["port"].default == 80
        assert specs["port"].type == "int"

        assert specs["timing"].type == "choice"
        assert specs["timing"].choices == ("slow", "normal", "fast")

        assert specs["protocol"].type == "choice"
        assert specs["protocol"].choices == ("tcp", "udp")

    def test_empty_base_model_has_no_options(self):
        assert ModuleOptions.specs() == ()
        assert ModuleOptions.required_options() == ()
