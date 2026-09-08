# open-tam M5–M10 全阶段产品设计文档

- 日期：2026-09-08
- 状态：待确认（用户批准后分阶段实施）
- 前置：M0–M3 已合入 main（107 tests green）；M4 Web UI 已完成于 `feat/m4-web-ui` 分支待合并

---

## 0. 文档结构

本文档覆盖 open-tam 从 M5 到 M10 的六个阶段设计，每阶段独立可验收。

| 阶段 | 主题 | 预估周期 |
|---|---|---|
| M5 | 实盘接入 | 2–3 周 |
| M6 | 知识沉淀与 Skill 系统 | 2–3 周 |
| M7 | 多租户与生产化 | 2–3 周 |
| M8 | K8s 与基础设施排障 | 3–4 周 |
| M9 | 高级评测与质量闭环 | 持续 |
| M10 | 告警风暴与高级编排 | 远期 |

依赖链：M5 → M6 → M7；M8 独立于 M6/M7 但依赖 M5；M9 与 M5+ 并行；M10 依赖全部前序。

---

# M5 实盘接入

## 1. 背景与目标

mvp-plan M5 里程碑：

> - [ ] 云监控 webhook 告警接入
> - [ ] alibabacloud-observability MCP 替换 mock 后端
> - [ ] （可选）K8sGPT + kind 集群排障
> - [ ] （可选）ACS Agent Sandbox 隔离执行
> - **验收**：一条真实告警跑通完整闭环

现状：M0–M4 全部基于 mock 数据源（`mock-metrics-mcp-server` / `mock-logs-mcp-server`）。MCP 工具总线已预留替换路径——`query_metrics` / `query_logs` 签名固定，替换后端不影响编排层代码。

## 2. 已确认的范围决策

| 决策点 | 结论 |
|---|---|
| 告警来源 | 阿里云云监控 Webhook（CMS AlertCallback），兼容 Prometheus AlertManager 格式 |
| 指标后端 | alibabacloud-observability MCP（CMS DescribeMetricData） |
| 日志后端 | SLS（Simple Log Service）via MCP 或 SDK |
| 认证方式 | 环境变量 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET`，与现有 DashScope 配置并列 |
| 后端切换 | `config.py` 增加 `metrics_backend` / `logs_backend` 开关（mock / aliyun），运行时按配置选择 MCP server |
| 告警去重 | 内存态 + 文件态双保险：同一 `alert_name + service` 5 分钟内不重复触发排查 |
| K8sGPT / ACS | M5 不引入，留 M8 |

## 3. 非目标（M5 不做）

- K8s 集群排障（M8）
- ACS Agent Sandbox（M8）
- 多告警源聚合（M10）
- 数据库持久化（M7）

## 4. 架构变更

```
src/open_tam/
├── receiver/
│   ├── alert_receiver.py        # 现有：AlertEvent 标准化
│   ├── webhook.py               # 扩展现有：增加签名验证 + 去重 + 多格式适配
│   └── dedup.py                 # 新增：告警去重器（滑动窗口）
├── mcp_servers/
│   ├── metrics_server.py        # 保留（mock 后端）
│   ├── logs_server.py           # 保留（mock 后端）
│   ├── aliyun_metrics_server.py # 新增：alibabacloud-observability MCP 封装
│   └── aliyun_logs_server.py    # 新增：SLS MCP 封装
├── config.py                    # 扩展：metrics_backend / logs_backend / aliyun_* 配置项
└── orchestrator/
    └── tools.py                 # 扩展：后端选择逻辑（按 config 路由到 mock 或 aliyun MCP server）
```

### 4.1 云监控 Webhook 适配

**签名验证**：云监控回调支持 HMAC-SHA256 签名。`webhook.py` 增加 `verify_signature(request_body, signature_header, secret)` 校验。

**多格式适配**：

```python
# 云监控原生格式 → AlertEvent
def from_cms_alert(payload: dict) -> AlertEvent:
    return AlertEvent(
        alert_id=payload.get("alertId", generate_id()),
        alert_name=payload["alertName"],
        severity=map_severity(payload.get("level", "WARN")),
        service=payload.get("dimensions", {}).get("instanceId", "unknown"),
        metric=payload.get("metricName", ""),
        threshold=float(payload.get("threshold", 0)),
        current_value=float(payload.get("curValue", 0)),
        triggered_at=payload.get("alertTime", iso_now()),
        labels=payload.get("dimensions", {}),
    )

# Prometheus AlertManager → AlertEvent
def from_alertmanager(payload: dict) -> AlertEvent:
    alert = payload["alerts"][0]  # 取首个告警
    return AlertEvent(
        alert_id=alert.get("fingerprint", generate_id()),
        alert_name=alert["labels"]["alertname"],
        severity=alert["labels"].get("severity", "warning"),
        service=alert["labels"].get("service", "unknown"),
        metric=alert["labels"].get("metric", ""),
        threshold=0.0,
        current_value=0.0,
        triggered_at=alert["startsAt"],
        labels=alert["labels"],
    )
```

**去重器**（`dedup.py`）：

```python
class AlertDedup:
    """滑动窗口去重：同一 alert_name+service 在 window_seconds 内只触发一次排查"""
    def __init__(self, window_seconds: int = 300):
        self._seen: dict[str, float] = {}  # key -> last_triggered_ts
        self._window = window_seconds

    def should_process(self, alert: AlertEvent) -> bool:
        key = f"{alert.alert_name}:{alert.service}"
        now = time.time()
        last = self._seen.get(key, 0)
        if now - last < self._window:
            return False
        self._seen[key] = now
        return True
