# LLM 网关 M4a（鉴权 + 限流 + 计费）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给网关加上以 API Key 为中心的三道关卡——Bearer 鉴权、按 Key 的令牌桶限流、按 token 计量的配额与计费，并提供用量查询端点。

**Architecture:** 新增 `app/auth/` 模块：`ApiKey` 数据模型、`KeyStore`（内存，按配置播种）、`TokenBucketRateLimiter`（内存按 Key 限流）、`authorize` 依赖（鉴权→限流→配额三连）、`billing` 计费工具。这些在 lifespan 创建并挂到 `app.state`。`/v1/chat/completions` 加 `Depends(authorize)`，调用结束后按 token 计费（缓存命中不计费）。`GET /admin/usage` 暴露每个 Key 的用量。

**Tech Stack:** FastAPI（Depends/Header/HTTPException）、纯 Python（内存令牌桶/计费）、pytest。

> **里程碑说明**：本计划只覆盖 M4a（鉴权/限流/计费）。M4b（多供应商路由 + 熔断降级）单独成计划。承接已完成的 M1+M2+M3（30 passed, 1 skipped）。
> **存储**：内存实现（可后续换 Redis）。无需 Docker。
> **环境**：venv `.\.venv\Scripts\python.exe`；命令用 PowerShell。

---

## 现状（M3 结束）

```
app/
├── main.py            # lifespan: http_client + semantic_cache
├── config.py          # settings
├── schemas.py
├── providers/
├── cache/
├── sse.py
└── routes/
    ├── chat.py        # /v1/chat/completions（缓存+流式+非流式）+ get_provider
    └── cache.py       # /cache/stats
tests/                 # 30 passed, 1 skipped
```

## M4a 结束时新增/修改

```
app/config.py                 # 修改：+ 鉴权/限流/计费 配置
app/auth/__init__.py          # 新增（空）
app/auth/models.py            # 新增：ApiKey
app/auth/key_store.py         # 新增：KeyStore + build_key_store
app/auth/rate_limiter.py      # 新增：TokenBucketRateLimiter
app/auth/billing.py           # 新增：estimate_tokens + record_usage
app/auth/dependencies.py      # 新增：authenticate / authorize 依赖
app/main.py                   # 修改：lifespan 创建 key_store + rate_limiter
app/routes/chat.py            # 修改：加 authorize 依赖 + 调用后计费
app/routes/admin.py           # 新增：GET /admin/usage
tests/test_key_store.py       # 新增
tests/test_rate_limiter.py    # 新增
tests/test_billing.py         # 新增（estimate_tokens / record_usage 单元）
tests/test_auth_endpoint.py   # 新增（401/429/配额/用量 集成）
tests/test_chat_endpoint.py       # 修改：autouse 绕过 auth 的 fixture
tests/test_streaming_endpoint.py  # 修改：同上
tests/test_cache_endpoint.py      # 修改：同上
README.md                     # 修改：鉴权/限流/计费 说明
```

---

## Task 1: ApiKey 模型 + KeyStore + 限流器（纯单元）

**Files:**
- Modify: `app/config.py`
- Create: `app/auth/__init__.py`（空）
- Create: `app/auth/models.py`
- Create: `app/auth/key_store.py`
- Create: `app/auth/rate_limiter.py`
- Test: `tests/test_key_store.py`
- Test: `tests/test_rate_limiter.py`

- [ ] **Step 1: 在 `app/config.py` 的 Settings 追加配置**

在 `redis_url` 那行之后、`settings = Settings()` 之前插入：

```python
    # ---- 鉴权 / 限流 / 计费 ----
    gateway_api_keys: str = "dev-key"  # 逗号分隔的可用 key（演示用）
    default_rpm_limit: int = 60
    default_quota_tokens: int = 1_000_000
    price_per_1k_tokens: float = 0.001
```

- [ ] **Step 2: 写失败测试 `tests/test_key_store.py`**

