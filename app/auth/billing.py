from app.auth.models import ApiKey


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（流式无 usage 时用）：约 4 字符 1 token。"""
    return len(text) // 4


def record_usage(api_key: ApiKey, tokens: int, price_per_1k: float) -> None:
    api_key.used_tokens += tokens
    api_key.requests += 1
    api_key.cost += tokens / 1000.0 * price_per_1k
