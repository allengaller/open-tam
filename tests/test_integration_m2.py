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
from open_tam.reporting.report import save_report
from open_tam.tracing.trace import TraceRecorder, load_trace


def test_slow_query_end_to_end_with_delegation(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
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
