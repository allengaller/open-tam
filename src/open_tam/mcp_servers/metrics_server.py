from __future__ import annotations

import json
import sys
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from open_tam.faults import FaultState
from open_tam.timeutil import parse_iso_local
from open_tam.mock.metrics_data import generate_series

mcp = FastMCP("mock-metrics")


@mcp.tool()
def query_metrics(metric: str, service: str, start: str, end: str) -> str:
    """查询某服务某指标的时序数据。start/end 为 ISO 8601 时间，返回 JSON 数组字符串 [{ts, value}]。"""
    points = generate_series(
        metric=metric,
        service=service,
        start=parse_iso_local(start),
        end=parse_iso_local(end),
        state=FaultState(),
    )
    return json.dumps(
        [{"ts": p.ts.isoformat(), "value": p.value} for p in points],
        ensure_ascii=False,
    )


def _server_command() -> tuple[str, list[str]]:
    return sys.executable, ["-m", "open_tam.mcp_servers.metrics_server"]


if __name__ == "__main__":
    mcp.run()
