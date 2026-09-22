"""SQLite persistence layer with simple version-based migration."""
from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

CURRENT_SCHEMA_VERSION = 1


class Database:
    """SQLite database with WAL mode and simple migration."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        # 排查在后台线程回写状态，连接需跨线程使用（WAL 模式下安全）
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        assert self._conn is not None, "Database not connected"
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def migrate(self) -> None:
        assert self._conn is not None, "Database not connected"
        current = self._get_schema_version()
        if current < 1:
            self._migrate_v1()
        self._set_schema_version(CURRENT_SCHEMA_VERSION)

    def _get_schema_version(self) -> int:
        assert self._conn is not None
        try:
            row = self._conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _set_schema_version(self, version: int) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
            (version,),
        )
        self._conn.commit()

    def _migrate_v1(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY,
                version INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                api_key_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS investigations (
                id TEXT PRIMARY KEY,
                alert_id TEXT NOT NULL,
                user_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                root_cause TEXT,
                confidence TEXT,
                report_path TEXT,
                trace_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                alert_name TEXT NOT NULL,
                service TEXT NOT NULL,
                metric TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'warning',
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                params TEXT,
                result TEXT,
                dry_run INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skill_index (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                alert_pattern TEXT NOT NULL,
                confidence REAL NOT NULL,
                file_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_investigations_user ON investigations(user_id);
            CREATE INDEX IF NOT EXISTS idx_investigations_status ON investigations(status);
            CREATE INDEX IF NOT EXISTS idx_alerts_service ON alerts(service);
            CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_entries(actor);
        """)
        self._conn.commit()


_db_instance: Database | None = None


def get_database(db_path: str | Path | None = None) -> Database:
    global _db_instance
    if _db_instance is None:
        if db_path is None:
            raise ValueError("db_path required on first call")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _db_instance = Database(db_path)
        _db_instance.connect()
        _db_instance.migrate()
    return _db_instance


def reset_database() -> None:
    global _db_instance
    if _db_instance:
        _db_instance.close()
        _db_instance = None
