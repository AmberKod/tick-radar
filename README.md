# TickRadar

跨市场个人股票监控与资产管理系统。单仓库管理前后端，分别安装、构建和运行；通过 HTTP/OpenAPI 契约通信。

## 工程边界

- `frontend/`：Vue 3 + TypeScript + Vite，按功能模块组织页面、API 和状态。
- `backend/`：FastAPI + SQLAlchemy，统一使用 `src/cross_market` 包路径；API、Worker 独立入口。
- `deploy/`：MySQL 8、Redis 7、迁移服务、API、Worker、Nginx 的 Compose 配置。
- `scripts/`：契约导出等工程工具。

当前提供真实报价观察版：按代码查询 A 股、中国香港市场及美股报价，从查询结果登记证券并加入自选，Worker 独立采集，自选页面读取共享缓存。价格延迟未知，尚未通过开市时效与授权验收；交易预警和持仓计算尚未启用。数据源选择不绑定富途或 OpenD。

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

## 使用行情观察版

1. 打开 `http://127.0.0.1:18180/market`，输入标准代码（如 `CN:600519`、`HK:00700`、`US:AAPL`）或点击示例查询；公共报价无需 Token。
2. 点击“加入自选”，输入本机 `.env` 中的 `TR_API_TOKEN`。Token 只保存在当前页面内存，刷新页面后需要重新验证。
3. 选择或创建分组，确认交易所和证券类型，再加入自选。名称来自本次真实查询；美股交易所必须手选，供应商已知交易所与选择冲突时拒绝登记。
4. 在行情看板切换市场筛选，或进入“自选股”管理备注、顺序和分组。检查时间、源端时间、采集时间分别展示。

默认 Worker 每轮间隔 30 秒采集最多 50 个去重自选，行情看板和自选页通过鉴权 SSE 接收共享报价，不再定时请求报价接口。超过该总量的自选不保证后台覆盖；单个看板只展示所选分组前 50 个成员。可通过 `TR_QUOTE_REFRESH_INTERVAL_SECONDS`（10–300）和 `TR_QUOTE_MAX_SYMBOLS`（1–50）调整采集范围。API 不启动后台调度。

当前只有腾讯公共观察源，未配置独立备用。刷新使用 15 秒随机 owner 租约，Worker 发布同时校验实例 owner；共享上游预算每分钟最多 30 个批请求，Redis 不可用时每进程降为 10 批。失败保留旧价格及原采集时间并标记滞后，超过 180 秒缓存标记滞后；美股源端时间的时区尚未确认，不强行归一化。当前中国香港市场只接入 `HK:0xxxx` 港元柜台。

SSE 使用 `fetch` 流和内存 Token 请求头，连接及重连先发送最新全量快照，再接收报价更新；浏览器离线会取消旧连接并退避重连。连接显示“行情已连接/行情重连中”，切组、离开页面和退出会释放订阅。心跳每 10 秒发送，最长 300 秒轮换连接，每个 API 进程最多 8 条连接；缓存缺失等待 Worker，连接/重连不触发行情采集。Pub/Sub 不保存离线增量，事件 ID 不提供历史重放保证。

行情首页新增七所交易日历，区分常规交易、午间休市、常规时段外、休市和日历未知，并展示下一次开市/午后复市、收市、半日市标记及日历版本。常规日历状态与报价质量独立：开市不代表报价实时，延迟继续为 UNKNOWN；自动价格预警、止损通知、分钟线尚未启用。周末样本和页面闭环通过不代表阶段 0 Go；开市采样、独立备用和展示/缓存授权仍待验收。

日历固定使用已验证的 `exchange-calendars==4.13.3`，当前有效范围为交易所本地日期 `2026-01-01` 至 `2026-12-31`；覆盖外或加载失败返回 UNKNOWN，不按工作日猜测，也不推算下一年。沪深北的 2026 休市公告已逐日核对，显式共享 XSHG；库里的 BSE 别名实际指孟买交易所，本系统不使用该别名。中国香港使用 XHKG；NYSE、NASDAQ、AMEX 使用 XNYS 常规日历，并明确共享依据。午休、美国夏令时、提前收市及年初/年末边界已有回归，集合竞价细分、扩展时段、个股停牌与临时公告自动同步尚未实现。

临时全日闭市可通过 `TR_CALENDAR_CLOSED_DATES` JSON 配置，例如 `{"SSE:2026-12-31":"已核实的临时休市原因"}`，按具体交易所和本地日期生效，最多100项；这是格式示例，不是实际休市公告。配置更新后需重建 API/Worker 容器；系统会从下一次开闭市计算中跳过这些日期。空配置 `{}` 不覆盖日历，不提供临时开市、半日变更或单证券停牌入口。

