"""The interactive ``use``/``set``/``run`` shell.

This is the Metasploit-style REPL from the README::

    voidkit > use recon/port_scan
    voidkit (recon/port_scan) > set target 10.0.0.0/24
    voidkit (recon/port_scan) > run
    voidkit (recon/port_scan) > show results

Design: command routing lives in :meth:`Shell.dispatch`, which is pure with
respect to I/O (it mutates shell state and prints via a :class:`rich.console.Console`)
and never blocks on input. The prompt_toolkit event loop in :meth:`Shell.run` is a
thin wrapper that reads a line and hands it to :meth:`dispatch`, so the whole
command surface is testable without a terminal.

Output discipline (per the contract): ``rich`` is the operator-facing channel here;
``structlog`` carries the audit trail and is emitted by the modules themselves.
A module can only ever return an error :class:`Result`; it cannot crash the shell.
"""

from __future__ import annotations

import sys

import structlog
from rich.console import Console
from rich.table import Table

from voidkit.contract import ModuleBase, OptionError, OptionValidationError, Result, ResultStatus
from voidkit.loader import ModuleLoader, UnknownModuleError
from voidkit.store import ResultStore

__all__ = ["Shell"]

_log = structlog.get_logger("voidkit.shell")

COMMANDS = ("use", "set", "unset", "show", "run", "help", "exit", "quit")
SHOW_SUBCOMMANDS = ("options", "modules", "results")

_STATUS_STYLE = {
    ResultStatus.OK: "green",
    ResultStatus.PARTIAL: "yellow",
    ResultStatus.ERROR: "red",
}


