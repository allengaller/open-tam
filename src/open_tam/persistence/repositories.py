"""Repository classes for database entities."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from open_tam.persistence.database import Database


@dataclass
class UserRecord:
    id: str
    username: str
    api_key_hash: str
    role: str
    created_at: str
    updated_at: str


@dataclass
class InvestigationRecord:
    id: str
    alert_id: str
    user_id: str | None
    status: str
    root_cause: str | None
    confidence: str | None
    report_path: str | None
    trace_path: str | None
    created_at: str
    updated_at: str


@dataclass
class AlertRecord:
    id: str
    alert_name: str
    service: str
    metric: str
    severity: str
    payload: dict[str, Any]
    created_at: str


@dataclass
class AuditEntry:
    id: int
    action: str
    actor: str
    params: dict[str, Any] | None
    result: str | None
    dry_run: bool
    created_at: str


@dataclass
class EvalRunRecord:
    id: str
    model_label: str
    total: int
    located_rate: float
    hit_rate: float
    avg_steps: float
    avg_elapsed_s: float
    avg_evidence_sufficiency: float
    runs: list[dict[str, Any]]
    report_path: str | None
    created_at: str


class UserRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, user: UserRecord) -> None:
        assert self.db._conn is not None
        self.db._conn.execute(
            """INSERT INTO users (id, username, api_key_hash, role, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user.id, user.username, user.api_key_hash, user.role,
             user.created_at, user.updated_at),
        )
        self.db._conn.commit()

    def get_by_id(self, user_id: str) -> UserRecord | None:
        assert self.db._conn is not None
        row = self.db._conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return UserRecord(**dict(row)) if row else None

    def get_by_username(self, username: str) -> UserRecord | None:
        assert self.db._conn is not None
        row = self.db._conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return UserRecord(**dict(row)) if row else None

    def list_all(self) -> list[UserRecord]:
        assert self.db._conn is not None
        rows = self.db._conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC"
        ).fetchall()
        return [UserRecord(**dict(r)) for r in rows]

    def delete(self, user_id: str) -> bool:
        assert self.db._conn is not None
        cursor = self.db._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.db._conn.commit()
        return cursor.rowcount > 0


class InvestigationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, inv: InvestigationRecord) -> None:
        assert self.db._conn is not None
        self.db._conn.execute(
            """INSERT INTO investigations
               (id, alert_id, user_id, status, root_cause, confidence,
                report_path, trace_path, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (inv.id, inv.alert_id, inv.user_id, inv.status, inv.root_cause,
             inv.confidence, inv.report_path, inv.trace_path,
             inv.created_at, inv.updated_at),
        )
        self.db._conn.commit()

    def get_by_id(self, inv_id: str) -> InvestigationRecord | None:
        assert self.db._conn is not None
        row = self.db._conn.execute(
            "SELECT * FROM investigations WHERE id = ?", (inv_id,)
        ).fetchone()
        return InvestigationRecord(**dict(row)) if row else None

    def update_status(
        self, inv_id: str, status: str,
        root_cause: str | None = None, confidence: str | None = None,
        report_path: str | None = None, trace_path: str | None = None,
    ) -> None:
        assert self.db._conn is not None
        now = datetime.now().isoformat()
        self.db._conn.execute(
            """UPDATE investigations
               SET status = ?, root_cause = ?, confidence = ?,
                   report_path = ?, trace_path = ?, updated_at = ?
               WHERE id = ?""",
            (status, root_cause, confidence, report_path, trace_path, now, inv_id),
        )
        self.db._conn.commit()

    def list_by_user(self, user_id: str, limit: int = 50) -> list[InvestigationRecord]:
        assert self.db._conn is not None
        rows = self.db._conn.execute(
            "SELECT * FROM investigations WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [InvestigationRecord(**dict(r)) for r in rows]

    def list_all(self, limit: int = 50) -> list[InvestigationRecord]:
        assert self.db._conn is not None
        rows = self.db._conn.execute(
            "SELECT * FROM investigations ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [InvestigationRecord(**dict(r)) for r in rows]


class AlertRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, alert: AlertRecord) -> None:
        assert self.db._conn is not None
        self.db._conn.execute(
            """INSERT INTO alerts (id, alert_name, service, metric, severity, payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (alert.id, alert.alert_name, alert.service, alert.metric,
             alert.severity, json.dumps(alert.payload, ensure_ascii=False),
             alert.created_at),
        )
        self.db._conn.commit()

    def get_by_id(self, alert_id: str) -> AlertRecord | None:
        assert self.db._conn is not None
        row = self.db._conn.execute(
            "SELECT * FROM alerts WHERE id = ?", (alert_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return AlertRecord(**d)

    def list_by_service(self, service: str, limit: int = 50) -> list[AlertRecord]:
        assert self.db._conn is not None
        rows = self.db._conn.execute(
            "SELECT * FROM alerts WHERE service = ? ORDER BY created_at DESC LIMIT ?",
            (service, limit),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            results.append(AlertRecord(**d))
        return results


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, entry: AuditEntry) -> int:
        assert self.db._conn is not None
        cursor = self.db._conn.execute(
            """INSERT INTO audit_entries (action, actor, params, result, dry_run, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entry.action, entry.actor,
             json.dumps(entry.params, ensure_ascii=False) if entry.params else None,
             entry.result, int(entry.dry_run), entry.created_at),
        )
        self.db._conn.commit()
        return cursor.lastrowid

    def list_by_actor(self, actor: str, limit: int = 50) -> list[AuditEntry]:
        assert self.db._conn is not None
        rows = self.db._conn.execute(
            "SELECT * FROM audit_entries WHERE actor = ? ORDER BY created_at DESC LIMIT ?",
            (actor, limit),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"]) if d["params"] else None
            d["dry_run"] = bool(d["dry_run"])
            results.append(AuditEntry(**d))
        return results

    def list_all(self, limit: int = 50) -> list[AuditEntry]:
        assert self.db._conn is not None
        rows = self.db._conn.execute(
            "SELECT * FROM audit_entries ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"]) if d["params"] else None
            d["dry_run"] = bool(d["dry_run"])
            results.append(AuditEntry(**d))
        return results


class EvalRunRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, rec: EvalRunRecord) -> None:
        assert self.db._conn is not None
        self.db._conn.execute(
            """INSERT INTO eval_runs
               (id, model_label, total, located_rate, hit_rate, avg_steps,
                avg_elapsed_s, avg_evidence_sufficiency, runs_json, report_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rec.id, rec.model_label, rec.total, rec.located_rate, rec.hit_rate,
             rec.avg_steps, rec.avg_elapsed_s, rec.avg_evidence_sufficiency,
             json.dumps(rec.runs, ensure_ascii=False), rec.report_path, rec.created_at),
        )
        self.db._conn.commit()

    def get_by_id(self, run_id: str) -> EvalRunRecord | None:
        assert self.db._conn is not None
        row = self.db._conn.execute(
            "SELECT * FROM eval_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["runs"] = json.loads(d.pop("runs_json"))
        return EvalRunRecord(**d)

    def list_all(self, limit: int = 20) -> list[EvalRunRecord]:
        assert self.db._conn is not None
        rows = self.db._conn.execute(
            "SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["runs"] = json.loads(d.pop("runs_json"))
            results.append(EvalRunRecord(**d))
        return results
