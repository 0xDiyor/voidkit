"""Session persistence tests: state round-trip and graceful handling of bad files.

These exercise :class:`voidkit.session.Session` in isolation (no shell): build a
session, dump it to a state dict / file, reload it, and assert the state survives
exactly; then feed corrupt inputs and assert a clear :class:`SessionError` rather
than a crash.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voidkit.contract import Result, ResultStatus, record, utc_now
from voidkit.session import SESSION_VERSION, Session, SessionError


def make_result(module: str = "sample", category: str = "recon", **fields) -> Result:
    now = utc_now()
    return Result(
        module=module,
        category=category,
        status=ResultStatus.OK,
        started_at=now,
        finished_at=now,
        summary="one host",
        options={"target": "10.0.0.5"},
        keys={"count": 1},
        records=[record("host", address="10.0.0.5", state="up", **fields)],
    )


class TestStateRoundTrip:
    def test_to_state_from_state_preserves_everything(self):
        result = make_result()
        session = Session(
            name="job",
            module="recon/sample",
            options={"target": "10.0.0.5"},
            chain_from=result.id,
            results=[result],
        )

        restored = Session.from_state(session.to_state())

        assert restored.name == "job"
        assert restored.module == "recon/sample"
        assert restored.options == {"target": "10.0.0.5"}
        assert restored.chain_from == result.id
        assert len(restored.results) == 1
        # Result identity and payload survive the Phase 1 serialization verbatim.
        assert restored.results[0].to_dict() == result.to_dict()

    def test_empty_session_round_trips(self):
        restored = Session.from_state(Session().to_state())
        assert restored.module is None
        assert restored.options == {}
        assert restored.chain_from is None
        assert restored.results == []

    def test_state_is_json_serializable(self):
        state = Session(name="x", results=[make_result()]).to_state()
        # Must survive a JSON round-trip untouched (nothing non-serializable leaks in).
        assert json.loads(json.dumps(state)) == state
        assert state["voidkit_session_version"] == SESSION_VERSION


class TestFileRoundTrip:
    def test_save_then_load_preserves_state(self, tmp_path: Path):
        result = make_result()
        session = Session(
            name="job",
            module="recon/sample",
            options={"target": "10.0.0.5"},
            chain_from=result.id,
            results=[result],
        )
        path = tmp_path / "nested" / "job.json"

        session.save(path)
        assert path.is_file()  # save() creates parent directories

        loaded = Session.load(path)
        assert loaded.module == "recon/sample"
        assert loaded.options == {"target": "10.0.0.5"}
        assert loaded.chain_from == result.id
        assert loaded.results[0].to_dict() == result.to_dict()

    def test_multiple_results_keep_order(self, tmp_path: Path):
        results = [make_result(port=p) for p in (22, 80, 443)]
        path = tmp_path / "many.json"
        Session(results=results).save(path)
        loaded = Session.load(path)
        assert [r.id for r in loaded.results] == [r.id for r in results]


class TestGracefulErrors:
    def test_missing_file_raises_session_error(self, tmp_path: Path):
        with pytest.raises(SessionError, match="no session file"):
            Session.load(tmp_path / "nope.json")

    def test_non_json_file_raises_session_error(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("this is { not json")
        with pytest.raises(SessionError, match="not valid JSON"):
            Session.load(path)

    def test_non_object_top_level_raises(self, tmp_path: Path):
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]")
        with pytest.raises(SessionError, match="must be a JSON object"):
            Session.load(path)

    def test_wrong_version_raises(self, tmp_path: Path):
        path = tmp_path / "old.json"
        path.write_text(json.dumps({"voidkit_session_version": 999, "results": []}))
        with pytest.raises(SessionError, match="unsupported session version"):
            Session.load(path)

    def test_missing_version_raises(self):
        with pytest.raises(SessionError, match="unsupported session version"):
            Session.from_state({"results": []})

    def test_malformed_result_raises_with_index(self):
        state = {
            "voidkit_session_version": SESSION_VERSION,
            "results": [{"not": "a valid result"}],
        }
        with pytest.raises(SessionError, match="result #0 is not a valid Result"):
            Session.from_state(state)

    def test_results_wrong_type_raises(self):
        state = {"voidkit_session_version": SESSION_VERSION, "results": "nope"}
        with pytest.raises(SessionError, match="'results' must be a list"):
            Session.from_state(state)

    def test_options_wrong_type_raises(self):
        state = {
            "voidkit_session_version": SESSION_VERSION,
            "options": ["not", "a", "dict"],
            "results": [],
        }
        with pytest.raises(SessionError, match="'options' must be an object"):
            Session.from_state(state)

    def test_module_wrong_type_raises(self):
        state = {
            "voidkit_session_version": SESSION_VERSION,
            "module": 123,
            "results": [],
        }
        with pytest.raises(SessionError, match="'module' must be a string or null"):
            Session.from_state(state)
