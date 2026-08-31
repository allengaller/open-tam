# open-tam · SRE Agent

基于 AgentScope + MCP 的多 Agent 排障系统：告警进来，自动查指标、翻日志，产出结构化根因报告；排查过程全程落盘为语料。

- 架构一页纸：[docs/architecture.md](docs/architecture.md)
- MVP 分阶段清单：[docs/mvp-plan.md](docs/mvp-plan.md)
- 设计文档：[docs/superpowers/specs/2026-08-28-sre-agent-design.md](docs/superpowers/specs/2026-08-28-sre-agent-design.md)

## 快速开始

```bash
uv sync                          # Python 3.12，自动创建 .venv
uv run pytest -q                 # 全量测试
```

## 无 Key 演示（FakeChatModel 闭环）

```bash
uv run open-tam fault inject cpu_spike
echo '{"alert_name":"CPU使用率过高","service":"demo-app","metric":"cpu_usage","threshold":80,"current_value":92.5}' > /tmp/alert.json
uv run open-tam investigate --alert-file /tmp/alert.json --fake
uv run open-tam fault clear cpu_spike
cat reports/*.md                 # 三段式根因报告
```

## 真实模型排查（DashScope Qwen）

```bash
export DASHSCOPE_API_KEY=sk-...
uv run open-tam investigate --alert-file /tmp/alert.json
```

主备模型可通过 `OPEN_TAM_MODEL_PRIMARY` / `OPEN_TAM_MODEL_FALLBACK` 配置，默认 `qwen-plus` / `qwen-turbo`。

## 常用命令

| 命令 | 说明 |
|---|---|
| `open-tam metrics query --metric cpu_usage --service demo-app --start <iso> --end <iso>` | 查指标（`--transport mcp` 走 MCP stdio 后端） |
| `open-tam fault inject cpu_spike` / `fault clear cpu_spike` / `fault list` | 故障注入 |
| `open-tam investigate --alert-file <json> [--fake] [--transport mcp]` | 排查闭环，报告落盘 `reports/` |
| `uvicorn demo_app.app:app --port 8000` | 启动被诊断对象 demo-app（`/health` `/metrics` `/faults`） |
| `uv run python -m open_tam.mcp_servers.metrics_server` | 启动 mock-metrics MCP stdio 服务 |
| `open-tam logs query --service demo-app --start <iso> --end <iso> [--level ERROR] [--keyword slow]` | 查日志（双后端同 metrics） |
| `open-tam trace show <alert-id>` | 回放某次排查的 JSONL（含子 Agent 内部步骤） |
| `open-tam action list` | 查看白名单动作注册表 |
| `open-tam action run clear_fault --arg name=cpu_spike` | 执行白名单动作（safe 直接执行） |
| `open-tam action run rollback_release --arg service=demo-app` | 敏感动作：交互确认后执行 |
| `open-tam action run rollback_release --arg service=demo-app --yes` | 敏感动作：跳过确认 |
| `open-tam action run any --dry-run` | dry-run 预览，不实际执行 |
| `open-tam audit show` | 查看审计日志（JSONL） |
| `open-tam patrol run` | 立即巡检一次，产出巡检报告 |
| `open-tam patrol watch --every-min 5` | 每 5 分钟巡检一次（Ctrl-C 退出） |

## 已知环境注意事项

- macOS + Python 3.12.13+：`.venv` 内 editable `.pth` 若被标记 hidden（`UF_HIDDEN`），Python 会跳过它导致 `open_tam` 不可导入（本环境已观察到周期性复现）。修复：`chflags nohidden .venv/lib/python3.12/site-packages/*.pth`；pytest 已配置 `pythonpath = ["src"]` 不受影响。 彻底规避：`export UV_NO_EDITABLE=1` 后用非 editable 安装（pytest 已配置 `pythonpath = ["src"]` 不受影响）。
