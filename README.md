# LLM 网关（LLM Gateway）

高并发大模型统一接入网关。应用只需对接一个 OpenAI 兼容接口，由网关统一完成流式转发、语义缓存、多供应商路由、限流计费。

> 当前进度：M1（骨架 + 非流式转发）。设计文档见 `docs/superpowers/specs/2026-06-07-llm-gateway-design.md`。

## 快速开始

```powershell
# 1. 建虚拟环境并装依赖
& "C:\Users\guantao\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 配置 key
Copy-Item .env.example .env   # 然后编辑 .env 填入真实 key
# 当前默认供应商为 MiniMax：填 MINIMAX_API_KEY
# 注意区域：国内区 base_url 用 https://api.minimaxi.com/v1（api.minimax.io 是国际区，key 不通用）

# 3. 跑测试
.\.venv\Scripts\python.exe -m pytest -v

# 4. 启动服务
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 5. 真实调用冒烟（另开一个终端）
.\.venv\Scripts\python.exe scripts/smoke_real_call.py
```

## 接口

- `GET /health` —— 健康检查
- `POST /v1/chat/completions` —— OpenAI 兼容的对话补全（M1 为非流式）
