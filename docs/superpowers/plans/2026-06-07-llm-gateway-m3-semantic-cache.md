# LLM 网关 M3（语义缓存）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给网关加多级缓存——L1 精确命中 + L2 语义命中（相似问题也能命中），命中即直接返回（流式则回放），大幅省下游调用；并产出缓存命中率与命中/未命中延迟数据。

**Architecture:** 三层抽象：`Embedder`（文本→向量，默认本地 fastembed/ONNX）、`VectorStore`（向量增/查，默认内存 numpy 余弦，Redis 可选）、`SemanticCache`（组合 L1 精确字典 + L2 向量检索 + 相似度阈值 + 缓存资格判断）。缓存在 lifespan 创建并挂到 `app.state`。端点在请求前查缓存：命中直接返回/回放，未命中调下游并在结束后写缓存。统计命中率经 `/cache/stats` 暴露。

**Tech Stack:** fastembed（ONNX，轻量本地 embedding，无 torch）、numpy（内存余弦）、redis-py + RediSearch（可选向量后端）、FastAPI、pytest + respx。

> **里程碑说明**：本计划只覆盖 M3，承接已完成的 M1+M2（13 个测试全绿）。M4（限流/计费/路由）等后续单独成计划。
> **环境**：venv `.\.venv\Scripts\python.exe`；命令用 PowerShell。本机 Docker 已装但未启动、无本地 Redis——所以 **Redis 向量后端（Task 6）的测试设计为“连不上就 skip”**，真正验证需你先启动 Docker Desktop。
> **选型已定**：embedding 用本地 fastembed；向量存储用“内存默认 + Redis 可选”的可插拔方案。

---

## 现状（M2 结束时）

```
app/
├── main.py             # lifespan 创建共享 httpx.AsyncClient
├── config.py           # settings（deepseek_*, minimax_*）
├── schemas.py          # OpenAI 兼容模型
├── providers/          # base / openai_compatible / deepseek / minimax
└── routes/chat.py      # /v1/chat/completions（流式+非流式）+ get_provider
mock_upstream/app.py    # 压测用 Mock 上游
scripts/loadtest.py     # 压测脚本
tests/                  # 13 个测试全绿
```

## M3 结束时新增/修改

```
requirements.txt                  # 修改：+ fastembed, redis, numpy
app/config.py                     # 修改：+ 缓存相关配置
app/cache/__init__.py             # 新增（空）
app/cache/embedder.py             # 新增：Embedder 抽象 + FastEmbedEmbedder
app/cache/vector_store.py         # 新增：VectorStore 抽象 + InMemoryVectorStore
app/cache/redis_vector_store.py   # 新增：RedisVectorStore（可选后端）
app/cache/semantic_cache.py       # 新增：SemanticCache（L1+L2+阈值+资格+统计）
app/cache/factory.py              # 新增：按配置组装 SemanticCache
app/sse.py                        # 新增：SSE 工具（解析 delta / 合成回放）
app/main.py                       # 修改：lifespan 创建 semantic_cache
app/routes/chat.py                # 修改：端点接入缓存（流式+非流式）
app/routes/cache.py               # 新增：GET /cache/stats
scripts/cache_benchmark.py        # 新增：命中率与命中/未命中延迟基准
README.md                         # 修改：语义缓存说明 + 基准用法
tests/test_embedder.py            # 新增
tests/test_vector_store.py        # 新增
tests/test_semantic_cache.py      # 新增
tests/test_sse.py                 # 新增
tests/test_cache_endpoint.py      # 新增（端点缓存行为 + /cache/stats）
tests/test_redis_vector_store.py  # 新增（连不上则 skip）
```

> 单测一律用**确定性 FakeEmbedder + InMemoryVectorStore**，不触发模型下载；fastembed 真实加载仅在 Task 1 的手动验证里做一次。

---

## Task 1: 依赖与 Embedder 抽象（fastembed）

