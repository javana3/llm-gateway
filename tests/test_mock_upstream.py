from fastapi.testclient import TestClient

from mock_upstream.app import app


def test_mock_streams_sse_with_done():
    client = TestClient(app)
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "mock",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = b"".join(resp.iter_bytes())
    assert b"data:" in body
    assert b"[DONE]" in body


def test_mock_non_stream_returns_openai_shape():
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["usage"]["total_tokens"] >= 1
