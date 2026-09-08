"""SLS 日志服务 MCP server — GetLogs 封装。

工具签名与 mock-logs-mcp-server 完全一致：
    query_logs(service, start, end, level?, keyword?) -> list[LogRecord]

环境变量：
    ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET / ALIYUN_REGION
    ALIYUN_SLS_PROJECT / ALIYUN_SLS_LOGSTORE
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime


def _server_command() -> tuple[str, list[str]]:
    return sys.executable, ["-m", "open_tam.mcp_servers.aliyun_logs_server"]


try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package required. Run: uv add mcp", file=sys.stderr)
    raise

_server = FastMCP("aliyun-logs")


@_server.tool()
def query_logs(
    service: str,
    start: str,
    end: str,
    level: str | None = None,
    keyword: str | None = None,
) -> str:
    """查询 SLS 日志。签名与 mock 一致。"""
    access_key_id = os.environ.get("ALIYUN_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("ALIYUN_ACCESS_KEY_SECRET", "")
    project = os.environ.get("ALIYUN_SLS_PROJECT", "")
    logstore = os.environ.get("ALIYUN_SLS_LOGSTORE", "")
    region = os.environ.get("ALIYUN_REGION", "cn-hangzhou")

    if not all([access_key_id, access_key_secret, project, logstore]):
        return json.dumps([], ensure_ascii=False)

    try:
        from aliyun.log import LogClient, GetLogsRequest

        endpoint = f"{region}.log.aliyuncs.com"
        client = LogClient(endpoint, access_key_id, access_key_secret)

        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)

        query_parts = [f"service: {service}"]
        if level:
            query_parts.append(f"level: {level.upper()}")
        if keyword:
            query_parts.append(keyword)
        query = " AND ".join(query_parts)

        request = GetLogsRequest(
            project=project,
            logstore=logstore,
            from_time=int(start_dt.timestamp()),
            to_time=int(end_dt.timestamp()),
            query=query,
            line=100,
        )
        response = client.get_logs(request)

        records = [
            {
                "ts": log.get("__time__", start),
                "level": log.get("level", "INFO").upper(),
                "message": log.get("message", log.get("content", "")),
            }
            for log in response.get_logs()
        ]
        return json.dumps(records, ensure_ascii=False)
    except ImportError:
        return json.dumps([], ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


if __name__ == "__main__":
    _server.run()