```python
from app.auth.key_store import KeyStore, build_key_store
from app.auth.models import ApiKey


def test_add_and_get():
    store = KeyStore()
    store.add(ApiKey(key="abc", name="alice", rpm_limit=10, quota_tokens=100))
    got = store.get("abc")
    assert got is not None
    assert got.name == "alice"
    assert store.get("missing") is None


def test_remaining_tokens():
    k = ApiKey(key="abc", name="a", rpm_limit=10, quota_tokens=100)
    k.used_tokens = 30
    assert k.remaining_tokens == 70


def test_build_from_comma_separated_config():
    store = build_key_store("k1, k2 ,k3", rpm_limit=42, quota_tokens=999)
    assert {k.key for k in store.all()} == {"k1", "k2", "k3"}
    assert store.get("k1").rpm_limit == 42
    assert store.get("k2").quota_tokens == 999
```

- [ ] **Step 3: 写失败测试 `tests/test_rate_limiter.py`**

```python
from app.auth.rate_limiter import TokenBucketRateLimiter


def test_allows_up_to_capacity_then_blocks():
    limiter = TokenBucketRateLimiter()
    # rpm=2 → 桶容量 2；快速连发 3 次，前 2 次放行，第 3 次拒绝
    assert limiter.allow("k", rpm=2) is True
    assert limiter.allow("k", rpm=2) is True
    assert limiter.allow("k", rpm=2) is False


def test_separate_keys_have_separate_buckets():
    limiter = TokenBucketRateLimiter()
    assert limiter.allow("k1", rpm=1) is True
    assert limiter.allow("k2", rpm=1) is True  # 不同 key 互不影响
    assert limiter.allow("k1", rpm=1) is False
```

- [ ] **Step 4: 运行两个测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_key_store.py tests/test_rate_limiter.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.auth...'`。

- [ ] **Step 5: 建空文件 `app/auth/__init__.py`**

创建空文件 `app/auth/__init__.py`。

- [ ] **Step 6: 写 `app/auth/models.py`**

```python
from dataclasses import dataclass


@dataclass
class ApiKey:
    key: str
    name: str
    rpm_limit: int
    quota_tokens: int
    used_tokens: int = 0
    requests: int = 0
    cost: float = 0.0

    @property
    def remaining_tokens(self) -> int:
        return self.quota_tokens - self.used_tokens
```

- [ ] **Step 7: 写 `app/auth/key_store.py`**

```python
from app.auth.models import ApiKey


class KeyStore:
    def __init__(self) -> None:
        self._keys: dict[str, ApiKey] = {}

    def add(self, api_key: ApiKey) -> None:
        self._keys[api_key.key] = api_key

    def get(self, key: str) -> ApiKey | None:
        return self._keys.get(key)

    def all(self) -> list[ApiKey]:
        return list(self._keys.values())


def build_key_store(
    keys_csv: str, rpm_limit: int, quota_tokens: int
) -> KeyStore:
    store = KeyStore()
    for raw in keys_csv.split(","):
        k = raw.strip()
        if k:
            store.add(
                ApiKey(
                    key=k, name=k, rpm_limit=rpm_limit, quota_tokens=quota_tokens
                )
            )
    return store
```

- [ ] **Step 8: 写 `app/auth/rate_limiter.py`**

```python
import time


class TokenBucketRateLimiter:
    """按 key 的内存令牌桶。容量=rpm，匀速回填(rpm/60 每秒)。"""

    def __init__(self) -> None:
        # key -> (tokens, last_refill_monotonic)
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, rpm: int) -> bool:
        now = time.monotonic()
        capacity = float(rpm)
        refill_per_sec = rpm / 60.0
        tokens, last = self._buckets.get(key, (capacity, now))
        tokens = min(capacity, tokens + (now - last) * refill_per_sec)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            return True
        self._buckets[key] = (tokens, now)
        return False
```