```

持久化：去重状态写入 `var/dedup.json`，服务重启后恢复。

### 4.2 alibabacloud-observability MCP

**工具签名与 mock 完全一致**：

```
query_metrics(metric: str, service: str, start: str, end: str) -> list[MetricPoint]
query_logs(service: str, start: str, end: str, level: str | None, keyword: str | None) -> list[LogRecord]
```

**实现策略**：

- `aliyun_metrics_server.py`：调用 CMS `DescribeMetricData` API，将返回的 Datapoints JSON 解析为 `MetricPoint` 列表
- `aliyun_logs_server.py`：调用 SLS `GetLogs` API，将日志条目解析为 `LogRecord` 列表
- 时间格式：`start` / `end` 为 ISO 8601，内部转换为 Unix timestamp 传给阿里云 API
- 错误处理：API 限流返回空列表 + warning（不中断排查循环）

### 4.3 后端路由

`orchestrator/tools.py` 的 `McpStdioBackend` 扩展为按配置选择 MCP server 进程：

```python
def _metrics_server_cmd(settings: Settings) -> list[str]:
    if settings.metrics_backend == "aliyun":
        return [sys.executable, "-m", "open_tam.mcp_servers.aliyun_metrics_server"]
    return [sys.executable, "-m", "open_tam.mcp_servers.metrics_server"]
```

### 4.4 新增配置项

```python
# config.py 新增
metrics_backend: str = "mock"          # "mock" | "aliyun"
logs_backend: str = "mock"             # "mock" | "aliyun"
aliyun_region: str = "cn-hangzhou"
aliyun_access_key_id: str = ""         # 环境变量 ALIYUN_ACCESS_KEY_ID
aliyun_access_key_secret: str = ""     # 环境变量 ALIYUN_ACCESS_KEY_SECRET
aliyun_sls_project: str = ""           # SLS Project 名
aliyun_sls_logstore: str = ""          # SLS Logstore 名
dedup_window_seconds: int = 300
webhook_secret: str = ""               # 云监控签名密钥
```

## 5. 数据流

1. 云监控触发告警 → HTTP POST 到 `/alerts` → 签名验证 → 格式适配 → `AlertEvent`
2. 去重器检查：重复告警 → 200 + `{"dedup": true}` → 不触发排查
3. 新告警 → 启动排查（同 M4 流程，但 MCP 后端为 aliyun）
4. `query_metrics` → CMS API → 真实时序数据
5. `query_logs` → SLS API → 真实日志数据
6. 排查完成 → 报告 + trace 落盘（与 mock 路径格式完全一致）

## 6. 错误处理

| 故障点 | 策略 |
|---|---|
| 签名验证失败 | 401 + 审计日志记录来源 IP |
| 阿里云 API 认证失败 | 排查循环中工具返回错误信息，LLM 观察到后调整策略 |
| CMS API 限流（429） | 退避重试 3 次，仍失败返回空列表 + warning |
| SLS 查询超时 | 10s 超时，返回已获取的部分结果 |
| 去重器文件损坏 | 降级为内存态，下次启动重建 |

## 7. 测试策略

- 单测：`from_cms_alert` / `from_alertmanager` 格式转换（fixture 来自真实 payload 脱敏）
- 单测：去重器窗口逻辑（同 key 二次调用返回 False，过期后返回 True）
- 集成测试：mock CMS/SLS API（`responses` 库或 `httpx` mock），验证 `query_metrics` / `query_logs` 返回正确的 `MetricPoint` / `LogRecord`
- 端到端：录制真实告警 payload → 全链路排查 → 报告产出
- 回归：`metrics_backend=mock` 路径下现有全量测试不受影响

## 8. 验收标准

1. `POST /alerts` 接收云监控格式告警，签名验证通过，触发排查
2. 去重：同一告警 5 分钟内第二次 POST 不触发排查
3. `metrics_backend=aliyun` 配置下，`query_metrics` 返回 CMS 真实数据
4. `logs_backend=aliyun` 配置下，`query_logs` 返回 SLS 真实日志
5. 一条真实告警端到端跑通：告警 → 排查 → 报告 + trace 落盘
6. `metrics_backend=mock` 下现有测试全量 green

---

# M6 知识沉淀与 Skill 系统

## 1. 背景与目标

open-tam 核心差异化——"排查即语料"的深化。当前 trace 只用于回放和评测，未被主动利用。M6 目标：从历史 trace 中提取排查模式，反哺后续排查。

> - [ ] `open-tam learn` 命令：从 trace 中提取排查模板
> - [ ] Skill 存储与加载机制
> - [ ] ReAct 循环接入 Skill 先验知识
> - [ ] Web UI 知识库标签页
> - **验收**：历史排查经验被自动提取为 Skill，新排查时 Skill 被加载并影响排查路径

## 2. 已确认的范围决策

| 决策点 | 结论 |
|---|---|
| Skill 格式 | YAML 文件，存储于 `skills/` 目录 |
| 提取方式 | 规则提取（M6）+ LLM 辅助总结（M6 可选） |
| 匹配策略 | 按 `alert_name` 精确匹配 + `service` 模糊匹配 |
| 注入方式 | 作为 system prompt 补充，不强制路径 |
| 手动管理 | 支持手动创建/编辑/删除 Skill YAML |

## 3. 架构变更

```
src/open_tam/
├── skills/
│   ├── __init__.py
│   ├── loader.py         # Skill 加载与匹配
│   ├── extractor.py      # 从 trace 中提取排查模板
│   └── models.py         # Skill Pydantic 模型
├── cli.py                # 新增 open-tam skill list/learn/create/delete 命令
└── web/
    └── static/
        └── index.html    # 增加知识库标签页

