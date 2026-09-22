from __future__ import annotations

import random
import re
from datetime import datetime, timedelta

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.models import LogRecord

BASELINE_LOGS = [
    "GET /health 200 3ms",
    "GET /api/items 200 24ms",
    "GET /api/orders 200 41ms",
    "scheduled cleanup done",
    "cache refreshed",
]


def generate_logs(
    service: str,
    start: datetime,
    end: datetime,
    level: str | None = None,
    keyword: str | None = None,
    step_seconds: int = 60,
    seed: int = 42,
    state: FaultState | None = None,
    region: str = "cn-hangzhou",
) -> list[LogRecord]:
    rng = random.Random(seed)
    records: list[LogRecord] = []
    ts = start
    while ts <= end:
        records.append(LogRecord(
            ts=ts, level="INFO", service=service,
            message=rng.choice(BASELINE_LOGS),
        ))
        ts += timedelta(seconds=step_seconds)
    if state is not None:
        for mode in FAULT_MODES.values():
            if mode.service != service:
                continue
            win = state.window(mode.name)
            if not win:
                continue
            fault_region = state.region_of(mode.name)
            if fault_region and fault_region != region:
                continue
            t = max(win[0], start)
            while t <= min(win[1], end):
                records.append(LogRecord(
                    ts=t, level="ERROR", service=service,
                    message=mode.log_signature,
                ))
                t += timedelta(seconds=step_seconds)
    records.sort(key=lambda r: r.ts)
    if level:
        # LLM 可能传组合值（"ERROR/WARN"、"ERROR, WARN"），拆开匹配
        wanted = {lv.strip().upper() for lv in re.split(r"[,/、]", level) if lv.strip()}
        records = [r for r in records if r.level in wanted]
    if keyword:
        records = [r for r in records if keyword.lower() in r.message.lower()]
    return records