- [ ] **Step 9: 运行两个测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_key_store.py tests/test_rate_limiter.py -v`
Expected: 5 passed（key_store 3 + rate_limiter 2）。

- [ ] **Step 10: Commit**

```powershell
git add app/config.py app/auth/__init__.py app/auth/models.py app/auth/key_store.py app/auth/rate_limiter.py tests/test_key_store.py tests/test_rate_limiter.py
git commit -m "feat: ApiKey/KeyStore/令牌桶限流器(纯单元)`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 计费工具（estimate_tokens + record_usage）

**Files:**
- Create: `app/auth/billing.py`
- Test: `tests/test_billing.py`

- [ ] **Step 1: 写失败测试 `tests/test_billing.py`**

```python
from app.auth.billing import estimate_tokens, record_usage
from app.auth.models import ApiKey


def test_estimate_tokens_rough_quarter_of_chars():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1  # 4 字符 ≈ 1 token
    assert estimate_tokens("a" * 40) == 10


def test_record_usage_accumulates_tokens_requests_cost():
    k = ApiKey(key="x", name="x", rpm_limit=10, quota_tokens=1000)
    record_usage(k, tokens=200, price_per_1k=0.002)
    assert k.used_tokens == 200
    assert k.requests == 1
    assert k.cost == 0.0004  # 200/1000 * 0.002
    record_usage(k, tokens=300, price_per_1k=0.002)
    assert k.used_tokens == 500
    assert k.requests == 2


def test_record_zero_tokens_still_counts_request():
    k = ApiKey(key="x", name="x", rpm_limit=10, quota_tokens=1000)
    record_usage(k, tokens=0, price_per_1k=0.002)  # 缓存命中：0 token
    assert k.used_tokens == 0
    assert k.requests == 1
    assert k.cost == 0.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_billing.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.auth.billing'`。

- [ ] **Step 3: 写 `app/auth/billing.py`**

```python
from app.auth.models import ApiKey


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（流式无 usage 时用）：约 4 字符 1 token。"""
    return len(text) // 4


def record_usage(api_key: ApiKey, tokens: int, price_per_1k: float) -> None:
    api_key.used_tokens += tokens
    api_key.requests += 1
    api_key.cost += tokens / 1000.0 * price_per_1k
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_billing.py -v`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```powershell
git add app/auth/billing.py tests/test_billing.py
git commit -m "feat: 计费工具(token 估算 + 用量累计)`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: authorize 依赖 + 接入端点 + 既有测试绕过 fixture + 鉴权/限流集成测试

**Files:**
- Create: `app/auth/dependencies.py`
- Modify: `app/main.py`
- Modify: `app/routes/chat.py`
- Modify: `tests/test_chat_endpoint.py`（autouse 绕过 auth）
- Modify: `tests/test_streaming_endpoint.py`（autouse 绕过 auth）
- Modify: `tests/test_cache_endpoint.py`（autouse 绕过 auth）
- Test: `tests/test_auth_endpoint.py`

- [ ] **Step 1: 写 `app/auth/dependencies.py`**

```python
from fastapi import Header, HTTPException, Request

from app.auth.models import ApiKey


def authenticate(request: Request, authorization: str = Header(default="")) -> ApiKey:
    store = request.app.state.key_store
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer ") :].strip()
    api_key = store.get(token)
    if api_key is None:
        raise HTTPException(status_code=401, detail="invalid api key")
    return api_key


def authorize(request: Request, authorization: str = Header(default="")) -> ApiKey:
    """鉴权 → 限流 → 配额 三连。返回通过校验的 ApiKey。"""
    api_key = authenticate(request, authorization)
    limiter = request.app.state.rate_limiter
    if not limiter.allow(api_key.key, api_key.rpm_limit):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    if api_key.remaining_tokens <= 0:
        raise HTTPException(status_code=429, detail="token quota exhausted")
    return api_key
```

