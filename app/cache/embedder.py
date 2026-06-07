from abc import ABC, abstractmethod
import hashlib


class Embedder(ABC):
    """文本 → 稠密向量。"""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        ...


def _normalize(vec: list[float]) -> list[float]:
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0:
        return vec
    return [x / norm for x in vec]


class FakeEmbedder(Embedder):
    """确定性测试用 embedder：基于字符 n-gram 哈希到固定维度。
    不依赖任何模型下载，相似字符串向量更接近。"""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        text = text.lower()
        for i in range(len(text)):
            gram = text[i : i + 2]
            h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        return _normalize(vec)


class FastEmbedEmbedder(Embedder):
    """本地 fastembed（ONNX）实现，懒加载模型。"""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None

    def _ensure(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._ensure()
        vec = next(iter(model.embed([text])))
        return _normalize([float(x) for x in vec.tolist()])
