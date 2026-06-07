from app.auth.billing import estimate_tokens, record_usage
from app.auth.models import ApiKey


def test_estimate_tokens_rough_quarter_of_chars():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1  # 4 字符 ≈ 1 token
    assert estimate_tokens("a" * 40) == 10


def test_record_usage_accumulates_tokens_requests_cost():
    k = ApiKey(key="x", name="x", rpm_limit=10, quota_tokens=1000)
    record_usage(k, tokens=200, price_per_1k=0.002)
    assert k.used_tokens == 200
    assert k.requests == 1
    assert k.cost == 0.0004  # 200/1000 * 0.002
    record_usage(k, tokens=300, price_per_1k=0.002)
    assert k.used_tokens == 500
    assert k.requests == 2


def test_record_zero_tokens_still_counts_request():
    k = ApiKey(key="x", name="x", rpm_limit=10, quota_tokens=1000)
    record_usage(k, tokens=0, price_per_1k=0.002)  # 缓存命中：0 token
    assert k.used_tokens == 0
    assert k.requests == 1
    assert k.cost == 0.0
