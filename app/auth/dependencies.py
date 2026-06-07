from fastapi import Header, HTTPException, Request

from app.auth.models import ApiKey


def authenticate(request: Request, authorization: str = Header(default="")) -> ApiKey:
    store = request.app.state.key_store
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer ") :].strip()
    api_key = store.get(token)
    if api_key is None:
        raise HTTPException(status_code=401, detail="invalid api key")
    return api_key


def authorize(request: Request, authorization: str = Header(default="")) -> ApiKey:
    """鉴权 → 限流 → 配额 三连。返回通过校验的 ApiKey。"""
    api_key = authenticate(request, authorization)
    limiter = request.app.state.rate_limiter
    if not limiter.allow(api_key.key, api_key.rpm_limit):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    if api_key.remaining_tokens <= 0:
        raise HTTPException(status_code=429, detail="token quota exhausted")
    return api_key
