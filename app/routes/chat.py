from fastapi import APIRouter, Depends, Request

from app.providers.base import Provider
from app.providers.minimax import MiniMaxProvider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter()


def get_provider(request: Request) -> Provider:
    """M1：固定返回 MiniMax（已有可用 key）。M4 会扩展为按 model 路由。
    复用应用启动时创建的共享 httpx.AsyncClient（连接池）。"""
    return MiniMaxProvider(client=request.app.state.http_client)


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    provider: Provider = Depends(get_provider),
) -> ChatCompletionResponse:
    return await provider.chat(request)
