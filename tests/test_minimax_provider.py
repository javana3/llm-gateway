import httpx
import respx

from app.providers.minimax import MiniMaxProvider
from app.schemas import ChatCompletionRequest, ChatMessage


@respx.mock
async def test_minimax_forwards_to_v1_endpoint_and_parses_response():
    route = respx.post("https://api.minimax.io/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "cmpl-mm-1",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "MiniMax-M2.5",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "你好"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )
    )

    provider = MiniMaxProvider(
        api_key="test-key", base_url="https://api.minimax.io/v1"
    )
    req = ChatCompletionRequest(
        model="MiniMax-M2.5",
        messages=[ChatMessage(role="user", content="hi")],
    )
    resp = await provider.chat(req)

    assert route.called
    sent = route.calls.last.request
    # 验证 /v1 段没有被丢掉
    assert str(sent.url) == "https://api.minimax.io/v1/chat/completions"
    assert sent.headers["authorization"] == "Bearer test-key"
    assert resp.choices[0].message.content == "你好"
    assert resp.usage.total_tokens == 5
