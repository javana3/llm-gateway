import pytest

from app.cache.vector_store import VectorStore, InMemoryVectorStore


def test_search_returns_best_match_with_score():
    store = InMemoryVectorStore()
    store.add("k1", [1.0, 0.0], "value-1")
    store.add("k2", [0.0, 1.0], "value-2")

    results = store.search([1.0, 0.0], top_k=1)
    assert len(results) == 1
    value, score = results[0]
    assert value == "value-1"
    assert score == pytest.approx(1.0, abs=1e-6)


def test_search_empty_store_returns_empty():
    store = InMemoryVectorStore()
    assert store.search([1.0, 0.0], top_k=1) == []


def test_capacity_evicts_oldest():
    store = InMemoryVectorStore(max_entries=2)
    store.add("k1", [1.0, 0.0], "v1")
    store.add("k2", [0.0, 1.0], "v2")
    store.add("k3", [1.0, 1.0], "v3")  # 触发淘汰最旧的 k1
    assert store.size() == 2
    # k1 已被淘汰：精确查 [1,0] 命中的应是 k3 方向而非 k1
    values = [v for v, _ in store.search([1.0, 0.0], top_k=2)]
    assert "v1" not in values


def test_vector_store_is_abstract():
    with pytest.raises(TypeError):
        VectorStore()
