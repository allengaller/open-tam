from datetime import datetime

from open_tam.faults import FaultState
from open_tam.patrol import run_patrol


def test_patrol_clean_state_all_normal(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    now = datetime.now().replace(second=0, microsecond=0)
    path = run_patrol(tmp_path / "reports", now=now)
    text = path.read_text(encoding="utf-8")
    assert "检查项：" in text
    for mode in ("cpu_spike", "slow_query", "oom", "connection_pool_exhausted"):
        assert mode in text


def test_patrol_flags_injected_fault(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    FaultState().activate("cpu_spike", duration_minutes=30)
    now = datetime.now().replace(second=0, microsecond=0)
    path = run_patrol(tmp_path / "reports", now=now)
    text = path.read_text(encoding="utf-8")
    assert "异常" in text
    assert "cpu_spike" in text
    assert "open-tam investigate" in text


def test_patrol_report_filename_format(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    path = run_patrol(tmp_path / "reports", now=datetime(2026, 8, 31, 12, 0, 0))
    assert path.name == "patrol-20260831-120000.md"
