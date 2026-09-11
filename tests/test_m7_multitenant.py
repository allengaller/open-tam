"""Tests for M7: 多租户与生产化."""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from open_tam.auth.apikey import generate_api_key, hash_api_key, verify_api_key
from open_tam.auth.roles import Role, has_permission
from open_tam.notifications.dingtalk import DingTalkNotifier
from open_tam.notifications.dispatcher import (
    NotificationDispatcher,
    NotificationEvent,
    NotificationType,
)
from open_tam.notifications.feishu import FeishuNotifier
from open_tam.notifications.slack import SlackNotifier
from open_tam.persistence.database import Database, get_database, reset_database
from open_tam.persistence.repositories import (
    AlertRecord,
    AlertRepository,
    AuditEntry,
    AuditRepository,
    InvestigationRecord,
    InvestigationRepository,
    UserRecord,
    UserRepository,
)


class TestApiKey:
    def test_generate_api_key_format(self):
        key = generate_api_key()
        assert key.startswith("ot_")
        assert len(key) > 20

    def test_hash_and_verify(self):
        key = generate_api_key()
        hashed = hash_api_key(key)
        assert verify_api_key(key, hashed)
        assert not verify_api_key("wrong_key", hashed)

    def test_hash_deterministic(self):
        key = "test_key"
        h1 = hash_api_key(key)
        h2 = hash_api_key(key)
        assert h1 == h2


class TestRoles:
    def test_admin_has_all_permissions(self):
        assert has_permission(Role.ADMIN, "read")
        assert has_permission(Role.ADMIN, "write")
        assert has_permission(Role.ADMIN, "investigate")
        assert has_permission(Role.ADMIN, "manage_users")

    def test_operator_limited(self):
        assert has_permission(Role.OPERATOR, "read")
        assert has_permission(Role.OPERATOR, "investigate")
        assert not has_permission(Role.OPERATOR, "manage_users")

    def test_viewer_readonly(self):
        assert has_permission(Role.VIEWER, "read")
        assert not has_permission(Role.VIEWER, "write")
        assert not has_permission(Role.VIEWER, "investigate")

    def test_string_role(self):
        assert has_permission("admin", "read")
        assert not has_permission("invalid_role", "read")


class TestDatabase:
    def setup_method(self):
        reset_database()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"

    def teardown_method(self):
        reset_database()
        self.tmp.cleanup()

    def test_create_and_migrate(self):
        db = Database(self.db_path)
        db.connect()
        db.migrate()
        assert self.db_path.exists()
        db.close()

    def test_get_database_singleton(self):
        db1 = get_database(self.db_path)
        db2 = get_database()
        assert db1 is db2
        reset_database()

    def test_tables_created(self):
        db = Database(self.db_path)
        db.connect()
        db.migrate()
        tables = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r[0] for r in tables}
        assert "users" in table_names
        assert "investigations" in table_names
        assert "alerts" in table_names
        assert "audit_entries" in table_names
        db.close()


