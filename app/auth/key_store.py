from app.auth.models import ApiKey


class KeyStore:
    def __init__(self) -> None:
        self._keys: dict[str, ApiKey] = {}

    def add(self, api_key: ApiKey) -> None:
        self._keys[api_key.key] = api_key

    def get(self, key: str) -> ApiKey | None:
        return self._keys.get(key)

    def all(self) -> list[ApiKey]:
        return list(self._keys.values())


def build_key_store(
    keys_csv: str, rpm_limit: int, quota_tokens: int
) -> KeyStore:
    store = KeyStore()
    for raw in keys_csv.split(","):
        k = raw.strip()
        if k:
            store.add(
                ApiKey(
                    key=k, name=k, rpm_limit=rpm_limit, quota_tokens=quota_tokens
                )
            )
    return store
