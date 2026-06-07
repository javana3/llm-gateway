from app.providers.circuit_breaker import CircuitBreaker


def test_starts_closed_and_allows():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: 0.0)
    assert cb.state == "closed"
    assert cb.allow() is True


def test_opens_after_threshold_failures():
    t = [0.0]
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: t[0])
    cb.record_failure()
    assert cb.state == "closed"
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow() is False


def test_half_open_after_recovery_then_close_on_success():
    t = [0.0]
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: t[0])
    cb.record_failure()
    cb.record_failure()  # open at t=0
    t[0] = 5
    assert cb.allow() is False  # 冷却未到
    t[0] = 10
    assert cb.allow() is True  # 半开探测
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"


def test_half_open_failure_reopens():
    t = [0.0]
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: t[0])
    cb.record_failure()
    cb.record_failure()
    t[0] = 10
    cb.allow()  # 进入 half_open
    cb.record_failure()
    assert cb.state == "open"


def test_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, now=lambda: 0.0)
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert cb.state == "closed"  # 计数被重置过，未达阈值
