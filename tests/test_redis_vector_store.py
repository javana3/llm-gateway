import pytest

redis = pytest.importorskip("redis")


def _redis_available(url: str) -> bool:
    """能连上 Redis 且含 RediSearch 模块才算可用。"""
    try:
        client = redis.Redis.from_url(url)
        client.ping()
        names = {m.get(b"name", b"").lower() for m in client.module_list()}
        return any(b"search" in n for n in names)
    except Exception:
        return False


URL = "redis://localhost:6379"


@pytest.mark.skipif(
    not _redis_available(URL),
    reason="Redis(含 RediSearch) 不可用：需先启动 Docker 跑 redis/redis-stack",
)
def test_redis_vector_store_add_and_search():
    from app.cache.redis_vector_store import RedisVectorStore

    store = RedisVectorStore(url=URL, dim=3)
    store.add("k1", [1.0, 0.0, 0.0], "value-1")
    store.add("k2", [0.0, 1.0, 0.0], "value-2")
    results = store.search([1.0, 0.0, 0.0], top_k=1)
    assert results
    value, score = results[0]
    assert value == "value-1"
    assert score > 0.9
