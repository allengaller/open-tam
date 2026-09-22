"""Tests for M10: 跨集群/跨区域排查（region 维度故障 + MultiRegionBackend fan-out 聚合）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from open_tam.config import Settings
from open_tam.faults import FaultState
from open_tam.mock.logs_data import generate_logs
from open_tam.mock.metrics_data import generate_series
from open_tam.orchestrator.tools import InlineBackend, MultiRegionBackend


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    return FaultState(tmp_path)


def test_fault_region_isolated(state):
    state.activate("cpu_spike", duration_minutes=30, region="cn-hangzhou")
    now = datetime.now()
    assert state.is_active("cpu_spike", now=now, region="cn-hangzhou") is True
    assert state.is_active("cpu_spike", now=now, region="cn-shanghai") is False
    # region=None 的查询不过滤（兼容旧调用）
    assert state.is_active("cpu_spike", now=now) is True


def test_fault_without_region_hits_all_regions(state):
    state.activate("cpu_spike", duration_minutes=30)
    now = datetime.now()
    assert state.is_active("cpu_spike", now=now, region="cn-hangzhou") is True
    assert state.is_active("cpu_spike", now=now, region="cn-shanghai") is True


def test_series_region_aware(state):
    state.activate("cpu_spike", duration_minutes=30, region="cn-hangzhou")
    now = datetime.now()
    common = dict(metric="cpu_usage", service="demo-app",
                  start=now - timedelta(minutes=5), end=now + timedelta(minutes=5),
                  state=state)
    hz = [p.value for p in generate_series(region="cn-hangzhou", **common)]
    sh = [p.value for p in generate_series(region="cn-shanghai", **common)]
    assert max(hz) > 90
    assert max(sh) < 45


def test_series_without_region_unchanged(state):
    state.activate("cpu_spike", duration_minutes=30)
    now = datetime.now()
    common = dict(metric="cpu_usage", service="demo-app",
                  start=now - timedelta(minutes=5), end=now + timedelta(minutes=5),
                  state=state)
    assert max(p.value for p in generate_series(region="cn-shanghai", **common)) > 90
    # 不传 region 默认主区域，全局故障仍生效
    assert max(p.value for p in generate_series(**common)) > 90


def test_logs_region_aware(state):
    state.activate("cpu_spike", duration_minutes=30, region="cn-hangzhou")
    now = datetime.now()
    common = dict(service="demo-app", start=now - timedelta(minutes=5),
                  end=now + timedelta(minutes=5), state=state)
    hz = generate_logs(region="cn-hangzhou", **common)
    sh = generate_logs(region="cn-shanghai", **common)
    assert any("CPU usage above 85%" in r.message for r in hz)
    assert not any("CPU usage above 85%" in r.message for r in sh)


def test_multi_region_backend_fanout(state):
    state.activate("cpu_spike", duration_minutes=30, region="cn-hangzhou")
    now = datetime.now()
    backend = MultiRegionBackend(["cn-hangzhou", "cn-shanghai"],
                                 lambda r: InlineBackend())
    out = json.loads(backend.execute("query_metrics", {
        "metric": "cpu_usage", "service": "demo-app",
        "start": (now - timedelta(minutes=5)).isoformat(),
        "end": (now + timedelta(minutes=5)).isoformat(),
    }))
    assert [r["region"] for r in out["regions"]] == ["cn-hangzhou", "cn-shanghai"]
    by_region = {r["region"]: r for r in out["regions"]}
    hz_max = max(p["value"] for p in by_region["cn-hangzhou"]["result"])
    sh_max = max(p["value"] for p in by_region["cn-shanghai"]["result"])
    assert hz_max > 90 > sh_max


def test_multi_region_backend_error_isolated():
    class Boom:
        def execute(self, name, args):
            if args.get("region") == "cn-shanghai":
                raise RuntimeError("region down")
            return json.dumps([{"ok": 1}])

    backend = MultiRegionBackend(["cn-hangzhou", "cn-shanghai"], lambda r: Boom())
    out = json.loads(backend.execute("query_metrics", {"metric": "cpu_usage"}))
    by_region = {r["region"]: r for r in out["regions"]}
    assert by_region["cn-hangzhou"]["result"] == [{"ok": 1}]
    assert "RuntimeError" in by_region["cn-shanghai"]["error"]


def test_multi_region_non_aware_tool_passthrough():
    """k8s 等无 region 参数的工具不 fan-out，主区域结果原样返回。"""
    backend = MultiRegionBackend(["cn-hangzhou", "cn-shanghai"],
                                 lambda r: InlineBackend())
    out = backend.execute("query_k8s_events", {"namespace": "default"})
    assert json.loads(out) == {"error": "unknown tool: query_k8s_events"}


def test_regions_from_env(monkeypatch):
    monkeypatch.setenv("OPEN_TAM_REGIONS", "cn-hangzhou,cn-shanghai")
    assert Settings.load().regions == ("cn-hangzhou", "cn-shanghai")
    monkeypatch.delenv("OPEN_TAM_REGIONS")
    assert Settings.load().regions == ()


def test_fake_run_with_regions_config(tmp_path, monkeypatch, state):
    """多区域配置下 fake 排查全链路无回归。"""
    from open_tam.config import Settings
    from open_tam.models import AlertEvent
    from open_tam.orchestrator.investigate import run_investigation
    from open_tam.tracing.trace import TraceRecorder

    monkeypatch.setenv("OPEN_TAM_REGIONS", "cn-hangzhou,cn-shanghai")
    monkeypatch.setenv("OPEN_TAM_BASE_DIR", str(tmp_path))
    settings = Settings.load()
    alert = AlertEvent.model_validate({
        "alert_name": "cpu_usage 异常", "service": "demo-app",
        "metric": "cpu_usage", "threshold": 80, "current_value": 92.5,
    })
    sink_events: list[dict] = []
    make_trace = lambda agent: TraceRecorder(
        alert_id=alert.alert_id, traces_dir=settings.traces_dir,
        agent=agent, sink=sink_events.append)
    result, path = run_investigation(
        alert, settings, fake=True, transport="inline",
        trace=make_trace(None), metric_trace=make_trace("metric"),
        log_trace=make_trace("log"))
    assert result.root_cause
