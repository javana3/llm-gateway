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
