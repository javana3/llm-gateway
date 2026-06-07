from fastapi import APIRouter, Depends

from app.providers.base import Provider
from app.providers.minimax import MiniMaxProvider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter()


def get_provider() -> Provider:
    """M1：固定返回 MiniMax（已有可用 key）。M4 会扩展为按 model 路由。"""
    return MiniMaxProvider()


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    provider: Provider = Depends(get_provider),
) -> ChatCompletionResponse:
    return await provider.chat(request)
