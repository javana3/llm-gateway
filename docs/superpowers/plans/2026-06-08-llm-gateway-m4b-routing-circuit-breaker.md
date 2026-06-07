# LLM 网关 M4b（多供应商路由 + 熔断降级）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让网关在多个供应商间按链路路由，并带每供应商的熔断器——某供应商连续失败即熔断、自动故障转移到备用，冷却后半开探测恢复。

**Architecture:** 三块：`CircuitBreaker`（closed/open/half_open 状态机，注入时钟便于测试）、`ProviderRegistry`（name→Provider 注册表）、`RoutingProvider`（本身实现 `Provider` 接口，按 provider 链逐个尝试，每个 provider 配一个熔断器，失败则记账并转移到下一个；流式仅在"首个分块前"可转移）。`RoutingProvider` 在 lifespan 创建并由 `get_provider` 返回，端点代码零改动。全部失败抛 `AllProvidersUnavailable`，由异常处理器映射为 503。

**Tech Stack:** 纯 Python（状态机/注册表/路由）、FastAPI（异常处理器、health 端点）、pytest。

> **里程碑说明**：本计划覆盖 M4b，承接 M1+M2+M3+M4a（44 passed, 1 skipped）。M4b 完成后核心网关（设计文档 5.1/5.2）即全部落地。
> **存储/环境**：纯内存熔断状态；无需 Docker。venv `.\.venv\Scripts\python.exe`；命令用 PowerShell。
> **真实供应商现状**：仅有 MiniMax 国内区 key。默认 provider 链 = `minimax`（单条）。路由/熔断/转移逻辑用 fake provider 做确定性单测；多供应商链可经 `PROVIDER_CHAIN` 配置，文档给出示例。

---

## 现状（M4a 结束）

```
app/
├── main.py            # lifespan: http_client + semantic_cache + key_store + rate_limiter
├── config.py
├── providers/         # base / openai_compatible / deepseek / minimax
├── cache/  auth/  sse.py
└── routes/
    ├── chat.py        # get_provider 返回 MiniMaxProvider(共享client)
    ├── cache.py       # /cache/stats
    └── admin.py       # /admin/usage
tests/                 # 44 passed, 1 skipped
```

## M4b 结束时新增/修改

```
app/config.py                    # 修改：+ provider_chain / 熔断配置
app/providers/circuit_breaker.py # 新增：CircuitBreaker
app/providers/registry.py        # 新增：ProviderRegistry
app/providers/routing.py         # 新增：RoutingProvider + AllProvidersUnavailable
app/providers/factory.py         # 新增：build_registry + build_routing_provider
app/main.py                      # 修改：lifespan 建 registry+routing_provider；注册 503 异常处理器
app/routes/chat.py               # 修改：get_provider 返回 app.state.routing_provider
app/routes/admin.py              # 修改：+ GET /admin/providers（熔断状态）
tests/test_circuit_breaker.py    # 新增
tests/test_provider_registry.py  # 新增
tests/test_routing_provider.py   # 新增
tests/test_routing_endpoint.py   # 新增（503 + /admin/providers 集成）
README.md                        # 修改：路由/熔断说明
```

---

## Task 1: CircuitBreaker 状态机

**Files:**
- Create: `app/providers/circuit_breaker.py`
- Test: `tests/test_circuit_breaker.py`

- [ ] **Step 1: 写失败测试 `tests/test_circuit_breaker.py`**

```python
from app.providers.circuit_breaker import CircuitBreaker


def test_starts_closed_and_allows():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: 0.0)
    assert cb.state == "closed"
    assert cb.allow() is True


def test_opens_after_threshold_failures():
    t = [0.0]
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: t[0])
    cb.record_failure()
    assert cb.state == "closed"
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow() is False


def test_half_open_after_recovery_then_close_on_success():
    t = [0.0]
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: t[0])
    cb.record_failure()
    cb.record_failure()  # open at t=0
    t[0] = 5
    assert cb.allow() is False  # 冷却未到
    t[0] = 10
    assert cb.allow() is True  # 半开探测
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"


def test_half_open_failure_reopens():
    t = [0.0]
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: t[0])
    cb.record_failure()
    cb.record_failure()
    t[0] = 10
    cb.allow()  # 进入 half_open
    cb.record_failure()
    assert cb.state == "open"


def test_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: 0.0)
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert cb.state == "closed"  # 计数被重置过，未达阈值
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_circuit_breaker.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.providers.circuit_breaker'`。

