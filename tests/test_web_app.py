import json

import pytest
from httpx import ASGITransport, AsyncClient

from open_tam.web.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "traces"))
    return create_app()


async def test_post_investigation_invalid_alert_422(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": {"bad": 1}})
    assert r.status_code == 422


async def test_post_investigation_fake_streams_to_done(app):
    from open_tam.faults import FaultState
    FaultState().activate("cpu_spike", duration_minutes=30)
    alert = {"alert_name": "CPU使用率过高", "service": "demo-app",
             "metric": "cpu_usage", "threshold": 80, "current_value": 92.5}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": alert, "fake": True})
        assert r.status_code == 202
        inv_id = r.json()["id"]

        kinds: list[str] = []
        async with c.stream("GET", f"/api/investigations/{inv_id}/events") as s:
            assert s.status_code == 200
            assert s.headers["content-type"].startswith("text/event-stream")
            async for line in s.aiter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[len("data:"):].strip())
                kinds.append(event["kind"])
                if event["kind"] in ("done", "error"):
                    break

    assert kinds[0] == "alert_received"
    assert "tool_call" in kinds and "observation" in kinds and "final" in kinds
    assert kinds[-1] == "done"


async def test_events_unknown_id_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/investigations/nope/events")
    assert r.status_code == 404


async def test_faults_list_and_activate(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/faults")
        assert r.status_code == 200
        names = [f["name"] for f in r.json()["faults"]]
        assert "cpu_spike" in names

        r = await c.post("/api/faults/cpu_spike/activate")
        assert r.status_code == 200 and r.json()["activated"] == "cpu_spike"

        from open_tam.faults import FaultState
        assert FaultState().is_active("cpu_spike")

        r = await c.post("/api/faults/nope/activate")
        assert r.status_code == 404


async def test_index_served(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert "open-tam" in r.text