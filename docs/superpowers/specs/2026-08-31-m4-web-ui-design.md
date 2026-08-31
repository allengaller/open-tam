# M4 Web UI 设计（FastAPI 服务 + 单页聊天界面 + 流式排查过程）

- 日期：2026-08-31
- 状态：已确认（方案 A：进程内事件总线 + SSE 推流 + 无构建静态页）
- 前置：M0–M3 已完成合入 main（92 passed + 1 skipped）

## 1. 背景与目标

mvp-plan M4 里程碑：

> - [ ] FastAPI 服务 + 单页聊天界面
> - [ ] 排查过程流式展示（步骤/工具调用实时可见）
> - **验收**：浏览器发起排查并看到流式过程

现状可复用的基础：

- `fastapi`/`uvicorn` 已在依赖中；`receiver/webhook.py` 已有最小 FastAPI 应用（`POST /alerts` 落 inbox）
- 排查循环为同步实现（`ReActLoop.run_prompt`），`TraceRecorder.record` 逐条追加 JSONL（`alert_received`/`tool_call`/`observation`/`final`/`budget_exceeded`，`agent` 字段区分 orchestrator/metric/log），天然是流式事件源
- CLI `investigate` 是完整参考流程：告警 JSON → orchestrator 双子 Agent → 报告 + trace

## 2. 已确认的范围决策

| 决策点 | 结论 |
|---|---|
| 交互形态 | 单次排查会话；协议预留多轮追问扩展点（会话 id + 可重放事件流） |
| 敏感操作 | 沿用 agent 路径 AutoDeny：敏感动作自动拒绝并在流式过程展示拒绝原因，审计可查 |
| 告警输入 | 聊天框粘贴告警 JSON + 故障模板快捷入口（选故障 → 注入 demo-app 故障 + 预填告警 JSON） |
| fake 路径 | 支持（UI 开关），无 Key 也能完整演示验收 |
| 传输方案 | SSE（Server-Sent Events）+ 后台线程 + 事件广播；前端无构建步骤 |

## 3. 非目标（明确不做）

- 多轮追问（扩展点已预留：investigation id 即会话 id，事件缓存可重放）
- Web 版敏感操作人工确认（跨线程等待前端点击的 confirmer，留给后续）
- 历史排查列表页、鉴权、多用户
- 前端框架与构建工具链

## 4. 架构总览

```
src/open_tam/web/
├── __init__.py
├── app.py        # FastAPI 应用工厂 create_app(settings)：API 路由 + 静态页托管
├── events.py     # InvestigationHub：会话注册表 + 事件广播（线程→asyncio 桥接）
├── service.py    # Web 侧线程编排：创建会话、后台线程跑排查、推 done/error 事件
└── static/
    └── index.html   # 单文件前端（内嵌 CSS/JS，零构建，EventSource 消费 SSE）

src/open_tam/orchestrator/investigate.py   # 核心重构：排查组装主体（CLI 与 Web 共用）
```

两项对现有代码的改动：

1. **核心重构**：把 CLI `investigate` 的组装主体（fake 模型脚本构建、双子 Agent 组装、Guardrails/AutoDeny 接线、ReActLoop 运行、`save_report`）抽为
   `orchestrator/investigate.py: run_investigation(alert, settings, *, fake, transport, trace, metric_trace, log_trace) -> DiagnosisResult`。
   CLI `investigate` 命令改为：normalize → 建三个 TraceRecorder → 调 `run_investigation` → echo 输出，行为不变（全量测试回归保障）。
2. **TraceRecorder 加 sink**：构造参数 `sink: Callable[[dict], None] | None = None`。`record()` 照旧追加 JSONL；sink 存在时同步调用 `sink(entry)`（entry 含 `ts/alert_id/kind/agent?/...fields`）。trace 文件仍是唯一事实源，流式是旁路广播。

## 5. 组件与接口

### 5.1 InvestigationHub（web/events.py）

会话注册表与事件广播，单进程内存态（服务重启即清，可接受）。

- `create(alert, *, fake, transport) -> Investigation`：登记会话并返回。`Investigation` 含：`id`（uuid）、`status`（pending/running/done/error）、`alert`、`events: list[dict]`（带自增 `seq`，线程加锁 append）、`subscribers: list[Subscriber]`
- sink 回调（后台排查线程内被 TraceRecorder 调用）：加锁 append 事件到缓存（赋 seq）→ 遍历订阅者，对每个 queue 执行 `loop.call_soon_threadsafe(queue.put_nowait, entry)`
- `subscribe(id) -> (snapshot: list[dict], queue: asyncio.Queue)`：先取事件缓存快照（供 SSE 先重放），再注册新订阅者 queue。**每个订阅者独立 queue**，多标签页/刷新重连互不丢事件；重放 + queue 增量用 seq 天然衔接（新 queue 只收订阅之后的事件）
- 排查线程结束时由 service 调 `finish(id, result)` / `fail(id, error)`：更新 status，并广播终止事件（见 5.3 事件 schema）

### 5.2 API（web/app.py）

