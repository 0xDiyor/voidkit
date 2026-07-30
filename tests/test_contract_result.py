"""Contract tests: the Result schema, serialization round trips, and chaining reads."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from voidkit.contract import Record, Result, ResultError, ResultStatus, record, utc_now


def make_result(**overrides):
    defaults = {
        "module": "port_scan",
        "category": "recon",
        "status": ResultStatus.OK,
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "summary": "3 hosts up, 12 open ports",
        "options": {"target": "10.0.0.0/24", "port": 80},
        "keys": {"hosts_up": 3, "open_ports": 12},
        "records": [
            record("host", address="10.0.0.5", state="up"),
            record("host", address="10.0.0.9", state="up"),
            record("port", address="10.0.0.5", port=22, service="ssh"),
        ],
    }
    defaults.update(overrides)
    return Result(**defaults)


class TestSchema:
    def test_ids_are_unique(self):
        assert make_result().id != make_result().id

    def test_module_path_is_category_slash_name(self):
        assert make_result().module_path == "recon/port_scan"

    def test_schema_version_defaults_to_1(self):
        assert make_result().schema_version == 1

    def test_record_helper_builds_record(self):
        rec = record("host", address="10.0.0.1")
        assert rec == Record(type="host", fields={"address": "10.0.0.1"})

    def test_non_json_record_field_rejected(self):
        with pytest.raises(ValidationError):
            record("host", seen=datetime.now(UTC))

    def test_non_json_key_rejected(self):
        with pytest.raises(ValidationError):
            make_result(keys={"when": object()})


class TestStatusInvariants:
    def test_ok_with_errors_rejected(self):
        with pytest.raises(ValidationError, match="must not carry errors"):
            make_result(errors=[ResultError(message="boom")])

    def test_error_without_errors_rejected(self):
        with pytest.raises(ValidationError, match="at least one error"):
            make_result(status=ResultStatus.ERROR)

    def test_partial_without_errors_rejected(self):
        with pytest.raises(ValidationError, match="at least one error"):
            make_result(status=ResultStatus.PARTIAL)

    def test_partial_carries_records_and_errors(self):
        result = make_result(
            status=ResultStatus.PARTIAL,
            errors=[ResultError(message="10.0.0.9 timed out", kind="timeout")],
        )
        assert result.status is ResultStatus.PARTIAL
        assert result.records and result.errors

    def test_status_transition_revalidates(self):
        result = make_result()
        with pytest.raises(ValidationError):
            result.status = ResultStatus.ERROR  # no errors attached -> invalid

    def test_valid_transition_to_error(self):
        result = make_result(status=ResultStatus.PARTIAL, errors=[ResultError(message="half done")])
        result.status = ResultStatus.ERROR
        assert result.status is ResultStatus.ERROR


class TestSerialization:
    def test_to_dict_is_json_compatible(self):
        data = make_result().to_dict()
        json.dumps(data)  # must not raise
        assert data["status"] == "ok"
        assert isinstance(data["started_at"], str)
        assert data["records"][0] == {
            "type": "host",
            "fields": {"address": "10.0.0.5", "state": "up"},
        }

    def test_dict_round_trip_preserves_equality(self):
        original = make_result()
        assert Result.from_dict(original.to_dict()) == original

    def test_json_round_trip_preserves_equality(self):
        original = make_result(
            status=ResultStatus.PARTIAL,
            errors=[ResultError(message="timed out", kind="timeout", detail={"host": "10.0.0.9"})],
        )
        assert Result.from_json(original.to_json()) == original

    def test_round_trip_preserves_timestamps(self):
        original = make_result()
        restored = Result.from_dict(original.to_dict())
        assert restored.started_at == original.started_at
        assert restored.finished_at == original.finished_at

    def test_unknown_fields_rejected_on_load(self):
        data = make_result().to_dict()
        data["surprise"] = 1
        with pytest.raises(ValidationError):
            Result.from_dict(data)


class TestChainingReads:
    def test_records_of_selects_by_type(self):
        result = make_result()
        hosts = result.records_of("host")
        assert [rec.fields["address"] for rec in hosts] == ["10.0.0.5", "10.0.0.9"]
        assert result.records_of("domain") == []

    def test_values_extracts_one_field_across_records(self):
        assert make_result().values("host", "address") == ["10.0.0.5", "10.0.0.9"]

    def test_values_skips_records_missing_the_field(self):
        result = make_result(
            records=[record("host", address="10.0.0.5"), record("host", state="up")]
        )
        assert result.values("host", "address") == ["10.0.0.5"]

    def test_chaining_survives_a_save_load_cycle(self):
        restored = Result.from_json(make_result().to_json())
        assert restored.values("host", "address") == ["10.0.0.5", "10.0.0.9"]
        assert restored.keys["hosts_up"] == 3
