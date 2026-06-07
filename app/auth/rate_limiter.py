import time


class TokenBucketRateLimiter:
    """按 key 的内存令牌桶。容量=rpm，匀速回填(rpm/60 每秒)。"""

    def __init__(self) -> None:
        # key -> (tokens, last_refill_monotonic)
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, rpm: int) -> bool:
        now = time.monotonic()
        capacity = float(rpm)
        refill_per_sec = rpm / 60.0
        tokens, last = self._buckets.get(key, (capacity, now))
        tokens = min(capacity, tokens + (now - last) * refill_per_sec)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            return True
        self._buckets[key] = (tokens, now)
        return False
