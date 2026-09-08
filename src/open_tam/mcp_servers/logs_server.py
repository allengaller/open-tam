from __future__ import annotations

import json
import sys

from mcp.server.fastmcp import FastMCP

from open_tam.faults import FaultState
from open_tam.mock.logs_data import generate_logs
from open_tam.timeutil import parse_iso_local

mcp = FastMCP("mock-logs")


@mcp.tool()
def query_logs(service: str, start: str, end: str, level: str | None = None, keyword: str | None = None) -> str:
    """查询某服务的结构化日志。start/end 为 ISO 8601 时间；level 可选 INFO/WARN/ERROR；keyword 为消息子串（不区分大小写）。返回 JSON 数组字符串 [{ts, level, message}]。"""
    records = generate_logs(
        service=service,
        start=parse_iso_local(start),
        end=parse_iso_local(end),
        level=level,
        keyword=keyword,
        state=FaultState(),
    )
    return json.dumps(
        [{"ts": r.ts.isoformat(), "level": r.level, "message": r.message} for r in records],
        ensure_ascii=False,
    )


def _server_command() -> tuple[str, list[str]]:
    return sys.executable, ["-m", "open_tam.mcp_servers.logs_server"]


if __name__ == "__main__":
    mcp.run()