skills/                   # 项目根目录，Skill YAML 存储
├── cpu_spike_default.yaml
└── slow_query_db.yaml
```

### 3.1 Skill 数据模型

```python
class Skill(BaseModel):
    id: str                          # 唯一标识，也是文件名（不含 .yaml）
    name: str                        # 人类可读名称
    alert_pattern: str               # 匹配的告警名（支持 glob：cpu_*）
    service_pattern: str = "*"       # 匹配的服务（默认通配）
    description: str                 # 排查场景描述
    steps: list[SkillStep]           # 建议排查步骤
    root_cause_hints: list[str]      # 常见根因提示
    evidence_patterns: list[str]     # 关键证据特征（关键词匹配）
    created_from: str | None = None  # 来源 trace 文件路径（手动创建为 None）
    created_at: str                  # ISO 8601
    confidence: float = 0.0          # 提取置信度（0-1，基于出现频次）

class SkillStep(BaseModel):
    order: int
    action: str                      # "query_metrics" | "query_logs" | "analyze"
    params: dict                     # 建议参数（如 metric="cpu_util"）
    expected_signal: str             # 期望观察到的信号（如 "cpu > 80%"）
    rationale: str                   # 为什么查这个
```

### 3.2 Skill YAML 示例

```yaml
id: cpu_spike_default
name: CPU 飙升排查模板
alert_pattern: "cpu_*"
service_pattern: "*"
description: 应用 CPU 使用率飙升至 80% 以上的标准排查路径
steps:
  - order: 1
    action: query_metrics
    params:
      metric: cpu_util
      window: "15m"
    expected_signal: "cpu > 80% 持续 5 分钟以上"
    rationale: 确认 CPU 异常幅度与持续时间
  - order: 2
    action: query_metrics
    params:
      metric: load_average
      window: "15m"
    expected_signal: "load > CPU 核数 * 2"
    rationale: 判断是计算密集还是 IO 等待
  - order: 3
    action: query_logs
    params:
      level: ERROR
      window: "15m"
    expected_signal: "异常堆栈或超时日志"
    rationale: 查找触发 CPU 飙升的代码路径
  - order: 4
    action: analyze
    params: {}
    expected_signal: "根因 + 证据链"
    rationale: 综合指标与日志定位根因
root_cause_hints:
  - 死循环或递归过深
  - GC 频繁触发
  - 热点 key 导致单线程过载
  - 正则回溯
evidence_patterns:
  - "cpu_util > 80"
  - "load_average"
  - "GC"
  - "timeout"
created_from: traces/cpu-spike-abc123.jsonl
created_at: "2026-09-15T10:00:00Z"
confidence: 0.85
```

### 3.3 Trace 提取引擎（`open-tam learn`）

```python
def extract_skill_from_trace(trace_path: str) -> Skill:
    """从单条 trace 中提取排查模板"""
    entries = load_trace(trace_path)

    # 1. 提取工具调用序列
    tool_calls = [e for e in entries if e["kind"] == "tool_call"]
    steps = []
    for i, call in enumerate(tool_calls):
        steps.append(SkillStep(
            order=i + 1,
            action=call["tool"],
            params=call.get("arguments", {}),
            expected_signal="",  # 由 LLM 填充或留空
            rationale="",
        ))

    # 2. 提取根因
    final = next((e for e in entries if e["kind"] == "final"), None)
    root_cause_hints = [final["root_cause"]] if final else []

    # 3. 提取告警模式
    alert_received = next((e for e in entries if e["kind"] == "alert_received"), None)
    alert_pattern = alert_received["alert_name"] if alert_received else "*"

    # 4. 组装 Skill
    return Skill(
        id=generate_skill_id(alert_pattern),
        name=f"{alert_pattern} 排查模板",
        alert_pattern=alert_pattern,
        description=f"从 trace {trace_path} 自动提取",
        steps=steps,
        root_cause_hints=root_cause_hints,
        evidence_patterns=extract_evidence_keywords(entries),
        created_from=trace_path,
        created_at=iso_now(),
        confidence=calculate_confidence(entries),
    )
```

**批量学习**：`open-tam learn --traces traces/ --output skills/` 遍历所有 trace，按 `alert_name` 聚合，相同告警类型的多条 trace 合并为更高置信度的 Skill。

### 3.4 Skill 注入 ReAct 循环

```python
# orchestrator/loop.py 修改
def run_investigation(alert, settings, ...):
    # 加载匹配的 Skill
    skill = SkillLoader(settings.skills_dir).match(alert)
    if skill:
        system_prompt += f"\n\n## 排查参考（来自历史经验）\n{skill.to_prompt_section()}"

    # 后续 ReAct 循环不变——LLM 可参考也可忽略
