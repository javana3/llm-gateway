import hashlib
from dataclasses import dataclass

from app.cache.embedder import Embedder
from app.cache.vector_store import VectorStore
from app.schemas import ChatCompletionRequest


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    l1_hits: int = 0
    l2_hits: int = 0

    @property
    def hit_ratio(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class SemanticCache:
    """多级缓存：L1 精确（prompt 哈希）+ L2 语义（向量检索 + 阈值）。
    仅对低 temperature 请求启用（高随机性请求缓存会给错答案）。"""

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        similarity_threshold: float,
        max_temperature: float,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.similarity_threshold = similarity_threshold
        self.max_temperature = max_temperature
        self._exact: dict[str, str] = {}
        self.stats = CacheStats()

    @staticmethod
    def _query_text(request: ChatCompletionRequest) -> str:
        return "\n".join(f"{m.role}:{m.content}" for m in request.messages)

    def _exact_key(self, request: ChatCompletionRequest) -> str:
        raw = f"{request.model}|{self._query_text(request)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _eligible(self, request: ChatCompletionRequest) -> bool:
        return request.temperature <= self.max_temperature

    def get(self, request: ChatCompletionRequest) -> str | None:
        if not self._eligible(request):
            return None  # 资格不符：bypass，不计统计
        # L1 精确
        key = self._exact_key(request)
        if key in self._exact:
            self.stats.hits += 1
            self.stats.l1_hits += 1
            return self._exact[key]
        # L2 语义
        emb = self.embedder.embed(self._query_text(request))
        results = self.store.search(emb, top_k=1)
        if results and results[0][1] >= self.similarity_threshold:
            self.stats.hits += 1
            self.stats.l2_hits += 1
            return results[0][0]
        self.stats.misses += 1
        return None

    def set(self, request: ChatCompletionRequest, content: str) -> None:
        if not self._eligible(request):
            return
        key = self._exact_key(request)
        self._exact[key] = content
        self.store.add(key, self.embedder.embed(self._query_text(request)), content)
