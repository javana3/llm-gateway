from app.cache.embedder import FastEmbedEmbedder
from app.cache.semantic_cache import SemanticCache
from app.cache.vector_store import InMemoryVectorStore
from app.config import settings


def build_semantic_cache() -> SemanticCache:
    embedder = FastEmbedEmbedder(settings.embed_model)
    if settings.vector_store_backend == "redis":
        from app.cache.redis_vector_store import RedisVectorStore

        store = RedisVectorStore(
            url=settings.redis_url,
            dim=384,
            max_entries=settings.cache_max_entries,
        )
    else:
        store = InMemoryVectorStore(max_entries=settings.cache_max_entries)
    return SemanticCache(
        embedder=embedder,
        store=store,
        similarity_threshold=settings.cache_similarity_threshold,
        max_temperature=settings.cache_max_temperature,
    )