class TestUserRepository:
    def setup_method(self):
        reset_database()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.connect()
        self.db.migrate()
        self.repo = UserRepository(self.db)

    def teardown_method(self):
        self.db.close()
        reset_database()
        self.tmp.cleanup()

    def test_create_and_get(self):
        user = UserRecord(
            id="u1", username="alice",
            api_key_hash=hash_api_key("key1"),
            role="admin",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self.repo.create(user)
        fetched = self.repo.get_by_id("u1")
        assert fetched is not None
        assert fetched.username == "alice"
        assert fetched.role == "admin"

    def test_get_by_username(self):
        user = UserRecord(
            id="u2", username="bob",
            api_key_hash=hash_api_key("key2"),
            role="viewer",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self.repo.create(user)
        fetched = self.repo.get_by_username("bob")
        assert fetched is not None
        assert fetched.id == "u2"

    def test_list_all(self):
        for i in range(3):
            self.repo.create(UserRecord(
                id=f"u{i}", username=f"user{i}",
                api_key_hash=hash_api_key(f"key{i}"),
                role="viewer",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            ))
        users = self.repo.list_all()
        assert len(users) == 3

    def test_delete(self):
        user = UserRecord(
            id="u_del", username="del_user",
            api_key_hash=hash_api_key("key"),
            role="viewer",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self.repo.create(user)
        assert self.repo.delete("u_del")
        assert self.repo.get_by_id("u_del") is None


class TestInvestigationRepository:
    def setup_method(self):
        reset_database()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.connect()
        self.db.migrate()
        self.repo = InvestigationRepository(self.db)
        self.user_repo = UserRepository(self.db)
        self.user_repo.create(UserRecord(
            id="u1", username="testuser",
            api_key_hash=hash_api_key("key"),
            role="viewer",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        ))

    def teardown_method(self):
        self.db.close()
        reset_database()
        self.tmp.cleanup()

    def test_create_and_get(self):
        inv = InvestigationRecord(
            id="inv1", alert_id="alert1", user_id="u1",
            status="pending", root_cause=None, confidence=None,
            report_path=None, trace_path=None,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self.repo.create(inv)
        fetched = self.repo.get_by_id("inv1")
        assert fetched is not None
        assert fetched.status == "pending"

    def test_update_status(self):
        inv = InvestigationRecord(
            id="inv2", alert_id="alert2", user_id="u1",
            status="pending", root_cause=None, confidence=None,
            report_path=None, trace_path=None,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self.repo.create(inv)
        self.repo.update_status("inv2", "completed", root_cause="CPU spike", confidence="high")
        fetched = self.repo.get_by_id("inv2")
        assert fetched.status == "completed"
        assert fetched.root_cause == "CPU spike"

    def test_list_by_user(self):
        for i in range(3):
            self.repo.create(InvestigationRecord(
                id=f"inv{i}", alert_id=f"alert{i}", user_id="u1",
                status="pending", root_cause=None, confidence=None,
                report_path=None, trace_path=None,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            ))
        invs = self.repo.list_by_user("u1")
        assert len(invs) == 3


class TestAlertRepository:
    def setup_method(self):
        reset_database()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.connect()
        self.db.migrate()
        self.repo = AlertRepository(self.db)

    def teardown_method(self):
        self.db.close()
        reset_database()
        self.tmp.cleanup()

    def test_create_and_get(self):
        alert = AlertRecord(
            id="a1", alert_name="CPU高", service="demo-app",
            metric="cpu_usage", severity="warning",
            payload={"value": 92},
            created_at=datetime.now().isoformat(),
        )
        self.repo.create(alert)
        fetched = self.repo.get_by_id("a1")
        assert fetched is not None
        assert fetched.service == "demo-app"
        assert fetched.payload["value"] == 92


class TestAuditRepository:
    def setup_method(self):
        reset_database()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.connect()
        self.db.migrate()
        self.repo = AuditRepository(self.db)

    def teardown_method(self):
        self.db.close()
        reset_database()
        self.tmp.cleanup()

    def test_create_and_list(self):
        entry = AuditEntry(
            id=0, action="restart_service", actor="agent",
            params={"service": "demo-app"}, result="success",
            dry_run=False, created_at=datetime.now().isoformat(),
        )
        self.repo.create(entry)
        entries = self.repo.list_all()
        assert len(entries) == 1
        assert entries[0].action == "restart_service"


class TestNotifications:
    def test_dispatcher_with_no_notifiers(self):
        dispatcher = NotificationDispatcher()
        event = NotificationEvent(
            type=NotificationType.INVESTIGATION_COMPLETE,
            title="Test", content="Test content",
        )
        results = dispatcher.dispatch(event)
        assert results == []

    def test_dingtalk_empty_webhook(self):
        notifier = DingTalkNotifier("")
        event = NotificationEvent(
            type=NotificationType.INVESTIGATION_COMPLETE,
            title="Test", content="Test",
        )
        assert notifier.send(event) is False

    def test_feishu_empty_webhook(self):
        notifier = FeishuNotifier("")
        event = NotificationEvent(
            type=NotificationType.INVESTIGATION_COMPLETE,
            title="Test", content="Test",
        )
        assert notifier.send(event) is False

    def test_slack_empty_webhook(self):
        notifier = SlackNotifier("")
        event = NotificationEvent(
            type=NotificationType.INVESTIGATION_COMPLETE,
            title="Test", content="Test",
        )
        assert notifier.send(event) is False


class TestConfigM7:
    def test_settings_has_m7_fields(self):
        from open_tam.config import Settings
        settings = Settings.load()
        assert hasattr(settings, "database_url")
        assert hasattr(settings, "auth_enabled")
        assert hasattr(settings, "notify_dingtalk_webhook")
