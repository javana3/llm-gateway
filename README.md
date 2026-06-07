# LLM 网关（LLM Gateway）

高并发大模型统一接入网关。应用只需对接一个 OpenAI 兼容接口，由网关统一完成流式转发、语义缓存、多供应商路由、限流计费。

> 当前进度：M4a（鉴权 / 限流 / 计费）。设计文档见 `docs/superpowers/specs/2026-06-07-llm-gateway-design.md`。

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
- `POST /v1/chat/completions` —— OpenAI 兼容的对话补全；`stream=true` 时走 SSE 流式转发，否则返回完整 JSON

## 压测（M2）

压测打**本地 Mock 上游**而非真实 API，这样测的是网关本身的转发/并发能力。

```powershell
# 终端 A：启动 Mock 上游（可调 token 数与每 token 延迟）
$env:MOCK_TOKENS = "20"; $env:MOCK_DELAY = "0.01"
.\.venv\Scripts\python.exe -m uvicorn mock_upstream.app:app --port 9000

# 终端 B：让网关的下游指向 Mock，再启动网关
$env:MINIMAX_BASE_URL = "http://127.0.0.1:9000/v1"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 终端 C：发起压测
.\.venv\Scripts\python.exe scripts/loadtest.py --concurrency 50 --total 500
```

输出示例：
`concurrency=50 total=500 wall=2.41s QPS=207.5 P50=210ms P95=360ms P99=520ms`

逐步加大 `--concurrency`（如 10 / 50 / 100 / 200）记录 QPS 与 P95/P99，即可得到第一版并发-延迟数据。

## 语义缓存（M3）

- 多级缓存：L1 精确（prompt 哈希）+ L2 语义（fastembed 向量 + 余弦相似度阈值）。
- 仅缓存低 temperature（`CACHE_MAX_TEMPERATURE`，默认 0.5）的请求，避免高随机性请求被错误命中。
- 向量存储可插拔：默认内存（`VECTOR_STORE_BACKEND=memory`），可选 Redis（`=redis`，需 Docker 起 redis-stack）。
- 命中即直接返回；流式命中则把缓存内容合成 SSE 回放，体验一致。
- 统计：`GET /cache/stats` 返回 hits/misses/l1_hits/l2_hits/hit_ratio。

跑命中率基准（先启动网关）：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# 另一个终端：
.\.venv\Scripts\python.exe scripts/cache_benchmark.py
```

可选启用 Redis 向量后端：

```powershell
# 需本机 Docker 已启动
docker run -d --name redis-stack -p 6379:6379 redis/redis-stack:latest
$env:VECTOR_STORE_BACKEND = "redis"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

## 鉴权 / 限流 / 计费（M4a）

- **鉴权**：所有 `/v1/*` 请求需带 `Authorization: Bearer <key>`；key 由 `GATEWAY_API_KEYS`（逗号分隔）配置，无效返回 401。
- **限流**：每个 key 按 `DEFAULT_RPM_LIMIT` 令牌桶限流，超限返回 429。
- **计费**：按 token 计量（`PRICE_PER_1K_TOKENS`），实时扣减配额（`DEFAULT_QUOTA_TOKENS`），耗尽返回 429。**缓存命中不计费**。
- **用量**：`GET /admin/usage` 查看每个 key 的 requests / used_tokens / remaining_tokens / cost。

示例：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# 带 key 调用：
curl -H "Authorization: Bearer dev-key" -H "Content-Type: application/json" `
  -d '{"model":"MiniMax-M2.5","messages":[{"role":"user","content":"hi"}],"temperature":0}' `
  http://127.0.0.1:8000/v1/chat/completions
# 看用量：
curl http://127.0.0.1:8000/admin/usage
```