**Files:**
- Modify: `requirements.txt`
- Modify: `app/config.py`
- Create: `app/cache/__init__.py`（空）
- Create: `app/cache/embedder.py`
- Test: `tests/test_embedder.py`

- [ ] **Step 1: 在 `requirements.txt` 末尾追加依赖**

在文件末尾追加三行：
```
fastembed==0.7.*
redis==5.*
numpy==2.*
```

- [ ] **Step 2: 安装新依赖（后台跑，较慢）**

Run:
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --progress-bar off
```
Expected: 安装成功（fastembed 会带入 onnxruntime、tokenizers 等）。

- [ ] **Step 3: 确认 fastembed 可用并选定模型 id**

Run:
```powershell
.\.venv\Scripts\python.exe -c "from fastembed import TextEmbedding; import json; print(json.dumps([m['model'] for m in TextEmbedding.list_supported_models()]))"
```
Expected: 打印出受支持模型列表。确认其中含 `BAAI/bge-small-en-v1.5`（本计划默认用它）。若需中文可在 `.env` 用 `EMBED_MODEL` 切到列表中的多语言小模型（如 `intfloat/multilingual-e5-small`，若在列表中）。

- [ ] **Step 4: 在 `app/config.py` 的 Settings 中追加缓存配置**

在 `minimax_model` 那行之后、`settings = Settings()` 之前插入：

```python
    # ---- 语义缓存 ----
    cache_enabled: bool = True
    cache_similarity_threshold: float = 0.9
    cache_max_temperature: float = 0.5
    cache_max_entries: int = 10000
    embed_model: str = "BAAI/bge-small-en-v1.5"
    vector_store_backend: str = "memory"  # "memory" | "redis"
    redis_url: str = "redis://localhost:6379"
```

- [ ] **Step 5: 写失败测试 `tests/test_embedder.py`**

```python
from app.cache.embedder import Embedder, FakeEmbedder


def test_fake_embedder_is_deterministic_and_normalized():
    emb = FakeEmbedder(dim=16)
    v1 = emb.embed("hello world")
    v2 = emb.embed("hello world")
    assert v1 == v2  # 确定性
    assert len(v1) == 16
    # 单位向量（L2 范数约等于 1）
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_fake_embedder_similar_text_closer_than_unrelated():
    emb = FakeEmbedder(dim=64)

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))

    base = emb.embed("the quick brown fox")
    near = emb.embed("the quick brown foxes")  # 仅末尾不同
    far = emb.embed("zzzzz qqqqq")
    assert cos(base, near) > cos(base, far)


def test_embedder_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        Embedder()  # 抽象类不可实例化
```

- [ ] **Step 6: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedder.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.cache.embedder'`。

- [ ] **Step 7: 建空文件 `app/cache/__init__.py`**

创建空文件 `app/cache/__init__.py`。

- [ ] **Step 8: 写 `app/cache/embedder.py`**

```python
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
```

- [ ] **Step 9: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_embedder.py -v`
Expected: 3 passed。

- [ ] **Step 10: （手动一次性）验证 fastembed 真实可用**

Run:
```powershell
.\.venv\Scripts\python.exe -c "from app.cache.embedder import FastEmbedEmbedder; e=FastEmbedEmbedder('BAAI/bge-small-en-v1.5'); v=e.embed('hello'); print('dim=',len(v))"
```
Expected: 首次会下载模型（约 100-200MB），随后打印 `dim= 384`。（仅验证，不进测试。）

- [ ] **Step 11: Commit**

```powershell
git add requirements.txt app/config.py app/cache/__init__.py app/cache/embedder.py tests/test_embedder.py
git commit -m "feat: Embedder 抽象与 fastembed/Fake 实现`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: VectorStore 抽象 + 内存实现

**Files:**
- Create: `app/cache/vector_store.py`
- Test: `tests/test_vector_store.py`