```

Skill 注入为 system prompt 的附加段，不改变工具签名、不限制 LLM 自由度。

### 3.5 CLI 命令

| 命令 | 说明 |
|---|---|
| `open-tam skill list` | 列出所有 Skill（id / name / alert_pattern / confidence） |
| `open-tam skill learn --traces <dir>` | 从 trace 目录批量提取 Skill |
| `open-tam skill create --name <name> --alert <pattern>` | 交互式创建 Skill |
| `open-tam skill delete <id>` | 删除 Skill |
| `open-tam skill show <id>` | 查看 Skill 详情 |

### 3.6 Web UI 知识库标签页

- 列表视图：所有 Skill，按 confidence 降序
- 详情视图：步骤列表 + 根因提示 + 来源 trace 链接
- 操作：编辑（YAML 编辑器）、删除、从 trace 创建
- 排查页面：匹配到 Skill 时在报告卡片中展示"参考了 N 条历史经验"

## 4. 测试策略

- 单测：Skill YAML 序列化/反序列化、匹配逻辑（glob 模式）
- 单测：trace 提取引擎（用 M2 已有的 trace fixture）
- 集成测试：`open-tam skill learn` 从已有 trace 生成 Skill 文件
- 集成测试：Skill 注入后 ReAct 循环行为变化（fake 路径可验证 system prompt 包含 Skill 内容）
- 回归：无 Skill 时行为不变（`skills/` 目录为空或不存在时跳过注入）

## 5. 验收标准

1. `open-tam skill learn --traces traces/` 从现有 trace 生成至少 1 个 Skill YAML
2. `open-tam skill list` 展示生成的 Skill
3. 新排查匹配到 Skill 时，system prompt 包含排查参考信息
4. Web UI 知识库标签页可查看/编辑/删除 Skill
5. 无 Skill 时全量测试不受影响

---

# M7 多租户与生产化

## 1. 背景与目标

从个人工具到团队平台。当前所有状态为 JSON 文件，无认证，无用户概念。

> - [ ] SQLite 持久化层替代 JSON 文件
> - [ ] 简单认证（API Key / Bearer Token）
> - [ ] 角色权限（admin / operator / viewer）
> - [ ] 通知集成（钉钉 / 飞书 / Slack）
> - **验收**：多用户通过认证访问 Web UI，排查历史持久化可检索

## 2. 已确认的范围决策

| 决策点 | 结论 |
|---|---|
| 数据库 | SQLite（单文件部署，可后续升级 PostgreSQL） |
| 迁移 | 简单版本表 + 手动迁移脚本（不引入 alembic 重量级依赖） |
| 认证 | API Key（简单场景）+ 可选 OAuth2 Bearer（企业场景） |
| 角色 | admin（管理 Skill/配置/用户）、operator（发起排查/确认动作）、viewer（只读） |
| 通知 | Webhook 方式（钉钉/飞书/Slack 均支持），排查完成 + 敏感操作确认两个场景 |
| 会话归属 | 排查 session 绑定 user_id |

## 3. 架构变更

```
src/open_tam/
├── persistence/
│   ├── __init__.py
│   ├── database.py       # SQLite 连接管理 + 迁移
│   ├── models.py         # ORM 模型（investigation / audit / alert / skill）
│   └── repositories.py   # 数据访问层
├── auth/
│   ├── __init__.py
│   ├── middleware.py     # FastAPI 认证中间件
│   ├── apikey.py         # API Key 验证
│   └── roles.py          # 角色权限检查
├── notifications/
│   ├── __init__.py
│   ├── dispatcher.py     # 通知调度器
│   ├── dingtalk.py       # 钉钉 Webhook
│   ├── feishu.py         # 飞书 Webhook
│   └── slack.py          # Slack Webhook
├── config.py             # 新增：database_url / auth_* / notify_* 配置
└── web/
    └── app.py            # 接入认证中间件 + 通知钩子
```

### 3.1 数据库 Schema

```sql
-- 迁移版本表
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);

-- 排查记录
CREATE TABLE investigations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    alert_id TEXT NOT NULL,
    alert_name TEXT,
    service TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/running/done/error
    root_cause TEXT,
    confidence REAL,
    report_path TEXT,
    trace_path TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

-- 审计日志
CREATE TABLE audit_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    action TEXT NOT NULL,
    target TEXT,
    decision TEXT,  -- approved/denied/confirmed
    detail TEXT,    -- JSON
    created_at TEXT NOT NULL
);

-- 告警记录（含去重）
CREATE TABLE alerts (
    id TEXT PRIMARY KEY,
    alert_name TEXT NOT NULL,
    service TEXT,
    severity TEXT,
    payload TEXT,  -- 原始 JSON
    dedup_key TEXT,
    investigation_id TEXT,  -- 关联排查
    created_at TEXT NOT NULL,
    FOREIGN KEY (investigation_id) REFERENCES investigations(id)
);

-- 用户
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_key_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator',  -- admin/operator/viewer
    created_at TEXT NOT NULL
);

-- Skill 元数据（YAML 文件仍为事实源，表仅做索引）
CREATE TABLE skill_index (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    alert_pattern TEXT,
    confidence REAL,
    created_at TEXT NOT NULL
);
```

### 3.2 认证中间件

```python
# auth/middleware.py
async def auth_middleware(request: Request, call_next):
    # 白名单路径：健康检查、webhook（签名验证替代认证）
    if request.url.path in ("/health", "/alerts"):
        return await call_next(request)

    # 静态文件不需要认证（或按需开启）
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        return await call_next(request)

    # API Key 验证
    api_key = request.headers.get("X-API-Key") or extract_bearer(request)
    if not api_key:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    user = await verify_api_key(api_key)
    if not user:
        return JSONResponse({"error": "invalid api key"}, status_code=401)

    request.state.user = user
    return await call_next(request)
