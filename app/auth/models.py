from dataclasses import dataclass


@dataclass
class ApiKey:
    key: str
    name: str
    rpm_limit: int
    quota_tokens: int
    used_tokens: int = 0
    requests: int = 0
    cost: float = 0.0

    @property
    def remaining_tokens(self) -> int:
        return self.quota_tokens - self.used_tokens
