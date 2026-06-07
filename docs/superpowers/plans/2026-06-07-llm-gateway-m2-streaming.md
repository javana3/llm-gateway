# LLM 网关 M2（高并发异步流式转发）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让网关支持 OpenAI 兼容的 SSE 流式转发——边收边转、连接池复用、客户端断开即取消下游；并提供本地 Mock 上游与压测脚本，产出第一版并发/延迟数据。

**Architecture:** 在 `Provider` 接口上新增 `stream_chat`（异步生成器，逐块 yield 下游 SSE 字节）。`OpenAICompatibleProvider` 用 `httpx` 的 `client.stream(...)` + `aiter_bytes()` 实现真流式。应用启动时（lifespan）创建一个带连接池上限的共享 `httpx.AsyncClient`，所有请求复用它。`/v1/chat/completions` 在 `stream=True` 时返回 `StreamingResponse`，逐块转发并在客户端断开时停止。压测打本地 Mock 上游（可配 token 数/延迟），用异步脚本测 QPS 与 P50/P95/P99。

**Tech Stack:** FastAPI（StreamingResponse、lifespan）、httpx（AsyncClient.stream、Limits 连接池）、pytest + respx。

> **里程碑说明**：本计划只覆盖 M2，承接已完成的 M1。M3（语义缓存）等后续里程碑各自单独成计划。
> **环境**：venv 解释器 `.\.venv\Scripts\python.exe`；命令用 PowerShell；测试 `.\.venv\Scripts\python.exe -m pytest`。

---

## 现状（M1 结束时已有）

```
app/
├── main.py                 # FastAPI app + /health
├── config.py               # settings（deepseek_*, minimax_*）
├── schemas.py              # OpenAI 兼容模型
├── providers/
│   ├── base.py             # Provider 抽象（仅 chat）
│   ├── openai_compatible.py# OpenAICompatibleProvider（仅 chat，每次新建 client）
│   ├── deepseek.py         # DeepSeekProvider
│   └── minimax.py          # MiniMaxProvider（默认供应商）
└── routes/chat.py          # POST /v1/chat/completions（仅非流式）+ get_provider
tests/                      # 7 个测试全绿
```

## M2 结束时新增/修改的文件

```
app/providers/base.py            # 修改：新增抽象 stream_chat
app/providers/openai_compatible.py # 修改：共享 client 支持 + _client ctx + stream_chat
app/providers/deepseek.py        # 修改：__init__ 增加 client 参数
app/providers/minimax.py         # 修改：__init__ 增加 client 参数
app/main.py                      # 修改：lifespan 创建共享连接池 client
app/routes/chat.py               # 修改：get_provider 用共享 client；端点支持流式分支
mock_upstream/__init__.py        # 新增（空）
mock_upstream/app.py             # 新增：本地假大模型，SSE 逐 token 吐
scripts/loadtest.py              # 新增：异步压测脚本
tests/test_streaming_provider.py # 新增：provider 流式 respx 测试
tests/test_streaming_endpoint.py # 新增：端点流式 TestClient 测试
tests/test_lifespan.py           # 新增：共享 client 生命周期测试
tests/test_mock_upstream.py      # 新增：mock 上游 SSE 测试
tests/test_chat_endpoint.py      # 修改：FakeProvider 增加 stream_chat 桩
README.md                        # 修改：压测说明
```

---

## Task 1: Provider 流式能力（接口 + OpenAI 兼容实现 + 共享 client 支持）

**Files:**
- Modify: `app/providers/base.py`
- Modify: `app/providers/openai_compatible.py`
- Modify: `app/providers/deepseek.py`
- Modify: `app/providers/minimax.py`
- Modify: `tests/test_chat_endpoint.py`（给 FakeProvider 补 stream_chat 桩，避免抽象类实例化失败）
- Test: `tests/test_streaming_provider.py`

- [ ] **Step 1: 写失败测试 `tests/test_streaming_provider.py`**

