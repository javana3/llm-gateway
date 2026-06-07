from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 共享连接池：所有请求复用，避免每请求重建 TCP/TLS。
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(60.0, connect=10.0)
    app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)
app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
