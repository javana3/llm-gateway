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
