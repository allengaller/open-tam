from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import typer

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.orchestrator.tools import InlineBackend, McpStdioBackend

app = typer.Typer(help="open-tam SRE Agent", no_args_is_help=True)
metrics_app = typer.Typer(help="指标查询")
logs_app = typer.Typer(help="日志查询")
fault_app = typer.Typer(help="故障注入")
app.add_typer(metrics_app, name="metrics")
app.add_typer(logs_app, name="logs")
app.add_typer(fault_app, name="fault")


@metrics_app.command("query")
def metrics_query(
    metric: str = typer.Option(...),
    service: str = typer.Option("demo-app"),
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    transport: str = typer.Option("inline", help="inline 或 mcp"),
) -> None:
    datetime.fromisoformat(start)
    datetime.fromisoformat(end)
    backend = InlineBackend() if transport == "inline" else McpStdioBackend()
    typer.echo(f"# {metric} @ {service} ({transport})")
    typer.echo(backend.execute("query_metrics", {
        "metric": metric, "service": service, "start": start, "end": end,
    }))


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


@fault_app.command("inject")
def fault_inject(name: str, duration: int = typer.Option(30)) -> None:
    FaultState().activate(name, duration_minutes=duration)
    typer.echo(f"fault {name} activated for {duration}min")


@fault_app.command("clear")
def fault_clear(name: str) -> None:
    FaultState().clear(name)
    typer.echo(f"fault {name} cleared")


@fault_app.command("list")
def fault_list() -> None:
    for mode in FAULT_MODES.values():
        typer.echo(f"{mode.name}: {mode.anomaly_desc}")


@app.command("investigate")
def investigate(
    alert_file: str = typer.Option(..., help="告警 JSON 文件路径"),
    fake: bool = typer.Option(False, help="使用内置 FakeChatModel（无 Key 演示）"),
    transport: str = typer.Option("inline", help="inline 或 mcp"),
) -> None:
    """读取告警 JSON，运行排查循环并生成结构化根因报告。"""
    from open_tam.config import Settings
    from open_tam.orchestrator.loop import FakeChatModel, ModelReply, ReActLoop, ToolCall
    from open_tam.receiver.alert_receiver import normalize_alert
    from open_tam.reporting.report import save_report

    settings = Settings.load()
    raw = json.loads(Path(alert_file).read_text(encoding="utf-8"))
    alert = normalize_alert(raw)

    if fake:
        now = datetime.now().replace(second=0, microsecond=0)
        model = FakeChatModel([
            ModelReply(content="先查指标确认异常窗口", tool_calls=[ToolCall(
                id="t1", name="query_metrics",
                arguments={"metric": alert.metric, "service": alert.service,
                           "start": (now - timedelta(minutes=60)).isoformat(),
                           "end": now.isoformat()})]),
            ModelReply(content=(
                '```json\n{"root_cause": "demo-app /search 接口低效正则导致 CPU 飙升", '
                '"evidence": ["query_metrics 显示 cpu_usage 持续高于 85"], '
                '"actions": ["回滚最近发布", "优化正则逻辑"], "confidence": "high"}\n```'),
                tool_calls=[]),
        ])
    else:
        if not os.environ.get("DASHSCOPE_API_KEY"):
            typer.echo("错误：未设置 DASHSCOPE_API_KEY。真实排查需配置 Key，"
                       "或使用 --fake 走无 Key 演示路径。", err=True)
            raise typer.Exit(1)
        from open_tam.orchestrator.llm import AgentScopeChatModel

        model = AgentScopeChatModel(
            primary=settings.model_primary, fallback=settings.model_fallback
        )

    backend = InlineBackend() if transport == "inline" else McpStdioBackend()
    loop = ReActLoop(model=model, backend=backend, max_steps=settings.max_steps,
                     char_budget=settings.char_budget)
    result = loop.run(alert)
    path = save_report(alert, result, reports_dir=settings.reports_dir)
    typer.echo(f"report saved: {path}")
    typer.echo(result.root_cause or "未定位根因")


@app.command("version")
def version() -> None:
    from open_tam import __version__

    typer.echo(f"open-tam {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