- [ ] **Step 3: 写 `app/providers/circuit_breaker.py`**

```python
import time
from collections.abc import Callable


class CircuitBreaker:
    """每供应商熔断器。closed → 失败累计达阈值 → open；
    冷却到点 → half_open（放一个探测）；探测成功 → closed，失败 → 重新 open。"""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._now = now
        self.state = "closed"
        self._failures = 0
        self._opened_at = 0.0

    def allow(self) -> bool:
        if self.state == "open":
            if self._now() - self._opened_at >= self.recovery_timeout:
                self.state = "half_open"
                return True
            return False
        return True  # closed 或 half_open

    def record_success(self) -> None:
        self._failures = 0
        self.state = "closed"

    def record_failure(self) -> None:
        if self.state == "half_open":
            self.state = "open"
            self._opened_at = self._now()
            self._failures = 0
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self.state = "open"
            self._opened_at = self._now()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_circuit_breaker.py -v`
Expected: 5 passed。

- [ ] **Step 5: Commit**

```powershell
git add app/providers/circuit_breaker.py tests/test_circuit_breaker.py
git commit -m "feat: CircuitBreaker 状态机(closed/open/half_open)`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: ProviderRegistry

**Files:**
- Create: `app/providers/registry.py`
- Test: `tests/test_provider_registry.py`

- [ ] **Step 1: 写失败测试 `tests/test_provider_registry.py`**

```python
from app.providers.registry import ProviderRegistry


def test_register_get_and_names():
    reg = ProviderRegistry()
    sentinel_a = object()
    sentinel_b = object()
    reg.register("a", sentinel_a)
    reg.register("b", sentinel_b)
    assert reg.get("a") is sentinel_a
    assert reg.get("missing") is None
    assert set(reg.names()) == {"a", "b"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_provider_registry.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.providers.registry'`。

- [ ] **Step 3: 写 `app/providers/registry.py`**

```python
from app.providers.base import Provider


class ProviderRegistry:
    """name → Provider 注册表。"""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, name: str, provider: Provider) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> Provider | None:
        return self._providers.get(name)

    def names(self) -> list[str]:
        return list(self._providers.keys())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_provider_registry.py -v`
Expected: 1 passed。

- [ ] **Step 5: Commit**

```powershell
git add app/providers/registry.py tests/test_provider_registry.py
git commit -m "feat: ProviderRegistry 注册表`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: RoutingProvider（路由 + 熔断 + 故障转移）

**Files:**
- Create: `app/providers/routing.py`
- Test: `tests/test_routing_provider.py`

- [ ] **Step 1: 写失败测试 `tests/test_routing_provider.py`**

