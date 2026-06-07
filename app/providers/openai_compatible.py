from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.providers.base import Provider
from app.schemas import ChatCompletionRequest, ChatCompletionResponse


class OpenAICompatibleProvider(Provider):
    """复用于所有 OpenAI 兼容的下游供应商（DeepSeek / MiniMax / ...）。

    若传入共享的 httpx.AsyncClient（连接池复用），则复用之且不主动关闭；
    否则每次调用临时新建一个 client（M1 行为，便于测试）。
    """

    def __init__(
        self,
        name: str,
        api_key: str,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.client = client

    @property
    def _url(self) -> str:
        # 显式拼完整 URL，避免 httpx base_url 含 /v1 时被绝对路径覆盖丢段。
        return f"{self.base_url.rstrip('/')}/chat/completions"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    @asynccontextmanager
    async def _acquire(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.client is not None:
            yield self.client
        else:
            async with httpx.AsyncClient(timeout=60.0) as client:
                yield client

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        async with self._acquire() as client:
            resp = await client.post(
                self._url,
                headers=self._headers,
                json=request.model_dump(exclude_none=True),
            )
            resp.raise_for_status()
            return ChatCompletionResponse.model_validate(resp.json())

    async def stream_chat(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[bytes]:
        payload = request.model_dump(exclude_none=True)
        payload["stream"] = True
        async with self._acquire() as client:
            async with client.stream(
                "POST", self._url, headers=self._headers, json=payload
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk
