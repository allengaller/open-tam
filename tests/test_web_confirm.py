"""Tests for M7-B: 敏感操作 Web 确认（WebConfirmer + confirm 端点 + SSE 事件）。"""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from open_tam.persistence.database import Database, reset_database
from open_tam.web.app import create_app
from open_tam.web.service import WebConfirmer


def _sink():
    events = []
    return events.append, events


def test_web_confirmer_approved():
    sink, events = _sink()
    c = WebConfirmer(sink, timeout_seconds=2.0)
    result = {}

    def ask():
        result["approved"] = c.confirm("rollback_release", {"service": "demo-app"})

    t = threading.Thread(target=ask)
    t.start()
    while not events:
        pass
    assert events[0]["kind"] == "confirm_request"
    assert events[0]["action"] == "rollback_release"
    assert c.resolve(events[0]["request_id"], True)
    t.join(timeout=2)
    assert result["approved"] is True


def test_web_confirmer_denied():
    sink, events = _sink()
    c = WebConfirmer(sink, timeout_seconds=2.0)
    result = {}
    t = threading.Thread(target=lambda: result.update(approved=c.confirm("a", {})))
    t.start()
    while not events:
        pass
    c.resolve(events[0]["request_id"], False)
    t.join(timeout=2)
    assert result["approved"] is False


def test_web_confirmer_timeout():
    sink, _ = _sink()
    c = WebConfirmer(sink, timeout_seconds=0.2)
    assert c.confirm("a", {}) is False


def test_web_confirmer_wrong_request_id():
    sink, events = _sink()
    c = WebConfirmer(sink, timeout_seconds=2.0)
    t = threading.Thread(target=lambda: c.confirm("a", {}))
    t.start()
    while not events:
        pass
    assert c.resolve("nope", True) is False
    c.resolve(events[0]["request_id"], True)
    t.join(timeout=2)


ALERT = {"alert_name": "CPU使用率过高", "service": "demo-app",
         "metric": "cpu_usage", "threshold": 80, "current_value": 92.5}


@pytest.fixture
def db(tmp_path):
    reset_database()
    db = Database(tmp_path / "test.db")
    db.connect()
    db.migrate()
    yield db
    db.close()
    reset_database()


async def test_confirm_endpoint_end_to_end(db, tmp_path, monkeypatch):
    """ASGITransport 会攒完整响应体，SSE 无法中途交互；须起真 uvicorn 端口。"""
    import asyncio
    import socket

    import httpx
    import uvicorn

    import open_tam.web.service as service_mod
    from open_tam.faults import FaultState

    monkeypatch.setenv("OPEN_TAM_BASE_DIR", str(tmp_path))
    FaultState().activate("cpu_spike", duration_minutes=30)
    captured = {}

    def fake_run(alert, settings, *, fake, transport, trace, metric_trace,
                 log_trace, k8s_trace=None, confirmer=None):
        captured["confirmer"] = confirmer
        captured["approved"] = confirmer.confirm("rollback_release",
                                                 {"service": "demo-app"})
        return (SimpleNamespace(root_cause="rc", confidence="high",
                                evidence=[], actions=[]),
                "/tmp/report.md")

    monkeypatch.setattr(service_mod, "run_investigation", fake_run)
    app = create_app(db=db, auth_enabled=False)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "uvicorn failed to start"

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as c:
        r = await c.post("/api/investigations", json={"alert": ALERT, "fake": True})
        assert r.status_code == 202
        inv_id = r.json()["id"]

        final = None
        async with c.stream("GET", f"/api/investigations/{inv_id}/events") as s:
            assert s.status_code == 200
            async for line in s.aiter_lines():
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[len("data:"):].strip())
                if ev["kind"] == "confirm_request":
                    rr = await c.post(f"/api/investigations/{inv_id}/confirm",
                                      json={"request_id": ev["request_id"],
                                            "approved": True})
                    assert rr.status_code == 200
                if ev["kind"] in ("done", "error"):
                    final = ev
                    break
        server.should_exit = True

    assert captured["approved"] is True
    assert final is not None and final["kind"] == "done"


async def test_confirm_endpoint_unknown_inv_404(db):
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations/nope/confirm",
                         json={"request_id": "x", "approved": True})
    assert r.status_code == 404


async def test_confirm_endpoint_no_pending_409(db, monkeypatch):
    import open_tam.web.service as service_mod
    from open_tam.faults import FaultState

    FaultState().activate("cpu_spike", duration_minutes=30)

    def fake_run(alert, settings, **kw):
        return (SimpleNamespace(root_cause="rc", confidence="high",
                                evidence=[], actions=[]), "/tmp/report.md")

    monkeypatch.setattr(service_mod, "run_investigation", fake_run)
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": ALERT, "fake": True})
        inv_id = r.json()["id"]
        async with c.stream("GET", f"/api/investigations/{inv_id}/events") as s:
            async for line in s.aiter_lines():
                if line.startswith("data:"):
                    ev = json.loads(line[len("data:"):].strip())
                    if ev["kind"] in ("done", "error"):
                        break
        r = await c.post(f"/api/investigations/{inv_id}/confirm",
                         json={"request_id": "x", "approved": True})
    assert r.status_code == 409
