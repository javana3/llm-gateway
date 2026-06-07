import httpx
import respx

from app.providers.minimax import MiniMaxProvider
from app.schemas import ChatCompletionRequest, ChatMessage


@respx.mock
async def test_stream_chat_yields_downstream_sse_chunks():
    sse = (
        b'data: {"choices":[{"index":0,"delta":{"content":"he"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{"content":"llo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    route = respx.post("https://api.minimaxi.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=sse)
    )

    provider = MiniMaxProvider(
        api_key="test-key", base_url="https://api.minimaxi.com/v1"
    )
    req = ChatCompletionRequest(
        model="MiniMax-M2.5",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    chunks = [chunk async for chunk in provider.stream_chat(req)]
    body = b"".join(chunks)

    assert route.called
    # 下游被强制带上 stream=True
    sent_body = route.calls.last.request.content
    assert b'"stream": true' in sent_body or b'"stream":true' in sent_body
    # 两段 delta 与结束标记都被透传
    assert b'"he"' in body
    assert b'"llo"' in body
    assert b"[DONE]" in body
