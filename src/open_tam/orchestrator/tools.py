from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Protocol

from open_tam.faults import FaultState
from open_tam.mock.metrics_data import generate_series

QUERY_METRICS_SPEC = {
    "name": "query_metrics",
    "description": "查询某服务某指标的时序数据，用于确认/排除异常。参数 start/end 为 ISO 8601 时间。",
    "parameters": {
        "type": "object",
        "properties": {
            "metric": {"type": "string", "description": "指标名，如 cpu_usage"},
            "service": {"type": "string", "description": "服务名，如 demo-app"},
            "start": {"type": "string", "description": "起始时间 ISO 8601"},
            "end": {"type": "string", "description": "结束时间 ISO 8601"},
        },
        "required": ["metric", "service", "start", "end"],
    },
}

ALL_TOOLS: list[dict] = [QUERY_METRICS_SPEC]


def query_metrics_inline(metric: str, service: str, start: str, end: str) -> str:
    points = generate_series(
        metric=metric,
        service=service,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        state=FaultState(),
    )
    return json.dumps(
        [{"ts": p.ts.isoformat(), "value": p.value} for p in points],
        ensure_ascii=False,
    )


class Backend(Protocol):
    def execute(self, name: str, args: dict) -> str: ...


class InlineBackend:
    """直连本地实现——与 MCP server 共享同一函数，测试与生产同路径。"""

    def execute(self, name: str, args: dict) -> str:
        if name == "query_metrics":
            return query_metrics_inline(**args)
        return json.dumps({"error": f"unknown tool: {name}"})


class McpStdioBackend:
    """通过 MCP stdio 子进程调用 mock-metrics server（架构演示路径）。"""

    def execute(self, name: str, args: dict) -> str:
        import asyncio

        return asyncio.run(self._call(name, args))

    async def _call(self, name: str, args: dict) -> str:
        import subprocess

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        from open_tam.mcp_servers.metrics_server import _server_command

        command, cmd_args = _server_command()
        params = StdioServerParameters(
            command=command, args=cmd_args, env={**os.environ}
        )
        # CliRunner 捕获的 stderr 无 fileno，errlog 必须指向 DEVNULL
        async with stdio_client(params, errlog=subprocess.DEVNULL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
        return result.content[0].text
