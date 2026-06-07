# LLM 网关 M1（骨架 + 非流式转发）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭好 FastAPI 项目骨架，实现一个 OpenAI 兼容的 `/v1/chat/completions` 接口，通过 DeepSeek 适配器完成一次真实（非流式）大模型调用代理。

**Architecture:** 无状态 FastAPI 应用。请求经 OpenAI 兼容的 Pydantic 模型校验后，由依赖注入选出的 `Provider` 适配器转发到下游大模型，返回标准化响应。供应商通过抽象基类 `Provider` 解耦，便于后续（M2）加入流式与多供应商。

**Tech Stack:** Python 3.12, FastAPI, httpx (async), Pydantic v2 / pydantic-settings, pytest + pytest-asyncio + respx。

> **里程碑说明**：本计划只覆盖 M1。M2（流式转发）、M3（语义缓存）、M4（限流计费路由）、M5（监控部署）各自单独成计划，在前一里程碑完成后再编写。

> **Windows 环境提示**：真实 Python 解释器在 `C:\Users\guantao\AppData\Local\Programs\Python\Python312\python.exe`（`python.exe` 默认是商店占位符，不可用）。所有命令用该解释器或激活后的 venv。命令示例用 PowerShell 语法。

---

## 目标文件结构（M1 结束时）

```
后端项目/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app，挂载路由 + /health
│   ├── config.py            # 环境配置（DeepSeek key/base_url）
│   ├── schemas.py           # OpenAI 兼容请求/响应 Pydantic 模型
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py          # Provider 抽象基类
│   │   └── deepseek.py      # DeepSeek 适配器（非流式）
│   └── routes/
│       ├── __init__.py
│       └── chat.py          # /v1/chat/completions 接口 + get_provider 依赖
├── tests/
│   ├── __init__.py
│   ├── test_schemas.py
│   ├── test_deepseek_provider.py
│   └── test_chat_endpoint.py
├── scripts/
│   └── smoke_real_call.py   # 手动冒烟：打一次真实 DeepSeek
├── .venv/                   # 虚拟环境（git 忽略）
├── requirements.txt
├── pytest.ini
├── .env.example
├── .env                     # 真实 key（git 忽略）
├── .gitignore
└── README.md
```

每个文件单一职责：`schemas.py` 只管数据契约；`providers/` 只管"和下游模型对话"；`routes/` 只管 HTTP 编排；`config.py` 只管配置读取。

---

## Task 1: 项目脚手架与依赖

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `pytest.ini`
- Create: `app/__init__.py`（空文件）
- Create: `app/providers/__init__.py`（空文件）
- Create: `app/routes/__init__.py`（空文件）
- Create: `tests/__init__.py`（空文件）

- [ ] **Step 1: 写 `requirements.txt`**

```
fastapi==0.115.*
uvicorn[standard]==0.34.*
httpx==0.28.*
pydantic==2.*
pydantic-settings==2.*
pytest==8.*
pytest-asyncio==0.25.*
respx==0.22.*
```

- [ ] **Step 2: 写 `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
*.egg-info/
```

- [ ] **Step 3: 写 `.env.example`**

```
DEEPSEEK_API_KEY=your-deepseek-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

- [ ] **Step 4: 写 `pytest.ini`（开启 asyncio 自动模式）**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 5: 建空的包初始化文件**

创建 4 个空文件：`app/__init__.py`、`app/providers/__init__.py`、`app/routes/__init__.py`、`tests/__init__.py`（内容为空）。

- [ ] **Step 6: 创建虚拟环境并安装依赖**

Run:
```powershell
& "C:\Users\guantao\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Expected: 依赖安装成功，无报错。

- [ ] **Step 7: 验证 pytest 可运行（此时无测试）**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: `no tests ran`（说明环境就绪）。

- [ ] **Step 8: 复制 `.env.example` 为 `.env` 并填入真实 key**

Run: `Copy-Item .env.example .env`
然后手动把 `.env` 里的 `DEEPSEEK_API_KEY` 改成你的真实 key（此文件已被 git 忽略，不会提交）。

- [ ] **Step 9: Commit**