- [ ] **Step 2: 修改 `app/main.py`（lifespan 创建 key_store + rate_limiter）**

整体替换为：

```python
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.auth.key_store import build_key_store
from app.auth.rate_limiter import TokenBucketRateLimiter
from app.cache.factory import build_semantic_cache
from app.config import settings
from app.routes.admin import router as admin_router
from app.routes.cache import router as cache_router
from app.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(60.0, connect=10.0)
    app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    app.state.semantic_cache = build_semantic_cache()
    app.state.key_store = build_key_store(
        settings.gateway_api_keys,
        rpm_limit=settings.default_rpm_limit,
        quota_tokens=settings.default_quota_tokens,
    )
    app.state.rate_limiter = TokenBucketRateLimiter()
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(cache_router)
app.include_router(admin_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

> 注：`admin_router` 在 Task 4 创建。**先创建占位的 `app/routes/admin.py`** 以免本步 import 失败——见下一步。

- [ ] **Step 3: 创建占位 `app/routes/admin.py`（Task 4 会补内容）**

```python
from fastapi import APIRouter

router = APIRouter()
```

- [ ] **Step 4: 修改 `app/routes/chat.py`（加 authorize 依赖 + 调用后计费）**

整体替换为：

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.auth.billing import estimate_tokens, record_usage
from app.auth.dependencies import authorize
from app.auth.models import ApiKey
from app.config import settings
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
    """M1：固定返回 MiniMax（已有可用 key）。M4b 会扩展为按 model 路由。
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
    api_key: ApiKey = Depends(authorize),
):
    cache = http_request.app.state.semantic_cache
    price = settings.price_per_1k_tokens

    if request.stream:
        cached = cache.get(request)
        if cached is not None:
            record_usage(api_key, tokens=0, price_per_1k=price)  # 命中不计费
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
            record_usage(api_key, tokens=estimate_tokens(content), price_per_1k=price)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    cached = cache.get(request)
    if cached is not None:
        record_usage(api_key, tokens=0, price_per_1k=price)  # 命中不计费
        return _build_response(request.model, cached)

    resp = await provider.chat(request)
    content = resp.choices[0].message.content if resp.choices else ""
    if content:
        cache.set(request, content)
    record_usage(api_key, tokens=resp.usage.total_tokens, price_per_1k=price)
    return resp
```

- [ ] **Step 5: 给既有 3 个端点测试加 autouse 绕过 auth 的 fixture**

在 `tests/test_chat_endpoint.py`、`tests/test_streaming_endpoint.py`、`tests/test_cache_endpoint.py` 三个文件，各自在 import 区之后、第一个测试之前插入下面这段（三份完全相同）：

```python
import pytest

from app.auth.dependencies import authorize
from app.auth.models import ApiKey


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[authorize] = lambda: ApiKey(
        key="t", name="t", rpm_limit=1_000_000, quota_tokens=10**12
    )
    yield
    app.dependency_overrides.pop(authorize, None)
```

> 这三个文件均已 `from app.main import app`，故 `app` 可用。`pytest` 也可能已导入；重复 import 无害。

- [ ] **Step 6: 写鉴权/限流集成测试 `tests/test_auth_endpoint.py`**

