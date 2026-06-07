import httpx

from app.config import settings
from app.providers.openai_compatible import OpenAICompatibleProvider


class MiniMaxProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            name="minimax",
            api_key=api_key or settings.minimax_api_key,
            base_url=base_url or settings.minimax_base_url,
            client=client,
        )
