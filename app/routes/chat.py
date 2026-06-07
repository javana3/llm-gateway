from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.providers.base import Provider
from app.providers.minimax import MiniMaxProvider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter()


def get_provider(request: Request) -> Provider:
    """M1：固定返回 MiniMax（已有可用 key）。M4 会扩展为按 model 路由。
    复用应用启动时创建的共享 httpx.AsyncClient（连接池）。"""
    return MiniMaxProvider(client=request.app.state.http_client)


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    http_request: Request,
    provider: Provider = Depends(get_provider),
):
    if request.stream:

        async def event_stream():
            async for chunk in provider.stream_chat(request):
                # 客户端断开则停止拉取下游，释放连接，避免“幽灵请求”。
                if await http_request.is_disconnected():
                    break
                yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return await provider.chat(request)
