# LLM 推理网关（LLM Gateway）设计文档

- **日期**：2026-06-07
- **作者**：项目负责人（求职后端实习）
- **状态**：设计已确认，待转实现计划
- **目标**：一个能写进简历主战场、扛得住中厂/大厂深度追问的高并发后端项目

---

## 0. 背景与目标

冲后端实习（中厂 + 大厂都投），需要一个"够硬、不烂大街、又蹭上 AI 红利"的主力项目。
经调研（2026-06）：

- 秒杀/短链等传统项目已被归为"烂大街、易被 ATS/HR 秒挂"，需大量深水区改造才能救，性价比低。
- LLM 网关是 2026 年被市场直接验证的方向：阿里等在直接招"AI 大模型网关 / AI Hub"岗位；小林 coding 把"LLM 网关：限流/熔断/多模型路由/成本管理"列为面试考点；多份英文作品集指南把"Multi-Provider LLM Gateway"列为能 get hired 的标杆项目。

**项目定位（一句话）**：一个高并发的大模型统一接入网关——应用只需对接它一个 OpenAI 兼容接口，由它统一完成流式转发、语义缓存、多供应商路由、限流计费。

**与已有 Agent 项目的故事线**：应用层（Agent）+ 基建层（网关）= "既会写 AI 应用，也会做支撑 AI 应用的底层基础设施"。

---

## 1. 功能边界（YAGNI 砍过）

### 核心区（往死里挖，面试主战场）
- 🔥 **高并发异步流式转发**：SSE 边收边转、连接池复用、超时/背压控制、优雅取消。
- 🔥 **语义缓存**：相似问题命中缓存、向量检索、相似度阈值、命中率优化、多级缓存。

### 配套区（做扎实，不喧宾夺主）
- 多供应商适配 + 路由（DeepSeek / 智谱 / 通义 + 本地 Mock 上游）+ 故障转移/熔断。
- API Key 鉴权 + 令牌桶限流 + 按 token 配额/计费。
- 调用审计日志（异步落库）。
- 可观测性：Prometheus + Grafana（QPS / 延迟 / 缓存命中率 曲线 —— 压测证据来源）。

### 明确不做（YAGNI）
- ❌ 复杂前端管理界面（仅 API + 少量脚本，最多一个极简状态页）。
- ❌ 复杂用户/RBAC 权限体系（单层 API Key 足够）。
- ❌ 微调 / 训练（另一个项目）。
- ❌ 真·分布式多节点（单机 + Docker Compose，但代码为水平扩展留好接口：无状态网关、状态全放 Redis/PG）。

---

## 2. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| Web 框架 | **FastAPI**（async） | 原生异步、SSE/StreamingResponse 支持好、生态成熟、2026 作品集标配 |
| 异步 HTTP 客户端 | **httpx (AsyncClient)** | 支持异步流式、连接池复用 |
| 缓存/限流/配额/向量 | **Redis (Redis Stack)** | 热路径低延迟；RediSearch 向量索引(HNSW)做语义缓存 |
| 关系库 | **PostgreSQL** | API Key、审计、计费记录持久化 |
| Embedding 模型 | **本地 BGE-small (sentence-transformers)** | 免费、无 per-query API 成本、可控延迟 |
| 部署 | **Docker Compose** | 一键拉起：网关 + Redis + PG + Mock 上游 + Prometheus + Grafana |
| 压测 | **wrk / k6 + 自定义异步脚本** | 产出 QPS/延迟曲线 |
| 监控 | **Prometheus + Grafana** | 产出面试用的可视化证据 |

---

## 3. 整体架构与请求流转

