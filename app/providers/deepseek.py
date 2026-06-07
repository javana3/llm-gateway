import httpx

from app.config import settings
from app.providers.base import Provider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse


class DeepSeekProvider(Provider):
    name = "deepseek"

    def __init__(
        self, api_key: str | None = None, base_url: str | None = None
    ) -> None:
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = base_url or settings.deepseek_base_url

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60.0) as client:
            resp = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request.model_dump(exclude_none=True),
            )
            resp.raise_for_status()
            return ChatCompletionResponse.model_validate(resp.json())
