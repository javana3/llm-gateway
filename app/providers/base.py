from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schemas import ChatCompletionRequest, ChatCompletionResponse


class Provider(ABC):
    """所有下游大模型供应商适配器的统一接口。"""

    name: str

    @abstractmethod
    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """非流式：发送一次请求，返回完整响应。"""
        ...

    @abstractmethod
    def stream_chat(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[bytes]:
        """流式：返回一个异步生成器，逐块 yield 下游 SSE 原始字节。"""
        ...