- [ ] **Step 1: 写失败测试 `tests/test_vector_store.py`**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_vector_store.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.cache.vector_store'`。

- [ ] **Step 3: 写 `app/cache/vector_store.py`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_vector_store.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```powershell
git add app/cache/vector_store.py tests/test_vector_store.py
git commit -m "feat: VectorStore 抽象与内存余弦实现`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: SemanticCache（L1+L2+阈值+资格+统计）

**Files:**
- Create: `app/cache/semantic_cache.py`
- Test: `tests/test_semantic_cache.py`

- [ ] **Step 1: 写失败测试 `tests/test_semantic_cache.py`**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_semantic_cache.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.cache.semantic_cache'`。

- [ ] **Step 3: 写 `app/cache/semantic_cache.py`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_semantic_cache.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```powershell
git add app/cache/semantic_cache.py tests/test_semantic_cache.py
git commit -m "feat: SemanticCache(L1精确+L2语义+阈值+资格+统计)`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: SSE 工具（解析 delta / 合成回放）

**Files:**
- Create: `app/sse.py`
- Test: `tests/test_sse.py`

- [ ] **Step 1: 写失败测试 `tests/test_sse.py`**

```python
from app.sse import assemble_content_from_sse, replay_content_as_sse


def test_assemble_content_from_openai_style_sse():
    sse = (
        b'data: {"choices":[{"index":0,"delta":{"content":"He"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{"content":"llo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    assert assemble_content_from_sse(sse) == "Hello"


def test_assemble_ignores_non_data_and_done():
    sse = b": comment\n\ndata: [DONE]\n\n"
    assert assemble_content_from_sse(sse) == ""


def test_replay_roundtrips_through_assemble():
    chunks = list(replay_content_as_sse("Hello world", chunk_size=3))
    body = b"".join(chunks)
    assert b"[DONE]" in body
    assert assemble_content_from_sse(body) == "Hello world"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_sse.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.sse'`。

- [ ] **Step 3: 写 `app/sse.py`**

```python
import json
from collections.abc import Iterator


def assemble_content_from_sse(raw: bytes) -> str:
    """从 OpenAI 风格 SSE 字节流里拼出完整 assistant 文本。"""
    parts: list[str] = []
    for line in raw.split(b"\n"):
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[len(b"data:") :].strip()
        if payload == b"[DONE]" or not payload:
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in obj.get("choices", []):
            piece = choice.get("delta", {}).get("content")
            if piece:
                parts.append(piece)
    return "".join(parts)


def replay_content_as_sse(content: str, chunk_size: int = 16) -> Iterator[bytes]:
    """把缓存的完整文本切块，合成 OpenAI 风格 SSE 逐块吐，模拟流式体验。"""
    for i in range(0, len(content), chunk_size):
        piece = content[i : i + chunk_size]
        obj = {"choices": [{"index": 0, "delta": {"content": piece}}]}
        yield f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")
    yield b"data: [DONE]\n\n"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_sse.py -v`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```powershell
git add app/sse.py tests/test_sse.py
git commit -m "feat: SSE 工具(拼接 delta / 合成回放)`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 缓存工厂 + 接入 lifespan + 端点缓存（流式&非流式）+ /cache/stats

**Files:**
- Create: `app/cache/factory.py`
- Create: `app/routes/cache.py`
- Modify: `app/main.py`
- Modify: `app/routes/chat.py`
- Test: `tests/test_cache_endpoint.py`

- [ ] **Step 1: 写 `app/cache/factory.py`**

```python
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
```

> 注：`RedisVectorStore` 在 Task 6 实现；此处为延迟 import，backend=memory 时不会触发。

- [ ] **Step 2: 写失败测试 `tests/test_cache_endpoint.py`**

