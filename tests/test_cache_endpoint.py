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