```
客户端 (OpenAI 兼容请求 /v1/chat/completions)
      │
      ▼
┌─────────────────────────────────────────────┐
│              FastAPI 网关 (async, 无状态)       │
│                                               │
│  鉴权中间件 → 限流(令牌桶) → 配额检查           │
│        │                                       │
│        ▼                                       │
│   语义缓存查询 ──命中──► 流式回放缓存内容(SSE)   │
│        │ 未命中                                 │
│        ▼                                       │
│   路由选择(供应商/模型) → 健康检查/熔断          │
│        │                                       │
│        ▼                                       │
│   异步流式转发 (httpx async stream + SSE)        │
│        │  (边收边转给客户端，同时后台累积完整响应) │
│        ▼                                       │
│   写语义缓存 + 异步审计/计费落库                 │
└─────────────────────────────────────────────┘
   │            │              │
   ▼            ▼              ▼
 Redis      PostgreSQL    下游模型
(缓存/限流/  (Key/审计/    (国产API
 配额/向量)   计费)        + Mock上游)
```

**关键数据流**（非命中路径）：
1. 请求进入 → 鉴权 → 令牌桶限流 → 配额检查。
2. 对 query 做 embedding → Redis 向量检索找相似缓存（相似度 ≥ 阈值则命中）。
3. 命中：把缓存内容用 SSE 逐块"回放"给客户端（体验与真实流式一致）。
4. 未命中：路由选下游 → httpx 异步流式请求 → **边收边转给客户端，同时在后台 buffer 完整响应**。
5. 流结束：写语义缓存（异步）+ 异步记审计/扣费。

**无状态设计**：网关本身不存任何会话状态，所有状态（限流计数、配额、缓存、Key）都在 Redis/PG —— 这样多副本可水平扩展，是面试"如何扩展"的标准答案。

---

## 4. 核心深挖区设计（重头戏）

### 4.1 高并发异步流式转发

**问题**：大模型响应是流式（SSE，逐 token 返回），且单次请求耗时长（几秒~几十秒）。如果用同步阻塞模型，几百并发就会打满线程/连接。网关的价值在于用极少资源扛住大量长连接。

**设计要点**：
1. **全链路 async**：FastAPI + httpx.AsyncClient，事件循环单线程扛大量 IO 等待的长连接。
2. **连接池复用**：对每个下游供应商维护一个 httpx 连接池（`limits=Limits(max_connections, max_keepalive)`），避免每请求重建 TCP/TLS。
3. **边收边转（true streaming）**：用 `StreamingResponse` + `async for chunk in upstream.aiter_bytes()`，收到一块立即 `yield` 给客户端，不等完整响应。**同时**用一个轻量 buffer 累积完整内容，供流结束后写缓存。
4. **超时与背压控制**：
   - 连接超时 / 首字节超时（TTFB）/ 整体超时 三段式超时。
   - 客户端断开检测（`await request.is_disconnected()`）→ 立即取消下游请求，释放连接（避免"幽灵请求"耗资源）。
5. **优雅取消**：用 `asyncio.TaskGroup` / `CancelledError` 处理，确保客户端取消时下游 stream 被关闭。

**压测方案（产出曲线）**：
- 压测打 **本地 Mock 上游**（可配 TTFB、token 间隔、总 token 数），测的是网关本身的转发/并发能力，而非真实 API 延迟，干净可信。
- 指标：不同并发下的 QPS、P50/P95/P99 延迟、单实例最大稳定并发连接数。
- 对比实验（面试弹药）：
  - 同步阻塞实现 vs 全异步实现的并发对比。
  - 有无连接池复用的延迟对比。
  - 调优前后（如 worker 数、连接池大小、事件循环）的 QPS 曲线。

### 4.2 语义缓存

**问题**：传统精确缓存（key=完整 prompt 的 hash）命中率极低，因为用户问法千变万化。语义缓存用"语义相似"判断命中，大幅省钱省时延。