```python
import httpx
from fastapi.testclient import TestClient

from app.cache.embedder import FakeEmbedder
from app.cache.semantic_cache import SemanticCache
from app.cache.vector_store import InMemoryVectorStore
from app.main import app
from app.providers.base import Provider
from app.routes.chat import get_provider
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    Usage,
)


class CountingProvider(Provider):
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls += 1
        return ChatCompletionResponse(
            id="x",
            created=1,
            model=request.model,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(role="assistant", content="Paris"),
                    finish_reason="stop",
                )
            ],
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def stream_chat(self, request: ChatCompletionRequest):
        self.calls += 1
        yield b'data: {"choices":[{"index":0,"delta":{"content":"Paris"}}]}\n\n'
        yield b"data: [DONE]\n\n"


def install_test_cache():
    app.state.semantic_cache = SemanticCache(
        embedder=FakeEmbedder(dim=64),
        store=InMemoryVectorStore(),
        similarity_threshold=0.9,
        max_temperature=0.5,
    )


def test_non_stream_second_call_is_cache_hit():
    provider = CountingProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            install_test_cache()  # 覆盖 lifespan 建好的真实缓存
            body = {
                "model": "m",
                "messages": [{"role": "user", "content": "capital of France"}],
                "temperature": 0.0,
            }
            r1 = client.post("/v1/chat/completions", json=body)
            r2 = client.post("/v1/chat/completions", json=body)
            assert r1.json()["choices"][0]["message"]["content"] == "Paris"
            assert r2.json()["choices"][0]["message"]["content"] == "Paris"
            assert provider.calls == 1  # 第二次命中缓存，未再调下游
            stats = client.get("/cache/stats").json()
            assert stats["hits"] == 1
            assert stats["misses"] == 1
    finally:
        app.dependency_overrides.clear()


def test_stream_second_call_is_cache_hit_and_replays():
    provider = CountingProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            install_test_cache()
            body = {
                "model": "m",
                "messages": [{"role": "user", "content": "capital of France"}],
                "temperature": 0.0,
                "stream": True,
            }
            with client.stream("POST", "/v1/chat/completions", json=body) as resp:
                b1 = b"".join(resp.iter_bytes())
            with client.stream("POST", "/v1/chat/completions", json=body) as resp:
                assert resp.headers["content-type"].startswith("text/event-stream")
                b2 = b"".join(resp.iter_bytes())
            assert b"Paris" in b1
            assert b"Paris" in b2
            assert b"[DONE]" in b2
            assert provider.calls == 1  # 第二次走缓存回放
    finally:
        app.dependency_overrides.clear()


def test_high_temperature_bypasses_cache():
    provider = CountingProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            install_test_cache()
            body = {
                "model": "m",
                "messages": [{"role": "user", "content": "random please"}],
                "temperature": 1.0,
            }
            client.post("/v1/chat/completions", json=body)
            client.post("/v1/chat/completions", json=body)
            assert provider.calls == 2  # 高温不缓存，每次都打下游
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cache_endpoint.py -v`
Expected: FAIL（`/cache/stats` 404 或缓存未接入导致 `provider.calls != 1`）。

- [ ] **Step 4: 写 `app/routes/cache.py`**

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/cache/stats")
async def cache_stats(request: Request) -> dict:
    cache = request.app.state.semantic_cache
    s = cache.stats
    return {
        "hits": s.hits,
        "misses": s.misses,
        "l1_hits": s.l1_hits,
        "l2_hits": s.l2_hits,
        "hit_ratio": round(s.hit_ratio, 4),
    }
```

- [ ] **Step 5: 修改 `app/main.py`（lifespan 创建 semantic_cache，挂载 cache 路由）**

整体替换为：

```python
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.cache.factory import build_semantic_cache
from app.routes.cache import router as cache_router
from app.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 共享连接池：所有请求复用，避免每请求重建 TCP/TLS。
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(60.0, connect=10.0)
    app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    app.state.semantic_cache = build_semantic_cache()
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(cache_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: 修改 `app/routes/chat.py`（端点接入缓存）**

整体替换为：

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.providers.base import Provider
from app.providers.minimax import MiniMaxProvider
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    Usage,
)
from app.sse import assemble_content_from_sse, replay_content_as_sse

