from abc import ABC, abstractmethod

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
