from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from open_tam.models import AlertEvent
from open_tam.orchestrator.tools import ALL_TOOLS, Backend, InlineBackend

SYSTEM_PROMPT = """你是资深 SRE 运维专家。收到一条告警后，按"思考→调用工具→观察"循环排查：
1. 先用 query_metrics 确认告警指标的异常窗口与幅度；
2. 对照阈值判断是否真实异常，明确异常开始时间；
3. 定位根因后，**只输出一个 JSON 对象**（可包在 ```json 代码块中）：
   {"root_cause": "<根因，字符串；无法定位则为 null>",
    "evidence": ["<证据1>", ...],
    "actions": ["<建议动作1>", ...],
    "confidence": "high|medium|low",
    "excluded": ["<已排除项>", ...]}
4. 无法定位根因时 root_cause 填 null，并在 excluded 中列出已排除的可能。
不要输出 JSON 以外的解释性文字。"""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ModelReply:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply: ...


@dataclass
class Step:
    index: int
    thought: str | None
    tool_name: str | None
    arguments: dict | None
    observation: str | None
    error: str | None = None


@dataclass
class DiagnosisResult:
    alert_id: str
    root_cause: str | None
    evidence: list[str]
    actions: list[str]
    confidence: str
    excluded: list[str]
    steps: list[Step]
    raw_final: str | None = None


class FakeChatModel:
    """脚本化模型替身：按序返回预设回复，测试排查循环全逻辑。"""

    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        self.calls.append(messages)
        if not self.replies:
            raise AssertionError("FakeChatModel exhausted")
        return self.replies.pop(0)


class ReActLoop:
    def __init__(
        self,
        model: ChatModel,
        backend: Backend | None = None,
        max_steps: int = 15,
        char_budget: int = 60000,
    ) -> None:
        self.model = model
        self.backend: Backend = backend or InlineBackend()
        self.max_steps = max_steps
        self.char_budget = char_budget

    def run(self, alert: AlertEvent) -> DiagnosisResult:
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"告警信息：\n{alert.model_dump_json(indent=2)}"},
        ]
        steps: list[Step] = []
        for i in range(self.max_steps):
            reply = self.model.complete(messages, ALL_TOOLS)
            if reply.tool_calls:
                for tc in reply.tool_calls:
                    step = Step(index=i, thought=reply.content, tool_name=tc.name,
                                arguments=tc.arguments, observation=None)
                    try:
                        step.observation = self.backend.execute(tc.name, tc.arguments)
                    except Exception as exc:  # 工具失败不终止排查，失败即观察
                        step.error = f"{type(exc).__name__}: {exc}"
                        step.observation = json.dumps({"tool_error": step.error}, ensure_ascii=False)
                    steps.append(step)
                    messages.append({"role": "assistant", "content": reply.content or "",
                                     "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}]})
                    messages.append({"role": "tool", "name": tc.name, "content": step.observation})
            elif reply.content is not None:
                steps.append(Step(index=i, thought=reply.content, tool_name=None,
                                  arguments=None, observation=None))
                return self._finalize(alert, reply.content, steps)
            if sum(len(str(m)) for m in messages) > self.char_budget:
                break
        return DiagnosisResult(
            alert_id=alert.alert_id, root_cause=None,
            evidence=[], actions=["人工介入：自动排查达到步数/预算上限"],
            confidence="low", excluded=[],
            steps=steps, raw_final=None,
        )

    @staticmethod
    def _finalize(alert: AlertEvent, content: str, steps: list[Step]) -> DiagnosisResult:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return DiagnosisResult(
                    alert_id=alert.alert_id,
                    root_cause=data.get("root_cause"),
                    evidence=list(data.get("evidence", [])),
                    actions=list(data.get("actions", [])),
                    confidence=str(data.get("confidence", "low")),
                    excluded=list(data.get("excluded", [])),
                    steps=steps, raw_final=content,
                )
            except json.JSONDecodeError:
                pass
        return DiagnosisResult(
            alert_id=alert.alert_id, root_cause=content, evidence=[], actions=[],
            confidence="low", excluded=[], steps=steps, raw_final=content,
        )
