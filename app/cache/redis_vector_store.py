import struct

import redis
from redis.commands.search.field import TextField, VectorField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from app.cache.vector_store import VectorStore

_INDEX = "semcache_idx"
_PREFIX = "semcache:"


class RedisVectorStore(VectorStore):
    """基于 RediSearch HNSW 的向量后端（生产味实现）。"""

    def __init__(self, url: str, dim: int, max_entries: int = 10000) -> None:
        self.client = redis.Redis.from_url(url)
        self.dim = dim
        self.max_entries = max_entries
        self._ensure_index()

    def _ensure_index(self) -> None:
        try:
            self.client.ft(_INDEX).info()
        except redis.ResponseError:
            schema = (
                TextField("value"),
                VectorField(
                    "embedding",
                    "HNSW",
                    {"TYPE": "FLOAT32", "DIM": self.dim, "DISTANCE_METRIC": "COSINE"},
                ),
            )
            self.client.ft(_INDEX).create_index(
                schema,
                definition=IndexDefinition(
                    prefix=[_PREFIX], index_type=IndexType.HASH
                ),
            )

    def add(self, key: str, embedding: list[float], value: str) -> None:
        blob = struct.pack(f"{len(embedding)}f", *embedding)
        self.client.hset(
            f"{_PREFIX}{key}", mapping={"value": value, "embedding": blob}
        )

    def search(
        self, embedding: list[float], top_k: int = 1
    ) -> list[tuple[str, float]]:
        blob = struct.pack(f"{len(embedding)}f", *embedding)
        q = (
            Query(f"*=>[KNN {top_k} @embedding $vec AS score]")
            .sort_by("score")
            .return_fields("value", "score")
            .dialect(2)
        )
        res = self.client.ft(_INDEX).search(q, query_params={"vec": blob})
        out: list[tuple[str, float]] = []
        for doc in res.docs:
            # RediSearch COSINE 返回的是距离(1-相似度)，转成相似度
            distance = float(doc.score)
            value = doc.value
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            out.append((value, 1.0 - distance))
        return out