```python
import pytest

from app.providers.base import Provider
from app.providers.registry import ProviderRegistry
from app.providers.routing import RoutingProvider, AllProvidersUnavailable
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    Usage,
)


def _resp(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="x",
        created=1,
        model="m",
        choices=[
            Choice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=1),
    )


class WorkingProvider(Provider):
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def chat(self, request):
        self.calls += 1
        return _resp(self.content)

    async def stream_chat(self, request):
        self.calls += 1
        yield f'data: {{"choices":[{{"delta":{{"content":"{self.content}"}}}}]}}\n\n'.encode()
        yield b"data: [DONE]\n\n"


class FailingProvider(Provider):
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, request):
        self.calls += 1
        raise RuntimeError("provider down")

    async def stream_chat(self, request):
        self.calls += 1
        raise RuntimeError("provider down")
        yield b""  # 使其成为异步生成器（永不执行）


def _req() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="m", messages=[ChatMessage(role="user", content="hi")]
    )


def _registry(**providers) -> ProviderRegistry:
    reg = ProviderRegistry()
    for name, p in providers.items():
        reg.register(name, p)
    return reg


async def test_chat_uses_first_healthy_provider():
    work = WorkingProvider("primary")
    reg = _registry(a=work, b=WorkingProvider("backup"))
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=2, recovery_timeout=10)
    resp = await rp.chat(_req())
    assert resp.choices[0].message.content == "primary"


async def test_chat_fails_over_to_backup():
    fail = FailingProvider()
    work = WorkingProvider("backup")
    reg = _registry(a=fail, b=work)
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=2, recovery_timeout=10)
    resp = await rp.chat(_req())
    assert resp.choices[0].message.content == "backup"
    assert fail.calls == 1
    assert work.calls == 1


async def test_circuit_opens_and_skips_provider():
    fail = FailingProvider()
    work = WorkingProvider("backup")
    reg = _registry(a=fail, b=work)
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=2, recovery_timeout=10)
    await rp.chat(_req())  # a 失败 1
    await rp.chat(_req())  # a 失败 2 → 熔断打开
    fail.calls = 0
    await rp.chat(_req())  # a 被跳过，直接打 b
    assert fail.calls == 0


async def test_all_providers_fail_raises():
    reg = _registry(a=FailingProvider(), b=FailingProvider())
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=5, recovery_timeout=10)
    with pytest.raises(AllProvidersUnavailable):
        await rp.chat(_req())


async def test_stream_fails_over_before_first_chunk():
    fail = FailingProvider()
    work = WorkingProvider("backup")
    reg = _registry(a=fail, b=work)
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=2, recovery_timeout=10)
    chunks = [c async for c in rp.stream_chat(_req())]
    body = b"".join(chunks)
    assert b"backup" in body
    assert b"[DONE]" in body
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_routing_provider.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.providers.routing'`。

- [ ] **Step 3: 写 `app/providers/routing.py`**

```python
from collections.abc import AsyncIterator

from app.providers.base import Provider
from app.providers.circuit_breaker import CircuitBreaker
from app.providers.registry import ProviderRegistry
from app.schemas import ChatCompletionRequest, ChatCompletionResponse


class AllProvidersUnavailable(Exception):
    """provider 链里全部不可用（熔断或失败）。"""


class RoutingProvider(Provider):
    """按 provider 链路由 + 每供应商熔断 + 故障转移。本身是一个 Provider。"""

    name = "router"

    def __init__(
        self,
        registry: ProviderRegistry,
        chain: list[str],
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
    ) -> None:
        self.registry = registry
        self.chain = chain
        self.breakers: dict[str, CircuitBreaker] = {
            name: CircuitBreaker(failure_threshold, recovery_timeout)
            for name in chain
        }

    def _candidates(self) -> list[tuple[str, Provider]]:
        out: list[tuple[str, Provider]] = []
        for name in self.chain:
            provider = self.registry.get(name)
            if provider is not None and self.breakers[name].allow():
                out.append((name, provider))
        return out

    def circuit_states(self) -> dict[str, str]:
        return {name: self.breakers[name].state for name in self.chain}

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        last_exc: Exception | None = None
        for name, provider in self._candidates():
            try:
                resp = await provider.chat(request)
                self.breakers[name].record_success()
                return resp
            except Exception as exc:  # noqa: BLE001 - 故障转移需捕获一切
                self.breakers[name].record_failure()
                last_exc = exc
        raise AllProvidersUnavailable(str(last_exc) if last_exc else "no provider")

    async def stream_chat(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[bytes]:
        last_exc: Exception | None = None
        for name, provider in self._candidates():
            agen = provider.stream_chat(request)
            try:
                first = await agen.__anext__()
            except StopAsyncIteration:
                self.breakers[name].record_success()
                return  # 空流也算成功
            except Exception as exc:  # noqa: BLE001
                self.breakers[name].record_failure()
                last_exc = exc
                continue
            # 拿到首块即视为成功；此后无法再转移
            self.breakers[name].record_success()
            yield first
            async for chunk in agen:
                yield chunk
            return
        raise AllProvidersUnavailable(str(last_exc) if last_exc else "no provider")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_routing_provider.py -v`
Expected: 5 passed。

- [ ] **Step 5: Commit**

```powershell
git add app/providers/routing.py tests/test_routing_provider.py
git commit -m "feat: RoutingProvider 路由+熔断+故障转移`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 工厂 + 接入 app（lifespan / get_provider / 503 处理器）

