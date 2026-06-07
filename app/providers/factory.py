import httpx

from app.config import settings
from app.providers.deepseek import DeepSeekProvider
from app.providers.minimax import MiniMaxProvider
from app.providers.registry import ProviderRegistry
from app.providers.routing import RoutingProvider


def build_registry(client: httpx.AsyncClient) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register("minimax", MiniMaxProvider(client=client))
    reg.register("deepseek", DeepSeekProvider(client=client))
    return reg


def build_routing_provider(client: httpx.AsyncClient) -> RoutingProvider:
    reg = build_registry(client)
    chain = [n.strip() for n in settings.provider_chain.split(",") if n.strip()]
    return RoutingProvider(
        reg,
        chain=chain,
        failure_threshold=settings.circuit_failure_threshold,
        recovery_timeout=settings.circuit_recovery_timeout,
    )