```

### 3.3 通知调度

```python
# notifications/dispatcher.py
class NotificationDispatcher:
    def __init__(self, settings: Settings):
        self.channels = []
        if settings.notify_dingtalk_webhook:
            self.channels.append(DingTalkChannel(settings.notify_dingtalk_webhook))
        if settings.notify_feishu_webhook:
            self.channels.append(FeishuChannel(settings.notify_feishu_webhook))
        if settings.notify_slack_webhook:
            self.channels.append(SlackChannel(settings.notify_slack_webhook))

    async def on_investigation_done(self, investigation: Investigation):
        for ch in self.channels:
            await ch.send(
                title=f"排查完成: {investigation.alert_name}",
                body=f"根因: {investigation.root_cause}\n置信度: {investigation.confidence}",
            )

    async def on_sensitive_action(self, action: str, user_id: str):
        for ch in self.channels:
            await ch.send(
                title=f"敏感操作待确认: {action}",
                body=f"操作者: {user_id}，请确认是否执行",
            )
```

### 3.4 CLI 命令扩展

| 命令 | 说明 |
|---|---|
| `open-tam user create --name <name> --role <role>` | 创建用户，输出 API Key |
| `open-tam user list` | 列出用户 |
| `open-tam user delete <id>` | 删除用户 |
| `open-tam db migrate` | 执行数据库迁移 |
| `open-tam history list --limit 20` | 查看排查历史 |
| `open-tam history show <id>` | 查看排查详情 |

### 3.5 Web UI 扩展

- 登录页：API Key 输入
- 顶部导航增加用户信息 + 退出
- 排查历史列表页（从 SQLite 查询）
- 排查详情页（从数据库加载，不再依赖内存态 InvestigationHub）
- 敏感操作确认改为 Web 弹窗（替代 CLI 交互）

## 4. 测试策略

- 单测：数据库迁移（version 1 → 2 升级）、CRUD 操作
- 单测：认证中间件（无 key → 401、无效 key → 401、有效 key → 200 + user 注入）
- 单测：角色权限（viewer 不能发起排查、operator 不能管理用户）
- 集成测试：通知发送（mock webhook endpoint）
- 端到端：创建用户 → 登录 → 发起排查 → 查看历史 → 通知到达

## 5. 验收标准

1. `open-tam db migrate` 创建 SQLite 数据库与表
2. `open-tam user create` 创建用户并输出 API Key
3. Web UI 需认证访问，无 Key 返回 401
4. viewer 角色无法发起排查（API 403）
5. 排查完成后通知 webhook 被调用
6. 排查历史持久化，服务重启后可查
7. 现有 CLI 命令（investigate / eval / patrol）不受影响（无需认证）

---

# M8 K8s 与基础设施排障

## 1. 背景与目标

排障范围从应用层深入到 Kubernetes 基础设施层。

> - [ ] K8sGPT MCP 接入
> - [ ] `k8s-agent` 子 Agent
> - [ ] 新故障模式（pod_crash_loop / node_not_ready / dns_failure / cert_expiry）
> - [ ] （可选）ACS Agent Sandbox 隔离执行
> - **验收**：Pod CrashLoopBackOff 告警触发 k8s-agent 诊断，产出包含 Pod 事件与日志的根因报告

## 2. 已确认的范围决策

| 决策点 | 结论 |
|---|---|
| K8s 集群 | 开发用 kind，生产对接 ACK / 任意 kubeconfig |
| K8sGPT | 通过 MCP server 接入，工具签名固定 |
| k8s-agent | 与 metric-agent / log-agent 并列的第三个子 Agent |
| ACS Sandbox | 可选，用于高危动作隔离执行 |
| kubeconfig | 环境变量 `KUBECONFIG` 或 `~/.kube/config` |

## 3. 架构变更

```
src/open_tam/
├── mcp_servers/
│   ├── k8s_server.py           # 新增：K8sGPT MCP 封装
│   └── sandbox_server.py       # 新增（可选）：ACS Sandbox MCP 封装
├── orchestrator/
│   └── agents.py               # 新增 K8sAgent 子 Agent
├── faults.py                   # 新增故障模式
└── config.py                   # 新增：k8s_backend / kubeconfig / sandbox_* 配置

# 新故障模式
faults/
├── pod_crash_loop.yaml
├── node_not_ready.yaml
├── dns_failure.yaml
└── cert_expiry.yaml
```

### 3.1 K8s 工具接口

```
query_k8s_events(namespace: str, pod_name: str | None, kind: str | None) -> list[K8sEvent]
query_pod_status(namespace: str, pod_name: str) -> PodStatus
query_node_status(node_name: str) -> NodeStatus
analyze_with_k8sgpt(namespace: str, pod_name: str | None) -> list[K8sGPTFinding]
```

### 3.2 K8sAgent 子 Agent

```python
class K8sAgent(SpecialistAgent):
    """K8s 基础设施诊断专家"""
    system_prompt = """你是 Kubernetes 基础设施排障专家。
    当收到 Pod/Node 相关告警时：
    1. 先查 Pod 状态与事件（query_pod_status + query_k8s_events）
    2. 用 K8sGPT 做自动分析（analyze_with_k8sgpt）
    3. 必要时查 Node 状态（query_node_status）
    4. 综合所有证据给出根因"""
    tools = ["query_k8s_events", "query_pod_status", "query_node_status", "analyze_with_k8sgpt"]
