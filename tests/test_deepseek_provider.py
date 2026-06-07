import httpx
import respx

from app.providers.deepseek import DeepSeekProvider
from app.schemas import ChatCompletionRequest, ChatMessage


@respx.mock
async def test_deepseek_forwards_and_parses_response():
    route = respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
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
            },
        )
    )

    provider = DeepSeekProvider(api_key="test-key", base_url="https://api.deepseek.com")
    req = ChatCompletionRequest(
        model="deepseek-chat",
        messages=[ChatMessage(role="user", content="hello")],
    )
    resp = await provider.chat(req)

    assert route.called
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer test-key"
    assert resp.choices[0].message.content == "hi"
    assert resp.usage.total_tokens == 6
