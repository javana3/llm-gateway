from app.providers.base import Provider


class ProviderRegistry:
    """name → Provider 注册表。"""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, name: str, provider: Provider) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> Provider | None:
        return self._providers.get(name)

    def names(self) -> list[str]:
        return list(self._providers.keys())