```python
from fastapi.testclient import TestClient

from app.main import app
from app.routes.chat import get_provider
from app.providers.base import Provider
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    Usage,
)

BODY = {
    "model": "m",
    "messages": [{"role": "user", "content": "hi"}],
    "temperature": 0.0,
}


class DummyProvider(Provider):
    name = "dummy"

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            id="x",
            created=1,
            model=request.model,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(role="assistant", content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def stream_chat(self, request: ChatCompletionRequest):
        yield b"data: [DONE]\n\n"


def test_missing_token_is_401():
    with TestClient(app) as client:
        resp = client.post("/v1/chat/completions", json=BODY)
        assert resp.status_code == 401


def test_invalid_token_is_401():
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json=BODY,
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401


def test_valid_token_passes():
    app.dependency_overrides[get_provider] = lambda: DummyProvider()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/v1/chat/completions",
                json=BODY,
                headers={"Authorization": "Bearer dev-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["choices"][0]["message"]["content"] == "ok"
    finally:
        app.dependency_overrides.clear()


def test_rate_limit_returns_429():
    app.dependency_overrides[get_provider] = lambda: DummyProvider()
    try:
        with TestClient(app) as client:
            # 把 dev-key 的 rpm 调到 1，连发两次第二次应 429
            client.app.state.key_store.get("dev-key").rpm_limit = 1
            h = {"Authorization": "Bearer dev-key"}
            r1 = client.post("/v1/chat/completions", json=BODY, headers=h)
            r2 = client.post("/v1/chat/completions", json=BODY, headers=h)
            assert r1.status_code == 200
            assert r2.status_code == 429
    finally:
        app.dependency_overrides.clear()


def test_quota_exhausted_returns_429():
    app.dependency_overrides[get_provider] = lambda: DummyProvider()
    try:
        with TestClient(app) as client:
            k = client.app.state.key_store.get("dev-key")
            k.rpm_limit = 1000
            k.used_tokens = k.quota_tokens  # 配额耗尽
            resp = client.post(
                "/v1/chat/completions",
                json=BODY,
                headers={"Authorization": "Bearer dev-key"},
            )
            assert resp.status_code == 429
    finally:
        app.dependency_overrides.clear()
```

> 注：`test_rate_limit` 与 `test_quota` 直接改 `app.state.key_store` 里 dev-key 的属性；因为同一个 `app` 跨用例共享，每个用例用 `with TestClient(app)` 重新触发 lifespan、重建 key_store，互不污染。

- [ ] **Step 7: 运行全量测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 passed/skip（M3 的 30 passed,1 skipped + Task1 5 + Task2 3 + Task3 鉴权 5 = 43 passed, 1 skipped）。

- [ ] **Step 8: Commit**

```powershell
git add app/auth/dependencies.py app/main.py app/routes/chat.py app/routes/admin.py tests/test_chat_endpoint.py tests/test_streaming_endpoint.py tests/test_cache_endpoint.py tests/test_auth_endpoint.py
git commit -m "feat: API Key 鉴权+令牌桶限流+配额校验 接入端点`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 用量端点 /admin/usage + 计费集成测试

**Files:**
- Modify: `app/routes/admin.py`
- Test: `tests/test_auth_endpoint.py`（追加计费用例）

- [ ] **Step 1: 写 `app/routes/admin.py`（替换占位内容）**

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/admin/usage")
async def usage(request: Request) -> dict:
    store = request.app.state.key_store
    return {
        "keys": [
            {
                "name": k.name,
                "requests": k.requests,
                "used_tokens": k.used_tokens,
                "remaining_tokens": k.remaining_tokens,
                "cost": round(k.cost, 6),
            }
            for k in store.all()
        ]
    }
```

- [ ] **Step 2: 在 `tests/test_auth_endpoint.py` 末尾追加计费集成用例**

```python
def test_billing_records_usage_and_cache_hit_is_free():
    app.dependency_overrides[get_provider] = lambda: DummyProvider()
    try:
        with TestClient(app) as client:
            h = {"Authorization": "Bearer dev-key"}
            # 第一次：未命中，按 usage.total_tokens(=2) 计费
            client.post("/v1/chat/completions", json=BODY, headers=h)
            # 第二次：相同请求命中缓存，0 token、0 成本，但仍计一次 request
            client.post("/v1/chat/completions", json=BODY, headers=h)

            usage = client.get("/admin/usage").json()
            dev = next(k for k in usage["keys"] if k["name"] == "dev-key")
            assert dev["requests"] == 2
            assert dev["used_tokens"] == 2  # 仅第一次计了 2，命中那次 0
            assert dev["cost"] > 0.0
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: 运行全量测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 44 passed, 1 skipped。

