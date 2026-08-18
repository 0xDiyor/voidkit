"""Tab completion for the shell.

Completion is context-sensitive on the command being typed:

- first word            -> command names
- ``use <TAB>``         -> discovered module addresses (``category/name``)
- ``set``/``unset``     -> the selected module's option names
- ``show <TAB>``        -> the ``show`` subcommands
- ``chain <TAB>``       -> the ``chain`` subcommands
- ``chain from <TAB>``  -> chainable module addresses and stored result ids
- ``load``/``save``     -> saved session names on disk

The completer reads live state off the :class:`~voidkit.shell.Shell` (the current
module, the loader's discovered addresses) so it always reflects what is loaded.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from prompt_toolkit.completion import Completer, Completion

from voidkit.shell import CHAIN_SUBCOMMANDS, COMMANDS, SHOW_SUBCOMMANDS

if TYPE_CHECKING:
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

    from voidkit.shell import Shell

__all__ = ["VoidkitCompleter"]


class VoidkitCompleter(Completer):
    def __init__(self, shell: Shell) -> None:
        self.shell = shell

    def _candidates(self, parts: list[str]) -> Iterable[str]:
        if len(parts) <= 1:
            return COMMANDS
        if len(parts) == 2:
            command = parts[0]
            if command == "use":
                return self.shell.loader.addresses()
            if command in ("set", "unset"):
                return self.shell.current_option_names()
            if command == "show":
                return SHOW_SUBCOMMANDS
            if command == "chain":
                return CHAIN_SUBCOMMANDS
            if command in ("load", "save"):
                return self.shell.saved_session_names()
        if len(parts) == 3 and parts[0] == "chain" and parts[1] == "from":
            return self.shell.chain_candidates()
        return ()

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text = document.text_before_cursor.lstrip()
        parts = text.split(" ") if text else [""]
        word = parts[-1]
        for candidate in self._candidates(parts):
            if candidate.startswith(word):
                yield Completion(candidate, start_position=-len(word))