```powershell
git add requirements.txt .gitignore .env.example pytest.ini app/__init__.py app/providers/__init__.py app/routes/__init__.py tests/__init__.py
git commit -m "chore: 项目脚手架与依赖"
```

---

## Task 2: OpenAI 兼容数据模型（schemas）

**Files:**
- Create: `app/schemas.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: 写失败测试 `tests/test_schemas.py`**

```python
from app.schemas import ChatCompletionRequest, ChatCompletionResponse


def test_request_parses_minimal_payload():
    req = ChatCompletionRequest.model_validate({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "hello"}],
    })
    assert req.model == "deepseek-chat"
    assert req.messages[0].role == "user"
    assert req.messages[0].content == "hello"
    # 默认值
    assert req.stream is False
    assert req.temperature == 1.0


def test_response_round_trips_provider_json():
    payload = {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
    }
    resp = ChatCompletionResponse.model_validate(payload)
    assert resp.choices[0].message.content == "hi"
    assert resp.usage.total_tokens == 6
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_schemas.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.schemas'`。

- [ ] **Step 3: 写最小实现 `app/schemas.py`**

```python
from typing import Literal, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 1.0
    max_tokens: Optional[int] = None
    stream: bool = False


class Choice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_schemas.py -v`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```powershell
git add app/schemas.py tests/test_schemas.py
git commit -m "feat: OpenAI 兼容请求/响应模型"
```

---

## Task 3: Provider 抽象基类与 DeepSeek 适配器（非流式）

**Files:**
- Create: `app/providers/base.py`
- Create: `app/config.py`
- Create: `app/providers/deepseek.py`
- Test: `tests/test_deepseek_provider.py`

- [ ] **Step 1: 写失败测试 `tests/test_deepseek_provider.py`**

```python
import httpx
import respx

from app.providers.deepseek import DeepSeekProvider
from app.schemas import ChatCompletionRequest, ChatMessage


@respx.mock
async def test_deepseek_forwards_and_parses_response():
    route = respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "cmpl-1",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "deepseek-chat",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            },
        )
    )

    provider = DeepSeekProvider(api_key="test-key", base_url="https://api.deepseek.com")
    req = ChatCompletionRequest(
        model="deepseek-chat",
        messages=[ChatMessage(role="user", content="hello")],
    )
    resp = await provider.chat(req)

    assert route.called
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer test-key"
    assert resp.choices[0].message.content == "hi"
    assert resp.usage.total_tokens == 6
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_deepseek_provider.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.providers.deepseek'`。

- [ ] **Step 3: 写 `app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"


settings = Settings()
```

- [ ] **Step 4: 写 `app/providers/base.py`**

```python
from abc import ABC, abstractmethod

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
```

- [ ] **Step 5: 写 `app/providers/deepseek.py`**

```python
import httpx

from app.config import settings
from app.providers.base import Provider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse


class DeepSeekProvider(Provider):
    name = "deepseek"

    def __init__(
        self, api_key: str | None = None, base_url: str | None = None
    ) -> None:
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = base_url or settings.deepseek_base_url

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60.0) as client:
            resp = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request.model_dump(exclude_none=True),
            )
            resp.raise_for_status()
            return ChatCompletionResponse.model_validate(resp.json())
```

- [ ] **Step 6: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_deepseek_provider.py -v`
Expected: 1 passed。

- [ ] **Step 7: Commit**

```powershell
git add app/config.py app/providers/base.py app/providers/deepseek.py tests/test_deepseek_provider.py
git commit -m "feat: Provider 抽象与 DeepSeek 非流式适配器"
```

---

## Task 4: `/v1/chat/completions` 接口与应用入口

**Files:**
- Create: `app/routes/chat.py`
- Create: `app/main.py`
- Test: `tests/test_chat_endpoint.py`

- [ ] **Step 1: 写失败测试 `tests/test_chat_endpoint.py`**

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


class FakeProvider(Provider):
    name = "fake"

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            id="cmpl-fake",
            created=1,
            model=request.model,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(role="assistant", content="pong"),
                    finish_reason="stop",
                )
            ],
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def test_health_endpoint():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_completions_returns_provider_response():
    app.dependency_overrides[get_provider] = lambda: FakeProvider()
    try:
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "ping"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "pong"
        assert data["usage"]["total_tokens"] == 2
    finally:
        app.dependency_overrides.clear()


def test_chat_completions_rejects_invalid_payload():
    client = TestClient(app)
    resp = client.post("/v1/chat/completions", json={"messages": []})
    assert resp.status_code == 422  # 缺少 model 字段
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_chat_endpoint.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.main'`。

