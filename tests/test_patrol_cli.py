from typer.testing import CliRunner

from open_tam.cli import app

runner = CliRunner()


def test_patrol_run_creates_report(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    result = runner.invoke(app, ["patrol", "run"])
    assert result.exit_code == 0
    assert "patrol report" in result.output
    assert list((tmp_path / "reports").glob("patrol-*.md"))


def test_patrol_watch_runs_n_times(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    result = runner.invoke(app, ["patrol", "watch", "--every-min", "0", "--max-runs", "2"])
    assert result.exit_code == 0
    assert result.output.count("patrol report") == 2
