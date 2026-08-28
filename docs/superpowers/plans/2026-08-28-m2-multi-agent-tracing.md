# SRE Agent M2 实施计划（多 Agent + 语料）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 M2：mock 日志数据源与 query_logs 全链路、故障注册表扩至 4 模式、orchestrator 经 ask_metric_agent / ask_log_agent 委托专长子 Agent 协作、排查全程 trace JSONL 落盘并可回放。

**Architecture:** 子 Agent = 复用 `ReActLoop` 的专长实例（独立系统提示 + 单一数据工具），orchestrator 的工具表只有两个 ask_* 委托工具，由 `AgentBackend` 路由；叶子数据工具仍走 `InlineBackend`/`McpStdioBackend` 双后端。trace 由可选注入的 `TraceRecorder` 逐条追加 JSONL。

**Tech Stack:** 同 M0/M1（Python 3.12、pydantic、FastMCP、typer、pytest）。

**设计依据:** `docs/superpowers/specs/2026-08-28-sre-agent-design.md`（M2 里程碑）

---

### Task 1: LogRecord 数据模型

**Files:**
- Modify: `src/open_tam/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 追加失败测试（tests/test_models.py 末尾）**

```python
def test_log_record_normalizes_level():
    r = LogRecord(ts=datetime(2026, 8, 28, 10, 0), level="error", service="demo-app", message="boom")
    assert r.level == "ERROR"
```

并在顶部 import 行加入 `LogRecord`：

```python
from open_tam.models import AlertEvent, LogRecord, MetricPoint, MetricSeries
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL，`ImportError: cannot import name 'LogRecord'`

- [ ] **Step 3: 实现（src/open_tam/models.py 末尾追加）**

```python
class LogRecord(BaseModel):
    ts: datetime
    level: str
    service: str
    message: str

    @field_validator("level", mode="before")
    @classmethod
    def _upper_level(cls, v: object) -> str:
        return str(v).upper()
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_models.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/open_tam/models.py tests/test_models.py
git commit -m "feat: LogRecord 数据模型（level 归一化）"
```

---

### Task 2: 故障模式扩充与指标基线泛化

**Files:**
- Modify: `src/open_tam/faults.py`
- Modify: `src/open_tam/mock/metrics_data.py`
- Test: `tests/test_faults.py`、`tests/test_metrics_data.py`

- [ ] **Step 1: 追加失败测试**

`tests/test_faults.py` 末尾：

```python
import pytest


@pytest.mark.parametrize("name", ["cpu_spike", "slow_query", "oom", "connection_pool_exhausted"])
def test_fault_modes_have_full_story(name):
    mode = FAULT_MODES[name]
    assert mode.root_cause and mode.remediation and mode.anomaly_desc and mode.log_signature
    assert mode.baseline_mid < mode.baseline_high < mode.spike_value
```

`tests/test_metrics_data.py` 末尾：

```python
def test_slow_query_spike_in_window(tmp_path):
    state = FaultState(state_dir=tmp_path)
    state.activate("slow_query", duration_minutes=30)
    start = state.snapshot_time("slow_query")
    pts = generate_series(
        metric="db_query_duration_ms", service="demo-app",
        start=start - timedelta(minutes=5), end=start + timedelta(minutes=10),
        seed=7, state=state,
    )
    in_window = [p for p in pts if p.ts >= start]
    out_window = [p for p in pts if p.ts < start]
    assert in_window and all(p.value >= 3000 for p in in_window)
    assert out_window and all(p.value <= 350 for p in out_window)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_faults.py tests/test_metrics_data.py -q`
Expected: FAIL（KeyError: slow_query / AttributeError: baseline_mid）

- [ ] **Step 3: 修改 faults.py**

`FaultMode` 增加 `baseline_mid: float`（放在 `metric` 之后、`baseline_high` 之前），`FAULT_MODES` 替换为：

```python
FAULT_MODES: dict[str, FaultMode] = {
    "cpu_spike": FaultMode(
        name="cpu_spike",
        service="demo-app",
        metric="cpu_usage",
        baseline_mid=30.0,
        baseline_high=45.0,
        spike_value=92.0,
        anomaly_desc="cpu_usage 从基线 ~30% 飙升至 ~92% 并持续",
        root_cause="demo-app /search 接口新版本引入低效正则回溯，导致 CPU 飙升",
        remediation="回滚 demo-app 最近一次发布，并优化 /search 的正则匹配逻辑",
        log_signature="WARN CPU usage above 85% for 60s on demo-app",
    ),
    "slow_query": FaultMode(
        name="slow_query",
        service="demo-app",
        metric="db_query_duration_ms",
        baseline_mid=120.0,
        baseline_high=300.0,
        spike_value=3200.0,
        anomaly_desc="db_query_duration_ms 从基线 ~120ms 飙升至 ~3200ms 并持续",
        root_cause="/orders 接口新增 SQL 未命中索引，全表扫描导致慢查询",
        remediation="为 orders(user_id, created_at) 建立联合索引，并回滚未加索引的临时 SQL",
        log_signature="Slow query detected: SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC took 3241ms",
    ),
    "oom": FaultMode(
        name="oom",
        service="demo-app",
        metric="memory_usage",
        baseline_mid=55.0,
        baseline_high=70.0,
        spike_value=95.0,
        anomaly_desc="memory_usage 从基线 ~55% 爬升至 ~95% 并触发容器终止",
        root_cause="本地缓存无淘汰策略，对象持续累积导致容器 OOMKilled",
        remediation="为本地缓存增加 TTL 与最大条数上限，临时将内存扩容至 2Gi 并重启",
        log_signature="java.lang.OutOfMemoryError: Java heap space — container will be OOMKilled",
    ),
    "connection_pool_exhausted": FaultMode(
        name="connection_pool_exhausted",
        service="demo-app",
        metric="db_active_connections",
        baseline_mid=20.0,
        baseline_high=40.0,
        spike_value=50.0,
        anomaly_desc="db_active_connections 打满至池上限 50 并伴随请求超时",
        root_cause="慢事务长期占用数据库连接未释放，连接池耗尽后新请求超时",
        remediation="缩短事务边界并为查询设置 statement timeout，临时重启应用释放连接",
        log_signature="HikariPool-1 - Connection is not available, request timed out after 30000ms",
    ),
}
```

