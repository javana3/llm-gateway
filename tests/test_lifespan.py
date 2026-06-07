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
