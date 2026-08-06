"""Shell tests: command dispatch driven directly, no prompt_toolkit input needed.

Every test calls :meth:`Shell.dispatch` (what the REPL loop calls per line) and
asserts on shell state, the result store, and the captured rich output.
"""

from __future__ import annotations

from voidkit.contract import ResultStatus
from voidkit.shell import Shell


def output(shell: Shell) -> str:
    return shell.console.file.getvalue()


class TestUse:
    def test_use_selects_module_and_reflects_in_prompt(self, shell: Shell):
        shell.dispatch("use recon/sample")
        assert shell.current is not None
        assert shell.current.full_name == "recon/sample"
        assert shell.prompt_text == "voidkit (recon/sample) > "
        assert "using recon/sample" in output(shell)

    def test_use_unknown_module_reports_error_and_selects_nothing(self, shell: Shell):
        shell.dispatch("use recon/nonexistent")
        assert shell.current is None
        assert "unknown module 'recon/nonexistent'" in output(shell)

    def test_use_without_argument_shows_usage(self, shell: Shell):
        shell.dispatch("use")
        assert "usage: use" in output(shell)

    def test_use_announces_required_options(self, shell: Shell):
        shell.dispatch("use recon/sample")
        assert "required options: target" in output(shell)


class TestSetUnset:
    def test_set_declared_option_updates_value(self, shell: Shell):
        shell.dispatch("use recon/sample")
        shell.dispatch("set target 10.0.0.0/24")
        assert shell.current.option_values == {"target": "10.0.0.0/24"}

    def test_set_undeclared_option_reports_friendly_error(self, shell: Shell):
        shell.dispatch("use recon/sample")
        shell.dispatch("set nope 1")
        assert "unknown option 'nope'" in output(shell)
        assert shell.current.option_values == {}

    def test_set_invalid_value_reports_friendly_error(self, shell: Shell):
        shell.dispatch("use analysis/echo")
        shell.dispatch("set mode sideways")  # not in the Literal choices
        assert "invalid value for option 'mode'" in output(shell)
        assert "mode" not in shell.current.option_values

    def test_set_without_selected_module_errors(self, shell: Shell):
        shell.dispatch("set target 10.0.0.1")
        assert "no module selected" in output(shell)

    def test_set_value_with_spaces_is_preserved(self, shell: Shell):
        shell.dispatch("use analysis/echo")
        shell.dispatch("set message hello there world")
        assert shell.current.option_values["message"] == "hello there world"

    def test_unset_restores_default(self, shell: Shell):
        shell.dispatch("use analysis/echo")
        shell.dispatch("set mode upper")
        shell.dispatch("unset mode")
        assert "mode" not in shell.current.option_values

    def test_unset_unknown_option_errors(self, shell: Shell):
        shell.dispatch("use analysis/echo")
        shell.dispatch("unset nope")
        assert "unknown option 'nope'" in output(shell)


class TestRun:
    def test_run_without_required_options_reports_and_stores_nothing(self, shell: Shell):
        shell.dispatch("use recon/sample")
        shell.dispatch("run")
        assert "missing required option 'target'" in output(shell)
        assert len(shell.store) == 0

    def test_run_ok_stores_result_and_prints_summary(self, shell: Shell):
        shell.dispatch("use recon/sample")
        shell.dispatch("set target 10.0.0.5")
        shell.dispatch("run")

        assert len(shell.store) == 1
        result = shell.store.list_results()[0]
        assert result.status is ResultStatus.OK
        assert result.module_path == "recon/sample"
        assert result.options == {"target": "10.0.0.5"}
        out = output(shell)
        assert "recon/sample" in out
        assert "1 host: 10.0.0.5" in out

    def test_run_without_selected_module_errors(self, shell: Shell):
        shell.dispatch("run")
        assert "no module selected" in output(shell)

    def test_crashing_module_yields_error_result_not_shell_crash(self, shell: Shell):
        shell.dispatch("use analysis/crash")
        shell.dispatch("run")  # must not raise
        assert len(shell.store) == 1
        result = shell.store.list_results()[0]
        assert result.status is ResultStatus.ERROR
        assert "boom" in result.errors[0].message

    def test_options_reset_between_module_selections(self, shell: Shell):
        shell.dispatch("use recon/sample")
        shell.dispatch("set target 10.0.0.5")
        shell.dispatch("use analysis/echo")  # switch modules
        assert shell.current.option_values == {}


class TestShow:
    def test_show_modules_lists_all_discovered(self, shell: Shell):
        shell.dispatch("show modules")
        out = output(shell)
        assert "recon/sample" in out
        assert "analysis/echo" in out

    def test_show_options_lists_current_module_options(self, shell: Shell):
        shell.dispatch("use analysis/echo")
        shell.dispatch("set message hi")
        shell.dispatch("show options")
        out = output(shell)
        assert "message" in out
        assert "mode" in out
        assert "hi" in out  # the set value is shown

    def test_show_options_without_module_errors(self, shell: Shell):
        shell.dispatch("show options")
        assert "no module selected" in output(shell)

    def test_show_results_empty_then_populated(self, shell: Shell):
        shell.dispatch("show results")
        assert "no results yet" in output(shell)

        shell.dispatch("use recon/sample")
        shell.dispatch("set target 10.0.0.5")
        shell.dispatch("run")
        shell.dispatch("show results")
        out = output(shell)
        assert "recon/sample" in out
        assert "ok" in out

    def test_show_unknown_subcommand_shows_usage(self, shell: Shell):
        shell.dispatch("show everything")
        assert "usage: show" in output(shell)


class TestMisc:
    def test_blank_line_is_a_noop(self, shell: Shell):
        shell.dispatch("   ")
        assert output(shell) == ""

    def test_unknown_command_reports_error(self, shell: Shell):
        shell.dispatch("frobnicate")
        assert "unknown command 'frobnicate'" in output(shell)

    def test_exit_and_quit_set_should_exit(self, loader, console):
        for word in ("exit", "quit"):
            shell = Shell(loader=loader, console=console)
            shell.dispatch(word)
            assert shell.should_exit is True

    def test_help_lists_commands(self, shell: Shell):
        shell.dispatch("help")
        out = output(shell)
        for command in ("use", "set", "run", "show", "exit"):
            assert command in out


class TestEndToEndWorkflow:
    def test_readme_workflow_runs_end_to_end(self, shell: Shell):
        # use -> set -> run -> show results, the README's canonical sequence.
        shell.dispatch("use recon/sample")
        shell.dispatch("set target 10.0.0.0/24")
        shell.dispatch("run")
        shell.dispatch("show results")

        assert len(shell.store) == 1
        result = shell.store.list_results()[0]
        assert result.status is ResultStatus.OK
        assert result.records[0].fields["address"] == "10.0.0.0/24"
        assert "recon/sample" in output(shell)