```

### 3.3 新故障模式

```python
# pod_crash_loop
{
    "name": "pod_crash_loop",
    "anomaly_desc": "Pod 在 5 分钟内重启超过 3 次（CrashLoopBackOff）",
    "symptoms": {
        "k8s_events": ["BackOff", "CrashLoopBackOff"],
        "pod_status": "restart_count > 3",
    },
    "root_cause": "应用启动失败或运行时 panic",
    "suggested_actions": ["检查容器日志", "检查 liveness probe 配置", "检查资源限制"],
}

# node_not_ready
{
    "name": "node_not_ready",
    "anomaly_desc": "Node 状态变为 NotReady 超过 5 分钟",
    "symptoms": {
        "node_status": "conditions[Ready].status == False",
        "k8s_events": ["NodeNotReady"],
    },
    "root_cause": "kubelet 异常 / 资源耗尽 / 网络分区",
    "suggested_actions": ["检查 kubelet 日志", "检查节点资源使用", "检查网络连通性"],
}
```

### 3.4 ACS Agent Sandbox（可选）

```python
# sandbox_server.py
# 高危动作（restart_service / rollback_release / kubectl drain）在 MicroVM 中执行
# 工具签名不变，后端从本地执行切换为 Sandbox API 调用
execute_in_sandbox(command: str, timeout: int = 30) -> SandboxResult
```

## 4. 测试策略

- 单测：K8s 工具 mock（fake K8s API responses）
- 单测：新故障模式注入与症状匹配
- 集成测试：k8s-agent 在 fake 模型路径下正确委托工具
- 集成测试：kind 集群端到端（可选，CI 中标记为 slow）

## 5. 验收标准

1. K8sGPT MCP server 启动并可调用 `analyze_with_k8sgpt`
2. `pod_crash_loop` 故障注入后，k8s-agent 被 orchestrator 委托
3. 报告包含 Pod 事件、K8sGPT 分析结果、容器日志摘要
4. 现有 metric-agent / log-agent 不受影响
5. 全量测试 green

---

# M9 高级评测与质量闭环

## 1. 背景与目标

评测从"跑一次看命中率"升级为系统化质量保障体系。

> - [ ] OpenSRE 式多维度评测
> - [ ] LLM-as-Judge 证据充分性评分
> - [ ] A/B 模型对比评测
> - [ ] CI 集成回归评测
> - [ ] 评测结果可视化（Web UI）
> - **验收**：CI 每次 PR 自动跑评测，命中率低于阈值告警

## 2. 已确认的范围决策

| 决策点 | 结论 |
|---|---|
| 评测维度 | 根因命中率 + 证据充分性 + 误报率 + 排查效率（步数/耗时） |
| LLM-as-Judge | 用独立 LLM 调用评估报告质量（与排查模型解耦） |
| A/B 对比 | `open-tam eval --compare model_a model_b` 并行跑同一故障集 |
| CI 集成 | fake 路径评测作为 CI 必选步骤；真实模型评测可选 |
| 可视化 | Web UI 新增"评测"标签页，图表展示趋势 |

## 3. 架构变更

```
src/open_tam/
├── eval.py                  # 扩展现有：多维度评分 + A/B 对比
├── eval_judge.py            # 新增：LLM-as-Judge 评分器
├── eval_report.py           # 新增：评测报告生成（Markdown + JSON）
└── web/
    └── static/
        └── index.html       # 新增评测标签页
```

### 3.1 评测维度扩展

```python
class EvalResult(BaseModel):
    fault_name: str
    # 维度 1：根因命中（现有）
    root_cause_hit: bool
    # 维度 2：证据充分性（LLM-as-Judge）
    evidence_sufficiency: float  # 0-1，报告引用的证据是否充分支撑根因
    # 维度 3：排查效率
    steps_taken: int
    elapsed_seconds: float
    token_cost: int
    # 维度 4：误报检测（新增故障模式外的告警不应触发排查）
    false_positive: bool = False

class EvalSuite(BaseModel):
    results: list[EvalResult]
    summary: EvalSummary

class EvalSummary(BaseModel):
    total: int
    root_cause_hit_rate: float
    avg_evidence_sufficiency: float
    avg_steps: float
    avg_elapsed: float
    total_token_cost: int
    false_positive_rate: float
```

### 3.2 LLM-as-Judge

```python
class EvidenceJudge:
    """用独立 LLM 评估报告质量"""
    def __init__(self, model: ChatModel):
        self.model = model

    async def judge(self, report: str, trace: list[dict], expected_root_cause: str) -> float:
        prompt = f"""评估以下排障报告的质量（0-1 分）：

报告内容：
{report}

排查过程（trace）：
{json.dumps(trace, ensure_ascii=False)}

预期根因：{expected_root_cause}

评分标准：
- 0.0: 完全偏离根因
- 0.3: 提到相关区域但未定位
- 0.6: 根因正确但证据不充分
- 0.8: 根因正确且证据链完整
- 1.0: 根因精确 + 证据充分 + 排除项合理

只输出数字，不要解释。"""
        response = await self.model.chat(prompt)
        return float(response.text.strip())
