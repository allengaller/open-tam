"""Tests for M7: create_app 挂载 AuthMiddleware（Web 认证）。"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from open_tam.auth.apikey import generate_api_key, hash_api_key
from open_tam.persistence.database import Database, reset_database
from open_tam.persistence.repositories import UserRecord, UserRepository
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


@pytest.fixture
def operator_key(db):
    key = generate_api_key()
    UserRepository(db).create(UserRecord(
        id="u-operator", username="alice", api_key_hash=hash_api_key(key),
        role="operator", created_at="2026-09-22T00:00:00", updated_at="2026-09-22T00:00:00",
    ))
    return key


async def test_auth_enabled_missing_key_401(db):
    app = create_app(db=db, auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/faults")
    assert r.status_code == 401


async def test_auth_enabled_invalid_key_401(db):
    app = create_app(db=db, auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/faults", headers={"X-API-Key": "ot_wrong"})
    assert r.status_code == 401


async def test_auth_enabled_valid_key_200(db, operator_key):
    app = create_app(db=db, auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/faults", headers={"X-API-Key": operator_key})
    assert r.status_code == 200


async def test_auth_enabled_bearer_key_200(db, operator_key):
    app = create_app(db=db, auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/faults",
                        headers={"Authorization": f"Bearer {operator_key}"})
    assert r.status_code == 200


async def test_index_public_when_auth_enabled(db):
    app = create_app(db=db, auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/")
    assert r.status_code == 200


async def test_auth_disabled_by_default_no_key_200(monkeypatch, tmp_path):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/faults")
    assert r.status_code == 200


async def test_auth_enabled_from_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_TAM_AUTH_ENABLED", "true")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/faults")
    assert r.status_code == 401
