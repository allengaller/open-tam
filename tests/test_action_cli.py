# tests/test_action_cli.py
import json

from typer.testing import CliRunner

from open_tam.cli import app
from open_tam.faults import FaultState

runner = CliRunner()


def read_last_audit(tmp_path) -> dict:
    lines = (tmp_path / "var" / "audit.log").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def test_action_list_lists_registry():
    result = runner.invoke(app, ["action", "list"])
    assert result.exit_code == 0
    for name in ("clear_fault", "restart_service", "rollback_release"):
        assert name in result.output


def test_action_run_unknown_denied_and_audited(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    result = runner.invoke(app, ["action", "run", "deploy_to_prod"])
    assert result.exit_code == 0
    assert "白名单外" in result.output
    assert read_last_audit(tmp_path)["decision"] == "denied"
    assert read_last_audit(tmp_path)["action"] == "deploy_to_prod"


def test_action_run_dry_run_no_effect(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    FaultState().activate("cpu_spike", duration_minutes=30)
    result = runner.invoke(
        app, ["action", "run", "clear_fault", "--arg", "name=cpu_spike", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "dry-run" in result.output
    assert FaultState().is_active("cpu_spike") is True


def test_action_run_safe_executes(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    FaultState().activate("cpu_spike", duration_minutes=30)
    result = runner.invoke(app, ["action", "run", "clear_fault", "--arg", "name=cpu_spike"])
    assert result.exit_code == 0
    assert "cleared" in result.output
    assert FaultState().is_active("cpu_spike") is False


def test_action_run_sensitive_interactive_deny(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    result = runner.invoke(
        app, ["action", "run", "rollback_release", "--arg", "service=demo-app"], input="n\n"
    )
    assert result.exit_code == 0
    assert "未获人工确认" in result.output
    assert read_last_audit(tmp_path)["decision"] == "denied"


def test_action_run_sensitive_yes_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    result = runner.invoke(
        app, ["action", "run", "rollback_release", "--arg", "service=demo-app", "--yes"]
    )
    assert result.exit_code == 0
    assert "simulated" in result.output
    assert read_last_audit(tmp_path)["decision"] == "executed"


def test_audit_show_prints_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    runner.invoke(app, ["action", "run", "clear_fault", "--arg", "name=cpu_spike"])
    result = runner.invoke(app, ["audit", "show"])
    assert result.exit_code == 0
    assert "executed" in result.output
