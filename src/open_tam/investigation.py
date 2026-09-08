from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from open_tam.config import Settings
from open_tam.models import AlertEvent
from open_tam.orchestrator.loop import (
    ChatModel,
    FakeChatModel,
    ModelReply,
    ReActLoop,
    ToolCall,
)


@dataclass(frozen=True)
class InvestigationOutcome:
    alert_id: str
    root_cause: str | None
    confidence: str
    steps: int
    report_path: Path
    trace_path: Path


def run_investigation(
    alert: AlertEvent,
    *,
    settings: Settings,
    model: ChatModel | None = None,
    transport: str = "inline",
) -> InvestigationOutcome:
    """跑一次告警排查闭环，落盘报告与 trace。

    model=None 走真实模型路径（需 DASHSCOPE_API_KEY，子 Agent 共享同一 LLM 实例）；
    传入脚本化 model 时走演示路径，叶子子 Agent 使用内置单发 FakeChatModel。
    """
    from open_tam.actions import ACTION_REGISTRY
    from open_tam.guardrails import AuditLogger, AutoDeny, Guardrails
    from open_tam.orchestrator.agents import (
        LOG_AGENT_PROMPT,
        METRIC_AGENT_PROMPT,
        ORCHESTRATOR_PROMPT,
        AgentBackend,
        SpecialistAgent,
    )
    from open_tam.orchestrator.tools import (
        ORCHESTRATOR_TOOLS,
        QUERY_LOGS_SPEC,
        QUERY_METRICS_SPEC,
        GuardrailsBackend,
        InlineBackend,
        McpStdioBackend,
    )
    from open_tam.reporting.report import save_report
    from open_tam.tracing.trace import TraceRecorder

    if model is None:
        if not os.environ.get("DASHSCOPE_API_KEY"):
            raise RuntimeError(
                "未设置 DASHSCOPE_API_KEY。真实排查需配置 Key，或使用脚本化 model 演示。"
            )
        from open_tam.orchestrator.llm import AgentScopeChatModel

        model = AgentScopeChatModel(
            primary=settings.model_primary,
            fallback=settings.model_fallback,
            timeout=settings.model_timeout,
        )
        real = True
    else:
        real = False

    trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir)
    metric_trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir, agent="metric")
    log_trace = TraceRecorder(alert_id=alert.alert_id, traces_dir=settings.traces_dir, agent="log")
    leaf_backend = InlineBackend() if transport == "inline" else McpStdioBackend()

    now = datetime.now().replace(second=0, microsecond=0)
    window = {"start": (now - timedelta(minutes=60)).isoformat(), "end": now.isoformat()}

    if real:
        metric_agent = SpecialistAgent(
            name="metric", system_prompt=METRIC_AGENT_PROMPT,
            tools=[QUERY_METRICS_SPEC], backend=leaf_backend, model=model,
            trace=metric_trace,
        )
        log_agent = SpecialistAgent(
            name="log", system_prompt=LOG_AGENT_PROMPT,
            tools=[QUERY_LOGS_SPEC], backend=leaf_backend, model=model,
            trace=log_trace,
        )
    else:
        metric_agent = SpecialistAgent(
            name="metric", system_prompt=METRIC_AGENT_PROMPT,
            tools=[QUERY_METRICS_SPEC], backend=leaf_backend,
            model=FakeChatModel([ModelReply(
                content=f"{alert.metric} 在最近 30 分钟持续高于 {alert.threshold}，确认异常")]),
        )
        log_agent = SpecialistAgent(
            name="log", system_prompt=LOG_AGENT_PROMPT,
            tools=[QUERY_LOGS_SPEC], backend=leaf_backend,
            model=FakeChatModel([
                ModelReply(content=None, tool_calls=[ToolCall(
                    id="l1", name="query_logs",
                    arguments={"service": alert.service, "start": window["start"], "end": window["end"]})]),
                ModelReply(content="最近一小时无 ERROR 级日志，异常主要体现在指标层"),
            ]),
        )

    backend = AgentBackend({
        "ask_metric_agent": metric_agent,
        "ask_log_agent": log_agent,
    })
    guardrails = Guardrails(ACTION_REGISTRY, AuditLogger(settings.state_dir),
                            confirmer=AutoDeny())
    backend = GuardrailsBackend(backend, guardrails, actor="agent")
    loop = ReActLoop(model=model, backend=backend, max_steps=settings.max_steps,
                     char_budget=settings.char_budget, system_prompt=ORCHESTRATOR_PROMPT,
                     tools=ORCHESTRATOR_TOOLS, trace=trace)
    result = loop.run(alert)
    path = save_report(alert, result, reports_dir=settings.reports_dir)
    return InvestigationOutcome(
        alert_id=alert.alert_id,
        root_cause=result.root_cause,
        confidence=result.confidence,
        steps=len(result.steps),
        report_path=path,
        trace_path=trace.path,
    )


def demo_orchestrator_model() -> FakeChatModel:
    """CLI 无 Key 演示用的脚本化编排模型（cpu_spike 故障故事）。"""
    return FakeChatModel([
        ModelReply(content="先问指标子 Agent 确认异常", tool_calls=[ToolCall(
            id="t1", name="ask_metric_agent",
            arguments={"question": "demo-app 的 cpu_usage 最近一小时是否异常？异常窗口与幅度？"})]),
        ModelReply(content="再向日志子 Agent 要现场证据", tool_calls=[ToolCall(
            id="t2", name="ask_log_agent",
            arguments={"question": "检索 demo-app 最近一小时 ERROR/WARN 日志，找与 cpu_usage 异常相关的证据"})]),
        ModelReply(content=(
            '```json\n{"root_cause": "demo-app /search 接口低效正则导致 CPU 飙升", '
            '"evidence": ["指标子 Agent：cpu_usage 持续高于 85", "日志子 Agent 返回的现场证据"], '
            '"actions": ["回滚最近发布", "优化正则逻辑"], "confidence": "high"}\n```'),
            tool_calls=[]),
    ])