同时删除模块级 `_DEFAULT_STATE_DIR`（FaultState 已在构造时读 env）。

- [ ] **Step 4: 修改 mock/metrics_data.py 的基线计算**

```python
        base = (mode.baseline_mid if mode else 30.0) + 8 * math.sin(ts.timestamp() / 600)
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_faults.py tests/test_metrics_data.py tests/test_demo_app.py -q`
Expected: 全部 passed（demo-app 测试不受影响：cpu_usage 基线不变）

- [ ] **Step 6: Commit**

```bash
git add src/open_tam/faults.py src/open_tam/mock/metrics_data.py tests/test_faults.py tests/test_metrics_data.py
git commit -m "feat: 故障模式扩至 4 个并泛化指标基线（含日志签名）"
```

---

### Task 3: mock 日志生成器 logs_data.py

**Files:**
- Create: `src/open_tam/mock/logs_data.py`
- Test: `tests/test_logs_data.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_logs_data.py
from datetime import datetime, timedelta

from open_tam.faults import FaultState
from open_tam.mock.logs_data import generate_logs

START = datetime(2026, 8, 28, 10, 0)
END = datetime(2026, 8, 28, 11, 0)


def test_baseline_logs_are_info_only(tmp_path):
    records = generate_logs("demo-app", START, END, state=FaultState(state_dir=tmp_path))
    assert records
    assert all(r.level == "INFO" for r in records)


def test_fault_window_emits_error_logs(tmp_path):
    state = FaultState(state_dir=tmp_path)
    state.activate("slow_query", duration_minutes=30)
    start = state.snapshot_time("slow_query")
    records = generate_logs("demo-app", START, END, state=state)
    errors = [r for r in records if r.level == "ERROR"]
    assert errors
    assert all("Slow query detected" in r.message for r in errors)
    assert all(r.ts >= start for r in errors)
    assert all(r.ts <= start + timedelta(minutes=30) for r in errors)


def test_level_and_keyword_filters(tmp_path):
    state = FaultState(state_dir=tmp_path)
    state.activate("slow_query", duration_minutes=30)
    records = generate_logs("demo-app", START, END, level="error", state=state)
    assert records and all(r.level == "ERROR" for r in records)
    hits = generate_logs("demo-app", START, END, keyword="slow query", state=state)
    assert hits and all("slow query" in r.message.lower() for r in hits)
    assert generate_logs("demo-app", START, END, keyword="no-such-keyword", state=state) == []


def test_logs_deterministic(tmp_path):
    s1 = generate_logs("demo-app", START, END, state=FaultState(state_dir=tmp_path))
    s2 = generate_logs("demo-app", START, END, state=FaultState(state_dir=tmp_path))
    assert [(r.ts, r.level, r.message) for r in s1] == [(r.ts, r.level, r.message) for r in s2]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_logs_data.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 logs_data.py**

```python
# src/open_tam/mock/logs_data.py
from __future__ import annotations

import random
from datetime import datetime, timedelta

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.models import LogRecord

BASELINE_LOGS = [
    "GET /health 200 3ms",
    "GET /api/items 200 24ms",
    "GET /api/orders 200 41ms",
    "scheduled cleanup done",
    "cache refreshed",
]


def generate_logs(
    service: str,
    start: datetime,
    end: datetime,
    level: str | None = None,
    keyword: str | None = None,
    step_seconds: int = 60,
    seed: int = 42,
    state: FaultState | None = None,
) -> list[LogRecord]:
    rng = random.Random(seed)
    records: list[LogRecord] = []
    ts = start
    i = 0
    while ts <= end:
        records.append(LogRecord(
            ts=ts, level="INFO", service=service,
            message=rng.choice(BASELINE_LOGS),
        ))
        ts += timedelta(seconds=step_seconds)
        i += 1
    if state is not None:
        for mode in FAULT_MODES.values():
            if mode.service != service:
                continue
            win = state.window(mode.name)
            if not win:
                continue
            t = max(win[0], start)
            while t <= min(win[1], end):
                records.append(LogRecord(
                    ts=t, level="ERROR", service=service,
                    message=mode.log_signature,
                ))
                t += timedelta(seconds=step_seconds)
    records.sort(key=lambda r: r.ts)
    if level:
        records = [r for r in records if r.level == level.upper()]
    if keyword:
        records = [r for r in records if keyword.lower() in r.message.lower()]
    return records
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_logs_data.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/open_tam/mock/logs_data.py tests/test_logs_data.py
git commit -m "feat: 故障联动的 mock 日志生成器（级别/关键字过滤）"
```

---

### Task 4: mock-logs MCP 服务与 stdio 往返测试

**Files:**
- Create: `src/open_tam/mcp_servers/logs_server.py`
- Test: `tests/test_logs_server.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_logs_server.py
import json
import os
import sys
from datetime import datetime, timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_logs_stdio_roundtrip(tmp_path):
    now = datetime.now().replace(second=0, microsecond=0)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "open_tam.mcp_servers.logs_server"],
        env={**os.environ, "OPEN_TAM_STATE_DIR": str(tmp_path)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "query_logs",
                {
                    "service": "demo-app",
                    "start": now.isoformat(),
                    "end": (now + timedelta(minutes=5)).isoformat(),
                },
            )
    payload = json.loads(result.content[0].text)
    assert isinstance(payload, list) and payload
    assert {"ts", "level", "message"} <= set(payload[0].keys())
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_logs_server.py -q`
Expected: FAIL（子进程报 No module named open_tam.mcp_servers.logs_server）

- [ ] **Step 3: 实现 logs_server.py**

```python
# src/open_tam/mcp_servers/logs_server.py
from __future__ import annotations

