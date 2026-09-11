"""Tests for M8: K8s 与基础设施排障."""
from __future__ import annotations

import json

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.orchestrator.agents import K8S_AGENT_PROMPT
from open_tam.orchestrator.tools import (
    ANALYZE_WITH_K8SGPT_SPEC,
    ASK_K8S_AGENT_SPEC,
    ORCHESTRATOR_TOOLS,
    QUERY_K8S_EVENTS_SPEC,
    QUERY_NODE_STATUS_SPEC,
    QUERY_POD_STATUS_SPEC,
)


class TestK8sFaultModes:
    def test_pod_crash_loop_exists(self):
        assert "pod_crash_loop" in FAULT_MODES
        mode = FAULT_MODES["pod_crash_loop"]
        assert mode.metric == "pod_restart_count"
        assert "CrashLoopBackOff" in mode.anomaly_desc

    def test_node_not_ready_exists(self):
        assert "node_not_ready" in FAULT_MODES
        mode = FAULT_MODES["node_not_ready"]
        assert mode.metric == "node_ready"

    def test_dns_failure_exists(self):
        assert "dns_failure" in FAULT_MODES
        mode = FAULT_MODES["dns_failure"]
        assert "DNS" in mode.root_cause

    def test_cert_expiry_exists(self):
        assert "cert_expiry" in FAULT_MODES
        mode = FAULT_MODES["cert_expiry"]
        assert "TLS" in mode.root_cause or "证书" in mode.root_cause


class TestK8sToolSpecs:
    def test_query_k8s_events_spec(self):
        assert QUERY_K8S_EVENTS_SPEC["name"] == "query_k8s_events"
        assert "namespace" in QUERY_K8S_EVENTS_SPEC["parameters"]["properties"]

    def test_query_pod_status_spec(self):
        assert QUERY_POD_STATUS_SPEC["name"] == "query_pod_status"
        assert "pod_name" in QUERY_POD_STATUS_SPEC["parameters"]["required"]

    def test_query_node_status_spec(self):
        assert QUERY_NODE_STATUS_SPEC["name"] == "query_node_status"

    def test_analyze_with_k8sgpt_spec(self):
        assert ANALYZE_WITH_K8SGPT_SPEC["name"] == "analyze_with_k8sgpt"

    def test_ask_k8s_agent_in_orchestrator_tools(self):
        tool_names = [t["name"] for t in ORCHESTRATOR_TOOLS]
        assert "ask_k8s_agent" in tool_names
        assert ASK_K8S_AGENT_SPEC["name"] == "ask_k8s_agent"


class TestK8sAgentPrompt:
    def test_prompt_mentions_k8s_tools(self):
        assert "query_pod_status" in K8S_AGENT_PROMPT
        assert "query_k8s_events" in K8S_AGENT_PROMPT
        assert "analyze_with_k8sgpt" in K8S_AGENT_PROMPT

    def test_prompt_mentions_k8s_concepts(self):
        assert "Pod" in K8S_AGENT_PROMPT or "pod" in K8S_AGENT_PROMPT
        assert "Node" in K8S_AGENT_PROMPT or "node" in K8S_AGENT_PROMPT


class TestK8sServer:
    def test_k8s_server_imports(self):
        from open_tam.mcp_servers.k8s_server import (
            TOOLS,
        )
        assert len(TOOLS) == 4

    def test_query_k8s_events_no_fault(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
        from open_tam.mcp_servers.k8s_server import _query_k8s_events
        result = json.loads(_query_k8s_events("default"))
        assert result == []

    def test_query_k8s_events_with_crash_loop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
        FaultState(tmp_path).activate("pod_crash_loop", duration_minutes=30)
        from open_tam.mcp_servers.k8s_server import _query_k8s_events
        result = json.loads(_query_k8s_events("default"))
        assert len(result) >= 1
        assert any("CrashLoopBackOff" in e.get("reason", "") for e in result)

    def test_query_pod_status_crash_loop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
        FaultState(tmp_path).activate("pod_crash_loop", duration_minutes=30)
        from open_tam.mcp_servers.k8s_server import _query_pod_status
        result = json.loads(_query_pod_status("default", "demo-app-xxx"))
        assert result["phase"] == "CrashLoopBackOff"
        assert result["restart_count"] > 0

    def test_query_node_status_not_ready(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
        FaultState(tmp_path).activate("node_not_ready", duration_minutes=30)
        from open_tam.mcp_servers.k8s_server import _query_node_status
        result = json.loads(_query_node_status("worker-1"))
        assert result["ready"] is False

    def test_analyze_with_k8sgpt_findings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
        FaultState(tmp_path).activate("pod_crash_loop", duration_minutes=30)
        from open_tam.mcp_servers.k8s_server import _analyze_with_k8sgpt
        result = json.loads(_analyze_with_k8sgpt("default"))
        assert len(result) >= 1
        assert result[0]["type"] == "CrashLoopBackOff"


class TestK8sBackendRouting:
    def test_mcp_backend_routes_k8s_tools(self):
        from open_tam.orchestrator.tools import McpStdioBackend
        backend = McpStdioBackend()
        command, args = backend._resolve_command("query_k8s_events")
        assert "k8s_server" in args[1]

    def test_mcp_backend_routes_pod_status(self):
        from open_tam.orchestrator.tools import McpStdioBackend
        backend = McpStdioBackend()
        command, args = backend._resolve_command("query_pod_status")
        assert "k8s_server" in args[1]

    def test_mcp_backend_routes_analyze(self):
        from open_tam.orchestrator.tools import McpStdioBackend
        backend = McpStdioBackend()
        command, args = backend._resolve_command("analyze_with_k8sgpt")
        assert "k8s_server" in args[1]
