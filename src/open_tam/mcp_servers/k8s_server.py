"""Mock K8s MCP server for K8sGPT-style diagnostics."""
from __future__ import annotations

import json
import sys

from open_tam.faults import FaultState


def _query_k8s_events(namespace: str, pod_name: str | None = None, kind: str | None = None) -> str:
    events = []
    state = FaultState()
    if state.is_active("pod_crash_loop"):
        events.append({
            "type": "Warning",
            "reason": "BackOff",
            "message": "Back-off restarting failed container",
            "object": f"pod/{pod_name or 'demo-app-xxx'}",
        })
        events.append({
            "type": "Warning",
            "reason": "CrashLoopBackOff",
            "message": "Container crashed with exit code 1",
            "object": f"pod/{pod_name or 'demo-app-xxx'}",
        })
    if state.is_active("node_not_ready"):
        events.append({
            "type": "Warning",
            "reason": "NodeNotReady",
            "message": "Node condition Ready is False",
            "object": "node/worker-1",
        })
    if state.is_active("dns_failure"):
        events.append({
            "type": "Warning",
            "reason": "DNSLookupFailed",
            "message": "DNS lookup failed for external service",
            "object": f"pod/{pod_name or 'demo-app-xxx'}",
        })
    if kind:
        events = [e for e in events if kind.lower() in e.get("object", "").lower()]
    return json.dumps(events, ensure_ascii=False)


def _query_pod_status(namespace: str, pod_name: str) -> str:
    state = FaultState()
    status = {
        "name": pod_name,
        "namespace": namespace,
        "phase": "Running",
        "restart_count": 0,
        "ready": True,
    }
    if state.is_active("pod_crash_loop"):
        status["phase"] = "CrashLoopBackOff"
        status["restart_count"] = 5
        status["ready"] = False
    return json.dumps(status, ensure_ascii=False)


def _query_node_status(node_name: str) -> str:
    state = FaultState()
    status = {
        "name": node_name,
        "ready": True,
        "conditions": [{"type": "Ready", "status": "True"}],
    }
    if state.is_active("node_not_ready"):
        status["ready"] = False
        status["conditions"] = [{"type": "Ready", "status": "False"}]
    return json.dumps(status, ensure_ascii=False)


def _analyze_with_k8sgpt(namespace: str, pod_name: str | None = None) -> str:
    state = FaultState()
    findings = []
    if state.is_active("pod_crash_loop"):
        findings.append({
            "type": "CrashLoopBackOff",
            "severity": "critical",
            "message": "Pod is in CrashLoopBackOff state",
            "suggestion": "Check container logs and liveness probe configuration",
        })
    if state.is_active("node_not_ready"):
        findings.append({
            "type": "NodeNotReady",
            "severity": "critical",
            "message": "Node is in NotReady state",
            "suggestion": "Check kubelet logs and node resource usage",
        })
    if state.is_active("dns_failure"):
        findings.append({
            "type": "DNSFailure",
            "severity": "high",
            "message": "DNS resolution failing for pods",
            "suggestion": "Check CoreDNS pod status and configuration",
        })
    if state.is_active("cert_expiry"):
        findings.append({
            "type": "CertExpiry",
            "severity": "high",
            "message": "TLS certificate is expired or about to expire",
            "suggestion": "Renew certificate or configure cert-manager for auto-renewal",
        })
    return json.dumps(findings, ensure_ascii=False)


TOOLS = [
    {
        "name": "query_k8s_events",
        "description": "查询 K8s 事件（Pod/Node 相关）",
        "parameters": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "命名空间"},
                "pod_name": {"type": "string", "description": "Pod 名称（可选）"},
                "kind": {"type": "string", "description": "资源类型过滤（可选）"},
            },
            "required": ["namespace"],
        },
    },
    {
        "name": "query_pod_status",
        "description": "查询 Pod 状态",
        "parameters": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "命名空间"},
                "pod_name": {"type": "string", "description": "Pod 名称"},
            },
            "required": ["namespace", "pod_name"],
        },
    },
    {
        "name": "query_node_status",
        "description": "查询 Node 状态",
        "parameters": {
            "type": "object",
            "properties": {
                "node_name": {"type": "string", "description": "Node 名称"},
            },
            "required": ["node_name"],
        },
    },
    {
        "name": "analyze_with_k8sgpt",
        "description": "使用 K8sGPT 自动分析 K8s 问题",
        "parameters": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "命名空间"},
                "pod_name": {"type": "string", "description": "Pod 名称（可选）"},
            },
            "required": ["namespace"],
        },
    },
]


def _handle_tool_call(name: str, arguments: dict) -> str:
    if name == "query_k8s_events":
        return _query_k8s_events(
            arguments["namespace"],
            arguments.get("pod_name"),
            arguments.get("kind"),
        )
    if name == "query_pod_status":
        return _query_pod_status(arguments["namespace"], arguments["pod_name"])
    if name == "query_node_status":
        return _query_node_status(arguments["node_name"])
    if name == "analyze_with_k8sgpt":
        return _analyze_with_k8sgpt(
            arguments["namespace"],
            arguments.get("pod_name"),
        )
    return json.dumps({"error": f"unknown tool: {name}"})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if request.get("method") == "tools/list":
            result = {"tools": TOOLS}
        elif request.get("method") == "tools/call":
            params = request.get("params", {})
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            output = _handle_tool_call(name, arguments)
            result = {"content": [{"type": "text", "text": output}]}
        else:
            result = {"error": "method not supported"}
        response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()


def _server_command() -> tuple[str, list[str]]:
    return (sys.executable, ["-m", "open_tam.mcp_servers.k8s_server"])
