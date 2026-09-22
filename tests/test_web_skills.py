"""Tests for M6: Web UI 知识库标签页（/api/skills 列表/详情/删除 + done 事件 skill_used）。"""
from __future__ import annotations

import json

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from open_tam.auth.apikey import generate_api_key, hash_api_key
from open_tam.persistence.database import Database, reset_database
from open_tam.persistence.repositories import UserRecord, UserRepository
from open_tam.skills.models import Skill
from open_tam.web.app import create_app


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_BASE_DIR", str(tmp_path))
    reset_database()
    db = Database(tmp_path / "test.db")
    db.connect()
    db.migrate()
    yield db
    db.close()
    reset_database()


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    monkeypatch.setenv("OPEN_TAM_SKILLS_DIR", str(d))
    return d


def _skill_yaml(skills_dir, skill_id, name, confidence, alert_pattern="CPU*"):
    skills_dir.mkdir(parents=True, exist_ok=True)
    s = Skill(id=skill_id, name=name, alert_pattern=alert_pattern,
              confidence=confidence, description="从历史排查提取",
              root_cause_hints=["低效正则"], created_from="traces/x.json")
    path = skills_dir / f"{skill_id}.yaml"
    path.write_text(yaml.dump(s.model_dump(), allow_unicode=True), encoding="utf-8")


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


async def test_skills_list_empty(db, skills_dir):
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/skills")
    assert r.status_code == 200
    assert r.json() == {"skills": []}


async def test_skills_list_sorted_by_confidence(db, skills_dir):
    _skill_yaml(skills_dir, "s-low", "低置信", 0.4)
    _skill_yaml(skills_dir, "s-high", "高置信", 0.9)
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/skills")
    assert r.status_code == 200
    skills = r.json()["skills"]
    assert [s["id"] for s in skills] == ["s-high", "s-low"]
    assert set(skills[0]) >= {"id", "name", "alert_pattern", "confidence", "description"}


async def test_skill_detail(db, skills_dir):
    _skill_yaml(skills_dir, "s1", "CPU 排查经验", 0.8)
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/skills/s1")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "CPU 排查经验"
    assert body["root_cause_hints"] == ["低效正则"]
    assert body["created_from"] == "traces/x.json"
    assert "steps" in body


async def test_skill_detail_unknown_404(db, skills_dir):
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/skills/nope")
    assert r.status_code == 404


async def test_skill_delete_removes_file(db, skills_dir):
    _skill_yaml(skills_dir, "s1", "CPU 排查经验", 0.8)
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete("/api/skills/s1")
        assert r.status_code == 200
        assert not (skills_dir / "s1.yaml").exists()
        r = await c.get("/api/skills")
        assert r.json() == {"skills": []}


async def test_skill_delete_unknown_404(db, skills_dir):
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.delete("/api/skills/nope")
    assert r.status_code == 404


async def test_viewer_can_read_but_not_delete(db, skills_dir):
    _skill_yaml(skills_dir, "s1", "CPU 排查经验", 0.8)
    viewer_key = _user(db, "u-viewer", "viewer")
    op_key = _user(db, "u-op", "operator")
    admin_key = _user(db, "u-admin", "admin")
    app = create_app(db=db, auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/skills", headers={"X-API-Key": viewer_key})
        assert r.status_code == 200

        r = await c.delete("/api/skills/s1", headers={"X-API-Key": viewer_key})
        assert r.status_code == 403
        r = await c.delete("/api/skills/s1", headers={"X-API-Key": op_key})
        assert r.status_code == 403
        assert (skills_dir / "s1.yaml").exists()

        r = await c.delete("/api/skills/s1", headers={"X-API-Key": admin_key})
        assert r.status_code == 200
        assert not (skills_dir / "s1.yaml").exists()


async def test_done_event_carries_skill_used(db, skills_dir):
    from open_tam.faults import FaultState
    FaultState().activate("cpu_spike", duration_minutes=30)
    _skill_yaml(skills_dir, "s1", "CPU 排查经验", 0.8)
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": ALERT, "fake": True})
        inv_id = r.json()["id"]
        event = await _drain_to_done(c, inv_id)
    assert event["kind"] == "done"
    assert event["skill_used"] == {"name": "CPU 排查经验", "confidence": 0.8}


async def test_done_event_without_skill_is_none(db, skills_dir):
    from open_tam.faults import FaultState
    FaultState().activate("cpu_spike", duration_minutes=30)
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/investigations", json={"alert": ALERT, "fake": True})
        inv_id = r.json()["id"]
        event = await _drain_to_done(c, inv_id)
    assert event["kind"] == "done"
    assert event["skill_used"] is None
