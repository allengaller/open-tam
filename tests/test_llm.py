import os

import pytest

from open_tam.orchestrator.llm import AgentScopeChatModel
from open_tam.orchestrator.loop import ModelReply


def test_fallback_triggers_on_primary_failure(monkeypatch):
    model = AgentScopeChatModel(primary="fake-primary", fallback="fake-fallback", api_key="test")

    def fail_primary(name, messages, tools):
        if name == "fake-primary":
            raise RuntimeError("primary down")
        return ModelReply(content='{"root_cause": "ok", "confidence": "low"}', tool_calls=[])

    monkeypatch.setattr(model, "_call_via_agentscope", fail_primary)
    reply = model.complete([{"role": "user", "content": "hi"}], tools=[])
    assert reply.content and "ok" in reply.content


def test_both_models_failing_raises(monkeypatch):
    model = AgentScopeChatModel(primary="a", fallback="b", api_key="test")

    def always_fail(name, messages, tools):
        raise RuntimeError("down")

    monkeypatch.setattr(model, "_call_via_agentscope", always_fail)
    with pytest.raises(RuntimeError):
        model.complete([{"role": "user", "content": "hi"}], tools=[])


@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 DASHSCOPE_API_KEY")
def test_real_dashscope_smoke():
    model = AgentScopeChatModel()
    reply = model.complete([{"role": "user", "content": "回复一个字：好"}], tools=[])
    assert reply.content
