# LLM 网关 M6（Docker Compose 一键编排）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把网关容器化，并用 docker-compose 一键拉起 网关 + redis-stack + Prometheus + Grafana，让项目"克隆即可跑"，并顺带把语义缓存的 Redis 向量后端真正跑通。

**Architecture:** 多阶段无关的轻量 `Dockerfile`（python:3.12-slim + 依赖 + 应用，uvicorn 启动）。`docker-compose.yml` 编排四个服务：gateway（构建本镜像，连 Redis 向量后端）、redis（redis/redis-stack，含 RediSearch）、prometheus（抓 gateway /metrics）、grafana（匿名只读看板，数据源指向 prometheus）。Prometheus 抓取配置与 Grafana 数据源用 `deploy/` 下的配置文件挂载。

**Tech Stack:** Docker、docker-compose、redis-stack、prom/prometheus、grafana/grafana。

> **里程碑说明**：本计划覆盖 M6（部署编排，设计文档 8 节），是核心网关全部完成后的最后收尾。**需要本机 Docker 守护进程已启动**（已确认可用）。
> **环境**：Windows + Docker Desktop；命令用 PowerShell。镜像构建/拉取较慢，相关步骤标注后台执行并轮询。

---

## 现状（M5 结束）

```
后端项目/
├── app/                 # 完整网关（providers/cache/auth/metrics/routes…）
├── mock_upstream/
├── scripts/
├── requirements.txt
├── tests/               # 60 passed, 1 skipped（Redis 测试因本机无 Redis 而 skip）
└── docs/
```

## M6 结束时新增/修改

```
Dockerfile                     # 新增：网关镜像
.dockerignore                  # 新增：构建上下文裁剪
docker-compose.yml             # 新增：四服务编排
deploy/prometheus.yml          # 新增：Prometheus 抓取配置
deploy/grafana-datasource.yml  # 新增：Grafana 自动配置 Prometheus 数据源
README.md                      # 修改：Docker 一键启动说明
```

---

## Task 1: Dockerfile + .dockerignore（构建网关镜像）

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: 写 `.dockerignore`**

```
.venv/
.git/
__pycache__/
*.pyc
.pytest_cache/
tests/
docs/
*.log
.env
```

- [ ] **Step 2: 写 `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 先装依赖（利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷应用代码
COPY app ./app
COPY mock_upstream ./mock_upstream

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: 构建镜像（后台，较慢——会装 fastembed/onnxruntime 等）**

Run（后台执行，日志写文件）:
```powershell
docker build -t llm-gateway:latest . *> docker_build.log
```
轮询 `docker_build.log`，直到出现 `naming to docker.io/library/llm-gateway:latest` 或 `FINISHED`。
Expected: 构建成功，最后一行类似 `=> => naming to docker.io/library/llm-gateway:latest`。

- [ ] **Step 4: 冒烟——单独跑容器验证 /health（不依赖 compose）**

Run:
```powershell
docker run -d --name gw-smoke -p 8010:8000 llm-gateway:latest
Start-Sleep -Seconds 6
.\.venv\Scripts\python.exe -c "import httpx; print(httpx.get('http://127.0.0.1:8010/health').json())"
docker rm -f gw-smoke
```
Expected: 打印 `{'status': 'ok'}`。

- [ ] **Step 5: Commit**

```powershell
git add Dockerfile .dockerignore
git commit -m "feat: 网关 Dockerfile 与 .dockerignore`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: docker-compose.yml + Prometheus/Grafana 配置

**Files:**
- Create: `deploy/prometheus.yml`
- Create: `deploy/grafana-datasource.yml`
- Create: `docker-compose.yml`

- [ ] **Step 1: 写 `deploy/prometheus.yml`**

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: llm-gateway
    static_configs:
      - targets: ["gateway:8000"]
