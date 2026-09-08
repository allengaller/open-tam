"""alibabacloud-observability MCP server — CMS DescribeMetricData 封装。

工具签名与 mock-metrics-mcp-server 完全一致：
    query_metrics(metric, service, start, end) -> list[MetricPoint]

环境变量：
    ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET / ALIYUN_REGION
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime


def _server_command() -> tuple[str, list[str]]:
    return sys.executable, ["-m", "open_tam.mcp_servers.aliyun_metrics_server"]


try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package required. Run: uv add mcp", file=sys.stderr)
    raise

_server = FastMCP("aliyun-metrics")


def _get_client():
    """延迟初始化阿里云 CMS 客户端。"""
    try:
        from alibabacloud_cms20190101.client import Client
        from alibabacloud_tea_openapi.models import Config
    except ImportError:
        return None

    access_key_id = os.environ.get("ALIYUN_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("ALIYUN_ACCESS_KEY_SECRET", "")
    region = os.environ.get("ALIYUN_REGION", "cn-hangzhou")

    if not access_key_id or not access_key_secret:
        return None

    config = Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id=region,
        endpoint=f"metrics.{region}.aliyuncs.com",
    )
    return Client(config)


@_server.tool()
def query_metrics(metric: str, service: str, start: str, end: str) -> str:
    """查询 CMS 指标时序数据。签名与 mock 一致。"""
    client = _get_client()
    if client is None:
        return json.dumps([{"ts": start, "value": 0.0}], ensure_ascii=False)

    try:
        from alibabacloud_cms20190101.models import DescribeMetricDataRequest

        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)

        request = DescribeMetricDataRequest(
            namespace="acs_ecs_dashboard",
            metric_name=metric,
            dimensions=json.dumps([{"instanceId": service}]),
            start_time=str(int(start_dt.timestamp() * 1000)),
            end_time=str(int(end_dt.timestamp() * 1000)),
            period="60",
        )
        response = client.describe_metric_data(request)
        datapoints = json.loads(response.body.datapoints or "[]")

        points = [
            {
                "ts": datetime.fromtimestamp(dp["timestamp"] / 1000).isoformat(),
                "value": float(dp.get("Average", dp.get("Value", 0))),
            }
            for dp in datapoints
        ]
        return json.dumps(points, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


if __name__ == "__main__":
    _server.run()