**Files:**
- Modify: `app/config.py`
- Create: `app/providers/factory.py`
- Modify: `app/main.py`
- Modify: `app/routes/chat.py`
- Test: `tests/test_routing_endpoint.py`

- [ ] **Step 1: 在 `app/config.py` 的 Settings 追加配置**

在 `price_per_1k_tokens` 那行之后、`settings = Settings()` 之前插入：

```python
    # ---- 多供应商路由 / 熔断 ----
    provider_chain: str = "minimax"  # 逗号分隔的 provider 名，按序故障转移
    circuit_failure_threshold: int = 3
    circuit_recovery_timeout: float = 10.0
```

- [ ] **Step 2: 写 `app/providers/factory.py`**

```python
import httpx

from app.config import settings
from app.providers.deepseek import DeepSeekProvider
from app.providers.minimax import MiniMaxProvider
from app.providers.registry import ProviderRegistry
from app.providers.routing import RoutingProvider


def build_registry(client: httpx.AsyncClient) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register("minimax", MiniMaxProvider(client=client))
    reg.register("deepseek", DeepSeekProvider(client=client))
    return reg


def build_routing_provider(client: httpx.AsyncClient) -> RoutingProvider:
    reg = build_registry(client)
    chain = [n.strip() for n in settings.provider_chain.split(",") if n.strip()]
    return RoutingProvider(
        reg,
        chain=chain,
        failure_threshold=settings.circuit_failure_threshold,
        recovery_timeout=settings.circuit_recovery_timeout,
    )
```

- [ ] **Step 3: 修改 `app/main.py`（建 routing_provider + 注册 503 异常处理器）**

整体替换为：

```python
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.key_store import build_key_store
from app.auth.rate_limiter import TokenBucketRateLimiter
from app.cache.factory import build_semantic_cache
from app.config import settings
from app.providers.factory import build_routing_provider
from app.providers.routing import AllProvidersUnavailable
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
    app.state.routing_provider = build_routing_provider(app.state.http_client)
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(cache_router)
app.include_router(admin_router)


@app.exception_handler(AllProvidersUnavailable)
async def _all_providers_unavailable(request: Request, exc: AllProvidersUnavailable):
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc) or "all providers unavailable"},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: 修改 `app/routes/chat.py` 的 get_provider（返回 routing_provider）**

把 `get_provider` 函数体替换为：

```python
def get_provider(request: Request) -> Provider:
    """返回应用启动时构建的 RoutingProvider（多供应商路由 + 熔断 + 故障转移）。"""
    return request.app.state.routing_provider
```

并删除 `from app.providers.minimax import MiniMaxProvider` 这一行 import（不再直接用）。其余保持不变。

- [ ] **Step 5: 写集成测试 `tests/test_routing_endpoint.py`**

```python
from fastapi.testclient import TestClient

from app.main import app
from app.providers.registry import ProviderRegistry
from app.providers.routing import RoutingProvider
from app.routes.chat import get_provider
from app.auth.dependencies import authorize
from app.auth.models import ApiKey
from app.providers.base import Provider
from app.schemas import ChatCompletionRequest


class _Down(Provider):
    async def chat(self, request: ChatCompletionRequest):
        raise RuntimeError("down")

    async def stream_chat(self, request: ChatCompletionRequest):
        raise RuntimeError("down")
        yield b""


def _bypass_auth():
    app.dependency_overrides[authorize] = lambda: ApiKey(
        key="t", name="t", rpm_limit=10**9, quota_tokens=10**12
    )


def test_all_providers_down_returns_503():
    reg = ProviderRegistry()
    reg.register("x", _Down())
    rp = RoutingProvider(reg, chain=["x"], failure_threshold=5, recovery_timeout=10)
    app.dependency_overrides[get_provider] = lambda: rp
    _bypass_auth()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "m",
                    "messages": [{"role": "user", "content": "hi"}],
                    "temperature": 0.0,
                },
            )
            assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_admin_providers_reports_circuit_states():
    with TestClient(app) as client:
        data = client.get("/admin/providers").json()
        # 默认链含 minimax，状态初始为 closed
        assert "minimax" in data["circuits"]
        assert data["circuits"]["minimax"] == "closed"