- [ ] **Step 4: Commit**

```powershell
git add app/routes/admin.py tests/test_auth_endpoint.py
git commit -m "feat: /admin/usage 用量端点 + 计费集成测试(命中免费)`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 文档 + 手动冒烟

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: 在 `.env.example` 末尾追加鉴权/计费配置**

```
GATEWAY_API_KEYS=dev-key
DEFAULT_RPM_LIMIT=60
DEFAULT_QUOTA_TOKENS=1000000
PRICE_PER_1K_TOKENS=0.001
```

- [ ] **Step 2: 在 `README.md` 末尾追加“鉴权/限流/计费”一节**

```markdown

## 鉴权 / 限流 / 计费（M4a）

- **鉴权**：所有 `/v1/*` 请求需带 `Authorization: Bearer <key>`；key 由 `GATEWAY_API_KEYS`（逗号分隔）配置，无效返回 401。
- **限流**：每个 key 按 `DEFAULT_RPM_LIMIT` 令牌桶限流，超限返回 429。
- **计费**：按 token 计量（`PRICE_PER_1K_TOKENS`），实时扣减配额（`DEFAULT_QUOTA_TOKENS`），耗尽返回 429。**缓存命中不计费**。
- **用量**：`GET /admin/usage` 查看每个 key 的 requests / used_tokens / remaining_tokens / cost。

示例：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# 带 key 调用：
curl -H "Authorization: Bearer dev-key" -H "Content-Type: application/json" `
  -d '{"model":"MiniMax-M2.5","messages":[{"role":"user","content":"hi"}],"temperature":0}' `
  http://127.0.0.1:8000/v1/chat/completions
# 看用量：
curl http://127.0.0.1:8000/admin/usage
```
```

- [ ] **Step 3: 手动冒烟验证（401 与带 key 通过）**

启动网关（下游可指向 Mock 上游）后：
```powershell
# 无 key → 期望 401
(Invoke-WebRequest -Method Post http://127.0.0.1:8000/v1/chat/completions -ContentType 'application/json' -Body '{"model":"MiniMax-M2.5","messages":[{"role":"user","content":"hi"}],"temperature":0}' -SkipHttpErrorCheck).StatusCode
# 带 key → 期望 200，并能在 /admin/usage 看到 used_tokens 增长
```
Expected: 无 key 返回 401；带 `Authorization: Bearer dev-key` 返回 200；`/admin/usage` 中 dev-key 的 requests/used_tokens 增长。

- [ ] **Step 4: Commit**

```powershell
git add README.md .env.example
git commit -m "docs: 鉴权/限流/计费 说明与配置示例`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## M4a 验收标准

- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 全绿（约 44 passed, 1 skipped）。
- [ ] 无 / 错误 Bearer key → 401；正确 key → 200。
- [ ] 超过 rpm → 429；配额耗尽 → 429。
- [ ] 调用按 token 计费、写入 used_tokens/cost；缓存命中计 request 但 0 token、0 成本。
- [ ] `GET /admin/usage` 反映每 key 用量。
- [ ] 既有端点测试经 autouse fixture 绕过 auth，全部仍绿。
- [ ] 所有改动分任务提交。

完成后进入 M4b（多供应商路由 + 熔断降级）。

---

## 测试数量对照

| 阶段 | 累计 |
|---|---|
| M3 结束 | 30 passed, 1 skipped |
| Task 1 后 | 35（+key_store 3, +rate_limiter 2）|
| Task 2 后 | 38（+billing 3）|
| Task 3 后 | 43（+auth_endpoint 5）|
| Task 4 后 | 44（+billing 集成 1）|
| Task 5 后 | 44 passed, 1 skipped（文档/手动）|