class Shell:
    """Stateful REPL over a :class:`ModuleLoader` and a :class:`ResultStore`."""

    def __init__(
        self,
        loader: ModuleLoader,
        store: ResultStore | None = None,
        console: Console | None = None,
    ) -> None:
        self.loader = loader
        self.store = store if store is not None else ResultStore()
        self.console = console if console is not None else Console()
        self.current: ModuleBase | None = None
        self.should_exit = False

    # -- prompt / completion helpers ------------------------------------------

    @property
    def prompt_text(self) -> str:
        if self.current is not None:
            return f"voidkit ({self.current.full_name}) > "
        return "voidkit > "

    def current_option_names(self) -> list[str]:
        """Option names of the selected module (for ``set``/``unset`` completion)."""
        if self.current is None:
            return []
        return [spec.name for spec in self.current.option_specs()]

    # -- output helpers --------------------------------------------------------

    def _ok(self, message: str) -> None:
        self.console.print(f"[green][+][/green] {message}")

    def _error(self, message: str) -> None:
        self.console.print(f"[red][-][/red] {message}")

    def _note(self, message: str) -> None:
        self.console.print(f"[cyan][*][/cyan] {message}")

    # -- command routing -------------------------------------------------------

    def dispatch(self, line: str) -> None:
        """Parse and execute one command line. Never raises for user error."""
        stripped = line.strip()
        if not stripped:
            return
        parts = stripped.split()
        command, args = parts[0], parts[1:]

        handler = {
            "use": self.cmd_use,
            "set": self.cmd_set,
            "unset": self.cmd_unset,
            "show": self.cmd_show,
            "run": self.cmd_run,
            "help": self.cmd_help,
            "exit": self.cmd_exit,
            "quit": self.cmd_exit,
        }.get(command)

        if handler is None:
            self._error(f"unknown command '{command}' (try 'help')")
            return
        handler(args)

    def cmd_use(self, args: list[str]) -> None:
        if len(args) != 1:
            self._error("usage: use <category/name>")
            return
        address = args[0]
        try:
            module_cls = self.loader.get_module(address)
        except UnknownModuleError as exc:
            self._error(str(exc))
            return
        self.current = module_cls()
        _log.info("shell.use", module=address)
        self._ok(f"using {address}")
        required = self.current.required_options()
        if required:
            self._note(f"required options: {', '.join(required)}  (set them, then 'run')")

    def cmd_set(self, args: list[str]) -> None:
        if self.current is None:
            self._error("no module selected; use <category/name> first")
            return
        if len(args) < 2:
            self._error("usage: set <option> <value>")
            return
        name, value = args[0], " ".join(args[1:])
        try:
            self.current.set_option(name, value)
        except OptionError as exc:
            self._error(str(exc))
            return
        self._ok(f"{name} => {value}")

    def cmd_unset(self, args: list[str]) -> None:
        if self.current is None:
            self._error("no module selected; use <category/name> first")
            return
        if len(args) != 1:
            self._error("usage: unset <option>")
            return
        name = args[0]
        try:
            self.current.unset_option(name)
        except OptionError as exc:
            self._error(str(exc))
            return
        self._ok(f"{name} unset")

    def cmd_show(self, args: list[str]) -> None:
        if len(args) != 1 or args[0] not in SHOW_SUBCOMMANDS:
            self._error(f"usage: show <{'|'.join(SHOW_SUBCOMMANDS)}>")
            return
        {
            "options": self._show_options,
            "modules": self._show_modules,
            "results": self._show_results,
        }[args[0]]()

    def cmd_run(self, args: list[str]) -> None:
        if self.current is None:
            self._error("no module selected; use <category/name> first")
            return
        try:
            result = self.current.execute()
        except OptionValidationError as exc:
            for problem in exc.problems:
                self._error(problem)
            return
        self.store.add_result(result)
        self._render_result_summary(result)

    def cmd_help(self, args: list[str]) -> None:
        table = Table(title="Commands", show_header=True, header_style="bold")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description")
        rows = [
            ("use <category/name>", "Select a module to work with."),
            ("set <option> <value>", "Set an option on the selected module."),
            ("unset <option>", "Clear an option back to its default."),
            ("show options", "Show the selected module's options and current values."),
            ("show modules", "List all discovered modules."),
            ("show results", "List results stored this session."),
            ("run", "Validate options and execute the selected module."),
            ("help", "Show this help."),
            ("exit / quit", "Leave the shell."),
        ]
        for name, desc in rows:
            table.add_row(name, desc)
        self.console.print(table)

    def cmd_exit(self, args: list[str]) -> None:
        self.should_exit = True

    # -- show renderers --------------------------------------------------------

    def _show_options(self) -> None:
        if self.current is None:
            self._error("no module selected; use <category/name> first")
            return
        set_values = self.current.option_values
        table = Table(
            title=f"Options for {self.current.full_name}",
            show_header=True,
            header_style="bold",
        )
        table.add_column("Option", style="cyan", no_wrap=True)
        table.add_column("Value")
        table.add_column("Required", justify="center")
        table.add_column("Description")

        for spec in self.current.option_specs():
            if spec.name in set_values:
                value_cell = str(set_values[spec.name])
            elif spec.default is not None:
                value_cell = f"[dim]{spec.default}[/dim]"
            elif spec.required:
                value_cell = "[red]<required>[/red]"
            else:
                value_cell = "[dim]<unset>[/dim]"
            description = spec.description
            if spec.choices:
                description += f"  [dim](choices: {', '.join(map(str, spec.choices))})[/dim]"
            table.add_row(spec.name, value_cell, "yes" if spec.required else "no", description)

        self.console.print(table)

    def _show_modules(self) -> None:
        modules = self.loader.list_modules()
        if not modules:
            self._note("no modules discovered (drop .py modules under the modules directory)")
            return
        table = Table(title="Modules", show_header=True, header_style="bold")
        table.add_column("Address", style="cyan", no_wrap=True)
        table.add_column("Description")
        for category, name, description in modules:
            table.add_row(f"{category}/{name}", description)
        self.console.print(table)

    def _show_results(self) -> None:
        results = self.store.list_results()
        if not results:
            self._note("no results yet (run a module first)")
            return
        table = Table(title="Results", show_header=True, header_style="bold")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Module")
        table.add_column("Status", justify="center")
        table.add_column("Records", justify="right")
        table.add_column("Summary")
        for result in results:
            style = _STATUS_STYLE.get(result.status, "white")
            table.add_row(
                result.id[:8],
                result.module_path,
                f"[{style}]{result.status.value}[/{style}]",
                str(len(result.records)),
                result.summary or "",
            )
        self.console.print(table)

    def _render_result_summary(self, result: Result) -> None:
        style = _STATUS_STYLE.get(result.status, "white")
        marker = "+" if result.status is ResultStatus.OK else "-"
        self.console.print(
            f"[{style}][{marker}][/{style}] {result.module_path} "
            f"[{style}]{result.status.value}[/{style}] "
            f"({len(result.records)} record(s), id {result.id[:8]})"
        )
        if result.summary:
            self.console.print(f"    {result.summary}")
        for err in result.errors:
            self._error(f"{err.kind}: {err.message}")
        self._note("stored; 'show results' to list")

    # -- REPL loop -------------------------------------------------------------

    def _welcome(self) -> None:
        self._note("type 'help' for commands, 'exit' to quit")

    def _stdin_is_interactive(self) -> bool:
        try:
            return sys.stdin.isatty() and sys.stdout.isatty()
        except (ValueError, AttributeError):
            return False

    def run(self) -> None:
        """Start the REPL. Uses prompt_toolkit at a real terminal, plain input otherwise."""
        self._welcome()
        if self._stdin_is_interactive():
            self._run_interactive()
        else:
            self._run_batch()

    def _run_interactive(self) -> None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory

        from voidkit.completion import VoidkitCompleter

        session: PromptSession = PromptSession(
            history=InMemoryHistory(),
            completer=VoidkitCompleter(self),
        )
        while not self.should_exit:
            try:
                line = session.prompt(self.prompt_text)
            except KeyboardInterrupt:
                continue  # Ctrl-C abandons the current line, like a normal shell
            except EOFError:
                break  # Ctrl-D exits
            self.dispatch(line)

    def _run_batch(self) -> None:
        """Non-interactive fallback: read piped lines, exiting cleanly on EOF.

        OSError covers a stdin that refuses reads (e.g. under a test harness that
        captures it); either way the shell exits rather than looping or crashing.
        """
        while not self.should_exit:
            try:
                line = input(self.prompt_text)
            except (EOFError, OSError):
                break
            self.dispatch(line)
