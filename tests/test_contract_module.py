"""Contract tests: ModuleBase lifecycle, pinned by a toy example module.

EchoModule is the reference implementation of the contract: if these tests pass,
a module author can build against ModuleBase with no shell present.
"""

from typing import Literal

import pytest

from voidkit.contract import (
    ModuleBase,
    ModuleOptions,
    OptionValidationError,
    Result,
    ResultStatus,
    RunContext,
    UnknownOptionError,
    option,
    record,
    utc_now,
)


class EchoOptions(ModuleOptions):
    message: str = option(description="Text to echo back.")
    repeat: int = option(1, description="How many times to repeat the message.", ge=1)
    mode: Literal["plain", "upper"] = option("plain", description="Output transformation.")


class EchoModule(ModuleBase):
    name = "echo"
    category = "analysis"
    description = "Echo a message back as records (contract reference module)."
    options_model = EchoOptions

    def run(self, context: RunContext) -> Result:
        text = self.opts.message.upper() if self.opts.mode == "upper" else self.opts.message
        records = [record("message", text=text, index=i) for i in range(self.opts.repeat)]
        return self.ok(
            records=records,
            keys={"length": len(text)},
            summary=f"echoed {self.opts.repeat} time(s)",
        )


class CrashingModule(ModuleBase):
    name = "crash"
    category = "analysis"
    description = "Always raises, to pin execute()'s error handling."

    def run(self, context: RunContext) -> Result:
        raise RuntimeError("kaboom")


class HostCountModule(ModuleBase):
    """Toy downstream module: consumes an upstream result via the chaining reads."""

    name = "host_count"
    category = "analysis"
    description = "Count host records in the upstream result."

    def run(self, context: RunContext) -> Result:
        if context.upstream is None:
            return self.error("no upstream result to consume")
        addresses = context.upstream.values("host", "address")
        return self.ok(
            records=[record("stat", metric="host_count", value=len(addresses))],
            keys={"host_count": len(addresses), "source_result": context.upstream.id},
            summary=f"{len(addresses)} hosts from {context.upstream.module_path}",
        )


class TestClassContract:
    def test_full_name_is_category_slash_name(self):
        assert EchoModule(message="hi").full_name == "analysis/echo"

    def test_non_snake_case_name_rejected_at_class_creation(self):
        with pytest.raises(TypeError, match="snake_case"):

            class BadName(ModuleBase):
                name = "Bad-Name"
                category = "analysis"

                def run(self, context):
                    raise NotImplementedError

    def test_instantiating_without_name_and_category_rejected(self):
        class Nameless(ModuleBase):
            def run(self, context):
                raise NotImplementedError

        with pytest.raises(TypeError, match="name"):
            Nameless()

    def test_wrong_options_model_rejected(self):
        with pytest.raises(TypeError, match="options_model"):

            class BadOptions(ModuleBase):
                name = "bad_options"
                category = "analysis"
                options_model = dict

                def run(self, context):
                    raise NotImplementedError

    def test_abstract_run_cannot_be_skipped(self):
        with pytest.raises(TypeError):
            ModuleBase()  # abstract

    def test_required_options_and_specs_exposed_on_the_module(self):
        assert EchoModule.required_options() == ("message",)
        assert [spec.name for spec in EchoModule.option_specs()] == ["message", "repeat", "mode"]


class TestOptionLifecycle:
    def test_init_kwargs_set_options(self):
        module = EchoModule(message="hi", repeat="3")
        assert module.option_values == {"message": "hi", "repeat": 3}

    def test_set_option_after_init(self):
        module = EchoModule()
        module.set_option("message", "hi")
        module.set_option("mode", "upper")
        assert module.validate_options().mode == "upper"

    def test_set_unknown_option_rejected(self):
        with pytest.raises(UnknownOptionError):
            EchoModule().set_option("mesage", "typo")

    def test_unset_restores_default(self):
        module = EchoModule(message="hi", repeat=5)
        module.unset_option("repeat")
        assert module.validate_options().repeat == 1

    def test_unset_required_option_blocks_execution_again(self):
        module = EchoModule(message="hi")
        module.unset_option("message")
        with pytest.raises(OptionValidationError, match="message"):
            module.execute()

    def test_execute_without_required_options_raises_before_running(self):
        with pytest.raises(OptionValidationError, match="missing required option 'message'"):
            EchoModule().execute()


class TestExecution:
    def test_execute_returns_well_formed_ok_result(self):
        before = utc_now()
        result = EchoModule(message="hello", repeat=2, mode="upper").execute()
        after = utc_now()

        assert isinstance(result, Result)
        assert result.status is ResultStatus.OK
        assert result.module == "echo"
        assert result.category == "analysis"
        assert result.module_path == "analysis/echo"
        assert before <= result.started_at <= result.finished_at <= after
        assert result.summary == "echoed 2 time(s)"
        assert result.options == {"message": "hello", "repeat": 2, "mode": "upper"}
        assert result.keys == {"length": 5}
        assert [rec.fields["text"] for rec in result.records_of("message")] == ["HELLO", "HELLO"]
        assert result.errors == []

    def test_execute_result_survives_serialization(self):
        result = EchoModule(message="hi").execute()
        assert Result.from_dict(result.to_dict()) == result

    def test_crashing_run_yields_error_result_not_exception(self):
        result = CrashingModule().execute()
        assert result.status is ResultStatus.ERROR
        assert result.module_path == "analysis/crash"
        assert result.finished_at is not None
        assert len(result.errors) == 1
        assert "kaboom" in result.errors[0].message
        assert result.errors[0].kind == "exception"
        assert result.errors[0].detail == {"exception_type": "RuntimeError"}

    def test_run_returning_non_result_is_a_contract_violation(self):
        class Rogue(ModuleBase):
            name = "rogue"
            category = "analysis"

            def run(self, context):
                return {"not": "a result"}

        with pytest.raises(TypeError, match="must return a Result"):
            Rogue().execute()


class TestChaining:
    def test_downstream_module_consumes_upstream_result(self):
        upstream = Result(
            module="port_scan",
            category="recon",
            status=ResultStatus.OK,
            started_at=utc_now(),
            records=[
                record("host", address="10.0.0.5", state="up"),
                record("host", address="10.0.0.9", state="up"),
                record("port", address="10.0.0.5", port=22),
            ],
        )

        result = HostCountModule().execute(RunContext(upstream=upstream))

        assert result.status is ResultStatus.OK
        assert result.keys == {"host_count": 2, "source_result": upstream.id}
        assert result.summary == "2 hosts from recon/port_scan"

    def test_downstream_module_without_upstream_reports_error(self):
        result = HostCountModule().execute()
        assert result.status is ResultStatus.ERROR
        assert "no upstream result" in result.errors[0].message

    def test_chain_works_across_a_serialization_boundary(self):
        upstream = Result(
            module="port_scan",
            category="recon",
            status=ResultStatus.OK,
            started_at=utc_now(),
            records=[record("host", address="10.0.0.5")],
        )
        restored = Result.from_json(upstream.to_json())
        result = HostCountModule().execute(RunContext(upstream=restored))
        assert result.keys["host_count"] == 1
