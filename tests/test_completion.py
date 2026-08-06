"""Tab-completion tests: context-sensitive candidates for the shell."""

from __future__ import annotations

from prompt_toolkit.document import Document

from voidkit.completion import VoidkitCompleter
from voidkit.shell import Shell


def complete(shell: Shell, text: str) -> list[str]:
    completer = VoidkitCompleter(shell)
    document = Document(text, len(text))
    return [c.text for c in completer.get_completions(document, None)]


class TestCommandCompletion:
    def test_empty_line_offers_all_commands(self, shell: Shell):
        candidates = complete(shell, "")
        assert "use" in candidates and "run" in candidates and "show" in candidates

    def test_prefix_narrows_commands(self, shell: Shell):
        assert complete(shell, "s") == ["set", "show"]


class TestArgumentCompletion:
    def test_use_completes_module_addresses(self, shell: Shell):
        candidates = complete(shell, "use ")
        assert candidates == ["analysis/crash", "analysis/echo", "recon/sample"]

    def test_use_prefix_narrows_addresses(self, shell: Shell):
        assert complete(shell, "use recon/") == ["recon/sample"]

    def test_show_completes_subcommands(self, shell: Shell):
        assert complete(shell, "show ") == ["options", "modules", "results"]

    def test_set_completes_selected_module_option_names(self, shell: Shell):
        shell.dispatch("use analysis/echo")
        assert complete(shell, "set ") == ["message", "mode"]

    def test_set_prefix_narrows_option_names(self, shell: Shell):
        shell.dispatch("use analysis/echo")
        assert complete(shell, "set me") == ["message"]

    def test_unset_completes_option_names(self, shell: Shell):
        shell.dispatch("use analysis/echo")
        assert complete(shell, "unset ") == ["message", "mode"]

    def test_set_without_selected_module_offers_nothing(self, shell: Shell):
        assert complete(shell, "set ") == []

    def test_no_completion_for_option_values(self, shell: Shell):
        shell.dispatch("use analysis/echo")
        # Third token (the value) has no candidates.
        assert complete(shell, "set message ") == []
