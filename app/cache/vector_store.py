from abc import ABC, abstractmethod
from collections import OrderedDict

import numpy as np


class VectorStore(ABC):
    """向量增/查抽象。search 返回 [(value, cosine_score), ...] 按分数降序。"""

    @abstractmethod
    def add(self, key: str, embedding: list[float], value: str) -> None:
        ...

    @abstractmethod
    def search(
        self, embedding: list[float], top_k: int = 1
    ) -> list[tuple[str, float]]:
        ...


class InMemoryVectorStore(VectorStore):
    def __init__(self, max_entries: int = 10000) -> None:
        self.max_entries = max_entries
        # key -> (np.ndarray, value)，OrderedDict 保序便于 LRU 淘汰
        self._data: "OrderedDict[str, tuple[np.ndarray, str]]" = OrderedDict()

    def size(self) -> int:
        return len(self._data)

    def add(self, key: str, embedding: list[float], value: str) -> None:
        vec = np.asarray(embedding, dtype=np.float32)
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (vec, value)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)  # 淘汰最旧

    def search(
        self, embedding: list[float], top_k: int = 1
    ) -> list[tuple[str, float]]:
        if not self._data:
            return []
        q = np.asarray(embedding, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        scored: list[tuple[str, float]] = []
        for vec, value in self._data.values():
            vn = np.linalg.norm(vec)
            if vn == 0:
                continue
            score = float(np.dot(q, vec) / (qn * vn))
            scored.append((value, score))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]
