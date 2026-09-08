import asyncio
import os
import time

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


def test_primary_timeout_falls_back(monkeypatch):
    model = AgentScopeChatModel(
        primary="slow", fallback="fast", api_key="test", timeout=0.1
    )

    async def acall(name, messages, tools):
        if name == "slow":
            await asyncio.sleep(3)
        return ModelReply(content=f'{{"root_cause": "reply-from-{name}"}}', tool_calls=[])

    monkeypatch.setattr(model, "_acall", acall)
    start = time.monotonic()
    reply = model.complete([{"role": "user", "content": "hi"}], tools=[])
    elapsed = time.monotonic() - start
    assert reply.content and "reply-from-fast" in reply.content
    assert elapsed < 2.5  # 无超时会等满 3s


def test_settings_model_timeout_from_env(monkeypatch):
    from open_tam.config import Settings

    monkeypatch.setenv("OPEN_TAM_MODEL_TIMEOUT", "30")
    assert Settings.load().model_timeout == 30.0


@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 DASHSCOPE_API_KEY")
def test_real_dashscope_smoke():
    model = AgentScopeChatModel()
    reply = model.complete([{"role": "user", "content": "回复一个字：好"}], tools=[])
    assert reply.content
