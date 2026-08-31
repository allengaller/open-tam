import json
from datetime import datetime, timedelta

from typer.testing import CliRunner

from open_tam.cli import app

runner = CliRunner()


def test_serve_command_registered():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output and "--port" in result.output


def test_metrics_query_returns_points(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    now = datetime.now().replace(second=0, microsecond=0)
    result = runner.invoke(
        app,
        [
            "metrics", "query",
            "--metric", "cpu_usage",
            "--service", "demo-app",
            "--start", now.isoformat(),
            "--end", (now + timedelta(minutes=3)).isoformat(),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "cpu_usage" in result.output and "ts" in result.output


def test_fault_inject_and_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    r1 = runner.invoke(app, ["fault", "inject", "cpu_spike"])
    assert r1.exit_code == 0, r1.output
    assert json.loads((tmp_path / "fault_state.json").read_text())["cpu_spike"]
    r2 = runner.invoke(app, ["fault", "clear", "cpu_spike"])
    assert r2.exit_code == 0, r2.output
    assert json.loads((tmp_path / "fault_state.json").read_text()) == {}


def test_metrics_query_via_mcp_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    now = datetime.now().replace(second=0, microsecond=0)
    result = runner.invoke(
        app,
        [
            "metrics", "query", "--transport", "mcp",
            "--metric", "cpu_usage",
            "--service", "demo-app",
            "--start", now.isoformat(),
            "--end", (now + timedelta(minutes=2)).isoformat(),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "value" in result.output


def test_logs_query_via_mcp_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    now = datetime.now().replace(second=0, microsecond=0)
    result = runner.invoke(
        app,
        [
            "logs", "query", "--transport", "mcp",
            "--service", "demo-app",
            "--start", now.isoformat(),
            "--end", (now + timedelta(minutes=2)).isoformat(),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "INFO" in result.output