```python
import httpx
import respx

from app.providers.minimax import MiniMaxProvider
from app.schemas import ChatCompletionRequest, ChatMessage


@respx.mock
async def test_stream_chat_yields_downstream_sse_chunks():
    sse = (
        b'data: {"choices":[{"index":0,"delta":{"content":"he"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{"content":"llo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    route = respx.post("https://api.minimaxi.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=sse)
    )

    provider = MiniMaxProvider(
        api_key="test-key", base_url="https://api.minimaxi.com/v1"
    )
    req = ChatCompletionRequest(
        model="MiniMax-M2.5",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    chunks = [chunk async for chunk in provider.stream_chat(req)]
    body = b"".join(chunks)

    assert route.called
    # 下游被强制带上 stream=True
    sent_body = route.calls.last.request.content
    assert b'"stream": true' in sent_body or b'"stream":true' in sent_body
    # 两段 delta 与结束标记都被透传
    assert b'"he"' in body
    assert b'"llo"' in body
    assert b"[DONE]" in body
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_streaming_provider.py -v`
Expected: FAIL，`AttributeError: 'MiniMaxProvider' object has no attribute 'stream_chat'`（或抽象方法相关错误）。

- [ ] **Step 3: 修改 `app/providers/base.py`（新增抽象 stream_chat）**

整体替换为：

```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schemas import ChatCompletionRequest, ChatCompletionResponse


class Provider(ABC):
    """所有下游大模型供应商适配器的统一接口。"""

    name: str

    @abstractmethod
    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """非流式：发送一次请求，返回完整响应。"""
        ...

    @abstractmethod
    def stream_chat(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[bytes]:
        """流式：返回一个异步生成器，逐块 yield 下游 SSE 原始字节。"""
        ...
```

> 说明：`stream_chat` 是异步生成器函数，签名返回 `AsyncIterator[bytes]`，不写 `async def`/`await` 在抽象声明里（声明用普通 `def` 返回类型即可）。

- [ ] **Step 4: 修改 `app/providers/openai_compatible.py`（共享 client + _client ctx + stream_chat）**

整体替换为：

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.providers.base import Provider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse


