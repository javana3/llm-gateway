from app.providers.registry import ProviderRegistry


def test_register_get_and_names():
    reg = ProviderRegistry()
    sentinel_a = object()
    sentinel_b = object()
    reg.register("a", sentinel_a)
    reg.register("b", sentinel_b)
    assert reg.get("a") is sentinel_a
    assert reg.get("missing") is None
    assert set(reg.names()) == {"a", "b"}
