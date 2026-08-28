import json

from typer.testing import CliRunner

from open_tam.cli import app

runner = CliRunner()


def test_investigate_fake_writes_report(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    from open_tam.faults import FaultState
    FaultState().activate("cpu_spike", duration_minutes=30)

    alert_file = tmp_path / "alert.json"
    alert_file.write_text(json.dumps({
        "alert_name": "CPU使用率过高", "service": "demo-app",
        "metric": "cpu_usage", "threshold": 80, "current_value": 92.5,
    }), encoding="utf-8")

    result = runner.invoke(app, ["investigate", "--alert-file", str(alert_file), "--fake"])
    assert result.exit_code == 0, result.output
    reports = list((tmp_path / "reports").glob("*.md"))
    assert len(reports) == 1
    assert "## 结论摘要" in reports[0].read_text(encoding="utf-8")


def test_investigate_missing_file_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    result = runner.invoke(app, ["investigate", "--alert-file", str(tmp_path / "nope.json"), "--fake"])
    assert result.exit_code != 0
