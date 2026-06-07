# LLM 网关 M5（Prometheus 指标）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给网关加 Prometheus 指标——`/metrics` 暴露 HTTP 请求量/延迟、缓存命中/未命中、计费 token 总量，供 Grafana 抓取出图。

**Architecture:** 单一 `app/metrics.py` 定义全局指标对象（Counter/Histogram，用默认 registry）。`main.py` 加一个 HTTP 中间件，对每个请求记录数量与延迟。chat 端点在缓存命中/未命中与计费处增量对应计数器。`/metrics` 端点用 `prometheus_client.generate_latest` 输出标准文本格式。

**Tech Stack:** prometheus-client、FastAPI（中间件 + Response）、pytest。

> **里程碑说明**：本计划覆盖 M5（可观测性，设计文档 7 节的指标部分）。承接 M1–M4b（57 passed, 1 skipped）。纯代码、无需 Docker，可完整测通。Grafana/Docker Compose 编排留待 Docker 可用时单独做。
> **环境**：venv `.\.venv\Scripts\python.exe`；命令用 PowerShell。

---

## 现状（M4b 结束）

```
app/
├── main.py            # lifespan + 503 处理器
├── config.py
├── metrics.py         # ← 本里程碑新增
├── providers/  cache/  auth/  sse.py
└── routes/
    ├── chat.py        # /v1/chat/completions（鉴权+缓存+路由+流式+计费）
    ├── cache.py       # /cache/stats
    └── admin.py       # /admin/usage, /admin/providers
tests/                 # 57 passed, 1 skipped
```

## M5 结束时新增/修改

```
requirements.txt          # 修改：+ prometheus-client
app/metrics.py            # 新增：指标定义
app/routes/metrics.py     # 新增：GET /metrics
app/main.py               # 修改：HTTP 计量中间件 + 挂载 metrics 路由
app/routes/chat.py        # 修改：缓存命中/未命中、token 计数
tests/test_metrics.py     # 新增
README.md                 # 修改：指标说明
```

---

## Task 1: 指标定义 + /metrics 端点 + HTTP 中间件

**Files:**
- Modify: `requirements.txt`
- Create: `app/metrics.py`
- Create: `app/routes/metrics.py`
- Modify: `app/main.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: 在 `requirements.txt` 末尾追加依赖**

在文件末尾追加一行：
```
prometheus-client>=0.20
```

- [ ] **Step 2: 安装依赖**

Run: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt --progress-bar off`
Expected: 安装成功（prometheus-client 很小，秒装）。

- [ ] **Step 3: 写 `app/metrics.py`**

```python
from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "gateway_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "gateway_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["path"],
)
CACHE_HITS = Counter("gateway_cache_hits_total", "Semantic cache hits")
CACHE_MISSES = Counter("gateway_cache_misses_total", "Semantic cache misses")
TOKENS = Counter("gateway_tokens_total", "Total billed tokens")
```

- [ ] **Step 4: 写 `app/routes/metrics.py`**

```python
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

- [ ] **Step 5: 修改 `app/main.py`（加 HTTP 计量中间件 + 挂载 metrics 路由）**

在 import 区追加：
```python
import time
```
并把
```python
from app.providers.factory import build_routing_provider
```
之后追加：
```python
from app.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.routes.metrics import router as metrics_router
```

在 `app.include_router(admin_router)` 之后追加：
```python
app.include_router(metrics_router)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    HTTP_LATENCY.labels(path=path).observe(elapsed)
    HTTP_REQUESTS.labels(
        method=request.method, path=path, status=response.status_code
    ).inc()
    return response
```

- [ ] **Step 6: 写失败测试 `tests/test_metrics.py`**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_metrics_endpoint_exposes_prometheus_format():
    with TestClient(app) as client:
        client.get("/health")  # 先产生一次请求
        resp = client.get("/metrics")
        assert resp.status_code == 200
        body = resp.text
        # 标准 prometheus 文本格式，含我们定义的指标族
        assert "gateway_http_requests_total" in body
        assert "gateway_http_request_duration_seconds" in body


def test_http_requests_counter_increments_for_health():
    with TestClient(app) as client:
        client.get("/health")
        body = client.get("/metrics").text
        # /health 至少被计数一次（labels 里含 path="/health"）
        assert 'path="/health"' in body
```

- [ ] **Step 7: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_metrics.py -v`
Expected: 2 passed。

- [ ] **Step 8: 运行全量测试确认无回归**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 59 passed, 1 skipped。

- [ ] **Step 9: Commit**

```powershell
git add requirements.txt app/metrics.py app/routes/metrics.py app/main.py tests/test_metrics.py
git commit -m "feat: Prometheus 指标定义 + /metrics + HTTP 计量中间件`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 业务指标埋点（缓存命中/未命中、token）

**Files:**
- Modify: `app/routes/chat.py`
- Test: `tests/test_metrics.py`（追加用例）

- [ ] **Step 1: 修改 `app/routes/chat.py`（在缓存/计费处埋点）**

在 import 区追加：
```python
from app.metrics import CACHE_HITS, CACHE_MISSES, TOKENS
```

