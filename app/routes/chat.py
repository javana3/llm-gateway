from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.auth.billing import estimate_tokens, record_usage
from app.auth.dependencies import authorize
from app.auth.models import ApiKey
from app.config import settings
from app.providers.base import Provider
from app.providers.minimax import MiniMaxProvider
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    Usage,
)
from app.sse import assemble_content_from_sse, replay_content_as_sse

router = APIRouter()


def get_provider(request: Request) -> Provider:
    """M1：固定返回 MiniMax（已有可用 key）。M4b 会扩展为按 model 路由。
    复用应用启动时创建的共享 httpx.AsyncClient（连接池）。"""
    return MiniMaxProvider(client=request.app.state.http_client)


def _build_response(model: str, content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="cached",
        created=0,
        model=model,
        choices=[
            Choice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    http_request: Request,
    provider: Provider = Depends(get_provider),
    api_key: ApiKey = Depends(authorize),
):
    cache = http_request.app.state.semantic_cache
    price = settings.price_per_1k_tokens

    if request.stream:
        cached = cache.get(request)
        if cached is not None:
            record_usage(api_key, tokens=0, price_per_1k=price)  # 命中不计费
            return StreamingResponse(
                replay_content_as_sse(cached), media_type="text/event-stream"
            )

        async def event_stream():
            parts: list[bytes] = []
            async for chunk in provider.stream_chat(request):
                if await http_request.is_disconnected():
                    break
                parts.append(chunk)
                yield chunk
            content = assemble_content_from_sse(b"".join(parts))
            if content:
                cache.set(request, content)
            record_usage(api_key, tokens=estimate_tokens(content), price_per_1k=price)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    cached = cache.get(request)
    if cached is not None:
        record_usage(api_key, tokens=0, price_per_1k=price)  # 命中不计费
        return _build_response(request.model, cached)

    resp = await provider.chat(request)
    content = resp.choices[0].message.content if resp.choices else ""
    if content:
        cache.set(request, content)
    record_usage(api_key, tokens=resp.usage.total_tokens, price_per_1k=price)
    return resp