class OpenAICompatibleProvider(Provider):
    """复用于所有 OpenAI 兼容的下游供应商（DeepSeek / MiniMax / ...）。

    若传入共享的 httpx.AsyncClient（连接池复用），则复用之且不主动关闭；
    否则每次调用临时新建一个 client（M1 行为，便于测试）。
    """

    def __init__(
        self,
        name: str,
        api_key: str,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.client = client

    @property
    def _url(self) -> str:
        # 显式拼完整 URL，避免 httpx base_url 含 /v1 时被绝对路径覆盖丢段。
        return f"{self.base_url.rstrip('/')}/chat/completions"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    @asynccontextmanager
    async def _acquire(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.client is not None:
            yield self.client
        else:
            async with httpx.AsyncClient(timeout=60.0) as client:
                yield client

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        async with self._acquire() as client:
            resp = await client.post(
                self._url,
                headers=self._headers,
                json=request.model_dump(exclude_none=True),
            )
            resp.raise_for_status()
            return ChatCompletionResponse.model_validate(resp.json())

    async def stream_chat(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[bytes]:
        payload = request.model_dump(exclude_none=True)
        payload["stream"] = True
        async with self._acquire() as client:
            async with client.stream(
                "POST", self._url, headers=self._headers, json=payload
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk
```

- [ ] **Step 5: 修改 `app/providers/deepseek.py`（增加 client 参数）**

整体替换为：

```python
import httpx

from app.config import settings
from app.providers.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            name="deepseek",
            api_key=api_key or settings.deepseek_api_key,
            base_url=base_url or settings.deepseek_base_url,
            client=client,
        )
```

- [ ] **Step 6: 修改 `app/providers/minimax.py`（增加 client 参数）**

整体替换为：

```python
import httpx

from app.config import settings
from app.providers.openai_compatible import OpenAICompatibleProvider


class MiniMaxProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            name="minimax",
            api_key=api_key or settings.minimax_api_key,
            base_url=base_url or settings.minimax_base_url,
            client=client,
        )
```

- [ ] **Step 7: 修改 `tests/test_chat_endpoint.py` 的 FakeProvider，补 stream_chat 桩**

在 `FakeProvider` 类里，`chat` 方法之后追加：

```python
    async def stream_chat(self, request: ChatCompletionRequest):
        yield b'data: {"choices":[{"index":0,"delta":{"content":"pong"}}]}\n\n'
        yield b"data: [DONE]\n\n"
```

- [ ] **Step 8: 运行流式 provider 测试 + 全量测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: 全部 passed（原 7 个 + 新增 1 个 = 8 passed）。

- [ ] **Step 9: Commit**

```powershell
git add app/providers/base.py app/providers/openai_compatible.py app/providers/deepseek.py app/providers/minimax.py tests/test_chat_endpoint.py tests/test_streaming_provider.py
git commit -m "feat: Provider 流式能力(stream_chat)与共享 client 支持`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 共享连接池（应用 lifespan）

**Files:**
- Modify: `app/main.py`
- Modify: `app/routes/chat.py`（get_provider 用共享 client）
- Test: `tests/test_lifespan.py`

- [ ] **Step 1: 写失败测试 `tests/test_lifespan.py`**

```python
import httpx
from fastapi.testclient import TestClient

from app.main import app


def test_lifespan_creates_and_exposes_shared_client():
    # 进入 TestClient 上下文会触发 startup/shutdown 生命周期
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        shared = app.state.http_client
        assert isinstance(shared, httpx.AsyncClient)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_lifespan.py -v`
Expected: FAIL，`AttributeError: 'State' object has no attribute 'http_client'`。

- [ ] **Step 3: 修改 `app/main.py`（lifespan 创建共享连接池 client）**

整体替换为：

```python
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 共享连接池：所有请求复用，避免每请求重建 TCP/TLS。
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(60.0, connect=10.0)
    app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)
app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: 修改 `app/routes/chat.py` 的 get_provider（注入共享 client）**

把 `get_provider` 函数替换为（其余先不动）：

```python
def get_provider(request: Request) -> Provider:
    """M1：固定返回 MiniMax（已有可用 key）。M4 会扩展为按 model 路由。
    复用应用启动时创建的共享 httpx.AsyncClient（连接池）。"""
    return MiniMaxProvider(client=request.app.state.http_client)
```

并在文件顶部 import 中加入 `Request`：把
`from fastapi import APIRouter, Depends`
改为
`from fastapi import APIRouter, Depends, Request`

- [ ] **Step 5: 运行全量测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: 全部 passed（8 + 1 = 9 passed）。
> 说明：`test_chat_endpoint.py` 用 `dependency_overrides` 覆盖了 `get_provider`，不受新签名影响。

- [ ] **Step 6: Commit**

```powershell
git add app/main.py app/routes/chat.py tests/test_lifespan.py
git commit -m "feat: 共享 httpx 连接池(lifespan)并注入 provider`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 流式端点（SSE 边收边转 + 断开取消）

**Files:**
- Modify: `app/routes/chat.py`
- Test: `tests/test_streaming_endpoint.py`

- [ ] **Step 1: 写失败测试 `tests/test_streaming_endpoint.py`**

```python
from fastapi.testclient import TestClient

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


class StreamingFakeProvider(Provider):
    name = "streamfake"

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            id="x",
            created=1,
            model=request.model,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(role="assistant", content="full"),
                    finish_reason="stop",
                )
            ],
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def stream_chat(self, request: ChatCompletionRequest):
        yield b'data: {"choices":[{"index":0,"delta":{"content":"a"}}]}\n\n'
        yield b'data: {"choices":[{"index":0,"delta":{"content":"b"}}]}\n\n'
        yield b"data: [DONE]\n\n"


def test_stream_true_returns_event_stream():
    app.dependency_overrides[get_provider] = lambda: StreamingFakeProvider()
    try:
        client = TestClient(app)
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "MiniMax-M2.5",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = b"".join(resp.iter_bytes())
        assert b'"a"' in body
        assert b'"b"' in body
        assert b"[DONE]" in body
    finally:
        app.dependency_overrides.clear()


def test_stream_false_still_returns_json():
    app.dependency_overrides[get_provider] = lambda: StreamingFakeProvider()
    try:
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "MiniMax-M2.5",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "full"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_streaming_endpoint.py -v`
Expected: FAIL（`test_stream_true_returns_event_stream` 失败：当前端点对 stream 不分支，content-type 不是 text/event-stream）。

- [ ] **Step 3: 修改 `app/routes/chat.py`（端点流式分支 + 断开取消）**

整体替换为：

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.providers.base import Provider
from app.providers.minimax import MiniMaxProvider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter()


def get_provider(request: Request) -> Provider:
    """M1：固定返回 MiniMax（已有可用 key）。M4 会扩展为按 model 路由。
    复用应用启动时创建的共享 httpx.AsyncClient（连接池）。"""
    return MiniMaxProvider(client=request.app.state.http_client)


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    http_request: Request,
    provider: Provider = Depends(get_provider),
):
    if request.stream:

        async def event_stream():
            async for chunk in provider.stream_chat(request):
                # 客户端断开则停止拉取下游，释放连接，避免“幽灵请求”。
                if await http_request.is_disconnected():
                    break
                yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return await provider.chat(request)
```

> 注意：移除了原来的 `response_model=ChatCompletionResponse`（与 StreamingResponse 返回冲突）。非流式分支返回 Pydantic 模型，FastAPI 仍会正确序列化为 JSON。

- [ ] **Step 4: 运行全量测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: 全部 passed（9 + 2 = 11 passed）。

- [ ] **Step 5: Commit**

```powershell
git add app/routes/chat.py tests/test_streaming_endpoint.py
git commit -m "feat: /v1/chat/completions 支持 SSE 流式转发与断开取消`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 本地 Mock 上游（压测专用假大模型）

**Files:**
- Create: `mock_upstream/__init__.py`（空）
- Create: `mock_upstream/app.py`
- Test: `tests/test_mock_upstream.py`

- [ ] **Step 1: 写失败测试 `tests/test_mock_upstream.py`**

```python
from fastapi.testclient import TestClient

from mock_upstream.app import app


def test_mock_streams_sse_with_done():
    client = TestClient(app)
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "mock",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = b"".join(resp.iter_bytes())
    assert b"data:" in body
    assert b"[DONE]" in body


def test_mock_non_stream_returns_openai_shape():
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["usage"]["total_tokens"] >= 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mock_upstream.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'mock_upstream'`。

- [ ] **Step 3: 建空文件 `mock_upstream/__init__.py`**

创建空文件 `mock_upstream/__init__.py`。

- [ ] **Step 4: 写 `mock_upstream/app.py`**

```python
"""本地 Mock 上游：模拟一个 OpenAI 兼容的大模型服务，用于压测网关本身。

通过环境变量调参：
    MOCK_TOKENS  每次响应吐多少个 token（默认 20）
    MOCK_DELAY   每个 token 之间的间隔秒数（默认 0.01，模拟生成耗时）
"""
import asyncio
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="Mock LLM Upstream")

N_TOKENS = int(os.getenv("MOCK_TOKENS", "20"))
DELAY = float(os.getenv("MOCK_DELAY", "0.01"))


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    payload = await request.json()
    stream = bool(payload.get("stream", False))

    if stream:

        async def gen():
            for _ in range(N_TOKENS):
                chunk = {
                    "choices": [
                        {"index": 0, "delta": {"content": "x"}, "finish_reason": None}
                    ]
                }
                yield f"data: {json.dumps(chunk)}\n\n".encode()
                await asyncio.sleep(DELAY)
            yield b"data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    await asyncio.sleep(DELAY * N_TOKENS)
    return {
        "id": "mock-completion",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "mock",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "x" * N_TOKENS},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": N_TOKENS,
            "total_tokens": N_TOKENS + 1,
        },
    }
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mock_upstream.py -v`
Expected: 2 passed。

- [ ] **Step 6: Commit**

```powershell
git add mock_upstream/__init__.py mock_upstream/app.py tests/test_mock_upstream.py
git commit -m "feat: 本地 Mock 上游(SSE 逐token，延迟可配)用于压测`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 压测脚本与文档

**Files:**
- Create: `scripts/loadtest.py`
- Modify: `README.md`

- [ ] **Step 1: 写 `scripts/loadtest.py`**

```python
"""异步压测脚本：对网关发起 N 个并发流式请求，统计 QPS 与延迟分位。

压测前请将网关的下游指向本地 Mock 上游（见 README“压测”一节），
这样测的是网关本身的转发/并发能力，而非真实 API 的延迟。

用法：
    .\\.venv\\Scripts\\python.exe scripts/loadtest.py --concurrency 50 --total 500
"""
import argparse
import asyncio
import time

import httpx


async def one_request(client: httpx.AsyncClient, url: str, payload: dict) -> float:
    t0 = time.perf_counter()
    async with client.stream("POST", url, json=payload) as resp:
        async for _ in resp.aiter_bytes():
            pass
    return time.perf_counter() - t0


async def run(concurrency: int, total: int, url: str, payload: dict) -> None:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        async def worker() -> None:
            async with sem:
                latencies.append(await one_request(client, url, payload))

        t0 = time.perf_counter()
        await asyncio.gather(*[worker() for _ in range(total)])
        wall = time.perf_counter() - t0

    latencies.sort()

    def pct(p: float) -> float:
        idx = max(0, int(len(latencies) * p) - 1)
        return latencies[idx] * 1000

    print(
        f"concurrency={concurrency} total={total} "
        f"wall={wall:.2f}s QPS={total / wall:.1f} "
        f"P50={pct(0.5):.0f}ms P95={pct(0.95):.0f}ms P99={pct(0.99):.0f}ms"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions")
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--total", type=int, default=500)
    args = ap.parse_args()

    payload = {
        "model": "MiniMax-M2.5",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": True,
    }
    asyncio.run(run(args.concurrency, args.total, args.url, payload))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 在 `README.md` 末尾追加“压测”一节**

```markdown

## 压测（M2）

压测打**本地 Mock 上游**而非真实 API，这样测的是网关本身的转发/并发能力。

```powershell
# 终端 A：启动 Mock 上游（可调 token 数与每 token 延迟）
$env:MOCK_TOKENS = "20"; $env:MOCK_DELAY = "0.01"
.\.venv\Scripts\python.exe -m uvicorn mock_upstream.app:app --port 9000

# 终端 B：让网关的下游指向 Mock，再启动网关
$env:MINIMAX_BASE_URL = "http://127.0.0.1:9000/v1"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 终端 C：发起压测
.\.venv\Scripts\python.exe scripts/loadtest.py --concurrency 50 --total 500
```

输出示例：
`concurrency=50 total=500 wall=2.41s QPS=207.5 P50=210ms P95=360ms P99=520ms`

逐步加大 `--concurrency`（如 10 / 50 / 100 / 200）记录 QPS 与 P95/P99，即可得到第一版并发-延迟数据。
```

- [ ] **Step 3: 端到端压测冒烟验证（小规模）**

按上面三个终端启动 Mock 上游与网关后，运行小规模压测确认链路通：
```powershell
.\.venv\Scripts\python.exe scripts/loadtest.py --concurrency 10 --total 50
```
Expected: 打印一行 `concurrency=10 total=50 ... QPS=... P50=... P95=... P99=...`，无报错。

- [ ] **Step 4: Commit**

```powershell
git add scripts/loadtest.py README.md
git commit -m "feat: 异步压测脚本与压测文档`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## M2 验收标准

- [ ] `.\.venv\Scripts\python.exe -m pytest -v` 全绿（共 13 个测试：M1 的 7 + M2 的 6）。
- [ ] `stream=True` 时 `/v1/chat/completions` 返回 `text/event-stream`，逐块转发下游 SSE，含 `[DONE]`。
- [ ] `stream=False` 时仍返回标准 JSON（向后兼容）。
- [ ] 应用启动创建共享 httpx 连接池，provider 复用之。
- [ ] Mock 上游能 SSE 逐 token 吐，延迟/数量可配。
- [ ] 压测脚本能跑出 QPS 与 P50/P95/P99 数据。
- [ ] 所有改动分任务提交。

完成后进入 M3（语义缓存）的计划编写。

---

## 测试数量对照（便于核对）

| 阶段 | 累计测试数 |
|---|---|
| M1 结束 | 7 |
| Task 1 后 | 8（+streaming_provider）|
| Task 2 后 | 9（+lifespan）|
| Task 3 后 | 11（+streaming_endpoint 2 个）|
| Task 4 后 | 13（+mock_upstream 2 个）|
| Task 5 后 | 13（压测为手动验证，不加单测）|
