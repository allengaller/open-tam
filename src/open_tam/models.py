from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

SEVERITIES = {"critical", "warning", "info"}

# 云监控告警字段别名 -> AlertEvent 字段
ALIASES = {
    "alertName": "alert_name",
    "alertId": "alert_id",
    "metricName": "metric",
    "instanceId": "service",
}


class AlertEvent(BaseModel):
    alert_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    alert_name: str
    severity: str = "warning"
    service: str
    metric: str
    threshold: float
    current_value: float
    triggered_at: datetime = Field(default_factory=datetime.now)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, v: object) -> str:
        v = str(v).lower()
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(SEVERITIES)}, got {v!r}")
        return v

    @field_validator("labels", mode="before")
    @classmethod
    def _stringify_labels(cls, v: object) -> dict[str, str]:
        return {str(k): str(x) for k, x in dict(v).items()}

    @model_validator(mode="before")
    @classmethod
    def _map_aliases(cls, data: object) -> object:
        if isinstance(data, dict):
            data = {ALIASES.get(k, k): v for k, v in data.items()}
        return data


class MetricPoint(BaseModel):
    ts: datetime
    value: float


class MetricSeries(BaseModel):
    metric: str
    service: str
    points: list[MetricPoint] = Field(default_factory=list)
