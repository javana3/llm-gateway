"""手动冒烟：用真实 DeepSeek key 走一次完整链路。

运行前确保 .env 已填入真实 DEEPSEEK_API_KEY，并已启动服务：
    .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
然后：
    .\\.venv\\Scripts\\python.exe scripts/smoke_real_call.py
"""
import httpx


def main() -> None:
    resp = httpx.post(
        "http://127.0.0.1:8000/v1/chat/completions",
        json={
            "model": "MiniMax-M2.5",
            "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    print("模型回复：", data["choices"][0]["message"]["content"])
    print("token 用量：", data["usage"])


if __name__ == "__main__":
    main()
