"""M5 tests: adapters, dedup, webhook signature, backend routing."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ── adapters ──────────────────────────────────────────────


class TestCmsAdapter:
    def test_basic_cms_payload(self):
        from open_tam.receiver.adapters import from_cms_alert

        payload = {
            "alertId": "cms-001",
            "alertName": "cpu_spike",
            "level": "CRITICAL",
            "metricName": "cpu_usage",
            "threshold": 80.0,
            "curValue": 92.5,
            "alertTime": 1700000000000,
            "dimensions": {"instanceId": "demo-app", "region": "cn-hangzhou"},
        }
        event = from_cms_alert(payload)
        assert event.alert_id == "cms-001"
        assert event.alert_name == "cpu_spike"
        assert event.severity == "critical"
        assert event.service == "demo-app"
        assert event.metric == "cpu_usage"
        assert event.threshold == 80.0
        assert event.current_value == 92.5
        assert event.labels["region"] == "cn-hangzhou"

    def test_cms_dimensions_as_string(self):
        from open_tam.receiver.adapters import from_cms_alert

        payload = {
            "alertName": "oom",
            "metricName": "memory_usage",
            "threshold": 90.0,
            "curValue": 95.0,
            "dimensions": '{"instanceId": "web-svc"}',
        }
        event = from_cms_alert(payload)
        assert event.service == "web-svc"

    def test_cms_severity_mapping(self):
        from open_tam.receiver.adapters import from_cms_alert, map_severity

        assert map_severity("CRITICAL") == "critical"
        assert map_severity("WARN") == "warning"
        assert map_severity("1") == "critical"
        assert map_severity("P2") == "warning"
        assert map_severity("unknown") == "warning"


class TestAlertManagerAdapter:
    def test_basic_alertmanager_payload(self):
        from open_tam.receiver.adapters import from_alertmanager

        payload = {
            "alerts": [
                {
                    "fingerprint": "am-001",
                    "labels": {
                        "alertname": "HighCPU",
                        "severity": "critical",
                        "service": "api-gateway",
                        "metric": "cpu_usage",
                    },
                    "annotations": {"summary": "CPU is high"},
                    "startsAt": "2026-09-08T10:00:00Z",
                }
            ]
        }
        event = from_alertmanager(payload)
        assert event.alert_id == "am-001"
        assert event.alert_name == "HighCPU"
        assert event.severity == "critical"
        assert event.service == "api-gateway"
        assert event.labels["summary"] == "CPU is high"

    def test_empty_alertmanager_raises(self):
        from open_tam.receiver.adapters import from_alertmanager

        with pytest.raises(ValueError, match="no alerts"):
            from_alertmanager({"alerts": []})


class TestDetectFormat:
    def test_detect_cms(self):
        from open_tam.receiver.adapters import detect_format

        assert detect_format({"alertName": "x", "metricName": "y"}) == "cms"

    def test_detect_alertmanager(self):
        from open_tam.receiver.adapters import detect_format

        assert detect_format({"alerts": []}) == "alertmanager"

    def test_detect_native(self):
        from open_tam.receiver.adapters import detect_format

        assert detect_format({"alert_name": "x", "service": "y"}) == "native"

    def test_adapt_routes_correctly(self):
        from open_tam.receiver.adapters import adapt_alert

        cms = adapt_alert({"alertName": "cpu", "metricName": "cpu_usage", "service": "app", "threshold": 0, "current_value": 0})
        assert cms.alert_name == "cpu"

        am = adapt_alert({"alerts": [{"labels": {"alertname": "test", "service": "svc"}, "startsAt": "2026-01-01T00:00:00Z"}]})
        assert am.alert_name == "test"


# ── dedup ─────────────────────────────────────────────────


class TestAlertDedup:
    def test_first_call_passes(self):
        from open_tam.receiver.dedup import AlertDedup

        dedup = AlertDedup(window_seconds=300)
        assert dedup.should_process("cpu_spike", "demo-app") is True

    def test_second_call_within_window_suppressed(self):
        from open_tam.receiver.dedup import AlertDedup

        dedup = AlertDedup(window_seconds=300)
        dedup.should_process("cpu_spike", "demo-app")
        assert dedup.should_process("cpu_spike", "demo-app") is False

    def test_different_alert_passes(self):
        from open_tam.receiver.dedup import AlertDedup

        dedup = AlertDedup(window_seconds=300)
        assert dedup.should_process("cpu_spike", "demo-app") is True
        assert dedup.should_process("oom", "demo-app") is True

    def test_persist_and_reload(self, tmp_path):
        from open_tam.receiver.dedup import AlertDedup

        path = tmp_path / "dedup.json"
        dedup1 = AlertDedup(window_seconds=300, persist_path=path)
        dedup1.should_process("cpu_spike", "demo-app")
        assert path.exists()

        dedup2 = AlertDedup(window_seconds=300, persist_path=path)
        assert dedup2.should_process("cpu_spike", "demo-app") is False

    def test_corrupt_persist_fallback(self, tmp_path):
        from open_tam.receiver.dedup import AlertDedup

        path = tmp_path / "dedup.json"
        path.write_text("not json", encoding="utf-8")
        dedup = AlertDedup(window_seconds=300, persist_path=path)
        assert dedup.should_process("cpu_spike", "demo-app") is True


# ── webhook ───────────────────────────────────────────────


class TestWebhookSignature:
    def test_valid_signature(self):
        from open_tam.receiver.webhook import verify_signature

        body = b'{"alertName": "test"}'
        secret = "my-secret"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_signature(body, sig, secret) is True

    def test_invalid_signature(self):
        from open_tam.receiver.webhook import verify_signature

        body = b'{"alertName": "test"}'
        assert verify_signature(body, "wrong", "my-secret") is False

    def test_empty_secret_always_passes(self):
        from open_tam.receiver.webhook import verify_signature

        assert verify_signature(b"body", "", "") is True


class TestWebhookApp:
    def _make_app(self, tmp_path, **kwargs):
        from open_tam.receiver.webhook import create_webhook_app

        return create_webhook_app(
            inbox_dir=tmp_path / "inbox",
            state_dir=tmp_path / "state",
            **kwargs,
        )

    def test_native_alert_accepted(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._make_app(tmp_path)
        client = TestClient(app)
        payload = {"alert_name": "cpu_spike", "service": "demo-app", "metric": "cpu", "threshold": 80, "current_value": 92}
        resp = client.post("/alerts", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["dedup"] is False
        assert "alert_id" in data

    def test_cms_format_accepted(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._make_app(tmp_path)
        client = TestClient(app)
        payload = {
            "alertName": "cpu_spike",
            "metricName": "cpu_usage",
            "threshold": 80,
            "curValue": 92,
            "dimensions": {"instanceId": "demo-app"},
        }
        resp = client.post("/alerts", json=payload)
        assert resp.status_code == 201
        assert resp.json()["dedup"] is False

    def test_dedup_suppresses_duplicate(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._make_app(tmp_path)
        client = TestClient(app)
        payload = {"alert_name": "cpu_spike", "service": "demo-app", "metric": "cpu", "threshold": 80, "current_value": 92}
        resp1 = client.post("/alerts", json=payload)
        assert resp1.json()["dedup"] is False
        resp2 = client.post("/alerts", json=payload)
        assert resp2.json()["dedup"] is True

    def test_signature_required_when_configured(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._make_app(tmp_path, webhook_secret="test-secret")
        client = TestClient(app)
        payload = {"alert_name": "cpu_spike", "service": "demo-app", "metric": "cpu", "threshold": 80, "current_value": 92}
        resp = client.post("/alerts", json=payload)
        assert resp.status_code == 401

    def test_valid_signature_passes(self, tmp_path):
        from fastapi.testclient import TestClient

        secret = "test-secret"
        app = self._make_app(tmp_path, webhook_secret=secret)
        client = TestClient(app)
        body = json.dumps({"alert_name": "cpu_spike", "service": "demo-app", "metric": "cpu", "threshold": 80, "current_value": 92}).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        resp = client.post("/alerts", content=body, headers={"X-Signature": sig, "Content-Type": "application/json"})
        assert resp.status_code == 201

    def test_invalid_json_rejected(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._make_app(tmp_path)
        client = TestClient(app)
        resp = client.post("/alerts", content=b"not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 422

    def test_health_endpoint(self, tmp_path):
        from fastapi.testclient import TestClient

        app = self._make_app(tmp_path)
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── backend routing ───────────────────────────────────────


class TestBackendRouting:
    def test_mcp_backend_default_routes_to_mock(self):
        from open_tam.orchestrator.tools import McpStdioBackend

        backend = McpStdioBackend()
        cmd, args = backend._resolve_command("query_metrics")
        assert "metrics_server" in args[1]
        assert "aliyun" not in args[1]

    def test_mcp_backend_aliyun_routes_to_aliyun(self):
        from open_tam.orchestrator.tools import McpStdioBackend

        backend = McpStdioBackend(metrics_backend="aliyun")
        cmd, args = backend._resolve_command("query_metrics")
        assert "aliyun_metrics_server" in args[1]

    def test_mcp_backend_logs_aliyun_routes_to_sls(self):
        from open_tam.orchestrator.tools import McpStdioBackend

        backend = McpStdioBackend(logs_backend="aliyun")
        cmd, args = backend._resolve_command("query_logs")
        assert "aliyun_logs_server" in args[1]

    def test_mcp_backend_logs_default_routes_to_mock(self):
        from open_tam.orchestrator.tools import McpStdioBackend

        backend = McpStdioBackend()
        cmd, args = backend._resolve_command("query_logs")
        assert "logs_server" in args[1]
        assert "aliyun" not in args[1]


# ── config ────────────────────────────────────────────────


class TestSettingsM5:
    def test_default_backends_are_mock(self):
        from open_tam.config import Settings

        s = Settings.load()
        assert s.metrics_backend == "mock"
        assert s.logs_backend == "mock"

    def test_aliyun_config_from_env(self, monkeypatch):
        from open_tam.config import Settings

        monkeypatch.setenv("OPEN_TAM_METRICS_BACKEND", "aliyun")
        monkeypatch.setenv("OPEN_TAM_LOGS_BACKEND", "aliyun")
        monkeypatch.setenv("OPEN_TAM_ALIYUN_REGION", "cn-shanghai")
        monkeypatch.setenv("OPEN_TAM_ALIYUN_SLS_PROJECT", "my-project")
        monkeypatch.setenv("OPEN_TAM_DEDUP_WINDOW_SECONDS", "600")
        monkeypatch.setenv("OPEN_TAM_WEBHOOK_SECRET", "s3cret")

        s = Settings.load()
        assert s.metrics_backend == "aliyun"
        assert s.logs_backend == "aliyun"
        assert s.aliyun_region == "cn-shanghai"
        assert s.aliyun_sls_project == "my-project"
        assert s.dedup_window_seconds == 600
        assert s.webhook_secret == "s3cret"

    def test_skills_dir_default(self):
        from open_tam.config import Settings

        s = Settings.load()
        assert str(s.skills_dir).endswith("skills")
