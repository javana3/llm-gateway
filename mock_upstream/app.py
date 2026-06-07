"""本地 Mock 上游：模拟一个 OpenAI 兼容的大模型服务，用于压测网关本身。

通过环境变量调参：
    MOCK_TOKENS  每次响应吐多少个 token（默认 20）
    MOCK_DELAY   每个 token 之间的间隔秒数（默认 0.01，模拟生成耗时）
"""
import asyncio
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="Mock LLM Upstream")

N_TOKENS = int(os.getenv("MOCK_TOKENS", "20"))
DELAY = float(os.getenv("MOCK_DELAY", "0.01"))


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    payload = await request.json()
    stream = bool(payload.get("stream", False))

    if stream:

        async def gen():
            for _ in range(N_TOKENS):
                chunk = {
                    "choices": [
                        {"index": 0, "delta": {"content": "x"}, "finish_reason": None}
                    ]
                }
                yield f"data: {json.dumps(chunk)}\n\n".encode()
                await asyncio.sleep(DELAY)
            yield b"data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    await asyncio.sleep(DELAY * N_TOKENS)
    return {
        "id": "mock-completion",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "mock",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "x" * N_TOKENS},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": N_TOKENS,
            "total_tokens": N_TOKENS + 1,
        },
    }