| 方法/路径 | 说明 |
|---|---|
| `POST /api/investigations` | body `{"alert": {...}, "fake": bool=false, "transport": "inline"\|"mcp"="inline"}`。`normalize_alert` 校验失败 → 422 + 错误信息；成功 → 202 `{"id": "...", "status": "running"}`，排查已在后台线程启动 |
| `GET /api/investigations/{id}/events` | SSE（`StreamingResponse`，`media_type="text/event-stream"`）。先重放快照事件，再 `await queue.get()` 增量推送；收到 done/error 后关闭。15s 无事件发送 `: keep-alive` 注释行 |
| `GET /api/faults` | 返回 `FAULT_MODES` 列表（name/anomaly_desc），供前端生成故障模板 |
| `POST /api/faults/{name}/activate` | `FaultState().activate(name, duration_minutes=30)`，未知 name → 404；返回 `{"activated": name}` |
| `GET /` | 返回 `static/index.html` |

### 5.3 SSE 事件 schema

每条 `data:` 为一行 JSON：

- 过程事件 = trace entry 原样 + `seq` 字段：`{"ts","alert_id","kind","agent"?,"seq",...}`，kind 取值 `alert_received`/`tool_call`/`observation`/`final`/`budget_exceeded`
- 终止事件：`{"kind":"done","seq",...,"report_path","root_cause","confidence","evidence","actions"}` 或 `{"kind":"error","seq","error"}`

### 5.4 前端（web/static/index.html 单文件）

- 顶部：故障模板按钮排（`GET /api/faults` 渲染）。点选 → `POST /api/faults/{name}/activate` → 预填对应告警 JSON 到输入框
- 主区聊天式时间线：
  - 用户侧：告警 JSON 卡片
  - agent 侧逐条渲染流式事件：`tool_call`（工具名 + 参数摘要）、`observation`（折叠，点开展开原文）、thought 文本；`agent` 字段配色区分 orchestrator/metric/log
  - done 事件 → 最终报告卡片（根因/证据/建议动作/置信度 + 报告路径）；error 事件 → 错误卡片
- 底部输入区：JSON textarea + fake 开关 + transport 选择 + 发送按钮；`EventSource` 订阅 `/api/investigations/{id}/events`，done/error 后 `close()`
- 样式：简洁工具风，浅色单主题，不引入构建工具

### 5.5 CLI 新命令

`open-tam serve`：`uvicorn.run(create_app())`，`--host`（默认 127.0.0.1）/`--port`（默认 8000）。

## 6. 数据流

1. 用户粘贴 JSON 或选模板 → `POST /api/investigations` → `normalize_alert` → `hub.create` → service 在后台线程里组装三个 TraceRecorder（orchestrator/metric/log，创建时挂同一 hub sink，子 Agent 事件同样流入 SSE）并调 `run_investigation`
2. ReActLoop 与子 Agent 每步 `record` → JSONL 照旧追加 + sink 广播 → SSE 推送
3. 浏览器 EventSource 逐条渲染；`run_investigation` 返回 → `save_report` 照旧落 `reports/` → hub 推 `done`（含报告路径与根因摘要）→ SSE 关闭
4. 刷新页面 → 新 `subscribe` 拿快照重放 + 增量，过程不丢

## 7. 错误处理

- 告警非法（缺字段/类型错/非 dict）→ POST 422 + normalize 错误信息
- 排查线程内异常（模型失败、文件 IO 等）→ service 捕获 → `fail()` → 推 `{kind:"error"}` → SSE 关闭，会话标 error；已落盘 JSONL 与审计不受影响
- SSE 断开（刷新/网络）→ EventSource 原生重连或重新 subscribe，事件缓存重放补齐
- 未知 investigation id 的 SSE → 404；未知故障名 activate → 404
- fake 路径脚本固定，不会出现 FakeChatModel exhausted

## 8. 测试策略

- 单测：TraceRecorder sink（record 时回调被调、JSONL 行为不变、entry 内容完整）；InvestigationHub（广播、多订阅者、快照重放、seq 衔接）
- API 测试（httpx/TestClient，`asyncio_mode=auto` 已配置，环境变量 `OPEN_TAM_REPORTS_DIR`/`OPEN_TAM_TRACES_DIR`/`OPEN_TAM_STATE_DIR` 指 tmp）：
  - POST 非法告警 → 422；POST 合告警（fake）→ SSE 收到 `alert_received → tool_call → observation → … → done` 完整序列，报告落盘
  - `GET /api/faults` 列表与注册表一致；`POST /api/faults/{name}/activate` 后 `FaultState` 生效、未知名 404
- 回归：CLI investigate 重构后行为不变（现有全量测试必须仍绿，M4 完成前再跑一次全量）
- 手动验收（见验收标准）：真实浏览器走 golden path + 刷新重放

## 9. 验收标准

1. `open-tam serve` 启动，浏览器打开页面
2. 选故障模板（如 cpu_spike）→ 一键注入 + 预填告警 → 发送
3. 流式看到排查过程：思考/工具调用/观察逐条出现，子 Agent 事件可区分；敏感动作被拒时展示拒绝原因
4. 排查结束出现报告卡片（根因/证据/建议动作/置信度/报告路径），`reports/` 落盘、`traces/` 可回放（`open-tam trace show`）
5. 刷新页面重放不丢过程；无 Key 环境（fake 开关）同样可走通全流程

## 10. 已知行为与限制（记录，不在 M4 解决）

- 用户显式提供重复 `alert_id` 的告警：trace JSONL 交错追加、报告同名覆盖——与 CLI 现状一致（`alert_id` 缺省时自动生成 uuid 前 12 位，Web 每次粘贴天然新 id，不冲突）
- 会话态在内存（重启即清）；事件缓存无上限——演示工具定位下可接受
- 多轮追问：会话 id 与可重放事件流已预留，待后续里程碑决定协议
