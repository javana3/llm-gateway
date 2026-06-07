"""异步压测脚本：对网关发起 N 个并发流式请求，统计 QPS 与延迟分位。

压测前请将网关的下游指向本地 Mock 上游（见 README“压测”一节），
这样测的是网关本身的转发/并发能力，而非真实 API 的延迟。

用法：
    .\\.venv\\Scripts\\python.exe scripts/loadtest.py --concurrency 50 --total 500
"""
import argparse
import asyncio
import time

import httpx


async def one_request(client: httpx.AsyncClient, url: str, payload: dict) -> float:
    t0 = time.perf_counter()
    async with client.stream("POST", url, json=payload) as resp:
        async for _ in resp.aiter_bytes():
            pass
    return time.perf_counter() - t0


async def run(concurrency: int, total: int, url: str, payload: dict) -> None:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        async def worker() -> None:
            async with sem:
                latencies.append(await one_request(client, url, payload))

        t0 = time.perf_counter()
        await asyncio.gather(*[worker() for _ in range(total)])
        wall = time.perf_counter() - t0

    latencies.sort()

    def pct(p: float) -> float:
        idx = max(0, int(len(latencies) * p) - 1)
        return latencies[idx] * 1000

    print(
        f"concurrency={concurrency} total={total} "
        f"wall={wall:.2f}s QPS={total / wall:.1f} "
        f"P50={pct(0.5):.0f}ms P95={pct(0.95):.0f}ms P99={pct(0.99):.0f}ms"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions")
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--total", type=int, default=500)
    args = ap.parse_args()

    payload = {
        "model": "MiniMax-M2.5",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": True,
    }
    asyncio.run(run(args.concurrency, args.total, args.url, payload))


if __name__ == "__main__":
    main()
