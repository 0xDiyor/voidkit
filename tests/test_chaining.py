"""End-to-end tests for Phase 4: module chaining and session save/load.

These drive the shell through :meth:`Shell.dispatch` (what the REPL calls per
line) using ``chain_shell``, a shell whose modules include the downstream
``analysis/host_count`` module. The producer is the network-free ``recon/sample``
module, which emits a ``host`` record; the consumer reads those records off
``RunContext.upstream``. Everything is hermetic, no sockets, no real terminal.
"""

from __future__ import annotations

from pathlib import Path

from voidkit.contract import ResultStatus
from voidkit.loader import ModuleLoader
from voidkit.session import Session
from voidkit.shell import Shell
from voidkit.store import ResultStore


def output(shell: Shell) -> str:
    return shell.console.file.getvalue()


def run_producer(shell: Shell, target: str = "10.0.0.5") -> str:
    """Run ``recon/sample`` and return the stored result id."""
    shell.dispatch("use recon/sample")
    shell.dispatch(f"set target {target}")
    shell.dispatch("run")
    return shell.store.list_results()[-1].id


class TestChainByModuleAddress:
    def test_downstream_consumes_upstream_host_records(self, chain_shell: Shell):
        run_producer(chain_shell, "10.0.0.5")

        chain_shell.dispatch("use analysis/host_count")
        chain_shell.dispatch("chain from recon/sample")
        chain_shell.dispatch("run")

        downstream = chain_shell.store.list_results()[-1]
        assert downstream.status is ResultStatus.OK
        assert downstream.module_path == "analysis/host_count"
        # The downstream result reflects the upstream's host data.
        assert downstream.keys["host_count"] == 1
        assert downstream.values("host", "address") == ["10.0.0.5"]

    def test_chain_source_recorded_and_reported(self, chain_shell: Shell):
        run_producer(chain_shell)
        chain_shell.dispatch("chain from recon/sample")
        assert "chaining next run" in output(chain_shell)

        chain_shell.dispatch("use analysis/host_count")
        chain_shell.dispatch("run")
        assert "chained from recon/sample" in output(chain_shell)


class TestChainByResultId:
    def test_chain_from_result_id_prefix(self, chain_shell: Shell):
        result_id = run_producer(chain_shell, "10.0.0.9")

        chain_shell.dispatch("use analysis/host_count")
        chain_shell.dispatch(f"chain from {result_id[:8]}")
        chain_shell.dispatch("run")

        downstream = chain_shell.store.list_results()[-1]
        assert downstream.keys["source_result"] == result_id
        assert downstream.values("host", "address") == ["10.0.0.9"]

    def test_chain_from_unknown_ref_errors(self, chain_shell: Shell):
        chain_shell.dispatch("chain from recon/sample")
        assert "no stored result matches" in output(chain_shell)


class TestChainManagement:
    def test_chain_show_when_empty(self, chain_shell: Shell):
        chain_shell.dispatch("chain")
        assert "no chain source set" in output(chain_shell)

    def test_chain_show_reports_current_source(self, chain_shell: Shell):
        run_producer(chain_shell)
        chain_shell.dispatch("chain from recon/sample")
        chain_shell.dispatch("chain show")
        assert "chain source: recon/sample" in output(chain_shell)

    def test_chain_clear_drops_source(self, chain_shell: Shell):
        run_producer(chain_shell)
        chain_shell.dispatch("chain from recon/sample")
        chain_shell.dispatch("chain clear")
        assert chain_shell.chain_from is None
        assert "chain cleared" in output(chain_shell)

    def test_run_without_chain_leaves_downstream_without_upstream(self, chain_shell: Shell):
        # host_count with no upstream returns an error Result, not a crash.
        chain_shell.dispatch("use analysis/host_count")
        chain_shell.dispatch("run")
        downstream = chain_shell.store.list_results()[-1]
        assert downstream.status is ResultStatus.ERROR
        assert "no upstream result" in downstream.errors[0].message

    def test_stale_chain_source_reports_and_skips_run(self, chain_shell: Shell):
        run_producer(chain_shell)
        chain_shell.dispatch("chain from recon/sample")
        chain_shell.store.clear()  # source id no longer resolvable
        chain_shell.dispatch("use analysis/host_count")
        chain_shell.dispatch("run")
        assert "no longer in the store" in output(chain_shell)
        assert len(chain_shell.store) == 0  # run was skipped, nothing stored

    def test_bad_chain_subcommand_shows_usage(self, chain_shell: Shell):
        chain_shell.dispatch("chain sideways")
        assert "usage: chain" in output(chain_shell)


