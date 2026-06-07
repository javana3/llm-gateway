from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.key_store import build_key_store
from app.auth.rate_limiter import TokenBucketRateLimiter
from app.cache.factory import build_semantic_cache
from app.config import settings
from app.providers.factory import build_routing_provider
from app.providers.routing import AllProvidersUnavailable
from app.routes.admin import router as admin_router
from app.routes.cache import router as cache_router
from app.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(60.0, connect=10.0)
    app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    app.state.semantic_cache = build_semantic_cache()
    app.state.key_store = build_key_store(
        settings.gateway_api_keys,
        rpm_limit=settings.default_rpm_limit,
        quota_tokens=settings.default_quota_tokens,
    )
    app.state.rate_limiter = TokenBucketRateLimiter()
    app.state.routing_provider = build_routing_provider(app.state.http_client)
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(cache_router)
app.include_router(admin_router)


@app.exception_handler(AllProvidersUnavailable)
async def _all_providers_unavailable(request: Request, exc: AllProvidersUnavailable):
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc) or "all providers unavailable"},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
