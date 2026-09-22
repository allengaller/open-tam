"""Tests for M9: Web UI 评测标签页（eval_runs 落库 + /api/evals 列表/详情）。"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from open_tam.eval import EvalReport, EvalRun, persist_eval_report
from open_tam.persistence.database import Database, reset_database
from open_tam.persistence.repositories import EvalRunRecord, EvalRunRepository
from open_tam.web.app import create_app


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_BASE_DIR", str(tmp_path))
    reset_database()
    d = Database(tmp_path / "test.db")
    d.connect()
    d.migrate()
    yield d
    d.close()
    reset_database()


def _report(label="fake", hit=True, steps=3):
    run = EvalRun(fault="cpu_spike", root_cause="低效正则导致 CPU 飙升" if hit else None,
                  keyword_hit=hit, confidence="high", steps=steps, elapsed_s=1.5,
                  evidence_sufficiency=0.8)
    return EvalReport(model_label=label, runs=[run])


def _record(rid, created_at, label="fake", hit_rate=1.0):
    return EvalRunRecord(
        id=rid, model_label=label, total=1, located_rate=1.0, hit_rate=hit_rate,
        avg_steps=3.0, avg_elapsed_s=1.5, avg_evidence_sufficiency=0.8,
        runs=[{"fault": "cpu_spike", "keyword_hit": True, "steps": 3}],
        report_path=f"/tmp/{rid}.md", created_at=created_at)


def test_eval_run_repository_round_trip(db):
    repo = EvalRunRepository(db)
    repo.create(_record("r1", "2026-09-22T10:00:00"))
    got = repo.get_by_id("r1")
    assert got is not None
    assert got.runs == [{"fault": "cpu_spike", "keyword_hit": True, "steps": 3}]
    assert got.model_label == "fake"


def test_persist_eval_report(db):
    rid = persist_eval_report(db, _report(), "/tmp/x.md")
    rec = EvalRunRepository(db).get_by_id(rid)
    assert rec is not None
    assert rec.model_label == "fake"
    assert rec.total == 1
    assert abs(rec.hit_rate - 1.0) < 1e-9
    assert rec.runs[0]["fault"] == "cpu_spike"
    assert rec.report_path == "/tmp/x.md"


def test_migration_v1_to_v2(tmp_path):
    d = Database(tmp_path / "old.db")
    d.connect()
    d._migrate_v1()
    d._set_schema_version(1)
    d.migrate()
    tables = {r[0] for r in d._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "eval_runs" in tables
    d.close()
    reset_database()


async def test_evals_list_empty(db):
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/evals")
    assert r.status_code == 200
    assert r.json() == {"evals": []}


async def test_evals_list_newest_first(db):
    repo = EvalRunRepository(db)
    repo.create(_record("old", "2026-09-22T10:00:00", label="qwen-plus", hit_rate=0.75))
    repo.create(_record("new", "2026-09-22T11:00:00", label="qwen-max", hit_rate=1.0))
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/evals")
    assert r.status_code == 200
    evals = r.json()["evals"]
    assert [e["id"] for e in evals] == ["new", "old"]
    assert evals[0]["model_label"] == "qwen-max"
    assert evals[0]["hit_rate"] == 1.0
    assert "runs" not in evals[0]


async def test_evals_detail_returns_runs(db):
    repo = EvalRunRepository(db)
    repo.create(_record("r1", "2026-09-22T10:00:00"))
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/evals/r1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "r1"
    assert body["runs"] == [{"fault": "cpu_spike", "keyword_hit": True, "steps": 3}]


async def test_evals_detail_unknown_404(db):
    app = create_app(db=db, auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/evals/nope")
    assert r.status_code == 404
