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
) -> list[MetricPoint]:
    mode = next((m for m in FAULT_MODES.values() if m.metric == metric and m.service == service), None)
    fault_window = state.window(mode.name) if (state and mode) else None

    rng = random.Random(seed)
    points: list[MetricPoint] = []
    ts = start
    while ts <= end:
        base = 30 + 8 * math.sin(ts.timestamp() / 600)
        value = base + rng.uniform(-3, 3)
        if fault_window and fault_window[0] <= ts <= fault_window[1]:
            value = mode.spike_value + rng.uniform(-2, 2)
        points.append(MetricPoint(ts=ts, value=round(max(0.0, min(100.0, value)), 2)))
        ts += timedelta(seconds=step_seconds)
    return points
