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
