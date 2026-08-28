from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import typer

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.orchestrator.tools import (
    QUERY_LOGS_SPEC,
    QUERY_METRICS_SPEC,
    InlineBackend,
    McpStdioBackend,
)

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
    """读取告警 JSON，orchestrator 委托双子 Agent 排查并生成结构化根因报告与 trace。"""
    from open_tam.config import Settings
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
    from open_tam.orchestrator.tools import ORCHESTRATOR_TOOLS
    from open_tam.receiver.alert_receiver import normalize_alert
    from open_tam.reporting.report import save_report
    from open_tam.tracing.trace import TraceRecorder

    settings = Settings.load()
    raw = json.loads(Path(alert_file).read_text(encoding="utf-8"))
    alert = normalize_alert(raw)
    trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir)
    metric_trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir, agent="metric")
    log_trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir, agent="log")
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
        metric_agent = SpecialistAgent(
            name="metric", system_prompt=METRIC_AGENT_PROMPT,
            tools=[QUERY_METRICS_SPEC], backend=leaf_backend, model=llm,
            trace=metric_trace,
        )
        log_agent = SpecialistAgent(name="log", system_prompt=LOG_AGENT_PROMPT,
                                    tools=[QUERY_LOGS_SPEC], backend=leaf_backend, model=llm,
                                    trace=log_trace)

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


trace_app = typer.Typer(help="trace 回放")
app.add_typer(trace_app, name="trace")


@trace_app.command("show")
def trace_show(alert_id: str = typer.Argument(...)) -> None:
    """回放某次排查的 trace JSONL。"""
    from open_tam.config import Settings
    from open_tam.tracing.trace import load_trace

    settings = Settings.load()
    path = settings.traces_dir / f"{alert_id}.jsonl"
    if not path.exists():
        typer.echo(f"trace not found: {path}", err=True)
        raise typer.Exit(1)
    for record in load_trace(path):
        typer.echo(json.dumps(record, ensure_ascii=False))


@app.command("version")
def version() -> None:
    from open_tam import __version__

    typer.echo(f"open-tam {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
