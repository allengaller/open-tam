from datetime import datetime

import pytest
from pydantic import ValidationError

from open_tam.models import AlertEvent, MetricPoint, MetricSeries


def test_alert_event_from_valid_raw():
    raw = {
        "alert_name": "CPU使用率过高",
        "service": "demo-app",
        "metric": "cpu_usage",
        "threshold": 80.0,
        "current_value": 92.5,
        "triggered_at": "2026-08-28T10:00:00",
    }
    alert = AlertEvent.model_validate(raw)
    assert alert.alert_id
    assert alert.severity == "warning"
    assert alert.triggered_at == datetime.fromisoformat("2026-08-28T10:00:00")


def test_alert_event_maps_cloud_monitor_aliases():
    raw = {
        "alertName": "CPU使用率过高",
        "alertId": "abc123",
        "metricName": "cpu_usage",
        "service": "demo-app",
        "threshold": 80.0,
        "current_value": 92.5,
    }
    alert = AlertEvent.model_validate(raw)
    assert alert.alert_name == "CPU使用率过高"
    assert alert.alert_id == "abc123"
    assert alert.metric == "cpu_usage"


def test_alert_event_rejects_bad_severity():
    with pytest.raises(ValidationError):
        AlertEvent.model_validate(
            {
                "alert_name": "x",
                "service": "demo-app",
                "metric": "cpu_usage",
                "threshold": 1,
                "current_value": 2,
                "severity": "urgent",
            }
        )


def test_metric_series_roundtrip():
    s = MetricSeries(
        metric="cpu_usage",
        service="demo-app",
        points=[MetricPoint(ts=datetime(2026, 8, 28, 10, 0), value=30.0)],
    )
    assert s.points[0].value == 30.0
