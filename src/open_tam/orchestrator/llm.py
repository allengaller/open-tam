from __future__ import annotations

import asyncio
import json
import os

from open_tam.orchestrator.loop import ModelReply, ToolCall


class AgentScopeChatModel:
    """通过 AgentScope 2.x 接入 DashScope Qwen；主备模型自动切换。

    ChatModel 协议的 AgentScope 实现：负责三件事——
    消息格式转换（内部 dict → agentscope Msg/block）、
    工具 schema 转换（扁平 spec → OpenAI function 格式）、
    主备模型容错。
    """

    def __init__(
        self,
        primary: str = "qwen-plus",
        fallback: str = "qwen-turbo",
        api_key: str | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        last_error: Exception | None = None
        for name in (self.primary, self.fallback):
            try:
                return self._call_via_agentscope(name, messages, tools)
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _call_via_agentscope(
        self, model_name: str, messages: list[dict], tools: list[dict]
    ) -> ModelReply:
        return asyncio.run(self._acall(model_name, messages, tools))

    async def _acall(
        self, model_name: str, messages: list[dict], tools: list[dict]
    ) -> ModelReply:
        from agentscope.credential import DashScopeCredential
        from agentscope.model import DashScopeChatModel

        model = DashScopeChatModel(
            credential=DashScopeCredential(api_key=self.api_key),
            model=model_name,
            stream=False,
        )
        response = await model(
            messages=self._to_agentscope_messages(messages),
            tools=self._to_openai_tools(tools),
        )
        return self._from_agentscope_response(response)

    @staticmethod
    def _to_openai_tools(tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {}),
                },
            }
            for t in tools
        ]

    @staticmethod
    def _to_agentscope_messages(messages: list[dict]) -> list:
        from agentscope.message import (
            Msg,
            TextBlock,
            ToolCallBlock,
            ToolResultBlock,
        )

        out = []
        for m in messages:
            role = m["role"]
            content = m.get("content")
            if role == "assistant" and m.get("tool_calls"):
                blocks = []
                if content:
                    blocks.append(TextBlock(text=content))
                for tc in m["tool_calls"]:
                    blocks.append(
                        ToolCallBlock(
                            id=tc["id"],
                            name=tc["name"],
                            input=json.dumps(tc["arguments"], ensure_ascii=False),
                        )
                    )
                out.append(Msg(name="assistant", role="assistant", content=blocks))
            elif role == "tool":
                out.append(
                    Msg(
                        name="tool",
                        role="assistant",
                        content=[
                            ToolResultBlock(
                                id=m["tool_call_id"],
                                name=m["name"],
                                output=content,
                            )
                        ],
                    )
                )
            else:
                out.append(
                    Msg(name=role, role=role, content=[TextBlock(text=content or "")])
                )
        return out

    @staticmethod
    def _from_agentscope_response(response) -> ModelReply:
        from agentscope.message import TextBlock, ToolCallBlock

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in getattr(response, "content", None) or []:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolCallBlock):
                calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=json.loads(block.input or "{}"),
                    )
                )
        return ModelReply(content="".join(text_parts) or None, tool_calls=calls)
