"""Shared fixtures: a fake modules directory and a loader/shell over it.

The modules are written to ``tmp_path`` as real files so the loader exercises its
real importlib path. They are toy, network-free modules used to drive the shell
and loader tests.
"""

from __future__ import annotations

import textwrap
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from voidkit.loader import ModuleLoader
from voidkit.shell import Shell
from voidkit.store import ResultStore

ECHO_MODULE = '''
from typing import Literal

from voidkit.contract import ModuleBase, ModuleOptions, Result, RunContext, option, record


class EchoOptions(ModuleOptions):
    message: str = option(description="Text to echo back.")
    mode: Literal["plain", "upper"] = option("plain", description="Output transformation.")


class Echo(ModuleBase):
    name = "echo"
    category = "analysis"
    description = "Echo a message back as a record."
    options_model = EchoOptions

    def run(self, context: RunContext) -> Result:
        text = self.opts.message.upper() if self.opts.mode == "upper" else self.opts.message
        return self.ok(
            records=[record("message", text=text)],
            keys={"length": len(text)},
            summary=f"echoed: {text}",
        )
'''

SAMPLE_MODULE = '''
from voidkit.contract import ModuleBase, ModuleOptions, Result, RunContext, option, record


class SampleOptions(ModuleOptions):
    target: str = option(description="Target host or CIDR range.")


class Sample(ModuleBase):
    name = "sample"
    category = "recon"
    description = "Toy recon module (no network)."
    options_model = SampleOptions

    def run(self, context: RunContext) -> Result:
        return self.ok(
            records=[record("host", address=self.opts.target, state="up")],
            summary=f"1 host: {self.opts.target}",
        )
'''

CRASH_MODULE = '''
from voidkit.contract import ModuleBase, Result, RunContext


class Crash(ModuleBase):
    name = "crash"
    category = "analysis"
    description = "Always raises, to prove a module crash becomes an error Result."

    def run(self, context: RunContext) -> Result:
        raise RuntimeError("boom")
'''


def write_module(base: Path, category: str, name: str, source: str) -> Path:
    """Write ``base/<category>/<name>.py`` (creating the category dir)."""
    directory = base / category
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.py"
    path.write_text(textwrap.dedent(source))
    return path


@pytest.fixture
def module_dir(tmp_path: Path) -> Path:
    write_module(tmp_path, "analysis", "echo", ECHO_MODULE)
    write_module(tmp_path, "recon", "sample", SAMPLE_MODULE)
    write_module(tmp_path, "analysis", "crash", CRASH_MODULE)
    return tmp_path


@pytest.fixture
def loader(module_dir: Path) -> ModuleLoader:
    return ModuleLoader(module_dir)


@pytest.fixture
def console_buffer() -> StringIO:
    return StringIO()


@pytest.fixture
def console(console_buffer: StringIO) -> Console:
    # No terminal detection, no markup highlighting: deterministic captured text.
    return Console(file=console_buffer, width=200, force_terminal=False, highlight=False)


@pytest.fixture
def shell(loader: ModuleLoader, console: Console) -> Shell:
    return Shell(loader=loader, store=ResultStore(), console=console)