import json
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from open_tam.faults import FaultState
from open_tam.mock.logs_data import generate_logs

mcp = FastMCP("mock-logs")


@mcp.tool()
def query_logs(service: str, start: str, end: str, level: str | None = None, keyword: str | None = None) -> str:
    """查询某服务的结构化日志。start/end 为 ISO 8601 时间；level 可选 INFO/WARN/ERROR；keyword 为消息子串（不区分大小写）。返回 JSON 数组字符串 [{ts, level, message}]。"""
    records = generate_logs(
        service=service,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        level=level,
        keyword=keyword,
        state=FaultState(),
    )
    return json.dumps(
        [{"ts": r.ts.isoformat(), "level": r.level, "message": r.message} for r in records],
        ensure_ascii=False,
    )


def _server_command() -> tuple[str, list[str]]:
    return sys_executable(), ["-m", "open_tam.mcp_servers.logs_server"]


def sys_executable() -> str:
    import sys

    return sys.executable


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_logs_server.py -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/open_tam/mcp_servers/logs_server.py tests/test_logs_server.py
git commit -m "feat: mock-logs MCP stdio 服务与往返集成测试"
```

---

### Task 5: query_logs 工具接入 tools.py

**Files:**
- Modify: `src/open_tam/orchestrator/tools.py`
- Test: `tests/test_cli.py`（新增 transport=mcp 的 logs 查询）

- [ ] **Step 1: 追加失败测试（tests/test_cli.py 末尾）**

```python
def test_logs_query_via_mcp_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    now = datetime.now().replace(second=0, microsecond=0)
    result = runner.invoke(
        app,
        [
            "logs", "query", "--transport", "mcp",
            "--service", "demo-app",
            "--start", now.isoformat(),
            "--end", (now + timedelta(minutes=2)).isoformat(),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "INFO" in result.output
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_cli.py::test_logs_query_via_mcp_transport -q`
Expected: FAIL（CLI 无 logs 子命令）

- [ ] **Step 3: 修改 tools.py**

顶部 import 增加 `from open_tam.mock.logs_data import generate_logs`；`QUERY_METRICS_SPEC` 之后追加：

```python
QUERY_LOGS_SPEC = {
    "name": "query_logs",
    "description": "查询某服务的结构化日志，可按时间范围/级别/关键字过滤，用于获取异常现场证据。",
    "parameters": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "服务名，如 demo-app"},
            "start": {"type": "string", "description": "起始时间 ISO 8601"},
            "end": {"type": "string", "description": "结束时间 ISO 8601"},
            "level": {"type": "string", "description": "可选，INFO/WARN/ERROR"},
            "keyword": {"type": "string", "description": "可选，消息子串（不区分大小写）"},
        },
        "required": ["service", "start", "end"],
    },
}
```

`ALL_TOOLS` 改为 `ALL_TOOLS: list[dict] = [QUERY_METRICS_SPEC, QUERY_LOGS_SPEC]`；新增：

```python
def query_logs_inline(service: str, start: str, end: str, level: str | None = None, keyword: str | None = None) -> str:
    records = generate_logs(
        service=service,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        level=level,
        keyword=keyword,
        state=FaultState(),
    )
    return json.dumps(
        [{"ts": r.ts.isoformat(), "level": r.level, "message": r.message} for r in records],
        ensure_ascii=False,
    )
```

`InlineBackend.execute` 增加：

```python
        if name == "query_metrics":
            return query_metrics_inline(**args)
        if name == "query_logs":
            return query_logs_inline(**args)
        return json.dumps({"error": f"unknown tool: {name}"})
```

- [ ] **Step 4: cli.py 增加 logs 子命令（metrics_app 之后）**

```python
logs_app = typer.Typer(help="日志查询")
app.add_typer(logs_app, name="logs")


@logs_app.command("query")
def logs_query(
    service: str = typer.Option("demo-app"),
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    level: str = typer.Option(None),
    keyword: str = typer.Option(None),
    transport: str = typer.Option("inline", help="inline 或 mcp"),
) -> None:
    datetime.fromisoformat(start)
    datetime.fromisoformat(end)
    backend = InlineBackend() if transport == "inline" else McpStdioBackend()
    typer.echo(f"# logs @ {service} ({transport})")
    typer.echo(backend.execute("query_logs", {
        "service": service, "start": start, "end": end, "level": level, "keyword": keyword,
    }))
```

注意：`McpStdioBackend.execute` 按工具名调 `session.call_tool(name, args)`，query_logs 走 MCP 需把服务路由到对应 server——修改 `McpStdioBackend._call`：

```python
        from open_tam.mcp_servers.metrics_server import _server_command as metrics_cmd
        from open_tam.mcp_servers.logs_server import _server_command as logs_cmd

        command, cmd_args = logs_cmd() if name == "query_logs" else metrics_cmd()
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_cli.py -q`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/open_tam/orchestrator/tools.py src/open_tam/cli.py tests/test_cli.py
git commit -m "feat: query_logs 工具全链路（inline + MCP 双后端）与 CLI logs 子命令"
```

---

### Task 6: TraceRecorder 与回放

