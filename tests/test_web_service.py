import asyncio
import time

from open_tam.models import AlertEvent
from open_tam.web.events import InvestigationHub
from open_tam.web.service import start_investigation


def _alert() -> AlertEvent:
    return AlertEvent(alert_name="CPU使用率过高", service="demo-app",
                      metric="cpu_usage", threshold=80, current_value=92.5)


def _wait_status(hub: InvestigationHub, inv_id: str, *statuses: str,
                 timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = hub.get(inv_id).status
        if s in statuses:
            return s
        time.sleep(0.05)
    raise AssertionError(f"status did not reach {statuses} within {timeout}s")


def test_start_investigation_fake_runs_to_done(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "traces"))
    from open_tam.faults import FaultState
    FaultState().activate("cpu_spike", duration_minutes=30)

    hub = InvestigationHub()
    loop = asyncio.new_event_loop()

    inv = start_investigation(hub, _alert(), fake=True, transport="inline", loop=loop)
    assert inv.status == "running"
    _wait_status(hub, inv.id, "done", "error")

    assert inv.status == "done"
    kinds = [e["kind"] for e in inv.events]
    assert kinds[0] == "alert_received"
    assert "tool_call" in kinds and "observation" in kinds and "final" in kinds
    assert kinds[-1] == "done"
    done = inv.events[-1]
    assert done["root_cause"] and done["report_path"].endswith(".md")
    reports = list((tmp_path / "reports").glob("*.md"))
    assert len(reports) == 1
    loop.close()


def test_start_investigation_error_marks_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "traces"))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    hub = InvestigationHub()
    loop = asyncio.new_event_loop()
    inv = start_investigation(hub, _alert(), fake=False, transport="inline", loop=loop)
    _wait_status(hub, inv.id, "done", "error")

    assert inv.status == "error"
    assert inv.events[-1]["kind"] == "error"
    assert "DASHSCOPE_API_KEY" in inv.events[-1]["error"]
    loop.close()