from datetime import datetime, timedelta

import pytest

from open_tam.faults import FaultState
from open_tam.models import AlertEvent
from open_tam.orchestrator.loop import (
    FakeChatModel,
    ModelReply,
    ReActLoop,
    ToolCall,
)
from open_tam.orchestrator.tools import InlineBackend


@pytest.fixture(autouse=True)
def _state_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))


def _alert() -> AlertEvent:
    return AlertEvent.model_validate({
        "alert_name": "CPU使用率过高", "service": "demo-app",
        "metric": "cpu_usage", "threshold": 80, "current_value": 92.5,
        "triggered_at": datetime.now(),
    })


def _final_json(cause: str) -> str:
    return (
        '```json\n{"root_cause": "%s", "evidence": ["cpu_usage 达到 92"], '
        '"actions": ["回滚发布"], "confidence": "high"}\n```' % cause
    )


def _scripted_model() -> FakeChatModel:
    now = datetime.now().replace(second=0, microsecond=0)
    return FakeChatModel([
        ModelReply(
            content="先查指标确认异常窗口",
            tool_calls=[ToolCall(id="t1", name="query_metrics", arguments={
                "metric": "cpu_usage", "service": "demo-app",
                "start": (now - timedelta(minutes=60)).isoformat(),
                "end": now.isoformat(),
            })],
        ),
        ModelReply(content=_final_json("低效正则导致 CPU 飙升"), tool_calls=[]),
    ])


def test_loop_executes_tool_then_finalizes():
    FaultState().activate("cpu_spike", duration_minutes=30)
    result = ReActLoop(model=_scripted_model()).run(_alert())
    assert result.root_cause and "正则" in result.root_cause
    assert result.confidence == "high"
    assert len(result.steps) == 2
    assert result.steps[0].tool_name == "query_metrics"
    assert "92" in result.steps[0].observation


def test_loop_hits_step_budget():
    now = datetime.now().replace(second=0, microsecond=0)
    args = {"metric": "cpu_usage", "service": "demo-app",
            "start": (now - timedelta(minutes=5)).isoformat(), "end": now.isoformat()}
    endless = FakeChatModel([
        ModelReply(content=None, tool_calls=[ToolCall(id=f"t{i}", name="query_metrics", arguments=args)])
        for i in range(20)
    ])
    result = ReActLoop(model=endless, max_steps=3).run(_alert())
    assert result.root_cause is None
    assert len(result.steps) == 3


def test_final_without_code_fence():
    model = FakeChatModel([
        ModelReply(content='{"root_cause": "配置错误", "evidence": [], "actions": ["修改配置"], "confidence": "medium"}', tool_calls=[]),
    ])
    result = ReActLoop(model=model).run(_alert())
    assert result.root_cause == "配置错误"
    assert result.confidence == "medium"


def test_unparseable_final_falls_back_to_low_confidence():
    model = FakeChatModel([ModelReply(content="我觉得是正则问题", tool_calls=[])])
    result = ReActLoop(model=model).run(_alert())
    assert "正则" in (result.root_cause or "")
    assert result.confidence == "low"


def test_tool_error_becomes_observation_not_crash():
    now = datetime.now().replace(second=0, microsecond=0)
    model = FakeChatModel([
        ModelReply(content=None, tool_calls=[ToolCall(id="t1", name="query_metrics", arguments={
            "metric": "cpu_usage", "service": "demo-app",
            "start": "not-a-date", "end": now.isoformat(),
        })]),
        ModelReply(content='{"root_cause": null, "evidence": [], "actions": ["人工排查"], "confidence": "low", "excluded": []}'),
    ])
    result = ReActLoop(model=model).run(_alert())
    assert result.steps[0].error
    assert result.root_cause is None