- [ ] **Step 3: 写 `app/routes/chat.py`**

```python
from fastapi import APIRouter, Depends

from app.providers.base import Provider
from app.providers.deepseek import DeepSeekProvider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter()


def get_provider() -> Provider:
    """M1：固定返回 DeepSeek。M4 会扩展为按 model 路由。"""
    return DeepSeekProvider()


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    provider: Provider = Depends(get_provider),
) -> ChatCompletionResponse:
    return await provider.chat(request)
```

- [ ] **Step 4: 写 `app/main.py`**

```python
from fastapi import FastAPI

from app.routes.chat import router as chat_router

app = FastAPI(title="LLM Gateway")
app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_chat_endpoint.py -v`
Expected: 3 passed。

- [ ] **Step 6: 运行全部测试确认整体绿**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: 全部 passed（schemas 2 + provider 1 + endpoint 3 = 6 passed）。

- [ ] **Step 7: Commit**

```powershell
git add app/routes/chat.py app/main.py tests/test_chat_endpoint.py
git commit -m "feat: /v1/chat/completions 接口与应用入口"
```

---

## Task 5: 真实调用冒烟脚本与 README

**Files:**
- Create: `scripts/smoke_real_call.py`
- Create: `README.md`

- [ ] **Step 1: 写 `scripts/smoke_real_call.py`**

```python
"""手动冒烟：用真实 DeepSeek key 走一次完整链路。
运行前确保 .env 已填入真实 DEEPSEEK_API_KEY，并已启动服务：
    .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
然后：
    .\\.venv\\Scripts\\python.exe scripts/smoke_real_call.py
"""
import httpx


def main() -> None:
    resp = httpx.post(
        "http://127.0.0.1:8000/v1/chat/completions",
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    print("模型回复：", data["choices"][0]["message"]["content"])
    print("token 用量：", data["usage"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 写 `README.md`**

````markdown
# LLM 网关（LLM Gateway）

高并发大模型统一接入网关。应用只需对接一个 OpenAI 兼容接口，由网关统一完成流式转发、语义缓存、多供应商路由、限流计费。

> 当前进度：M1（骨架 + 非流式转发）。设计文档见 `docs/superpowers/specs/2026-06-07-llm-gateway-design.md`。

## 快速开始

```powershell
# 1. 建虚拟环境并装依赖
& "C:\Users\guantao\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 配置 key
Copy-Item .env.example .env   # 然后编辑 .env 填入真实 DEEPSEEK_API_KEY

# 3. 跑测试
.\.venv\Scripts\python.exe -m pytest -v

# 4. 启动服务
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 5. 真实调用冒烟（另开一个终端）
.\.venv\Scripts\python.exe scripts/smoke_real_call.py
```

## 接口

- `GET /health` —— 健康检查
- `POST /v1/chat/completions` —— OpenAI 兼容的对话补全（M1 为非流式）
````

- [ ] **Step 3: 手动冒烟验证真实链路**

先启动服务（一个终端）：
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
另一个终端运行：
```powershell
.\.venv\Scripts\python.exe scripts/smoke_real_call.py
```
Expected: 打印出 DeepSeek 的真实回复和 token 用量。若失败，检查 `.env` 中的 key 是否正确。

- [ ] **Step 4: Commit**

```powershell
git add scripts/smoke_real_call.py README.md
git commit -m "docs: 冒烟脚本与 README"
```

---

## M1 验收标准

- [ ] `.\.venv\Scripts\python.exe -m pytest -v` 全绿（6 个测试）。
- [ ] 启动服务后 `GET /health` 返回 `{"status": "ok"}`。
- [ ] 冒烟脚本能用真实 DeepSeek key 拿到真实回复。
- [ ] 代码结构符合上文"目标文件结构"，职责清晰。
- [ ] 所有改动已分任务提交到 git。

完成后即进入 M2（高并发异步流式转发）的计划编写。
```
