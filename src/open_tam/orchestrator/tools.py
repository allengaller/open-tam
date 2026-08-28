from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Protocol

from open_tam.faults import FaultState
from open_tam.mock.logs_data import generate_logs
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

QUERY_LOGS_SPEC = {
    "name": "query_logs",
    "description": "查询某服务的结构化日志，可按时间范围/级别/关键字过滤，用于获取异常现场证据。",
    "parameters": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "服务名，如 demo-app"},
            "start": {"type": "string", "description": "起始时间 ISO 8601"},
            "end": {"type": "string", "description": "结束时间 ISO 8601"},
            "level": {"type": "string", "description": "可选，INFO/WARN/ERROR"},
            "keyword": {"type": "string", "description": "可选，消息子串（不区分大小写）"},
        },
        "required": ["service", "start", "end"],
    },
}

ALL_TOOLS: list[dict] = [QUERY_METRICS_SPEC, QUERY_LOGS_SPEC]


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


def subprocess_env() -> dict[str, str]:
    """MCP 子进程环境：把 src 注入 PYTHONPATH，使子进程导入不依赖 editable .pth。"""
    env = {**os.environ}
    src = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


class InlineBackend:
    """直连本地实现——与 MCP server 共享同一函数，测试与生产同路径。"""

    def execute(self, name: str, args: dict) -> str:
        if name == "query_metrics":
            return query_metrics_inline(**args)
        if name == "query_logs":
            return query_logs_inline(**args)
        return json.dumps({"error": f"unknown tool: {name}"})


def query_logs_inline(service: str, start: str, end: str, level: str | None = None, keyword: str | None = None) -> str:
    records = generate_logs(
        service=service,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        level=level,
        keyword=keyword,
        state=FaultState(),
    )
    return json.dumps(
        [{"ts": r.ts.isoformat(), "level": r.level, "message": r.message} for r in records],
        ensure_ascii=False,
    )


class McpStdioBackend:
    """通过 MCP stdio 子进程调用 mock-metrics server（架构演示路径）。"""

    def execute(self, name: str, args: dict) -> str:
        import asyncio

        return asyncio.run(self._call(name, args))

    async def _call(self, name: str, args: dict) -> str:
        import subprocess

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        from open_tam.mcp_servers.logs_server import _server_command as logs_cmd
        from open_tam.mcp_servers.metrics_server import _server_command as metrics_cmd

        command, cmd_args = logs_cmd() if name == "query_logs" else metrics_cmd()
        params = StdioServerParameters(
            command=command, args=cmd_args, env=subprocess_env()
        )
        # CliRunner 捕获的 stderr 无 fileno，errlog 必须指向 DEVNULL
        async with stdio_client(params, errlog=subprocess.DEVNULL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
        return result.content[0].text

ASK_METRIC_AGENT_SPEC = {
    "name": "ask_metric_agent",
    "description": "向指标分析子 Agent 提问：确认异常是否存在、异常窗口与幅度。",
    "parameters": {
        "type": "object",
        "properties": {"question": {"type": "string", "description": "要分析的问题"}},
        "required": ["question"],
    },
}

ASK_LOG_AGENT_SPEC = {
    "name": "ask_log_agent",
    "description": "向日志检索子 Agent 提问：获取异常现场的日志证据。",
    "parameters": {
        "type": "object",
        "properties": {"question": {"type": "string", "description": "要检索的问题"}},
        "required": ["question"],
    },
}

ORCHESTRATOR_TOOLS: list[dict] = [ASK_METRIC_AGENT_SPEC, ASK_LOG_AGENT_SPEC]
