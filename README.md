# TickRadar

跨市场个人股票监控与资产管理系统。单仓库管理前后端，分别安装、构建和运行；通过 HTTP/OpenAPI 契约通信。

## 工程边界

- `frontend/`：Vue 3 + TypeScript + Vite，按功能模块组织页面、API 和状态。
- `backend/`：FastAPI + SQLAlchemy，统一使用 `src/cross_market` 包路径；API、Worker 独立入口。
- `deploy/`：MySQL 8、Redis 7、迁移服务、API、Worker、Nginx 的 Compose 配置。
- `scripts/`：契约导出等工程工具。

系统基础、证券主数据及自选股模块分批实施。行情、交易预警、持仓计算等能力继续等待相应验收；数据源选择不绑定富途或 OpenD。

## 本地运行

以下命令在仓库根目录执行。Windows Git Bash 使用 `backend/.venv/Scripts/python.exe`；其他系统改为 `backend/.venv/bin/python`。

```bash
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -c backend/constraints.txt -e "./backend[dev]"
npm --prefix frontend ci

# API：与其他项目隔离使用 18100 端口。
backend/.venv/Scripts/python.exe -m uvicorn cross_market.apps.api.main:app --host 127.0.0.1 --port 18100

# 新终端启动前端，默认端口 15173，/api 请求代理至 18100。
npm --prefix frontend run dev

# MySQL / Redis 可用时，在独立终端启动 Worker。
backend/.venv/Scripts/python.exe -m cross_market.apps.worker.main
```

后端连接参数使用 `TR_MYSQL_*`、`TR_REDIS_URL` 环境变量。后端不会自动读取仓库 `.env`；本地启动前需设置环境变量，Compose 则通过 `--env-file` 显式加载。数据库和缓存未运行时，系统状态页会显示真实异常；存活检查仍可访问，就绪检查返回 503。

## 容器运行

首次运行可使用下面的入口生成随机数据库密码和访问 Token；已有 `.env` 时会拒绝覆盖，凭据不输出。也可手工复制 `.env.example` 并替换示例值。Token 仅注入后端，不能写入 `VITE_*` 配置。需要已启动的 Docker Linux 引擎。

```bash
# 仅首次生成；已有本地配置时跳过这一行。
python scripts/init_local_env.py
docker compose --env-file .env -f deploy/docker-compose.yml config --quiet
docker compose --env-file .env -f deploy/docker-compose.yml up --build -d
```

访问 `http://127.0.0.1:18180`。仅 Nginx 映射回环地址；API、MySQL、Redis 不映射宿主机端口。迁移成功后才启动 API 和 Worker。数据库使用持久卷；删除持久卷会丢失数据。

## 迁移与接口契约

MySQL 可用并已设置连接环境变量后执行迁移；应用启动不会自动建表。

```bash
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head

# 导出契约无需启动 API；前端只消费契约 JSON，不导入 Python 源码。
backend/.venv/Scripts/python.exe scripts/export_openapi.py --output backend/openapi.json
npm --prefix frontend run generate:api
```

## 接口与验证

- `GET /health/live`：API 存活。
- `GET /health/ready`：必需依赖就绪；Worker 失联时为降级，不误报 API 死亡。
- `GET /api/v1/system/status`：组件状态和未启用任务。
- `GET /api/v1/system/modules`：功能模块实施目录。
- `GET /openapi.json`：后端接口契约。
- `GET /api/v1/auth/session`：验证内存中的 Bearer Token。
- `/api/v1/securities`：手工证券资料、分页搜索、市场筛选及名称/状态修改。
- `/api/v1/watchlist-groups`、`/api/v1/watchlists`：自选分组与成员增删、排序、备注和移动。

证券与自选接口全部需要 `Authorization: Bearer ...`；后端未配置 `TR_API_TOKEN` 时返回 `503 AUTH_NOT_CONFIGURED`，不会自动放行。Token 只在当前页面内存中保存，刷新和退出后需重新输入。手工证券资料标记为 `MANUAL`，不代表交易所或行情供应商已验证。

```bash
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests
backend/.venv/Scripts/python.exe -m ruff check backend
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

最新验证（2026-11-22）：后端 62 项、前端 24 项测试通过，Ruff、ESLint、类型检查和构建通过。隔离 HTTP 与浏览器录入、自选、备注、退出清理通过；桌面双栏、520px 备注弹窗和 390px 布局已验证。

真实 Docker 链路也已通过：独立镜像构建、MySQL 8.4.13 迁移至 `0002`、Redis 心跳及实例锁、Nginx 静态页面与 API 代理。并发创建重复分组仅一次成功；不同分组并发写入序号连续；MySQL 重启后自选及备注保留。重复 Worker 被拒绝；Worker 停止时 API 仍为 200 并标记 `degraded/stale`，Redis 不可读时 Worker 为 `unknown`，恢复后整体 `healthy`。合成验证记录已清理。

默认 Web 端口使用 `18180`，避免本机已有服务占用 `18080`。Worker 不另开健康端口，由 API 汇总 Redis 心跳判断。容器验收不代表行情源实时能力验收；数据备份、真实 SSE 业务和市场时效仍未完成。前端生产依赖审计零问题；测试工具间接依赖仍有 4 项 moderate，另保留一条 Starlette/httpx 测试弃用提示。

金额相关接口后续采用十进制字符串，时间带明确时区。注释说明职责、边界和设计原因；模块按复杂度分层，不预建空 Domain。阶段 0 的时效、额度、主备和授权验证通过后，再启用实时行情与风控。
