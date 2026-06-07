from app.auth.key_store import KeyStore, build_key_store
from app.auth.models import ApiKey


def test_add_and_get():
    store = KeyStore()
    store.add(ApiKey(key="abc", name="alice", rpm_limit=10, quota_tokens=100))
    got = store.get("abc")
    assert got is not None
    assert got.name == "alice"
    assert store.get("missing") is None


def test_remaining_tokens():
    k = ApiKey(key="abc", name="a", rpm_limit=10, quota_tokens=100)
    k.used_tokens = 30
    assert k.remaining_tokens == 70


def test_build_from_comma_separated_config():
    store = build_key_store("k1, k2 ,k3", rpm_limit=42, quota_tokens=999)
    assert {k.key for k in store.all()} == {"k1", "k2", "k3"}
    assert store.get("k1").rpm_limit == 42
    assert store.get("k2").quota_tokens == 999
