import httpx

from app.providers.base import Provider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse


class OpenAICompatibleProvider(Provider):
    """复用于所有 OpenAI 兼容的下游供应商（DeepSeek / MiniMax / ...）。"""

    def __init__(self, name: str, api_key: str, base_url: str) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = base_url

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        # 显式拼完整 URL，避免 httpx base_url 含 /v1 时被绝对路径覆盖丢段。
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request.model_dump(exclude_none=True),
            )
            resp.raise_for_status()
            return ChatCompletionResponse.model_validate(resp.json())
