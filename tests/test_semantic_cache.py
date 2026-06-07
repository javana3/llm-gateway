from app.cache.embedder import FakeEmbedder
from app.cache.semantic_cache import SemanticCache
from app.cache.vector_store import InMemoryVectorStore
from app.schemas import ChatCompletionRequest, ChatMessage


def make_cache(threshold: float = 0.9, max_temp: float = 0.5) -> SemanticCache:
    return SemanticCache(
        embedder=FakeEmbedder(dim=64),
        store=InMemoryVectorStore(),
        similarity_threshold=threshold,
        max_temperature=max_temp,
    )


def req(content: str, temperature: float = 0.0) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="m",
        messages=[ChatMessage(role="user", content=content)],
        temperature=temperature,
    )


def test_miss_then_exact_hit():
    cache = make_cache()
    r = req("what is the capital of France")
    assert cache.get(r) is None
    cache.set(r, "Paris")
    assert cache.get(r) == "Paris"
    assert cache.stats.hits == 1
    assert cache.stats.misses == 1


def test_semantic_hit_on_similar_query():
    cache = make_cache(threshold=0.6)
    cache.set(req("the quick brown fox jumps"), "ANSWER")
    # 近似问法（FakeEmbedder 下字符高度重合 → 余弦高）
    hit = cache.get(req("the quick brown fox jumped"))
    assert hit == "ANSWER"


def test_unrelated_query_misses():
    cache = make_cache(threshold=0.9)
    cache.set(req("the quick brown fox jumps"), "ANSWER")
    assert cache.get(req("zzzz qqqq wwww")) is None


def test_high_temperature_is_not_cached():
    cache = make_cache(max_temp=0.5)
    r = req("deterministic question", temperature=1.0)
    cache.set(r, "X")  # 资格不符，不应写入
    assert cache.get(r) is None  # 资格不符，直接 bypass（不计入命中）
    assert cache.stats.hits == 0
