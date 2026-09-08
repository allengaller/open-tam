from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from open_tam.models import AlertEvent


def generate_id() -> str:
    return uuid4().hex[:12]


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SEVERITY_MAP = {
    "critical": "critical",
    "crITICAL": "critical",
    "1": "critical",
    "P1": "critical",
    "warning": "warning",
    "WARN": "warning",
    "warn": "warning",
    "2": "warning",
    "P2": "warning",
    "info": "info",
    "INFO": "info",
    "3": "info",
    "4": "info",
    "P3": "info",
    "P4": "info",
}


def map_severity(raw: str) -> str:
    normalized = str(raw).strip().lower()
    _LOWER_MAP = {k.lower(): v for k, v in _SEVERITY_MAP.items()}
    return _LOWER_MAP.get(normalized, "warning")


def from_cms_alert(payload: dict) -> AlertEvent:
    """阿里云云监控 CMS 告警格式 → AlertEvent。"""
    dimensions = payload.get("dimensions", {})
    if isinstance(dimensions, str):
        import json
        try:
            dimensions = json.loads(dimensions)
        except (json.JSONDecodeError, TypeError):
            dimensions = {}

    alert_time = payload.get("alertTime")
    if isinstance(alert_time, (int, float)):
        triggered_at = datetime.fromtimestamp(alert_time / 1000, tz=timezone.utc)
    elif isinstance(alert_time, str):
        triggered_at = datetime.fromisoformat(alert_time)
    else:
        triggered_at = datetime.now(timezone.utc)

    return AlertEvent(
        alert_id=str(payload.get("alertId", generate_id())),
        alert_name=str(payload.get("alertName", "unknown")),
        severity=map_severity(payload.get("level", "WARN")),
        service=str(dimensions.get("instanceId", dimensions.get("service", "unknown"))),
        metric=str(payload.get("metricName", "")),
        threshold=float(payload.get("threshold", 0)),
        current_value=float(payload.get("curValue", 0)),
        triggered_at=triggered_at,
        labels={str(k): str(v) for k, v in dimensions.items()},
    )


def from_alertmanager(payload: dict) -> AlertEvent:
    """Prometheus AlertManager 告警格式 → AlertEvent。"""
    alerts = payload.get("alerts", [])
    if not alerts:
        raise ValueError("AlertManager payload has no alerts")
    alert = alerts[0]
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    starts_at = alert.get("startsAt")
    if isinstance(starts_at, str):
        triggered_at = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    else:
        triggered_at = datetime.now(timezone.utc)

    return AlertEvent(
        alert_id=str(alert.get("fingerprint", generate_id())),
        alert_name=str(labels.get("alertname", "unknown")),
        severity=map_severity(labels.get("severity", "warning")),
        service=str(labels.get("service", labels.get("instance", "unknown"))),
        metric=str(labels.get("metric", "")),
        threshold=float(labels.get("threshold", 0)),
        current_value=float(labels.get("value", 0)),
        triggered_at=triggered_at,
        labels={
            **{str(k): str(v) for k, v in labels.items()},
            "summary": annotations.get("summary", ""),
            "description": annotations.get("description", ""),
        },
    )


def detect_format(payload: dict) -> str:
    """检测告警格式：cms / alertmanager / native。"""
    if "alerts" in payload and isinstance(payload.get("alerts"), list):
        return "alertmanager"
    if "alertName" in payload and "metricName" in payload:
        return "cms"
    return "native"


def adapt_alert(payload: dict) -> AlertEvent:
    """自动检测格式并适配为 AlertEvent。"""
    fmt = detect_format(payload)
    if fmt == "alertmanager":
        return from_alertmanager(payload)
    if fmt == "cms":
        return from_cms_alert(payload)
    return AlertEvent.model_validate(payload)