class TestSaveLoadShellCommands:
    def test_save_writes_session_file(self, chain_shell: Shell, sessions_dir: Path):
        run_producer(chain_shell, "10.0.0.5")
        chain_shell.dispatch("save job1")

        path = sessions_dir / "job1.json"
        assert path.is_file()
        assert "session 'job1' saved" in output(chain_shell)

        session = Session.load(path)
        assert session.module == "recon/sample"
        assert session.options == {"target": "10.0.0.5"}
        assert len(session.results) == 1

    def test_load_restores_module_options_and_results(
        self, chain_loader: ModuleLoader, console, sessions_dir: Path
    ):
        # Save from one shell...
        saver = Shell(loader=chain_loader, console=console, sessions_dir=sessions_dir)
        run_producer(saver, "10.0.0.7")
        saver.dispatch("save resumable")

        # ...load into a fresh shell and confirm work is resumable.
        fresh = Shell(loader=chain_loader, console=console, sessions_dir=sessions_dir)
        fresh.dispatch("load resumable")

        assert len(fresh.store) == 1
        assert fresh.current is not None
        assert fresh.current.full_name == "recon/sample"
        assert fresh.current.option_values == {"target": "10.0.0.7"}
        assert "session 'resumable' loaded" in output(fresh)

    def test_load_missing_session_reports_gracefully(self, chain_shell: Shell):
        chain_shell.dispatch("load nope")
        assert "no session file" in output(chain_shell)
        # Shell survives and stays usable.
        assert chain_shell.should_exit is False

    def test_load_corrupt_session_reports_gracefully(
        self, chain_shell: Shell, sessions_dir: Path
    ):
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "broken.json").write_text("{ not json")
        chain_shell.dispatch("load broken")
        assert "not valid JSON" in output(chain_shell)

    def test_save_rejects_unsafe_name(self, chain_shell: Shell):
        chain_shell.dispatch("save ../escape")
        assert "invalid session name" in output(chain_shell)

    def test_save_and_load_preserve_chain_source(
        self, chain_loader: ModuleLoader, console, sessions_dir: Path
    ):
        saver = Shell(loader=chain_loader, console=console, sessions_dir=sessions_dir)
        run_producer(saver)
        saver.dispatch("chain from recon/sample")
        saver.dispatch("save chained")

        fresh = Shell(loader=chain_loader, console=console, sessions_dir=sessions_dir)
        fresh.dispatch("load chained")
        assert fresh.chain_from is not None
        assert fresh.store.get_result(fresh.chain_from) is not None


class TestChainAcrossSaveLoad:
    def test_save_then_load_fresh_and_continue_the_chain(
        self, chain_loader: ModuleLoader, console, sessions_dir: Path
    ):
        # 1. Producer runs and the session is saved.
        saver = Shell(loader=chain_loader, console=console, sessions_dir=sessions_dir)
        producer_id = run_producer(saver, "10.0.0.42")
        saver.dispatch("save handoff")

        # 2. A brand-new shell loads the session, then runs the downstream module
        #    chained off the restored upstream result.
        fresh = Shell(loader=chain_loader, console=console, sessions_dir=sessions_dir)
        fresh.dispatch("load handoff")
        fresh.dispatch("use analysis/host_count")
        fresh.dispatch(f"chain from {producer_id}")
        fresh.dispatch("run")

        downstream = fresh.store.list_results()[-1]
        assert downstream.status is ResultStatus.OK
        assert downstream.keys["source_result"] == producer_id
        assert downstream.values("host", "address") == ["10.0.0.42"]

    def test_chain_source_survives_and_runs_after_reload(
        self, chain_loader: ModuleLoader, console, sessions_dir: Path
    ):
        # Set the chain source before saving; after reload a run should chain
        # without re-issuing 'chain from'.
        saver = Shell(loader=chain_loader, console=console, sessions_dir=sessions_dir)
        run_producer(saver, "10.0.0.99")
        saver.dispatch("chain from recon/sample")
        saver.dispatch("save sticky")

        fresh = Shell(loader=chain_loader, console=console, sessions_dir=sessions_dir)
        fresh.dispatch("load sticky")
        fresh.dispatch("use analysis/host_count")
        fresh.dispatch("run")  # chain source restored from the session

        downstream = fresh.store.list_results()[-1]
        assert downstream.status is ResultStatus.OK
        assert downstream.values("host", "address") == ["10.0.0.99"]


def test_store_is_the_backing_for_chaining(chain_shell: Shell):
    """Sanity: a fresh ResultStore chains correctly through the shell."""
    assert isinstance(chain_shell.store, ResultStore)
    run_producer(chain_shell)
    chain_shell.dispatch("use analysis/host_count")
    chain_shell.dispatch("chain from recon/sample")
    chain_shell.dispatch("run")
    assert chain_shell.store.list_results()[-1].keys["host_count"] == 1
