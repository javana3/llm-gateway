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
