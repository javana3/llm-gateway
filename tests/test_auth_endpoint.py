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
