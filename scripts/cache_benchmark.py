"""缓存基准：发一批“有重复/近似”的请求，统计命中率与命中/未命中延迟差。

需先启动网关（真实下游或 Mock 上游均可），默认打 http://127.0.0.1:8000。
用法：
    .\\.venv\\Scripts\\python.exe scripts/cache_benchmark.py
"""
import argparse
import asyncio
import time

import httpx

# 10 个“语义相近/重复”的问法，命中率应明显 > 0
QUERIES = [
    "What is the capital of France?",
    "What's the capital city of France?",
    "Tell me the capital of France.",
    "capital of France?",
    "What is the capital of France",
    "What is the capital of France?",
    "Which city is the capital of France?",
    "France capital city name?",
    "What is the capital of France?",
    "the capital of France is what",
]


async def call(client, url, content):
    t0 = time.perf_counter()
    body = {
        "model": "MiniMax-M2.5",
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.0,
    }
    r = await client.post(url, json=body)
    r.raise_for_status()
    return time.perf_counter() - t0


async def run(url: str, stats_url: str) -> None:
    async with httpx.AsyncClient(timeout=120.0) as client:
        latencies = []
        for q in QUERIES:
            latencies.append(await call(client, url, q))
        stats = (await client.get(stats_url)).json()

    print(f"requests={len(QUERIES)} latencies_ms={[round(x*1000) for x in latencies]}")
    print(f"first(miss)≈{latencies[0]*1000:.0f}ms  last(likely hit)≈{latencies[-1]*1000:.0f}ms")
    print(f"cache stats: {stats}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    asyncio.run(
        run(f"{args.base}/v1/chat/completions", f"{args.base}/cache/stats")
    )


if __name__ == "__main__":
    main()
