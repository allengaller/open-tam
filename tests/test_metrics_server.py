import json
import sys
from datetime import datetime, timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from open_tam.orchestrator.tools import subprocess_env


async def test_stdio_roundtrip(tmp_path):
    now = datetime.now().replace(second=0, microsecond=0)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "open_tam.mcp_servers.metrics_server"],
        env={**subprocess_env(), "OPEN_TAM_STATE_DIR": str(tmp_path)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "query_metrics",
                {
                    "metric": "cpu_usage",
                    "service": "demo-app",
                    "start": now.isoformat(),
                    "end": (now + timedelta(minutes=5)).isoformat(),
                },
            )
    payload = json.loads(result.content[0].text)
    assert isinstance(payload, list) and len(payload) >= 5
    assert {"ts", "value"} <= set(payload[0].keys())
