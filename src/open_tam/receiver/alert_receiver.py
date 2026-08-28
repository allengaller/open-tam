from __future__ import annotations

from open_tam.models import AlertEvent


def normalize_alert(raw: dict) -> AlertEvent:
    """把云监控风格告警 payload 标准化为 AlertEvent。非 dict 直接拒绝。"""
    if not isinstance(raw, dict):
        raise ValueError(f"alert payload must be a dict, got {type(raw).__name__}")
    return AlertEvent.model_validate(raw)