在流式分支：把
```python
        cached = cache.get(request)
        if cached is not None:
            record_usage(api_key, tokens=0, price_per_1k=price)  # 命中不计费
            return StreamingResponse(
                replay_content_as_sse(cached), media_type="text/event-stream"
            )
```
改为
```python
        cached = cache.get(request)
        if cached is not None:
            CACHE_HITS.inc()
            record_usage(api_key, tokens=0, price_per_1k=price)  # 命中不计费
            return StreamingResponse(
                replay_content_as_sse(cached), media_type="text/event-stream"
            )
```

并把流式 `event_stream` 内的
```python
            content = assemble_content_from_sse(b"".join(parts))
            if content:
                cache.set(request, content)
            record_usage(api_key, tokens=estimate_tokens(content), price_per_1k=price)
```
改为
```python
            content = assemble_content_from_sse(b"".join(parts))
            if content:
                cache.set(request, content)
            CACHE_MISSES.inc()
            tokens = estimate_tokens(content)
            TOKENS.inc(tokens)
            record_usage(api_key, tokens=tokens, price_per_1k=price)
```

在非流式分支：把
```python
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
改为
```python
    cached = cache.get(request)
    if cached is not None:
        CACHE_HITS.inc()
        record_usage(api_key, tokens=0, price_per_1k=price)  # 命中不计费
        return _build_response(request.model, cached)

    resp = await provider.chat(request)
    content = resp.choices[0].message.content if resp.choices else ""
    if content:
        cache.set(request, content)
    CACHE_MISSES.inc()
    TOKENS.inc(resp.usage.total_tokens)
    record_usage(api_key, tokens=resp.usage.total_tokens, price_per_1k=price)
    return resp
```

- [ ] **Step 2: 在 `tests/test_metrics.py` 末尾追加埋点集成用例**

```python
def test_cache_metrics_increment_on_chat():
    from app.auth.dependencies import authorize
    from app.auth.models import ApiKey
    from app.routes.chat import get_provider
    from app.providers.base import Provider
    from app.schemas import (
        ChatCompletionRequest,
        ChatCompletionResponse,
        ChatMessage,
        Choice,
        Usage,
    )

    class _P(Provider):
        async def chat(self, request: ChatCompletionRequest):
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
            yield b"data: [DONE]\n\n"

    app.dependency_overrides[get_provider] = lambda: _P()
    app.dependency_overrides[authorize] = lambda: ApiKey(
        key="t", name="t", rpm_limit=10**9, quota_tokens=10**12
    )
    try:
        with TestClient(app) as client:
            body = {
                "model": "m",
                "messages": [{"role": "user", "content": "capital of France"}],
                "temperature": 0.0,
            }
            client.post("/v1/chat/completions", json=body)  # miss
            client.post("/v1/chat/completions", json=body)  # hit
            text = client.get("/metrics").text
            assert "gateway_cache_misses_total" in text
            assert "gateway_cache_hits_total" in text
            assert "gateway_tokens_total" in text
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: 运行全量测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 60 passed, 1 skipped。

- [ ] **Step 4: Commit**

```powershell
git add app/routes/chat.py tests/test_metrics.py
git commit -m "feat: 缓存命中/未命中与 token 指标埋点`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 文档 + 手动冒烟

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 `README.md` 末尾追加“指标 / 可观测性”一节**

```markdown

## 指标 / 可观测性（M5）

- `GET /metrics` 暴露 Prometheus 文本格式指标：
  - `gateway_http_requests_total{method,path,status}` —— 请求量
  - `gateway_http_request_duration_seconds{path}` —— 延迟直方图（可算 P50/P95/P99）
  - `gateway_cache_hits_total` / `gateway_cache_misses_total` —— 缓存命中/未命中
  - `gateway_tokens_total` —— 计费 token 总量
- 用 Prometheus 抓取 `/metrics`，再在 Grafana 出 QPS / 延迟分位 / 缓存命中率 大盘。

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
curl http://127.0.0.1:8000/metrics
```
```

- [ ] **Step 2: 手动冒烟验证**

启动网关后：
```powershell
.\.venv\Scripts\python.exe -c "import httpx; print('gateway_http_requests_total' in httpx.get('http://127.0.0.1:8000/metrics').text)"
```
Expected: 打印 `True`。

- [ ] **Step 3: Commit**

```powershell
git add README.md
git commit -m "docs: 指标/可观测性说明`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## M5 验收标准

- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 全绿（约 60 passed, 1 skipped）。
- [ ] `GET /metrics` 返回 Prometheus 文本格式，含 HTTP/缓存/token 指标族。
- [ ] HTTP 中间件对每个请求计数并记录延迟。
- [ ] chat 端点在命中/未命中、计费处正确埋点。
- [ ] 所有改动分任务提交。

完成后：可观测性（指标）落地。剩余可选收尾仅 Docker Compose 编排（需 Docker）。

---

## 测试数量对照

| 阶段 | 累计 |
|---|---|
| M4b 结束 | 57 passed, 1 skipped |
| Task 1 后 | 59（+metrics 2）|
| Task 2 后 | 60（+metrics 集成 1）|
| Task 3 后 | 60 passed, 1 skipped（文档/手动）|
