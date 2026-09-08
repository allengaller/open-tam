import json
from pathlib import Path

from open_tam.guardrails import (
    ActionSpec,
    AuditLogger,
    AutoApprove,
    AutoDeny,
    Guardrails,
)


def make_guard(tmp_path: Path, confirmer=None) -> tuple[Guardrails, Path]:
    state = tmp_path / "var"
    registry = {
        "noop": ActionSpec(
            name="noop", description="测试动作", params={"target": "目标"},
            sensitivity="safe", runner=lambda a: f"noop {a['target']} done",
        ),
        "risky": ActionSpec(
            name="risky", description="测试敏感动作", params={"target": "目标"},
            sensitivity="sensitive", runner=lambda a: f"risky {a['target']} done",
        ),
    }
    audit = AuditLogger(state)
    return Guardrails(registry, audit, confirmer=confirmer), state / "audit.log"


def read_audit(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_unknown_action_denied_and_audited(tmp_path):
    guard, audit_path = make_guard(tmp_path)
    out = json.loads(guard.run("rm_rf", {}, actor="agent"))
    assert out["denied"] is True
    assert "白名单外" in out["reason"]
    entries = read_audit(audit_path)
    assert entries[-1]["decision"] == "denied"
    assert entries[-1]["action"] == "rm_rf"
    assert entries[-1]["actor"] == "agent"


def test_safe_action_executed_and_audited(tmp_path):
    guard, audit_path = make_guard(tmp_path)
    out = guard.run("noop", {"target": "demo-app"})
    assert out == "noop demo-app done"
    entries = read_audit(audit_path)
    assert entries[-1]["decision"] == "executed"
    assert entries[-1]["result"] == "noop demo-app done"


def test_param_mismatch_denied(tmp_path):
    guard, _ = make_guard(tmp_path)
    missing = json.loads(guard.run("noop", {}))
    extra = json.loads(guard.run("noop", {"target": "x", "evil": "1"}))
    assert "缺少参数" in missing["reason"]
    assert "多余参数" in extra["reason"]


def test_dry_run_previews_without_execution(tmp_path):
    guard, audit_path = make_guard(tmp_path)
    out = guard.run("noop", {"target": "demo-app"}, dry_run=True)
    assert "dry-run" in out and "demo-app" in out
    entries = read_audit(audit_path)
    assert entries[-1]["decision"] == "dry_run"


def test_sensitive_denied_without_confirmation(tmp_path):
    guard, audit_path = make_guard(tmp_path, confirmer=AutoDeny())
    out = json.loads(guard.run("risky", {"target": "demo-app"}))
    assert out["denied"] is True
    assert "未获人工确认" in out["reason"]
    assert read_audit(audit_path)[-1]["decision"] == "denied"


def test_sensitive_executes_when_confirmer_approves(tmp_path):
    guard, _ = make_guard(tmp_path, confirmer=AutoApprove())
    out = guard.run("risky", {"target": "demo-app"})
    assert out == "risky demo-app done"


def test_confirmed_flag_skips_confirmer(tmp_path):
    guard, _ = make_guard(tmp_path, confirmer=AutoDeny())
    out = guard.run("risky", {"target": "demo-app"}, confirmed=True)
    assert out == "risky demo-app done"


def test_audit_entries_reader(tmp_path):
    guard, _ = make_guard(tmp_path)
    guard.run("noop", {"target": "a"})
    guard.run("noop", {"target": "b"})
    audit = AuditLogger(tmp_path / "var")
    assert [e["arguments"]["target"] for e in audit.entries()] == ["a", "b"]
