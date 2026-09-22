from __future__ import annotations

import os
from datetime import datetime, timedelta

from open_tam.actions import ACTION_REGISTRY
from open_tam.config import Settings
from open_tam.guardrails import AuditLogger, AutoDeny, Confirmer, Guardrails
from open_tam.models import AlertEvent
from open_tam.orchestrator.agents import (
    K8S_AGENT_PROMPT,
    LOG_AGENT_PROMPT,
    METRIC_AGENT_PROMPT,
    ORCHESTRATOR_PROMPT,
    AgentBackend,
    SpecialistAgent,
)
from open_tam.orchestrator.loop import (
    DiagnosisResult,
    FakeChatModel,
    ModelReply,
    ReActLoop,
    ToolCall,
)
from open_tam.orchestrator.tools import (
    ANALYZE_WITH_K8SGPT_SPEC,
    ORCHESTRATOR_TOOLS,
    QUERY_K8S_EVENTS_SPEC,
    QUERY_LOGS_SPEC,
    QUERY_METRICS_SPEC,
    QUERY_NODE_STATUS_SPEC,
    QUERY_POD_STATUS_SPEC,
    GuardrailsBackend,
    InlineBackend,
    McpStdioBackend,
)
from open_tam.reporting.report import save_report
from open_tam.skills.loader import SkillLoader
from open_tam.tracing.trace import TraceRecorder


def _build_system_prompt(alert: AlertEvent, settings: Settings, base_prompt: str) -> str:
    """加载匹配的 Skill 并注入 system prompt。"""
    try:
        loader = SkillLoader(settings.skills_dir)
        skill = loader.match(alert.alert_name, alert.service)
        if skill:
            return base_prompt + "\n\n" + skill.to_prompt_section()
    except Exception:
        pass
    return base_prompt


def run_investigation(
    alert: AlertEvent,
    settings: Settings,
    *,
    fake: bool = False,
    transport: str = "inline",
    trace: TraceRecorder,
    metric_trace: TraceRecorder,
    log_trace: TraceRecorder,
    k8s_trace: TraceRecorder | None = None,
    confirmer: Confirmer | None = None,
) -> tuple[DiagnosisResult, object]:
    """orchestrator 三子 Agent 排查闭环：运行 ReActLoop 并落盘报告。

    返回 (DiagnosisResult, 报告路径)。trace recorder 由调用方创建
    （CLI 不传 sink；Web 传 sink 做流式广播）。confirmer 决定敏感操作
    的人工确认方式：默认 None → AutoDeny；Web 传 WebConfirmer 走 SSE 弹窗。
    """
    leaf_backend = InlineBackend() if transport == "inline" else McpStdioBackend()

    now = datetime.now().replace(second=0, microsecond=0)
    window = {"start": (now - timedelta(minutes=60)).isoformat(), "end": now.isoformat()}

    k8s_tools = [QUERY_K8S_EVENTS_SPEC, QUERY_POD_STATUS_SPEC, QUERY_NODE_STATUS_SPEC, ANALYZE_WITH_K8SGPT_SPEC]

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
        k8s_agent = SpecialistAgent(
            name="k8s", system_prompt=K8S_AGENT_PROMPT,
            tools=k8s_tools, backend=leaf_backend,
            model=FakeChatModel([ModelReply(content="K8s 集群状态正常，无异常事件")]),
        )
    else:
        if not os.environ.get("DASHSCOPE_API_KEY"):
            raise RuntimeError("未设置 DASHSCOPE_API_KEY。真实排查需配置 Key，或使用 fake 演示路径。")
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
        k8s_agent = SpecialistAgent(
            name="k8s", system_prompt=K8S_AGENT_PROMPT,
            tools=k8s_tools, backend=leaf_backend, model=llm,
            trace=k8s_trace,
        )

    backend = AgentBackend({
        "ask_metric_agent": metric_agent,
        "ask_log_agent": log_agent,
        "ask_k8s_agent": k8s_agent,
    })
    guardrails = Guardrails(ACTION_REGISTRY, AuditLogger(settings.state_dir),
                            confirmer=confirmer if confirmer is not None else AutoDeny())
    backend = GuardrailsBackend(backend, guardrails, actor="agent")
    system_prompt = _build_system_prompt(alert, settings, ORCHESTRATOR_PROMPT)
    loop = ReActLoop(model=orch_model, backend=backend, max_steps=settings.max_steps,
                     char_budget=settings.char_budget, system_prompt=system_prompt,
                     tools=ORCHESTRATOR_TOOLS, trace=trace)
    result = loop.run(alert)
    path = save_report(alert, result, reports_dir=settings.reports_dir)
    return result, path