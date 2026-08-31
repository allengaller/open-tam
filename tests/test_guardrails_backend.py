# tests/test_guardrails_backend.py
import json

from open_tam.actions import ACTION_REGISTRY
from open_tam.guardrails import AuditLogger, AutoDeny, Guardrails
from open_tam.orchestrator.agents import ORCHESTRATOR_PROMPT
from open_tam.orchestrator.tools import ORCHESTRATOR_TOOLS, GuardrailsBackend


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        return "ok"


def test_orchestrator_tools_include_execute_action():
    assert [t["name"] for t in ORCHESTRATOR_TOOLS] == [
        "ask_metric_agent", "ask_log_agent", "execute_action",
    ]


def test_prompt_mentions_action_policy():
    assert "execute_action" in ORCHESTRATOR_PROMPT
    assert "敏感" in ORCHESTRATOR_PROMPT


def test_guardrails_backend_routes_execute_action(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path / "var"), confirmer=AutoDeny())
    backend = GuardrailsBackend(RecordingBackend(), guard, actor="agent")
    out = json.loads(backend.execute("execute_action", {
        "action": "rollback_release", "arguments": {"service": "demo-app"},
    }))
    assert out["denied"] is True
    assert (tmp_path / "var" / "audit.log").exists()


def test_guardrails_backend_executes_safe_action(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path / "var"), confirmer=AutoDeny())
    backend = GuardrailsBackend(RecordingBackend(), guard, actor="agent")
    out = backend.execute("execute_action", {
        "action": "clear_fault", "arguments": {"name": "cpu_spike"},
    })
    assert "cleared" in out


def test_guardrails_backend_passes_through_other_tools(tmp_path):
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path / "var"), confirmer=AutoDeny())
    inner = RecordingBackend()
    backend = GuardrailsBackend(inner, guard)
    assert backend.execute("query_metrics", {"metric": "cpu_usage"}) == "ok"
    assert inner.calls == [("query_metrics", {"metric": "cpu_usage"})]