```

- [ ] **Step 6: 运行全量测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 passed/skip（M4a 的 44 passed,1 skipped + Task1 5 + Task2 1 + Task3 5 + Task4 集成 2 = 57 passed, 1 skipped）。
> 说明：`/admin/providers` 端点在 Task 5 实现；本步的 `test_admin_providers_reports_circuit_states` 会先失败 → 在 Task 5 实现后转绿。**因此本步只先运行除该用例外的测试**：
> Run: `.\.venv\Scripts\python.exe -m pytest -q --deselect tests/test_routing_endpoint.py::test_admin_providers_reports_circuit_states`
> Expected: 56 passed, 1 skipped。

- [ ] **Step 7: Commit**

```powershell
git add app/config.py app/providers/factory.py app/main.py app/routes/chat.py tests/test_routing_endpoint.py
git commit -m "feat: 接入 RoutingProvider(lifespan/get_provider) 与 503 处理器`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: /admin/providers 熔断状态端点 + 文档

**Files:**
- Modify: `app/routes/admin.py`
- Modify: `README.md`

- [ ] **Step 1: 在 `app/routes/admin.py` 追加 providers 端点**

在文件末尾追加：

```python
@router.get("/admin/providers")
async def providers(request: Request) -> dict:
    rp = request.app.state.routing_provider
    return {"chain": rp.chain, "circuits": rp.circuit_states()}
```

- [ ] **Step 2: 运行全量测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 57 passed, 1 skipped。

- [ ] **Step 3: 在 `README.md` 末尾追加“多供应商路由 / 熔断”一节**

```markdown

## 多供应商路由 / 熔断降级（M4b）

- **路由链**：`PROVIDER_CHAIN`（逗号分隔的 provider 名，如 `minimax,deepseek`）按序尝试。
- **故障转移**：链中某 provider 调用失败，自动转移到下一个；流式仅在"首个分块前"可转移。
- **熔断**：每个 provider 一个熔断器，连续失败达 `CIRCUIT_FAILURE_THRESHOLD` 即熔断（跳过），冷却 `CIRCUIT_RECOVERY_TIMEOUT` 秒后半开探测，成功则恢复。
- **全部不可用** → 503。
- **状态**：`GET /admin/providers` 查看链与各 provider 熔断状态。

```powershell
$env:PROVIDER_CHAIN = "minimax,deepseek"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
curl http://127.0.0.1:8000/admin/providers
```
```

- [ ] **Step 4: 手动冒烟验证**

启动网关（下游指向 Mock 上游）后：
```powershell
.\.venv\Scripts\python.exe -c "import httpx; print(httpx.get('http://127.0.0.1:8000/admin/providers').json())"
```
Expected: 打印 `{'chain': ['minimax'], 'circuits': {'minimax': 'closed'}}`（或你配置的链）。

- [ ] **Step 5: Commit**

```powershell
git add app/routes/admin.py README.md
git commit -m "feat: /admin/providers 熔断状态端点 + 路由文档`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## M4b 验收标准

- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 全绿（约 57 passed, 1 skipped）。
- [ ] 链中首个健康 provider 优先；失败自动转移到下一个。
- [ ] 某 provider 连续失败达阈值 → 熔断、后续被跳过；冷却后半开探测恢复。
- [ ] 流式在首块前可转移。
- [ ] 全部不可用 → 503。
- [ ] `GET /admin/providers` 反映链与熔断状态。
- [ ] 既有端点测试（override get_provider）不受影响，全绿。
- [ ] 所有改动分任务提交。

完成后：核心网关（设计文档 5.1 路由/容灾 + 5.2 鉴权/限流/计费 + 4.1 流式 + 4.2 缓存）全部落地。可选收尾：Prometheus 指标 + Docker Compose 一键编排（设计文档 7/8 节）。

---

## 测试数量对照

| 阶段 | 累计 |
|---|---|
| M4a 结束 | 44 passed, 1 skipped |
| Task 1 后 | 49（+circuit_breaker 5）|
| Task 2 后 | 50（+registry 1）|
| Task 3 后 | 55（+routing_provider 5）|
| Task 4 后 | 56（+routing_endpoint 1，另 1 用例在 Task5 转绿）|
| Task 5 后 | 57 passed, 1 skipped |
