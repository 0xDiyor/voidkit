"""CLI tests: version reporting and the banner + shell entry point.

The bare-run test relies on the shell's non-interactive fallback: under pytest,
stdin is not a TTY, so ``Shell.run`` reads no input and exits cleanly, letting us
assert on the banner without blocking on a prompt.
"""

import subprocess
import sys

import pytest

from voidkit import __version__
from voidkit.cli import main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == "Void Kit 0.1.0"


def test_dunder_version_matches_cli():
    assert __version__ == "0.1.0"


def test_bare_run_prints_banner_and_starts_shell(capsys, tmp_path):
    # Point discovery at an empty dir so the run is hermetic, then let the shell's
    # non-interactive fallback exit cleanly (no TTY under pytest).
    exit_code = main(["--modules-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert f"Void Kit {__version__}" in out
    assert "type 'help' for commands" in out  # the shell's welcome line


def test_python_dash_m_entry_point():
    result = subprocess.run(
        [sys.executable, "-m", "voidkit", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Void Kit 0.1.0" in result.stdout