**设计要点**：
1. **Embedding**：本地 BGE-small 模型把 query 向量化（免费、低延迟、无外部依赖）。
2. **向量检索**：Redis Stack 的 RediSearch 建 HNSW 向量索引，存 `(embedding, 缓存内容, 元数据)`。查询时 KNN 取最相近的若干条。
3. **相似度阈值**：cosine 相似度 ≥ 阈值（如 0.95，可配）才算命中；阈值是准确率/命中率的权衡旋钮（面试可深入讲）。
4. **命中即流式回放**：命中的缓存内容也用 SSE 逐块吐回，保证客户端体验一致（不会"命中就一次性返回、未命中才流式"这种割裂）。
5. **缓存写入**：仅缓存"确定性较高"的请求（如 `temperature` 低于某阈值的请求），高随机性请求不缓存（否则命中了反而给错答案）—— 这是个体现思考深度的设计点。
6. **多级缓存**：
   - L1：精确匹配（prompt hash → Redis string），命中最快，零 embedding 开销。
   - L2：语义匹配（向量检索）。
   - 先查 L1，再查 L2。
7. **缓存治理**：TTL 过期、容量上限淘汰（LRU）、按 namespace/租户隔离。

**潜在坑与对策（面试加分）**：
- **缓存穿透**：恶意/大量不同 query 全部 miss → 可加请求合并/布隆过滤思想（这里更适合用"是否值得缓存"的前置判断）。
- **相似但语义不同**：阈值过低会误命中（如"今天天气"vs"明天天气"），需阈值调优 + 可选的轻量二次校验。
- **缓存命中率优化**：可记录 miss 的 query，离线分析阈值与 embedding 模型的影响。

**压测方案**：构造带一定"相似问题比例"的请求集，画 缓存命中率 vs 阈值 曲线、命中/未命中的延迟对比（命中应低一个数量级）。

---

## 5. 配套功能设计

### 5.1 多供应商适配与路由
- **统一抽象**：定义 `Provider` 接口（`async stream_chat(request) -> AsyncIterator[chunk]`），每个供应商（DeepSeek/智谱/通义/Mock）实现一个适配器，负责请求/响应格式转换为 OpenAI 兼容。
- **路由策略**：按模型名路由 + 同模型多供应商时按权重/健康度选择。
- **故障转移 + 熔断**：供应商连续失败 → 熔断器打开 → 自动切到备用供应商；半开探测恢复。

### 5.2 鉴权 + 限流 + 配额计费
- **鉴权**：网关签发 API Key（存 PG，Redis 缓存校验结果）；请求头 `Authorization: Bearer <key>`。
- **限流**：Redis + Lua 实现令牌桶（原子），按 Key 维度限 QPS/RPM。
- **配额/计费**：按 token 计量（请求/响应 token 数 × 单价），Redis 实时扣减配额，PG 落账单明细。

### 5.3 审计日志
- 每次调用异步写 PG：时间、Key、模型、供应商、token 数、耗时、是否命中缓存、状态。
- 异步落库（后台任务/队列），不阻塞主链路。

---

## 6. 数据模型

### PostgreSQL
```sql
-- API Key 与租户
api_keys(id, key_hash, name, tenant_id, quota_tokens, rpm_limit, status, created_at)

-- 调用审计/计费明细
call_logs(id, key_id, model, provider, prompt_tokens, completion_tokens,
          cost, latency_ms, cache_hit, status, created_at)

-- 供应商配置
providers(id, name, base_url, models[], weight, enabled)
```

### Redis（键设计）
```
ratelimit:{key_id}              -> 令牌桶状态 (Lua 原子操作)
quota:{key_id}                  -> 剩余配额 token 数
authcache:{key_hash}           -> 鉴权结果缓存 (TTL)
cache:exact:{prompt_hash}      -> L1 精确缓存内容
idx:semcache (RediSearch)      -> L2 语义缓存向量索引 (HNSW)
circuit:{provider}             -> 熔断器状态
```

---

## 7. 可观测性与压测（面试证据）

### 监控（Prometheus + Grafana）
暴露 `/metrics`，核心指标：
- `gateway_requests_total{model,provider,cache_hit,status}`
- `gateway_request_duration_seconds`（直方图，算 P50/P95/P99）
- `gateway_cache_hit_ratio`
- `gateway_upstream_inflight`（在途连接数）
- `gateway_tokens_total`

