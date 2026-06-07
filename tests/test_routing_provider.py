import pytest

from app.providers.base import Provider
from app.providers.registry import ProviderRegistry
from app.providers.routing import RoutingProvider, AllProvidersUnavailable
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    Usage,
)


def _resp(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="x",
        created=1,
        model="m",
        choices=[
            Choice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=1),
    )


class WorkingProvider(Provider):
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def chat(self, request):
        self.calls += 1
        return _resp(self.content)

    async def stream_chat(self, request):
        self.calls += 1
        yield f'data: {{"choices":[{{"delta":{{"content":"{self.content}"}}}}]}}\n\n'.encode()
        yield b"data: [DONE]\n\n"


class FailingProvider(Provider):
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, request):
        self.calls += 1
        raise RuntimeError("provider down")

    async def stream_chat(self, request):
        self.calls += 1
        raise RuntimeError("provider down")
        yield b""  # 使其成为异步生成器（永不执行）


def _req() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="m", messages=[ChatMessage(role="user", content="hi")]
    )


def _registry(**providers) -> ProviderRegistry:
    reg = ProviderRegistry()
    for name, p in providers.items():
        reg.register(name, p)
    return reg


async def test_chat_uses_first_healthy_provider():
    work = WorkingProvider("primary")
    reg = _registry(a=work, b=WorkingProvider("backup"))
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=2, recovery_timeout=10)
    resp = await rp.chat(_req())
    assert resp.choices[0].message.content == "primary"


async def test_chat_fails_over_to_backup():
    fail = FailingProvider()
    work = WorkingProvider("backup")
    reg = _registry(a=fail, b=work)
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=2, recovery_timeout=10)
    resp = await rp.chat(_req())
    assert resp.choices[0].message.content == "backup"
    assert fail.calls == 1
    assert work.calls == 1


async def test_circuit_opens_and_skips_provider():
    fail = FailingProvider()
    work = WorkingProvider("backup")
    reg = _registry(a=fail, b=work)
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=2, recovery_timeout=10)
    await rp.chat(_req())  # a 失败 1
    await rp.chat(_req())  # a 失败 2 → 熔断打开
    fail.calls = 0
    await rp.chat(_req())  # a 被跳过，直接打 b
    assert fail.calls == 0


async def test_all_providers_fail_raises():
    reg = _registry(a=FailingProvider(), b=FailingProvider())
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=5, recovery_timeout=10)
    with pytest.raises(AllProvidersUnavailable):
        await rp.chat(_req())


async def test_stream_fails_over_before_first_chunk():
    fail = FailingProvider()
    work = WorkingProvider("backup")
    reg = _registry(a=fail, b=work)
    rp = RoutingProvider(reg, chain=["a", "b"], failure_threshold=2, recovery_timeout=10)
    chunks = [c async for c in rp.stream_chat(_req())]
    body = b"".join(chunks)
    assert b"backup" in body
    assert b"[DONE]" in body