**Files:**
- Create: `src/open_tam/tracing/__init__.py`（空文件）
- Create: `src/open_tam/tracing/trace.py`
- Modify: `src/open_tam/config.py`（加 traces_dir）
- Test: `tests/test_trace.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_trace.py
from open_tam.tracing.trace import TraceRecorder, load_trace


def test_recorder_appends_jsonl_and_loads(tmp_path):
    rec = TraceRecorder("a1", traces_dir=tmp_path)
    rec.record("alert_received", user="alert json")
    rec.record("tool_call", tool="query_metrics", arguments={"metric": "cpu_usage"})
    records = load_trace(rec.path)
    assert [r["kind"] for r in records] == ["alert_received", "tool_call"]
    assert records[1]["arguments"] == {"metric": "cpu_usage"}
    assert records[0]["alert_id"] == "a1"
    assert records[0]["ts"]


def test_trace_env_default_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "t"))
    rec = TraceRecorder("a2")
    rec.record("final", content="done")
    assert (tmp_path / "t" / "a2.jsonl").exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_trace.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 trace.py**

```python
# src/open_tam/tracing/trace.py
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


class TraceRecorder:
    """排查过程逐条追加 JSONL：每行 {ts, alert_id, kind, ...fields}，可回放。"""

    def __init__(self, alert_id: str, traces_dir: Path | str | None = None) -> None:
        base = (
            Path(traces_dir)
            if traces_dir
            else Path(os.environ.get("OPEN_TAM_TRACES_DIR", "traces"))
        )
        base.mkdir(parents=True, exist_ok=True)
        self.alert_id = alert_id
        self.path = base / f"{alert_id}.jsonl"

    def record(self, kind: str, **fields: object) -> None:
        line = json.dumps(
            {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "alert_id": self.alert_id,
                "kind": kind,
                **fields,
            },
            ensure_ascii=False,
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_trace(path: Path | str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]
```

- [ ] **Step 4: config.py 的 Settings 增加 traces_dir**

字段列表加 `traces_dir: Path`，`load()` 返回加：

```python
            traces_dir=Path(os.environ.get("OPEN_TAM_TRACES_DIR", base / "traces")),
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_trace.py -q`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/open_tam/tracing/__init__.py src/open_tam/tracing/trace.py src/open_tam/config.py tests/test_trace.py
git commit -m "feat: TraceRecorder JSONL 落盘与 load_trace 回放"
```

---

### Task 7: ReActLoop 泛化（自定义提示/工具表 + trace 接入）

**Files:**
- Modify: `src/open_tam/orchestrator/loop.py`
- Test: `tests/test_react_loop.py`（追加）

- [ ] **Step 1: 追加失败测试（tests/test_react_loop.py 末尾）**

```python
def test_run_prompt_with_custom_tools_and_trace(tmp_path):
    from open_tam.tracing.trace import TraceRecorder, load_trace

    model = FakeChatModel([
        ModelReply(content=None, tool_calls=[ToolCall(id="t1", name="query_logs", arguments={"service": "demo-app", "start": "2026-08-28T00:00:00", "end": "2026-08-28T01:00:00"})]),
        ModelReply(content="日志显示慢查询", tool_calls=[]),
    ])
    rec = TraceRecorder("t-custom", traces_dir=tmp_path)
    loop = ReActLoop(model=model, trace=rec, system_prompt="你是日志专家", tools=[{"name": "query_logs"}])
    result = loop.run_prompt("你是日志专家", "查一下日志", alert_id="t-custom")
    assert result.root_cause == "日志显示慢查询"
    kinds = [r["kind"] for r in load_trace(rec.path)]
    assert kinds == ["alert_received", "tool_call", "observation", "final"]


def test_budget_exceeded_traced(tmp_path):
    from open_tam.tracing.trace import TraceRecorder, load_trace

    now = datetime.now().replace(second=0, microsecond=0)
    args = {"metric": "cpu_usage", "service": "demo-app",
            "start": (now - timedelta(minutes=5)).isoformat(), "end": now.isoformat()}
    endless = FakeChatModel([
        ModelReply(content=None, tool_calls=[ToolCall(id=f"t{i}", name="query_metrics", arguments=args)])
        for i in range(20)
    ])
    rec = TraceRecorder("t-budget", traces_dir=tmp_path)
    ReActLoop(model=endless, max_steps=1, trace=rec).run(_alert())
    kinds = [r["kind"] for r in load_trace(rec.path)]
    assert kinds == ["alert_received", "tool_call", "observation", "budget_exceeded"]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_react_loop.py -q`
Expected: FAIL（run_prompt 不存在、trace 参数不存在）

- [ ] **Step 3: 修改 loop.py**

`__init__` 签名改为：

```python
    def __init__(
        self,
        model: ChatModel,
        backend: Backend | None = None,
        max_steps: int = 15,
        char_budget: int = 60000,
        system_prompt: str = SYSTEM_PROMPT,
        tools: list[dict] | None = None,
        trace: "TraceRecorder | None" = None,
    ) -> None:
        self.model = model
        self.backend: Backend = backend or InlineBackend()
        self.max_steps = max_steps
        self.char_budget = char_budget
        self.system_prompt = system_prompt
        self.tools: list[dict] = tools if tools is not None else ALL_TOOLS
        self.trace = trace
```

顶部 `from typing import Protocol` 旁加 `from __future__ import annotations` 已有；类型引用 `"TraceRecorder | None"` 改为直接 `TraceRecorder | None` 并在文件顶部加：

```python
from open_tam.tracing.trace import TraceRecorder
```

`run` 改为薄封装：

```python
    def run(self, alert: AlertEvent) -> DiagnosisResult:
        return self.run_prompt(
            self.system_prompt,
            f"告警信息：\n{alert.model_dump_json(indent=2)}",
            alert_id=alert.alert_id,
        )

    def run_prompt(self, system: str, user: str, alert_id: str = "adhoc") -> DiagnosisResult:
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if self.trace:
            self.trace.record("alert_received", user=user)
        steps: list[Step] = []
        for i in range(self.max_steps):
            reply = self.model.complete(messages, self.tools)
            if reply.tool_calls:
                for tc in reply.tool_calls:
                    step = Step(index=i, thought=reply.content, tool_name=tc.name,
                                arguments=tc.arguments, observation=None)
                    try:
                        step.observation = self.backend.execute(tc.name, tc.arguments)
                    except Exception as exc:
                        step.error = f"{type(exc).__name__}: {exc}"
                        step.observation = json.dumps({"tool_error": step.error}, ensure_ascii=False)
                    steps.append(step)
                    if self.trace:
                        self.trace.record("tool_call", step=i, thought=step.thought,
                                          tool=tc.name, arguments=tc.arguments)
                        self.trace.record("observation", step=i, tool=tc.name,
                                          observation=step.observation, error=step.error)
                    messages.append({"role": "assistant", "content": reply.content or "",
                                     "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}]})
                    messages.append({"role": "tool", "name": tc.name,
                                     "tool_call_id": tc.id, "content": step.observation})
            elif reply.content is not None:
                steps.append(Step(index=i, thought=reply.content, tool_name=None,
                                  arguments=None, observation=None))
                if self.trace:
                    self.trace.record("final", content=reply.content)
                return self._finalize(alert_id, reply.content, steps)
            if sum(len(str(m)) for m in messages) > self.char_budget:
                break
        if self.trace:
            self.trace.record("budget_exceeded", steps=len(steps))
        return DiagnosisResult(
            alert_id=alert_id, root_cause=None,
            evidence=[], actions=["人工介入：自动排查达到步数/预算上限"],
            confidence="low", excluded=[],
            steps=steps, raw_final=None,
        )
```

`_finalize` 第一个参数从 `alert: AlertEvent` 改为 `alert_id: str`（内部只用 alert.alert_id，直接替换即可）。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_react_loop.py tests/test_investigate.py -q`
Expected: 全部 passed（M1 行为不变）

- [ ] **Step 5: Commit**

```bash
git add src/open_tam/orchestrator/loop.py tests/test_react_loop.py
git commit -m "feat: ReActLoop 支持自定义提示/工具表并接入 TraceRecorder"
```

---

### Task 8: 专长子 Agent 与 AgentBackend

**Files:**
- Create: `src/open_tam/orchestrator/agents.py`
- Test: `tests/test_agents.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_agents.py
from datetime import datetime, timedelta

from open_tam.faults import FaultState
from open_tam.orchestrator.agents import (
    AgentBackend,
    LOG_AGENT_PROMPT,
    METRIC_AGENT_PROMPT,
    ORCHESTRATOR_PROMPT,
    SpecialistAgent,
)
from open_tam.orchestrator.loop import FakeChatModel, ModelReply, ToolCall
from open_tam.orchestrator.tools import (
    QUERY_LOGS_SPEC,
    QUERY_METRICS_SPEC,
    InlineBackend,
)


def _log_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    FaultState().activate("slow_query", duration_minutes=30)
    now = datetime.now().replace(second=0, microsecond=0)
    model = FakeChatModel([
        ModelReply(content=None, tool_calls=[ToolCall(id="l1", name="query_logs", arguments={
            "service": "demo-app",
            "start": (now - timedelta(minutes=30)).isoformat(),
            "end": now.isoformat(),
        })]),
        ModelReply(content="发现 ERROR 日志：Slow query detected ... 共 2 条"),
    ])
    return SpecialistAgent(name="log", system_prompt=LOG_AGENT_PROMPT,
                           tools=[QUERY_LOGS_SPEC], model=model)


def test_log_agent_returns_log_evidence(tmp_path, monkeypatch):
    agent = _log_agent(tmp_path, monkeypatch)
    answer = agent.run("查最近 30 分钟慢查询日志")
    assert "Slow query detected" in answer


def test_agent_backend_routes_ask_tools(tmp_path, monkeypatch):
    log_agent = _log_agent(tmp_path, monkeypatch)
    backend = AgentBackend({"ask_log_agent": log_agent})
    observation = backend.execute("ask_log_agent", {"question": "查日志"})
    assert "Slow query detected" in observation
    assert "unknown tool" in backend.execute("ask_nobody", {})


def test_metric_agent_direct_answer(monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", "/tmp/unused")
    model = FakeChatModel([ModelReply(content="cpu_usage 最近 30 分钟持续高于 85，确认异常")])
    agent = SpecialistAgent(name="metric", system_prompt=METRIC_AGENT_PROMPT,
                            tools=[QUERY_METRICS_SPEC], model=model, backend=InlineBackend())
    assert "确认异常" in agent.run("cpu_usage 是否异常？")


def test_prompts_mention_delegation():
    assert "ask_metric_agent" in ORCHESTRATOR_PROMPT
    assert "ask_log_agent" in ORCHESTRATOR_PROMPT
    assert "query_logs" in LOG_AGENT_PROMPT
    assert "query_metrics" in METRIC_AGENT_PROMPT
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_agents.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 agents.py**

```python
# src/open_tam/orchestrator/agents.py
from __future__ import annotations

import json

from open_tam.orchestrator.loop import ChatModel, DiagnosisResult, ReActLoop
from open_tam.orchestrator.tools import Backend, InlineBackend

ORCHESTRATOR_PROMPT = """你是资深 SRE 运维专家（orchestrator）。收到告警后，通过两个子 Agent 排查：
- ask_metric_agent(question)：向指标分析子 Agent 提问，确认异常是否存在、异常窗口与幅度；
- ask_log_agent(question)：向日志检索子 Agent 提问，获取异常现场的日志证据。
先向指标子 Agent 确认异常，需要现场证据时再询问日志子 Agent；证据足够后定位根因。
最终**只输出一个 JSON 对象**（可包在 ```json 代码块中）：
{"root_cause": "<根因；无法定位则为 null>", "evidence": ["<证据>"], "actions": ["<建议动作>"], "confidence": "high|medium|low", "excluded": ["<已排除项>"]}
evidence 必须引用子 Agent 返回的关键证据原文。不要输出 JSON 以外的解释性文字。"""

METRIC_AGENT_PROMPT = """你是指标分析子 Agent。用 query_metrics 查询时序数据，回答"异常是否存在、何时开始、幅度多大"。
完成回答后只输出结论文本（不要 JSON、不要多余前缀）。"""

LOG_AGENT_PROMPT = """你是日志检索子 Agent。用 query_logs 检索异常现场日志（可按级别 ERROR/WARN 与关键字过滤），提炼与问题直接相关的日志证据。
完成回答后只输出证据清单文本，每条一行。"""


class SpecialistAgent:
    """专长子 Agent：独立系统提示 + 单一数据工具，由 orchestrator 以工具形式委托调用。"""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[dict],
        model: ChatModel,
        backend: Backend | None = None,
        max_steps: int = 5,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools
        self.model = model
        self.backend: Backend = backend or InlineBackend()
        self.max_steps = max_steps

    def run(self, question: str) -> str:
        loop = ReActLoop(
            model=self.model, backend=self.backend, max_steps=self.max_steps,
            system_prompt=self.system_prompt, tools=self.tools,
        )
        result: DiagnosisResult = loop.run_prompt(
            self.system_prompt, question, alert_id=f"subagent-{self.name}"
        )
        return result.root_cause or "（无结论）"


class AgentBackend:
    """orchestrator 的工具后端：把 ask_* 委托工具路由到对应 SpecialistAgent。"""

    def __init__(self, specialists: dict[str, SpecialistAgent]) -> None:
        self.specialists = specialists

    def execute(self, name: str, args: dict) -> str:
        if name in self.specialists:
            return self.specialists[name].run(args["question"])
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_agents.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/open_tam/orchestrator/agents.py tests/test_agents.py
git commit -m "feat: metric/log 专长子 Agent 与 AgentBackend 委托路由"
```

---

### Task 9: CLI investigate 接入子 Agent + trace show

**Files:**
- Create: `src/open_tam/orchestrator/agents.py`（Task 8 已建）
- Modify: `src/open_tam/orchestrator/tools.py`（新增 ORCHESTRATOR_TOOLS）
- Modify: `src/open_tam/cli.py`
- Test: `tests/test_investigate.py`（追加）

- [ ] **Step 0: tools.py 末尾新增委托工具 spec 与 orchestrator 工具表**

```python
ASK_METRIC_AGENT_SPEC = {
    "name": "ask_metric_agent",
    "description": "向指标分析子 Agent 提问：确认异常是否存在、异常窗口与幅度。",
    "parameters": {
        "type": "object",
        "properties": {"question": {"type": "string", "description": "要分析的问题"}},
        "required": ["question"],
    },
}

ASK_LOG_AGENT_SPEC = {
    "name": "ask_log_agent",
    "description": "向日志检索子 Agent 提问：获取异常现场的日志证据。",
    "parameters": {
        "type": "object",
        "properties": {"question": {"type": "string", "description": "要检索的问题"}},
        "required": ["question"],
    },
}

ORCHESTRATOR_TOOLS: list[dict] = [ASK_METRIC_AGENT_SPEC, ASK_LOG_AGENT_SPEC]
```

- [ ] **Step 1: 追加失败测试（tests/test_investigate.py 末尾）**

```python
def test_investigate_fake_writes_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "traces"))
    from open_tam.faults import FaultState
    FaultState().activate("cpu_spike", duration_minutes=30)

    alert_file = tmp_path / "alert.json"
    alert_file.write_text(json.dumps({
        "alert_name": "CPU使用率过高", "service": "demo-app",
        "metric": "cpu_usage", "threshold": 80, "current_value": 92.5,
    }), encoding="utf-8")

    result = runner.invoke(app, ["investigate", "--alert-file", str(alert_file), "--fake"])
    assert result.exit_code == 0, result.output
    traces = list((tmp_path / "traces").glob("*.jsonl"))
    assert len(traces) == 1
    alert_id = traces[0].stem
    shown = runner.invoke(app, ["trace", "show", alert_id])
    assert shown.exit_code == 0, shown.output
    assert "alert_received" in shown.output and "final" in shown.output
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_investigate.py -q`
Expected: 新测试 FAIL（无 trace 产出 / trace 命令不存在），旧测试仍 PASS

- [ ] **Step 3: 修改 cli.py investigate（fake 分支与接线）**

import 区追加：

```python
from open_tam.orchestrator.agents import (
    LOG_AGENT_PROMPT,
    METRIC_AGENT_PROMPT,
    AgentBackend,
    SpecialistAgent,
)
from open_tam.orchestrator.loop import ORCHESTRATOR_PROMPT
from open_tam.orchestrator.tools import ORCHESTRATOR_TOOLS, QUERY_LOGS_SPEC, QUERY_METRICS_SPEC
from open_tam.tracing.trace import TraceRecorder
```

investigate 函数体内，`settings = Settings.load()` 之后加：

```python
    trace = TraceRecorder(alert_id=normalize_alert(json.loads("{}")).alert_id if False else None)  # 占位删除
```

——上面这行不要；正确写法是先标准化 alert 再建 recorder。完整函数体替换为：

```python
    settings = Settings.load()
    raw = json.loads(Path(alert_file).read_text(encoding="utf-8"))
    alert = normalize_alert(raw)
    trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir)
    leaf_backend = InlineBackend() if transport == "inline" else McpStdioBackend()

    now = datetime.now().replace(second=0, microsecond=0)
    window = {"start": (now - timedelta(minutes=60)).isoformat(), "end": now.isoformat()}

    if fake:
        orch_model = FakeChatModel([
            ModelReply(content="先问指标子 Agent 确认异常", tool_calls=[ToolCall(
                id="t1", name="ask_metric_agent",
                arguments={"question": f"{alert.service} 的 {alert.metric} 最近一小时是否异常？异常窗口与幅度？"})]),
            ModelReply(content="再向日志子 Agent 要现场证据", tool_calls=[ToolCall(
                id="t2", name="ask_log_agent",
                arguments={"question": f"检索 {alert.service} 最近一小时 ERROR/WARN 日志，找与 {alert.metric} 异常相关的证据"})]),
            ModelReply(content=(
                '```json\n{"root_cause": "demo-app /search 接口低效正则导致 CPU 飙升", '
                '"evidence": ["指标子 Agent：cpu_usage 持续高于 85", "日志子 Agent 返回的现场证据"], '
                '"actions": ["回滚最近发布", "优化正则逻辑"], "confidence": "high"}\n```'),
                tool_calls=[]),
        ])
        metric_agent = SpecialistAgent(
            name="metric", system_prompt=METRIC_AGENT_PROMPT,
            tools=[QUERY_METRICS_SPEC], backend=leaf_backend,
            model=FakeChatModel([ModelReply(content="cpu_usage 在最近 30 分钟持续高于 85，确认异常")]),
        )
        log_agent = SpecialistAgent(
            name="log", system_prompt=LOG_AGENT_PROMPT,
            tools=[QUERY_LOGS_SPEC], backend=leaf_backend,
            model=FakeChatModel([
                ModelReply(content=None, tool_calls=[ToolCall(id="l1", name="query_logs", arguments={
                    "service": alert.service, "start": window["start"], "end": window["end"],
                })]),
                ModelReply(content="最近一小时无 ERROR 级日志，异常主要体现在指标层"),
            ]),
        )
    else:
        if not os.environ.get("DASHSCOPE_API_KEY"):
            typer.echo("错误：未设置 DASHSCOPE_API_KEY。真实排查需配置 Key，"
                       "或使用 --fake 走无 Key 演示路径。", err=True)
            raise typer.Exit(1)
        from open_tam.orchestrator.llm import AgentScopeChatModel

        llm = AgentScopeChatModel(
            primary=settings.model_primary, fallback=settings.model_fallback
        )
        orch_model = llm
        metric_agent = SpecialistAgent(name="metric", system_prompt=METRIC_AGENT_PROMPT,
                                       tools=[QUERY_METRICS_SPEC], backend=leaf_backend, model=llm)
        log_agent = SpecialistAgent(name="log", system_prompt=LOG_AGENT_PROMPT,
                                    tools=[QUERY_LOGS_SPEC], backend=leaf_backend, model=llm)

    backend = AgentBackend({
        "ask_metric_agent": metric_agent,
        "ask_log_agent": log_agent,
    })
    loop = ReActLoop(model=orch_model, backend=backend, max_steps=settings.max_steps,
                     char_budget=settings.char_budget, system_prompt=ORCHESTRATOR_PROMPT,
                     tools=ORCHESTRATOR_TOOLS, trace=trace)
    result = loop.run(alert)
    path = save_report(alert, result, reports_dir=settings.reports_dir)
    typer.echo(f"report saved: {path}")
    typer.echo(f"trace saved: {trace.path}")
    typer.echo(result.root_cause or "未定位根因")
```

同时在函数顶部 import 区把原来局部的 `from open_tam.orchestrator.loop import FakeChatModel, ModelReply, ReActLoop, ToolCall` 等保持（FakeChatModel/ModelReply/ToolCall/ReActLoop 仍需要）。

- [ ] **Step 4: cli.py 增加 trace show 命令**

```python
@app.command("trace")
def trace_show(alert_id: str = typer.Argument(...)) -> None:
    """回放某次排查的 trace JSONL。"""
    from open_tam.tracing.trace import load_trace

    settings = Settings.load()
    path = settings.traces_dir / f"{alert_id}.jsonl"
    if not path.exists():
        typer.echo(f"trace not found: {path}", err=True)
        raise typer.Exit(1)
    for record in load_trace(path):
        typer.echo(json.dumps(record, ensure_ascii=False))
```

（`Settings` 已在函数内 import——trace_show 内同样局部 import。）

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_investigate.py tests/test_cli.py -q`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add src/open_tam/orchestrator/tools.py src/open_tam/cli.py tests/test_investigate.py
git commit -m "feat: investigate 接入双子 Agent 协作与 trace 落盘，新增 trace show 回放"
```

---

### Task 10: M2 集成测试 + 验收 + 文档

**Files:**
- Create: `tests/test_integration_m2.py`
- Modify: `docs/mvp-plan.md`、`README.md`

- [ ] **Step 1: 写集成测试**

```python
# tests/test_integration_m2.py
from datetime import datetime, timedelta

from open_tam.faults import FaultState
from open_tam.models import AlertEvent
from open_tam.orchestrator.agents import (
    LOG_AGENT_PROMPT,
    METRIC_AGENT_PROMPT,
    ORCHESTRATOR_PROMPT,
    AgentBackend,
    SpecialistAgent,
)
from open_tam.orchestrator.loop import (
    FakeChatModel,
    ModelReply,
    ReActLoop,
    ToolCall,
)
from open_tam.orchestrator.tools import ORCHESTRATOR_TOOLS, QUERY_LOGS_SPEC, QUERY_METRICS_SPEC
```

集成测试正文（同文件）：

```python
def test_slow_query_end_to_end_with_delegation(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    from open_tam.orchestrator.tools import ORCHESTRATOR_TOOLS
    from open_tam.orchestrator.tools import QUERY_LOGS_SPEC, QUERY_METRICS_SPEC
    from open_tam.reporting.report import save_report
    from open_tam.tracing.trace import TraceRecorder, load_trace

    FaultState().activate("slow_query", duration_minutes=30)
    alert = AlertEvent.model_validate({
        "alert_name": "数据库查询耗时过高", "service": "demo-app",
        "metric": "db_query_duration_ms", "threshold": 1000, "current_value": 3241,
        "triggered_at": datetime.now(),
    })

    now = datetime.now().replace(second=0, microsecond=0)
    orch_model = FakeChatModel([
        ModelReply(content=None, tool_calls=[ToolCall(id="t1", name="ask_log_agent", arguments={
            "question": "检索 demo-app 最近 30 分钟慢查询相关 ERROR 日志"})]),
        ModelReply(content=(
            '```json\n{"root_cause": "/orders 接口新增 SQL 未命中索引，全表扫描导致慢查询", '
            '"evidence": ["日志子 Agent：Slow query detected: SELECT * FROM orders WHERE user_id = ? took 3241ms"], '
            '"actions": ["为 orders(user_id, created_at) 建立联合索引"], "confidence": "high"}\n```'),
            tool_calls=[]),
    ])
    log_agent = SpecialistAgent(
        name="log", system_prompt=LOG_AGENT_PROMPT,
        tools=[QUERY_LOGS_SPEC],
        model=FakeChatModel([
            ModelReply(content=None, tool_calls=[ToolCall(id="l1", name="query_logs", arguments={
                "service": "demo-app", "level": "ERROR",
                "start": (now - timedelta(minutes=30)).isoformat(),
                "end": now.isoformat(),
            })]),
            ModelReply(content="发现 ERROR 日志 2 条：Slow query detected ..."),
        ]),
    )
    metric_agent = SpecialistAgent(
        name="metric", system_prompt=METRIC_AGENT_PROMPT,
        tools=[QUERY_METRICS_SPEC],
        model=FakeChatModel([ModelReply(content="db_query_duration_ms 近 30 分钟持续高于 3000ms，确认异常")]),
    )

    trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=tmp_path / "traces")
    loop = ReActLoop(model=orch_model, backend=AgentBackend({
        "ask_metric_agent": metric_agent, "ask_log_agent": log_agent,
    }), system_prompt=ORCHESTRATOR_PROMPT, tools=ORCHESTRATOR_TOOLS, trace=trace)
    result = loop.run(alert)

    assert result.root_cause and "索引" in result.root_cause
    report_path = save_report(alert, result, reports_dir=tmp_path / "reports")
    report_text = report_path.read_text(encoding="utf-8")
    for heading in ("## 结论摘要", "## 异常清单", "## 建议动作"):
        assert heading in report_text
    assert "Slow query detected" in report_text

    records = load_trace(trace.path)
    kinds = [r["kind"] for r in records]
    assert kinds[0] == "alert_received" and kinds[-1] == "final"
    log_observations = [r for r in records if r["kind"] == "observation" and r.get("tool") == "ask_log_agent"]
    assert log_observations and "Slow query detected" in log_observations[0]["observation"]
```

- [ ] **Step 2: 运行确认通过（含全量回归）**

Run: `uv run pytest -q`
Expected: 全部 passed（累计约 55+ 用例）

- [ ] **Step 3: 手动验收（M2 验收标准）**

```bash
uv run open-tam fault inject slow_query
echo '{"alert_name":"数据库查询耗时过高","service":"demo-app","metric":"db_query_duration_ms","threshold":1000,"current_value":3241}' > /tmp/alert.json
DASHSCOPE_API_KEY=$(python3 -c "import json;print(json.load(open('/Users/allengaller/.bailian/config.json'))['api_key'])") \
  uv run open-tam investigate --alert-file /tmp/alert.json --transport mcp
uv run open-tam fault clear slow_query
uv run open-tam trace show $(ls traces | head -1 | sed 's/\.jsonl//')
```
Expected: 报告三段结构完整且引用日志证据；trace show 输出完整 JSONL 可回放。

- [ ] **Step 4: 更新 docs/mvp-plan.md M2 勾选与验收记录、README 命令表（logs query / trace show）**

- [ ] **Step 5: Commit**

```bash
git add src/open_tam/orchestrator/tools.py tests/test_integration_m2.py docs/mvp-plan.md README.md
git commit -m "feat: M2 多 Agent 协作集成测试与验收（慢查询证据链 + trace 回放）"
```

---

## 计划自检记录

1. **Spec 覆盖**：mock-logs（T3/T4）、故障模式扩充（T2）、子 Agent 协作（T7/T8/T9）、trace 落盘与回放（T6/T7/T9）、验收"慢查询用上日志证据/报告三段/trace 可回放"（T10）。
2. **占位符**：无 TBD；Task 9 Step 3 中的"占位删除"行是显式标记的"不要执行"反例说明，非遗留 TODO。
3. **类型一致性**：`SpecialistAgent(name, system_prompt, tools, model, backend, max_steps)` 与两处构造一致；`AgentBackend.execute(name,args)` 与 Backend 协议一致；`run_prompt(system,user,alert_id)` 与 T9/T10 调用一致；`TraceRecorder(alert_id, traces_dir)` 与 T7/T9/T10 一致；`ORCHESTRATOR_TOOLS` 在 T10 定义、T9 import 依赖 T10 先行——执行顺序调整为：执行 T9 前先把 T10 中 tools.py 的 ORCHESTRATOR_TOOLS 代码块补入（作为 T9 的 Step 0），T10 只保留集成测试与文档。
