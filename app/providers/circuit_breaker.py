import time
from collections.abc import Callable


class CircuitBreaker:
    """每供应商熔断器。closed → 失败累计达阈值 → open；
    冷却到点 → half_open（放一个探测）；探测成功 → closed，失败 → 重新 open。"""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._now = now
        self.state = "closed"
        self._failures = 0
        self._opened_at = 0.0

    def allow(self) -> bool:
        if self.state == "open":
            if self._now() - self._opened_at >= self.recovery_timeout:
                self.state = "half_open"
                return True
            return False
        return True  # closed 或 half_open

    def record_success(self) -> None:
        self._failures = 0
        self.state = "closed"

    def record_failure(self) -> None:
        if self.state == "half_open":
            self.state = "open"
            self._opened_at = self._now()
            self._failures = 0
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self.state = "open"
            self._opened_at = self._now()