router = APIRouter()


def get_provider(request: Request) -> Provider:
    """M1：固定返回 MiniMax（已有可用 key）。M4 会扩展为按 model 路由。
    复用应用启动时创建的共享 httpx.AsyncClient（连接池）。"""
    return MiniMaxProvider(client=request.app.state.http_client)


def _build_response(model: str, content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="cached",
        created=0,
        model=model,
        choices=[
            Choice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    http_request: Request,
    provider: Provider = Depends(get_provider),
):
    cache = http_request.app.state.semantic_cache

    if request.stream:
        cached = cache.get(request)
        if cached is not None:
            return StreamingResponse(
                replay_content_as_sse(cached), media_type="text/event-stream"
            )

        async def event_stream():
            parts: list[bytes] = []
            async for chunk in provider.stream_chat(request):
                if await http_request.is_disconnected():
                    break
                parts.append(chunk)
                yield chunk
            content = assemble_content_from_sse(b"".join(parts))
            if content:
                cache.set(request, content)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    cached = cache.get(request)
    if cached is not None:
        return _build_response(request.model, cached)

    resp = await provider.chat(request)
    content = resp.choices[0].message.content if resp.choices else ""
    if content:
        cache.set(request, content)
    return resp
```

- [ ] **Step 7: 运行缓存端点测试 + 全量测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: 全部 passed（M1+M2 的 13 + Task1~4 新增 3+4+4+3=14 + Task5 的 3 = 30 passed）。

- [ ] **Step 8: Commit**

```powershell
git add app/cache/factory.py app/routes/cache.py app/main.py app/routes/chat.py tests/test_cache_endpoint.py
git commit -m "feat: 端点接入语义缓存(流式回放+非流式)与 /cache/stats`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Redis 向量后端（可选，连不上则 skip）

**Files:**
- Create: `app/cache/redis_vector_store.py`
- Test: `tests/test_redis_vector_store.py`

- [ ] **Step 1: 写 `app/cache/redis_vector_store.py`**

```python
import struct

import redis
from redis.commands.search.field import TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
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
```

- [ ] **Step 2: 写 `tests/test_redis_vector_store.py`（连不上则 skip）**

```python
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
```

- [ ] **Step 3: 运行测试（预期 skip 或 pass）**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_redis_vector_store.py -v`
Expected: 1 skipped（本机 Redis 未启动）。若你已用 Docker 起了 `redis/redis-stack` 则应 1 passed。

- [ ] **Step 4: 运行全量测试确认无回归**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 30 passed, 1 skipped。

- [ ] **Step 5: Commit**

```powershell
git add app/cache/redis_vector_store.py tests/test_redis_vector_store.py
git commit -m "feat: RedisVectorStore(RediSearch HNSW)可选后端`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 缓存基准脚本与文档

**Files:**
- Create: `scripts/cache_benchmark.py`
- Modify: `README.md`

- [ ] **Step 1: 写 `scripts/cache_benchmark.py`**

```python
"""缓存基准：发一批“有重复/近似”的请求，统计命中率与命中/未命中延迟差。

需先启动网关（真实下游或 Mock 上游均可），默认打 http://127.0.0.1:8000。
用法：
    .\\.venv\\Scripts\\python.exe scripts/cache_benchmark.py
"""
import argparse
import asyncio
import time

import httpx

# 10 个“语义相近/重复”的问法，命中率应明显 > 0
QUERIES = [
    "What is the capital of France?",
    "What's the capital city of France?",
    "Tell me the capital of France.",
    "capital of France?",
    "What is the capital of France",
    "What is the capital of France?",
    "Which city is the capital of France?",
    "France capital city name?",
    "What is the capital of France?",
    "the capital of France is what",
]


async def call(client, url, content):
    t0 = time.perf_counter()
    body = {
        "model": "MiniMax-M2.5",
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.0,
    }
    r = await client.post(url, json=body)
    r.raise_for_status()
    return time.perf_counter() - t0


async def run(url: str, stats_url: str) -> None:
    async with httpx.AsyncClient(timeout=120.0) as client:
        latencies = []
        for q in QUERIES:
            latencies.append(await call(client, url, q))
        stats = (await client.get(stats_url)).json()

    print(f"requests={len(QUERIES)} latencies_ms={[round(x*1000) for x in latencies]}")
    print(f"first(miss)≈{latencies[0]*1000:.0f}ms  last(likely hit)≈{latencies[-1]*1000:.0f}ms")
    print(f"cache stats: {stats}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    asyncio.run(
        run(f"{args.base}/v1/chat/completions", f"{args.base}/cache/stats")
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 在 `README.md` 末尾追加“语义缓存”一节**

```markdown

## 语义缓存（M3）

- 多级缓存：L1 精确（prompt 哈希）+ L2 语义（fastembed 向量 + 余弦相似度阈值）。
- 仅缓存低 temperature（`CACHE_MAX_TEMPERATURE`，默认 0.5）的请求，避免高随机性请求被错误命中。
- 向量存储可插拔：默认内存（`VECTOR_STORE_BACKEND=memory`），可选 Redis（`=redis`，需 Docker 起 redis-stack）。
- 命中即直接返回；流式命中则把缓存内容合成 SSE 回放，体验一致。
- 统计：`GET /cache/stats` 返回 hits/misses/l1_hits/l2_hits/hit_ratio。

跑命中率基准（先启动网关）：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# 另一个终端：
.\.venv\Scripts\python.exe scripts/cache_benchmark.py
```

可选启用 Redis 向量后端：

```powershell
# 需本机 Docker 已启动
docker run -d --name redis-stack -p 6379:6379 redis/redis-stack:latest
$env:VECTOR_STORE_BACKEND = "redis"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
```

- [ ] **Step 3: 手动基准验证**

启动网关（下游可指向 Mock 上游以免烧真实额度），运行：
```powershell
.\.venv\Scripts\python.exe scripts/cache_benchmark.py
```
Expected: 打印 10 条延迟与 `cache stats`，其中 `hits >= 1`、后面的请求延迟明显低于第一条（命中走缓存）。

- [ ] **Step 4: Commit**

```powershell
git add scripts/cache_benchmark.py README.md
git commit -m "feat: 语义缓存基准脚本与文档`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## M3 验收标准

- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 全绿（约 30 passed, 1 skipped）。
- [ ] 相同/相似低温请求第二次命中缓存，不再调下游（`/cache/stats` 体现 hits）。
- [ ] 流式命中时返回 `text/event-stream` 并回放缓存内容含 `[DONE]`。
- [ ] 高 temperature 请求绕过缓存。
- [ ] 向量存储可插拔：内存默认可用；Redis 后端代码就绪（Docker 起来后可验证）。
- [ ] 缓存基准脚本能跑出命中率与命中/未命中延迟差。
- [ ] 所有改动分任务提交。

完成后进入 M4（限流/计费/多供应商路由）的计划编写。

---

## 测试数量对照

| 阶段 | 累计测试 |
|---|---|
| M2 结束 | 13 |
| Task 1 后 | 16（+embedder 3）|
| Task 2 后 | 20（+vector_store 4）|
| Task 3 后 | 24（+semantic_cache 4）|
| Task 4 后 | 27（+sse 3）|
| Task 5 后 | 30（+cache_endpoint 3）|
| Task 6 后 | 30 passed + 1 skipped（+redis 1，本机 skip）|
| Task 7 后 | 同上（基准为手动验证）|