```

### 3.3 A/B 模型对比

```bash
open-tam eval --compare qwen-plus qwen-max --faults cpu_spike,slow_query,oom
```

输出对比报告：

```markdown
# A/B 评测报告: qwen-plus vs qwen-max

| 指标 | qwen-plus | qwen-max | 差异 |
|---|---|---|---|
| 根因命中率 | 75% | 100% | +25% |
| 平均步数 | 4.2 | 3.0 | -28.6% |
| 平均耗时 | 12.3s | 18.7s | +52% |
| Token 成本 | 2,340 | 5,120 | +119% |
| 证据充分性 | 0.65 | 0.88 | +35% |

结论：qwen-max 命中率和证据质量更高，但成本和延迟也显著增加。
```

### 3.4 CI 集成

```yaml
# .github/workflows/eval.yml
- name: Run eval (fake path)
  run: |
    open-tam eval --fake --faults cpu_spike,slow_query,oom,connection_pool_exhausted --min-hit-rate 0.75
```

`--min-hit-rate` 低于阈值时 CI 失败。

### 3.5 Web UI 评测标签页

- 评测历史列表（时间 / 模型 / 命中率 / 步数）
- 趋势图：命中率随时间变化（折线图）
- 单次评测详情：每个故障的命中/未命中 + 报告链接
- A/B 对比视图

## 4. 测试策略

- 单测：EvalResult 计算逻辑、LLM-as-Judge prompt 构建
- 集成测试：`open-tam eval --compare` 生成对比报告
- CI 测试：fake 路径评测在 CI 中稳定运行

## 5. 验收标准

1. `open-tam eval` 输出包含 4 个维度的评分
2. LLM-as-Judge 评分与人工评分相关性 > 0.7（抽样 10 例验证）
3. `open-tam eval --compare` 生成 A/B 对比 Markdown 报告
4. CI 中 fake 路径评测稳定运行，命中率阈值生效
5. Web UI 评测标签页展示趋势图与详情

---

# M10 告警风暴与高级编排

## 1. 背景与目标

面向大规模生产环境的终极能力。

> - [ ] 告警关联聚合（同一根因的多条告警合并）
> - [ ] 告警优先级队列（P0 抢占）
> - [ ] 修复 Playbook 编排（多步修复流程）
> - [ ] 跨集群/跨区域排查
> - **验收**：10 条关联告警聚合为 1 个排查任务；Playbook 自动执行 3 步修复

## 2. 已确认的范围决策

| 决策点 | 结论 |
|---|---|
| 关联策略 | 基于时间窗口 + service 重叠 + 指标相关性 |
| 优先级 | P0/P1/P2/P3 四级，P0 立即排查，P2+ 排队 |
| Playbook | YAML 定义，护栏逐条执行，敏感步骤需确认 |
| 跨区域 | 多个 MCP 后端实例并行查询 |

## 3. 架构变更

```
src/open_tam/
├── storm/
│   ├── __init__.py
│   ├── correlator.py     # 告警关联引擎
│   ├── priority_queue.py # 优先级排查队列
│   └── aggregator.py     # 聚合报告生成
├── playbook/
│   ├── __init__.py
│   ├── models.py         # Playbook / Step Pydantic 模型
│   ├── executor.py       # Playbook 执行器（逐条 + 护栏）
│   └── registry.py       # Playbook 注册表
└── config.py             # 新增：storm_* / playbook_* 配置
```

### 3.1 告警关联引擎

```python
class AlertCorrelator:
    """时间窗口 + 服务重叠关联"""
    def __init__(self, window_seconds: int = 60):
        self._buffer: list[AlertEvent] = []
        self._window = window_seconds

    def correlate(self, alert: AlertEvent) -> str | None:
        """返回关联组 ID，无关联返回 None"""
        # 策略 1：同 service + 时间窗口
        # 策略 2：上下游 service（配置依赖图）
        # 策略 3：同节点（K8s node label 重叠）
        ...

    def get_group(self, group_id: str) -> list[AlertEvent]:
        """获取关联组所有告警"""
        ...
```

### 3.2 修复 Playbook

```yaml
# playbooks/oom_remediation.yaml
id: oom_remediation
name: OOM 修复流程
trigger:
  alert_pattern: "oom*"
  confidence_threshold: 0.7  # 排查置信度 > 0.7 才自动执行

steps:
  - order: 1
    action: restart_service
    params:
      service: "{{ alert.service }}"
    sensitivity: safe
    auto_execute: true
    on_failure: abort

  - order: 2
    action: scale_memory_limit
    params:
      service: "{{ alert.service }}"
      multiplier: 1.5
    sensitivity: sensitive
    auto_execute: false  # 需人工确认
    on_failure: rollback

  - order: 3
    action: notify_team
    params:
      channel: "#oncall"
      message: "OOM 修复完成: {{ alert.service }}，内存限制已扩容 1.5x"
    sensitivity: safe
    auto_execute: true
```

### 3.3 Playbook 执行器

```python
class PlaybookExecutor:
    def __init__(self, guardrails: Guardrails, notifications: NotificationDispatcher):
        self.guardrails = guardrails
        self.notifications = notifications

    async def execute(self, playbook: Playbook, context: dict) -> PlaybookResult:
        results = []
        for step in playbook.steps:
            # 护栏检查
            if not self.guardrails.is_allowed(step.action):
                results.append(StepResult(step=step, status="denied"))
                if step.on_failure == "abort":
                    break
                continue

            # 敏感操作需确认
            if step.sensitivity == "sensitive" and not step.auto_execute:
                await self.notifications.on_sensitive_action(step.action, context["user_id"])
                # 等待确认...

            # 执行
            result = await self.guardrails.execute(step.action, step.params)
            results.append(StepResult(step=step, status="done", result=result))

            if not result.success and step.on_failure == "rollback":
                await self._rollback(results[:-1])
                break

        return PlaybookResult(steps=results)