2026 日历核对依据：[上交所休市公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)、[深交所休市公告](https://www.szse.cn/disclosure/notice/t20251222_618087.html)、[北交所休市公告](https://www.bse.cn/important_news/200027428.html)、[港交所证券市场假期](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/cc_SEHK_CT_075_2025.pdf)、[NYSE 假期和交易时间](https://nyse.com/trade/hours-calendars)、[Nasdaq 股票假期](https://www.nasdaq.com/market-activity/stock-market-holiday-schedule)。交易前仍需核对交易所临时公告；此模块不等同于自动交易或预警授权。

## 历史日线 K 线

休市不会阻止查询已有历史数据。进入侧栏“历史K线”或点击报价表中的“历史K线”，也可直接打开 `http://127.0.0.1:18180/market/history?symbol=US:AAPL`；历史页面无需 Token，不依赖最新报价是否成功或交易日历是否开市。

- 支持真实日线蜡烛图及供应商原始成交量，红涨绿跌，可缩放、拖拽、悬停查看精确 OHLCV 字符串。默认120根，可选60/120/250/640根；接口范围1至640。
- A股、中国香港市场支持不复权/raw、前复权/qfq、后复权/hfq，具体标的仍以供应商返回为准；美股当前支持raw/qfq，hfq明确返回 `422 ADJUSTMENT_UNSUPPORTED`，不退回不复权冒充后复权。
- 港股复权走专用历史接口；美股先从历史响应的证券元信息核对代码及交易所后缀，再读取对应完整序列。类别股如 `US:BRK.B` 不截断。北交所样本历史覆盖不足或为空时会如实显示，不保证所有标的均有640根历史。
- 首批保守排除交易所本地日期为今天的 Bar，即使当日已收市也不纳入；页面明确实际起止日、请求/返回根数、复权和采集时间。历史数据不套用实时报价180秒过期规则，也不拼接当前报价。
- OHLC使用十进制字符串、日期严格升序，校验高低价范围、非负成交量和响应体大小；附加公司行动字段不当作OHLCV。成交量单位尚未独立核验，保持原始值，不混用不同市场的“股/手”。
- 本批使用独立60秒进程内缓存，最多32项；同进程请求有并发控制，历史上游预算30次HTTP/分钟（美股身份探测也计数）。单请求6秒、整个历史查询12秒，前端等待15秒；超限/忙碌显示错误，不无限请求或降级伪造。
- `history_complete` 只表示达到请求根数，不保证无缺日、全部上市历史或所有公司行动正确。前复权历史可能因后续公司行动修订。日线长期存储和分钟线尚未实现；历史链路不启动Worker，不写实时缓存或广播，不落MySQL。日线指标观察计算已接入，见下节。

2026-11-22周末实测：`CN:600519`、`HK:00700`、`US:AAPL`及`US:BRK.B`均取得120根截至2026-11-20的日线；A股640根查询和已支持复权口径通过。真实浏览器9项验收、页面错误0，桌面及390px布局通过。证据为 `artifacts/history-validation.json`、`backend-history-tests.xml`、`frontend-history-tests.json`、`history-desktop.png`、`history-mobile.png`。源为腾讯公开历史接口，展示和长期存储许可仍待核实。

## 日线指标观察

打开“历史K线”并查询标的后，默认显示MA均线与MACD副图，图中可切换KDJ/ATR。“显示技术指标”开关立即重新查询，无需再点查询；展开“指标参数”可选择“短周期观察”或“标准参数”，也可调整周期后点击查询生效。参数不保存为数据库配置档案；输入非法值或MACD快线不小于慢线时不提交请求。只看纯K线可关闭开关，或通过`?symbol=US:AAPL&indicators=off`直接打开。

- 短周期观察：MA10、MACD(6,13,5)、KDJ(13,5,5)、ATR14；标准参数：MA20、MACD(12,26,9)、KDJ(9,3,3)、ATR14。
- MA叠加主图，可开关；MACD、KDJ、ATR在独立副图切换，成交量单独成区。悬停显示精确十进制字符串；未成熟值显示“预热不足”，图上不把空值当零。
- 指标最多展示500根，纯历史仍支持640根。接口按参数额外请求预热历史，总量最多640；响应说明源根数、实际裁掉的预热根数与期望预热数。来源不足或上限限制会提示，预热不保证递归指标绝对收敛；不同历史长度可能产生种子差异。
- 使用同一来源、同一复权序列计算后裁剪，指标日期与展示Bar严格对齐。保留原始历史截止日期和采集时间，单独标记计算时间、实际参数、参数SHA-256及`daily-v1`算法版本，不拼接当日或当前报价，不产生买卖信号或自动告警。
- 公式：SMA为窗口均值；EMA用前n项均值作种子，alpha=2/(n+1)；DIF为快慢EMA差，DEA用signal个有效DIF均值初始化，MACD柱为2×(DIF−DEA)。KDJ从完整回看窗口起算，K/D初值50，RSV零分母取50，递归平滑，J=3K−2D且不截断。ATR首根TR=高−低，之后兼顾昨收缺口；前n个TR均值初始化，再按Wilder递推。
- 领域计算使用Decimal精度80，最终输出10位小数、ROUND_HALF_EVEN，不在中间步骤人为截断。相同参数、相同输入和算法版本可复现；供应商指标的初始化或复权历史可能不同，不能只凭同名指标认定完全一致。

2026-11-22用同次真实历史数据，三市场短周期组合与美股标准组合共4组、3,840个输出值与独立pandas rolling/ewm参考逐点核对，绝对误差均≤1e-8。浏览器5项验收及原历史9项、SSE7项回归通过，页面错误0；证据为`artifacts/daily-indicators-reference.json`、`daily-indicators-browser.json`、`backend-indicators-tests.xml`、`frontend-indicators-tests.json`和`indicators-desktop.png`/`indicators-mobile.png`。本批不增加数据库表或Worker任务，配置档案持久化、分钟指标、指标缓存及规则引擎后续实施。

## 迁移与接口契约

MySQL 可用并已设置连接环境变量后执行迁移；应用启动不会自动建表。

```bash
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head

# 导出契约无需启动 API；前端只消费契约 JSON，不导入 Python 源码。
backend/.venv/Scripts/python.exe scripts/export_openapi.py --output backend/openapi.json
npm --prefix frontend run generate:api
```

## 加密备份与隔离恢复验收

运维入口独立运行，不在 API/Worker 启动时执行。首次安装额外依赖，并在仓库根目录执行：

```bash
backend/.venv/Scripts/python.exe -m pip install -c backend/constraints.txt -e "./backend[backup]"

# 仅首次生成；已有密钥时拒绝覆盖。
backend/.venv/Scripts/python.exe -m cross_market.operations.backup init-key
backend/.venv/Scripts/python.exe -m cross_market.operations.backup create

# 将下面路径替换为 create 输出的实际备份文件。
backend/.venv/Scripts/python.exe -m cross_market.operations.backup inspect artifacts/backups/<文件名>.trbk
backend/.venv/Scripts/python.exe -m cross_market.operations.backup restore-check artifacts/backups/<文件名>.trbk
```

`--key <路径>` 必须放在子命令之前，`create --output <目录>` 可选择另一个备份目录。所有相对路径以命令当前工作目录为基准；在仓库根目录之外执行时，应显式指定密钥、归档及输出目录的绝对路径。默认密钥为 `.local-secrets/backup.key`，备份为 `artifacts/backups/*.trbk`；密钥与备份禁止放进同一目录树，两者均被 Git 和镜像构建忽略。文件权限按 `0600` 创建；Windows 的实际访问控制由目录 ACL 决定。

- AES-256-GCM 对元数据和 SQL 做完整性认证。文件损坏或密钥错误时，在创建容器前拒绝；密钥丢失无法恢复，请另行安全保管。
- 导出仅使用 Compose `tick-radar/mysql` 容器的内部凭据，不读主机 `.env` 或打印密码，SQL 仅在内存和管道中传递，磁盘只落密文。
- 首版限制 SQL 为 64 MiB，只支持 InnoDB 基础表；视图、触发器、例程、事件或其他表引擎会拒绝。备份期间禁止 DDL/数据库迁移；数据写入通过一致性事务快照导出。
- `restore-check` 只会创建唯一临时 MySQL，禁网、不映射端口、不挂源卷，校验迁移版本、表行数和重新导出摘要后清理。它不提供覆盖当前数据库的入口；跨机演练还需预先准备归档中记录的本地 MySQL 镜像。
- 当前实现为按需备份与恢复验收，不自动创建计划、不自动删除历史文件。默认目录仍在同一台机器，异机复制、密钥独立保管、30 份日备份/12 份月备份的保留执行尚未配置。

2026-11-22 真实演练已恢复非空证券/自选数据，重导出摘要一致，源库恢复前后及合成数据清理后的摘要未改变；临时容器无残留。演练归档含当时的合成资料；清理后已另行生成并恢复验证不含合成记录的备份。应按归档的创建时间和验收报告选择恢复点，不能将演练备份当作日常业务备份。

## 接口与验证

- `GET /health/live`：API 存活。
- `GET /health/ready`：必需依赖就绪；Worker 失联时为降级，不误报 API 死亡。
- `GET /api/v1/system/status`：组件、Worker 与任务状态，含采集最近成功时间。
- `GET /api/v1/system/modules`：功能模块实施目录。
- `GET /openapi.json`：后端接口契约。
- `GET /api/v1/auth/session`：验证内存中的 Bearer Token。
- `GET /api/v1/events/stream?symbols=...`：鉴权 SSE，单次最多50代码；事件为 snapshot / quote.updated / heartbeat / error，data契约为 QuoteStreamEvent。Token不接受URL传递。
- `GET /api/v1/market-calendar/statuses`：公共七所常规日历，可用 `?exchange=NASDAQ` 筛选一所；不接受任意日期查询。
- `GET /api/v1/market/quote?symbol=...`、`GET /api/v1/market/quotes?symbols=...`：公共观察报价，匿名 GET 不允许强制刷新。
- `GET /api/v1/market/history?symbol=US:AAPL&limit=120&adjustment=raw`：公共历史日线，与实时链路及日历开市状态独立。
- `POST /api/v1/indicators/daily`：公共只读日线指标计算；body为`{symbol,limit,adjustment,parameters}`，不接受客户端上传Bar，不写入业务事实。
- `POST /api/v1/market/refresh`：鉴权主动刷新，受共享租约和预算限制。
- `POST /api/v1/securities/from-quote`：鉴权真实查询后登记证券，来源标记 `TENCENT_LOOKUP`。
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

最新验证（2026-11-22）：含备份可选依赖时后端 397 项、前端 71 项测试通过，Ruff、ESLint、类型检查、生产构建和 pip check 通过。真实浏览器 9 项检查通过、页面运行错误 0，覆盖匿名查询、首次验证后保留报价、快捷加自选、美股交易所手选、四市场筛选、可读时间、自选页报价、退出与 Token 不落浏览器存储；桌面与 390px 布局已复验。既有业务证据位于忽略的 `artifacts/backend-market-tests.xml`、`frontend-market-tests.json`、`market-browser-validation.json`。本批日历验收 6 项通过、SSE 7 项回归通过，页面错误均为 0；最终测试与日历证据为 `backend-calendar-tests.xml`、`frontend-calendar-tests.json`、`market-calendar-validation.json`，含容器内午休、半日市、DST 和覆盖外 UNKNOWN 核验。

真实 Docker 链路也已通过：独立镜像构建、MySQL 8.4.13 迁移至 `0003`、Redis 心跳及实例锁、Nginx 静态页面与 API 代理。Nginx 使用 Docker DNS 动态解析 API 容器地址，API 独立重建后代理恢复已实测。关闭浏览器后的 35 秒无行情 HTTP 请求窗口中，两个自选的采集时间继续推进，采集任务为 success；证据为 `artifacts/market-worker-validation.json`。并发创建重复分组仅一次成功；不同分组并发写入序号连续；MySQL 重启后自选及备注保留。重复 Worker 被拒绝；Worker 停止时 API 仍为 200 并标记 `degraded/stale`，Redis 不可读时 Worker 为 `unknown`，恢复后整体 `healthy`。合成验证记录已清理。

默认 Web 端口使用 `18180`，避免本机已有服务占用 `18080`。Worker 不另开健康端口，由 API 汇总 Redis 心跳判断。容器验收不代表行情源实时能力验收；加密备份/隔离恢复已通过，定时与异机保管、开市时效和实时预警仍未完成。鉴权 SSE 和断线快照恢复已完成，真实推送验收 7 项通过，页面错误 0，退出后 Redis 订阅数归零；证据为 `artifacts/quote-stream-validation.json`、`backend-sse-tests.xml` 和 `frontend-sse-tests.json`。前端生产依赖审计零问题；测试工具间接依赖仍有 4 项 moderate，另保留一条 Starlette/httpx 测试弃用提示。

观察报价金额采用十进制字符串；归一化时间带明确时区，未知源端时区保留原文。注释说明职责、边界和设计原因；模块按复杂度分层，不预建空 Domain。阶段 0 的时效、额度、主备和授权验证通过后，再启用实时行情与风控。
