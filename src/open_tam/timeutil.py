from __future__ import annotations

from datetime import datetime


def parse_iso_local(value: str) -> datetime:
    """解析 ISO 8601 时间并归一为本地 naive datetime。

    LLM 生成的时间可能带 Z 或 UTC 偏移（"…T00:05:00Z"），而 mock 数据窗口、
    故障窗口均为本地 naive 时间；aware/naive 混比会直接 TypeError。
    """
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt
