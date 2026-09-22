"""Tests for M7-A2: 排查落库（alerts/investigations）+ 角色权限。"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from open_tam.auth.apikey import generate_api_key, hash_api_key
from open_tam.persistence.database import Database, reset_database
from open_tam.persistence.repositories import (
    AlertRepository,
    InvestigationRepository,
    UserRecord,
    UserRepository,
)
from open_tam.web.app import create_app


@pytest.fixture
def db(tmp_path):
    reset_database()
    db = Database(tmp_path / "test.db")
    db.connect()
    db.migrate()
    yield db
    db.close()
    reset_database()


def _user(db, user_id, role):
    key = generate_api_key()
    UserRepository(db).create(UserRecord(
        id=user_id, username=user_id, api_key_hash=hash_api_key(key),
        role=role, created_at="2026-09-22T00:00:00", updated_at="2026-09-22T00:00:00",
    ))
    return key


async def _drain_to_done(client, inv_id):
    async with client.stream("GET", f"/api/investigations/{inv_id}/events") as s:
        async for line in s.aiter_lines():
            if line.startswith("data:"):
                event = json.loads(line[len("data:"):].strip())
                if event["kind"] in ("done", "error"):
                    return event


ALERT = {"alert_name": "CPU使用率过高", "service": "demo-app",
         "metric": "cpu_usage", "threshold": 80, "current_value": 92.5}


async def test_post_persists_alert_and_investigation(db):
    from open_tam.faults import FaultState
    FaultState().activate("cpu_spike", duration_minutes=30)
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": ALERT, "fake": True})
        assert r.status_code == 202
        inv_id = r.json()["id"]
        event = await _drain_to_done(c, inv_id)
        assert event["kind"] == "done"

    alerts = AlertRepository(db)
    invs = InvestigationRepository(db)
    assert len(alerts.list_by_service("demo-app")) == 1
    rec = invs.get_by_id(inv_id)
    assert rec is not None
    assert rec.status == "done"
    assert rec.root_cause
    assert rec.report_path


async def test_investigation_error_updates_status(db, monkeypatch):
    import open_tam.web.service as service_mod
    app = create_app(db=db, auth_enabled=False)

    def _boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(service_mod, "run_investigation", _boom)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": ALERT, "fake": True})
        inv_id = r.json()["id"]
        event = await _drain_to_done(c, inv_id)
        assert event["kind"] == "error"

    rec = InvestigationRepository(db).get_by_id(inv_id)
    assert rec is not None and rec.status == "error"


async def test_investigation_bound_to_user(db):
    from open_tam.faults import FaultState
    FaultState().activate("cpu_spike", duration_minutes=30)
    key = _user(db, "u-op", "operator")
    app = create_app(db=db, auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": ALERT, "fake": True},
                         headers={"X-API-Key": key})
        assert r.status_code == 202
        inv_id = r.json()["id"]
        await _drain_to_done(c, inv_id)

    rec = InvestigationRepository(db).get_by_id(inv_id)
    assert rec is not None and rec.user_id == "u-op"


async def test_viewer_cannot_investigate(db):
    key = _user(db, "u-viewer", "viewer")
    app = create_app(db=db, auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": ALERT, "fake": True},
                         headers={"X-API-Key": key})
    assert r.status_code == 403


async def test_operator_can_investigate(db):
    from open_tam.faults import FaultState
    FaultState().activate("cpu_spike", duration_minutes=30)
    key = _user(db, "u-op2", "operator")
    app = create_app(db=db, auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": ALERT, "fake": True},
                         headers={"X-API-Key": key})
    assert r.status_code == 202
