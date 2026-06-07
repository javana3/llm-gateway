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

    async def stream_chat(self, request: ChatCompletionRequest):
        yield b'data: {"choices":[{"index":0,"delta":{"content":"pong"}}]}\n\n'
        yield b"data: [DONE]\n\n"


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
    # 用 with 触发 lifespan，使共享 client 就绪（get_provider 依赖它）
    with TestClient(app) as client:
        resp = client.post("/v1/chat/completions", json={"messages": []})
    assert resp.status_code == 422  # 缺少 model 字段
