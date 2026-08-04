"""Result store tests: add / list / get / clear over the Phase 1 Result schema."""

from __future__ import annotations

from voidkit.contract import Result, ResultStatus, record, utc_now
from voidkit.store import ResultStore


def make_result(module: str = "sample", category: str = "recon", summary: str = "") -> Result:
    return Result(
        module=module,
        category=category,
        status=ResultStatus.OK,
        started_at=utc_now(),
        finished_at=utc_now(),
        summary=summary,
        records=[record("host", address="10.0.0.1")],
    )


class TestAddAndList:
    def test_add_returns_id_and_stores_result(self):
        store = ResultStore()
        result = make_result()
        returned = store.add_result(result)
        assert returned == result.id
        assert store.list_results() == [result]
        assert len(store) == 1

    def test_list_preserves_insertion_order(self):
        store = ResultStore()
        first = make_result(summary="first")
        second = make_result(summary="second")
        store.add_result(first)
        store.add_result(second)
        assert [r.summary for r in store.list_results()] == ["first", "second"]

    def test_list_returns_a_copy(self):
        store = ResultStore()
        store.add_result(make_result())
        snapshot = store.list_results()
        snapshot.clear()
        assert len(store) == 1  # mutating the returned list does not affect the store

    def test_adding_same_id_replaces_rather_than_duplicating(self):
        store = ResultStore()
        result = make_result(summary="original")
        store.add_result(result)
        replacement = result.model_copy(update={"summary": "revised"})
        store.add_result(replacement)
        assert len(store) == 1
        assert store.get_result(result.id).summary == "revised"


class TestGet:
    def test_get_returns_stored_result(self):
        store = ResultStore()
        result = make_result()
        store.add_result(result)
        assert store.get_result(result.id) is result

    def test_get_unknown_id_returns_none(self):
        assert ResultStore().get_result("nope") is None


class TestClear:
    def test_clear_empties_the_store(self):
        store = ResultStore()
        result = make_result()
        store.add_result(result)
        store.clear()
        assert store.list_results() == []
        assert len(store) == 0
        assert store.get_result(result.id) is None

    def test_bool_reflects_emptiness(self):
        store = ResultStore()
        assert not store
        store.add_result(make_result())
        assert store
