from typer.testing import CliRunner

from open_tam.cli import app

runner = CliRunner()


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "traces"))


def test_eval_fake_reports_hits(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    from open_tam.config import Settings
    from open_tam.eval import run_eval

    report = run_eval(["cpu_spike", "oom"], settings=Settings.load(), runs=1, fake=True)
    assert [r.fault for r in report.runs] == ["cpu_spike", "oom"]
    assert report.total == 2
    assert report.located_rate == 1.0
    assert report.hit_rate == 1.0
    assert all(r.steps >= 2 for r in report.runs)
    assert all(r.confidence == "high" for r in report.runs)
    # 每轮结束后故障状态被清理，不污染下一次评测
    from open_tam.faults import FaultState
    assert not FaultState().is_active("cpu_spike")
    assert not FaultState().is_active("oom")


def test_eval_report_written(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    from open_tam.config import Settings
    from open_tam.eval import run_eval, write_eval_report

    report = run_eval(["slow_query"], settings=Settings.load(), runs=1, fake=True)
    path = write_eval_report(report, tmp_path / "reports")
    assert path.name.startswith("eval-") and path.suffix == ".md"
    text = path.read_text(encoding="utf-8")
    assert "slow_query" in text
    assert "命中率" in text
    assert "fake" in text


def test_eval_cli_fake(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = runner.invoke(app, ["eval", "--fake", "--faults", "cpu_spike"])
    assert result.exit_code == 0, result.output
    assert "命中率" in result.output
    assert list((tmp_path / "reports").glob("eval-*.md"))


def test_eval_cli_unknown_fault(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = runner.invoke(app, ["eval", "--fake", "--faults", "nope"])
    assert result.exit_code != 0
    assert "未知故障模式" in result.output
