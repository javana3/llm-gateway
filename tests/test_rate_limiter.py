from app.auth.rate_limiter import TokenBucketRateLimiter


def test_allows_up_to_capacity_then_blocks():
    limiter = TokenBucketRateLimiter()
    # rpm=2 → 桶容量 2；快速连发 3 次，前 2 次放行，第 3 次拒绝
    assert limiter.allow("k", rpm=2) is True
    assert limiter.allow("k", rpm=2) is True
    assert limiter.allow("k", rpm=2) is False


def test_separate_keys_have_separate_buckets():
    limiter = TokenBucketRateLimiter()
    assert limiter.allow("k1", rpm=1) is True
    assert limiter.allow("k2", rpm=1) is True  # 不同 key 互不影响
    assert limiter.allow("k1", rpm=1) is False