```

## 4. 测试策略

- 单测：关联引擎（同 service 关联、跨 service 依赖关联）
- 单测：优先级队列（P0 抢占 P2）
- 集成测试：Playbook 执行（mock 动作后端，验证护栏 + 通知 + 回滚）
- 端到端：10 条关联告警 → 聚合 → 排查 → Playbook 修复

## 5. 验收标准

1. 10 条同 service 告警在 60s 窗口内聚合为 1 个排查任务
2. P0 告警抢占正在执行的 P2 排查
3. Playbook 3 步修复流程自动执行，敏感步骤等待确认
4. 执行失败时按 on_failure 策略回滚
5. 全量测试 green

---

# 附录 A: 全局配置项汇总

```ini
# === 模型 ===
OPEN_TAM_MODEL_PRIMARY=qwen-plus
OPEN_TAM_MODEL_FALLBACK=qwen-turbo
OPEN_TAM_MODEL_TIMEOUT=30
OPEN_TAM_MAX_STEPS=15
OPEN_TAM_CHAR_BUDGET=4096

# === 后端选择（M5）===
OPEN_TAM_METRICS_BACKEND=mock          # mock | aliyun
OPEN_TAM_LOGS_BACKEND=mock             # mock | aliyun
OPEN_TAM_K8S_BACKEND=none              # none | k8sgpt

# === 阿里云（M5）===
OPEN_TAM_ALIYUN_REGION=cn-hangzhou
OPEN_TAM_ALIYUN_ACCESS_KEY_ID=
OPEN_TAM_ALIYUN_ACCESS_KEY_SECRET=
OPEN_TAM_ALIYUN_SLS_PROJECT=
OPEN_TAM_ALIYUN_SLS_LOGSTORE=

# === Webhook（M5）===
OPEN_TAM_WEBHOOK_SECRET=
OPEN_TAM_DEDUP_WINDOW_SECONDS=300

# === Skill（M6）===
OPEN_TAM_SKILLS_DIR=skills/

# === 数据库（M7）===
OPEN_TAM_DATABASE_URL=sqlite:///var/open_tam.db

# === 认证（M7）===
OPEN_TAM_AUTH_ENABLED=false
OPEN_TAM_AUTH_SECRET=

# === 通知（M7）===
OPEN_TAM_NOTIFY_DINGTALK_WEBHOOK=
OPEN_TAM_NOTIFY_FEISHU_WEBHOOK=
OPEN_TAM_NOTIFY_SLACK_WEBHOOK=

# === K8s（M8）===
OPEN_TAM_KUBECONFIG=

# === 告警风暴（M10）===
OPEN_TAM_STORM_WINDOW_SECONDS=60
OPEN_TAM_STORM_CORRELATION_ENABLED=false
```

# 附录 B: 里程碑验收矩阵

| 阶段 | 验收标准 | 依赖 |
|---|---|---|
| M5 | 一条真实告警跑通完整闭环 | M4 合并 |
| M6 | 历史排查经验被提取为 Skill 并反哺新排查 | M5（需要真实 trace） |
| M7 | 多用户认证访问，排查历史持久化可检索 | M5（需要真实数据源） |
| M8 | Pod CrashLoopBackOff 告警触发 k8s-agent 诊断 | M5（K8s 集群可用） |
| M9 | CI 每次 PR 自动跑评测，命中率阈值生效 | M2+（评测框架存在即可） |
| M10 | 关联告警聚合 + Playbook 自动修复 | M5 + M7 + M8 |

# 附录 C: 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 阿里云 API 限流 | 排查中断 | 退避重试 + 缓存近期查询结果 |
| LLM 输出不稳定 | 根因命中率波动 | Skill 先验约束 + 评测监控 + 多模型 fallback |
| SQLite 并发瓶颈 | 多用户写入冲突 | WAL 模式 + 写入队列；必要时升级 PostgreSQL |
| K8sGPT 误报 | 错误诊断干扰 | 置信度阈值 + 人工确认 |
| 告警风暴压垮系统 | 排查队列堆积 | 优先级队列 + 并发限流 + 关联聚合 |
| Skill 质量退化 | 排查路径被错误引导 | Skill 置信度衰减 + 定期重新学习 |

# 附录 D: 术语表

| 术语 | 定义 |
|---|---|
| TAM | Technical Account Manager，技术客户经理 |
| RCA | Root Cause Analysis，根因分析 |
| Skill | 从历史 trace 中提取的排查模板 |
| Playbook | 预定义的多步修复流程 |
| Trace | 排查过程的结构化记录（JSONL） |
| Guardrails | 护栏系统：白名单 + dry-run + 人工确认 + 审计 |
| MCP | Model Context Protocol，模型上下文协议 |
| CMS | Cloud Monitor Service，阿里云云监控 |
| SLS | Simple Log Service，阿里云日志服务 |
| K8sGPT | K8s 诊断工具，基于 LLM 分析集群问题 |
| ACS | Alibaba Container Service，阿里云容器服务 |