Grafana 大盘 → 直接截图进简历/作品集。

### 压测
- 工具：wrk / k6 + 自定义异步脚本（模拟流式客户端）。
- 场景：纯转发（打 Mock 上游）、带语义缓存（含相似问题）、故障转移。
- **产出物**：
  1. QPS vs 并发 曲线（同步 vs 异步对比）。
  2. P95/P99 延迟随并发变化曲线。
  3. 缓存命中率 vs 阈值 曲线 + 命中/未命中延迟对比。
  4. 单实例最大稳定并发连接数。

---

## 8. 部署

`docker-compose.yml` 一键拉起：
- `gateway`（FastAPI，uvicorn/gunicorn 多 worker）
- `redis`（Redis Stack，含 RediSearch）
- `postgres`
- `mock-upstream`（本地假大模型，压测用）
- `prometheus` + `grafana`

提供 `.env.example`、`README`（含快速启动、压测复现步骤、Grafana 大盘截图）。

---

## 9. 里程碑计划（适配 1-2 个月）

| 阶段 | 周 | 目标 | 产出 |
|---|---|---|---|
| **M1 骨架打通** | 第 1 周 | FastAPI 骨架 + OpenAI 兼容接口 + 一个真实国产供应商 + 非流式转发跑通 | 能代理一次真实调用 |
| **M2 核心：流式转发** | 第 2-3 周 | 全异步 SSE 边收边转 + 连接池 + 超时/取消 + Mock 上游 + 首轮压测 | QPS 曲线 v1 |
| **M3 核心：语义缓存** | 第 4-5 周 | BGE embedding + Redis 向量检索 + 多级缓存 + 阈值调优 + 命中率压测 | 命中率曲线 |
| **M4 配套功能** | 第 6 周 | 鉴权 + 令牌桶限流 + 配额计费 + 多供应商路由 + 熔断 + 审计 | 功能完整 |
| **M5 可观测+部署+打磨** | 第 7-8 周 | Prometheus/Grafana + Docker Compose + 完整压测报告 + README + 优化对比实验 | 简历级成品 |

> 时间紧时的优先级：M1 → M2 → M3 是不可砍的核心；M4 可适当精简（如先做限流+鉴权，计费简化）；M5 的监控与压测报告**不能砍**（那是和别人拉开差距的关键证据）。

---

## 10. 面试弹药（怎么讲）

- **一句话介绍**："我做了一个高并发的大模型统一网关，应用对接一个 OpenAI 兼容接口，由它统一做流式转发、语义缓存和多供应商容灾。单实例能稳定扛住 X 并发长连接，语义缓存把命中请求的延迟降低了一个数量级。"
- **能深挖 20 分钟的点**：
  1. 为什么全异步、async 怎么扛住大量长连接、事件循环原理。
  2. 边收边转怎么实现、客户端断开如何取消下游、背压。
  3. 语义缓存的相似度阈值权衡、什么请求该缓存、命中率怎么优化。
  4. 怎么科学压测一个代理层（为什么要 Mock 上游）。
  5. 无状态设计如何支撑水平扩展。
- **量化成果**（压测产出）：QPS 优化曲线、P99 延迟、缓存命中率、命中/未命中延迟对比。

---

## 11. 风险与应对

| 风险 | 应对 |
|---|---|
| 语义缓存误命中影响正确性 | 阈值调优 + 仅缓存低 temperature 请求 + 可选二次校验 |
| 本地 embedding 模型增加延迟 | BGE-small 轻量；L1 精确缓存先挡一层；可异步预热 |
| Redis Stack 向量功能上手成本 | 提前做最小可行 demo 验证 RediSearch HNSW |
| 范围膨胀、深度被摊薄 | 严守 YAGNI 清单；M1-M3 核心优先；配套区可精简 |
| 真实国产 API 限流/费用 | 功能演示用真实 API，压测一律打 Mock 上游 |
