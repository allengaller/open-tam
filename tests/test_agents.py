from datetime import datetime, timedelta

from open_tam.faults import FaultState
from open_tam.orchestrator.agents import (
    LOG_AGENT_PROMPT,
    METRIC_AGENT_PROMPT,
    ORCHESTRATOR_PROMPT,
    AgentBackend,
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
