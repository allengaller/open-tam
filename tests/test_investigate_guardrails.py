from open_tam.actions import ACTION_REGISTRY
from open_tam.faults import FaultState
from open_tam.guardrails import AuditLogger, AutoDeny, Guardrails
from open_tam.models import AlertEvent
from open_tam.orchestrator.agents import ORCHESTRATOR_PROMPT, AgentBackend
from open_tam.orchestrator.loop import FakeChatModel, ModelReply, ReActLoop, ToolCall
from open_tam.orchestrator.tools import ORCHESTRATOR_TOOLS, GuardrailsBackend


def make_alert() -> AlertEvent:
    return AlertEvent(alert_name="CPU飙高", service="demo-app", metric="cpu_usage",
                      threshold=85, current_value=92)


def make_loop(tmp_path, replies) -> ReActLoop:
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path / "var"), confirmer=AutoDeny())
    backend = GuardrailsBackend(AgentBackend({}), guard, actor="agent")
    return ReActLoop(model=FakeChatModel(replies), backend=backend,
                     system_prompt=ORCHESTRATOR_PROMPT, tools=ORCHESTRATOR_TOOLS)


def test_agent_executes_safe_action_and_audits(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    FaultState().activate("cpu_spike", duration_minutes=30)
    replies = [
        ModelReply(content="根因已确认，执行修复", tool_calls=[ToolCall(
            id="t1", name="execute_action",
            arguments={"action": "clear_fault", "arguments": {"name": "cpu_spike"}})]),
        ModelReply(content='```json\n{"root_cause": "CPU 飙升（已修复）", "evidence": ["e1"], '
                           '"actions": ["观察恢复情况"], "confidence": "high"}\n```'),
    ]
    result = make_loop(tmp_path, replies).run(make_alert())
    assert "cleared" in result.steps[0].observation
    assert FaultState().is_active("cpu_spike") is False
    audit = AuditLogger(tmp_path / "var").entries()
    assert audit[0]["actor"] == "agent"
    assert audit[0]["decision"] == "executed"


def test_agent_sensitive_action_denied_and_loop_continues(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    replies = [
        ModelReply(content="尝试回滚", tool_calls=[ToolCall(
            id="t1", name="execute_action",
            arguments={"action": "rollback_release", "arguments": {"service": "demo-app"}})]),
        ModelReply(content='```json\n{"root_cause": "根因X", "evidence": ["e1"], '
                           '"actions": ["人工确认后回滚"], "confidence": "medium"}\n```'),
    ]
    result = make_loop(tmp_path, replies).run(make_alert())
    assert "未获人工确认" in result.steps[0].observation
    assert result.root_cause == "根因X"
    audit = AuditLogger(tmp_path / "var").entries()
    assert audit[0]["decision"] == "denied"
