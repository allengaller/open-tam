from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.models import MetricPoint


def generate_series(
    metric: str,
    service: str,
    start: datetime,
    end: datetime,
    step_seconds: int = 60,
    seed: int = 42,
    state: FaultState | None = None,
    region: str = "cn-hangzhou",
) -> list[MetricPoint]:
    mode = next((m for m in FAULT_MODES.values() if m.metric == metric and m.service == service), None)
    fault_window = state.window(mode.name) if (state and mode) else None
    fault_region = state.region_of(mode.name) if (state and mode and fault_window) else None

    rng = random.Random(seed)
    points: list[MetricPoint] = []
    ts = start
    while ts <= end:
        base = (mode.baseline_mid if mode else 30.0) + 8 * math.sin(ts.timestamp() / 600)
        value = base + rng.uniform(-3, 3)
        region_hit = fault_region is None or fault_region == region
        if fault_window and region_hit and fault_window[0] <= ts <= fault_window[1]:
            value = mode.spike_value + rng.uniform(-2, 2)
        points.append(MetricPoint(ts=ts, value=round(max(0.0, value), 2)))
        ts += timedelta(seconds=step_seconds)
    return points