```

- [ ] **Step 2: 写 `deploy/grafana-datasource.yml`**

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

- [ ] **Step 3: 写 `docker-compose.yml`**

```yaml
services:
  gateway:
    build: .
    ports:
      - "8000:8000"
    environment:
      VECTOR_STORE_BACKEND: redis
      REDIS_URL: redis://redis:6379
      MINIMAX_API_KEY: ${MINIMAX_API_KEY:-}
      MINIMAX_BASE_URL: ${MINIMAX_BASE_URL:-https://api.minimaxi.com/v1}
      GATEWAY_API_KEYS: ${GATEWAY_API_KEYS:-dev-key}
    depends_on:
      - redis

  redis:
    image: redis/redis-stack:latest
    ports:
      - "6379:6379"
      - "8001:8001"

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./deploy/prometheus.yml:/etc/prometheus/prometheus.yml
    depends_on:
      - gateway

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
      GF_SECURITY_ADMIN_PASSWORD: admin
    volumes:
      - ./deploy/grafana-datasource.yml:/etc/grafana/provisioning/datasources/datasource.yml
    depends_on:
      - prometheus
```

- [ ] **Step 4: 拉起整套（后台，较慢——拉取 redis-stack/prometheus/grafana 镜像）**

Run（后台执行，日志写文件）:
```powershell
docker compose up -d --build *> docker_compose_up.log
```
轮询 `docker_compose_up.log` 直到结束；随后：
```powershell
docker compose ps
```
Expected: gateway / redis / prometheus / grafana 四个服务 State 均为 `running`（或 `Up`）。

- [ ] **Step 5: 验证网关与指标抓取链路**

Run:
```powershell
Start-Sleep -Seconds 8
.\.venv\Scripts\python.exe -c "import httpx; print('health', httpx.get('http://127.0.0.1:8000/health').json()); print('metrics has http', 'gateway_http_requests_total' in httpx.get('http://127.0.0.1:8000/metrics').text)"
.\.venv\Scripts\python.exe -c "import httpx; r=httpx.get('http://127.0.0.1:9090/api/v1/targets'); print('prom targets up:', any(t.get('health')=='up' for t in r.json()['data']['activeTargets']))"
```
Expected: `health {'status':'ok'}`；`metrics has http True`；Prometheus 至少一个 target 抓取成功后 `prom targets up: True`（首次可能需多等几秒再试）。

- [ ] **Step 6: Commit**

```powershell
git add deploy/prometheus.yml deploy/grafana-datasource.yml docker-compose.yml
git commit -m "feat: docker-compose 编排(gateway+redis-stack+prometheus+grafana)`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 验证 Redis 向量后端（让 skip 的测试转绿）+ README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 对运行中的 redis-stack 跑 Redis 向量后端测试**

compose 已把 redis-stack 暴露在 `localhost:6379`。在宿主机直接跑那条原本 skip 的测试：
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_redis_vector_store.py -v
```
Expected: `1 passed`（不再 skip——因为 redis-stack 已在 6379 且含 RediSearch）。

- [ ] **Step 2: 跑全量测试确认整体**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: `61 passed`（原 60 passed + 此前 skip 的 Redis 用例现转 passed；若 compose 未运行则该用例仍 skip）。

- [ ] **Step 3: 在 `README.md` 顶部"快速开始"前追加"Docker 一键启动"一节**

在 `## 快速开始` 这一行之前插入：

```markdown
## Docker 一键启动（推荐）

需要本机 Docker。一条命令拉起 网关 + Redis(向量后端) + Prometheus + Grafana：

```powershell
# 可选：把真实 key 放进环境（否则缓存/路由仍可跑，仅真实下游调用需要）
$env:MINIMAX_API_KEY = "你的key"
docker compose up -d --build
```

- 网关：http://127.0.0.1:8000 （`/health` `/metrics` `/v1/chat/completions` …）
- Prometheus：http://127.0.0.1:9090
- Grafana：http://127.0.0.1:3000 （匿名可看，数据源已自动配好 Prometheus）
- Redis Insight：http://127.0.0.1:8001

停止：`docker compose down`

```

```

- [ ] **Step 4: 停掉 compose（清理；保留镜像）**

Run:
```powershell
docker compose down
```
Expected: 四个容器被移除。

- [ ] **Step 5: Commit**

```powershell
git add README.md
git commit -m "docs: Docker 一键启动说明`n`nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## M6 验收标准

- [ ] `docker build` 成功产出 `llm-gateway:latest`，容器 `/health` 返回 ok。
- [ ] `docker compose up -d --build` 四服务全部 running。
- [ ] 网关 `/metrics` 可访问；Prometheus 成功抓取 gateway target。
- [ ] Grafana 起来且数据源自动指向 Prometheus。
- [ ] compose 运行时 `tests/test_redis_vector_store.py` 转为 passed（Redis 向量后端真实跑通）。
- [ ] README 有 Docker 一键启动说明。
- [ ] 所有改动分任务提交。

完成后：设计文档全部能力落地，项目"克隆即跑、一键编排、可观测"。

---

## 备注：清理日志

构建/启动产生的 `docker_build.log` / `docker_compose_up.log` 已被 `.gitignore` 的 `*.log` 规则忽略，不会进提交；可在结束后手动删除。
