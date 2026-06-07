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
