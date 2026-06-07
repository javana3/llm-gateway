from collections.abc import AsyncIterator

from app.providers.base import Provider
from app.providers.circuit_breaker import CircuitBreaker
from app.providers.registry import ProviderRegistry
from app.schemas import ChatCompletionRequest, ChatCompletionResponse


class AllProvidersUnavailable(Exception):
    """provider 链里全部不可用（熔断或失败）。"""


class RoutingProvider(Provider):
    """按 provider 链路由 + 每供应商熔断 + 故障转移。本身是一个 Provider。"""

    name = "router"

    def __init__(
        self,
        registry: ProviderRegistry,
        chain: list[str],
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
    ) -> None:
        self.registry = registry
        self.chain = chain
        self.breakers: dict[str, CircuitBreaker] = {
            name: CircuitBreaker(failure_threshold, recovery_timeout)
            for name in chain
        }

    def _candidates(self) -> list[tuple[str, Provider]]:
        out: list[tuple[str, Provider]] = []
        for name in self.chain:
            provider = self.registry.get(name)
            if provider is not None and self.breakers[name].allow():
                out.append((name, provider))
        return out

    def circuit_states(self) -> dict[str, str]:
        return {name: self.breakers[name].state for name in self.chain}

    async def chat(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        last_exc: Exception | None = None
        for name, provider in self._candidates():
            try:
                resp = await provider.chat(request)
                self.breakers[name].record_success()
                return resp
            except Exception as exc:  # noqa: BLE001 - 故障转移需捕获一切
                self.breakers[name].record_failure()
                last_exc = exc
        raise AllProvidersUnavailable(str(last_exc) if last_exc else "no provider")

    async def stream_chat(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[bytes]:
        last_exc: Exception | None = None
        for name, provider in self._candidates():
            agen = provider.stream_chat(request)
            try:
                first = await agen.__anext__()
            except StopAsyncIteration:
                self.breakers[name].record_success()
                return  # 空流也算成功
            except Exception as exc:  # noqa: BLE001
                self.breakers[name].record_failure()
                last_exc = exc
                continue
            # 拿到首块即视为成功；此后无法再转移
            self.breakers[name].record_success()
            yield first
            async for chunk in agen:
                yield chunk
            return
        raise AllProvidersUnavailable(str(last_exc) if last_exc else "no provider")
