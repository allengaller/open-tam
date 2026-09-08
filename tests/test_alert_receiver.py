import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from open_tam.receiver.alert_receiver import normalize_alert
from open_tam.receiver.webhook import create_webhook_app


def test_normalize_alert_happy_path():
    event = normalize_alert({
        "alert_name": "CPU使用率过高", "severity": "Critical",
        "service": "demo-app", "metric": "cpu_usage",
        "threshold": 80, "current_value": 92.5,
    })
    assert event.severity == "critical"
    assert event.alert_id


def test_normalize_alert_missing_field_raises():
    with pytest.raises(ValidationError):
        normalize_alert({"alert_name": "x"})


def test_normalize_alert_rejects_non_dict():
    with pytest.raises(ValueError):
        normalize_alert("not-a-dict")


def test_webhook_persists_alert(tmp_path):
    client = TestClient(create_webhook_app(inbox_dir=tmp_path / "inbox", state_dir=tmp_path / "state"))
    resp = client.post("/alerts", json={
        "alert_name": "CPU使用率过高", "service": "demo-app",
        "metric": "cpu_usage", "threshold": 80, "current_value": 92.5,
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["alert_id"]
    inbox = tmp_path / "inbox"
    files = list(inbox.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["alert_id"] == body["alert_id"]
