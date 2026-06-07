from app.schemas import ChatCompletionRequest, ChatCompletionResponse


def test_request_parses_minimal_payload():
    req = ChatCompletionRequest.model_validate({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "hello"}],
    })
    assert req.model == "deepseek-chat"
    assert req.messages[0].role == "user"
    assert req.messages[0].content == "hello"
    # 默认值
    assert req.stream is False
    assert req.temperature == 1.0


def test_response_round_trips_provider_json():
    payload = {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
    }
    resp = ChatCompletionResponse.model_validate(payload)
    assert resp.choices[0].message.content == "hi"
    assert resp.usage.total_tokens == 6
