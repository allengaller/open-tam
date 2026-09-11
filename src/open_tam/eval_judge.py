"""LLM-as-Judge: 用独立 LLM 评估排查报告质量。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from open_tam.orchestrator.loop import ChatModel, FakeChatModel, ModelReply

JUDGE_PROMPT = """你是一个排障报告质量评审专家。请评估以下排障报告的质量（0.0 到 1.0 之间的小数）。

## 报告内容
{report}

## 排查过程摘要
{trace_summary}

## 预期根因
{expected_root_cause}

## 评分标准
- 0.0: 完全偏离根因，报告无价值
- 0.3: 提到相关区域但未定位真正根因
- 0.5: 根因方向正确但证据不充分
- 0.7: 根因正确，证据链基本完整
- 0.9: 根因精确，证据充分，排除项合理
- 1.0: 完美——根因精确 + 证据链完整 + 建议动作合理 + 排除项清晰

请只输出一个数字（如 0.7），不要输出其他内容。"""


@dataclass(frozen=True)
class JudgeVerdict:
    score: float
    dimension: str
    detail: str = ""


class EvidenceJudge:
    """用 LLM 评估报告质量。"""

    def __init__(self, model: ChatModel | None = None) -> None:
        self.model = model

    def judge(
        self,
        report: str,
        trace_entries: list[dict],
        expected_root_cause: str,
    ) -> JudgeVerdict:
        trace_summary = self._summarize_trace(trace_entries)
        prompt = JUDGE_PROMPT.format(
            report=report[:3000],
            trace_summary=trace_summary[:2000],
            expected_root_cause=expected_root_cause,
        )
        reply = self.model.complete([{"role": "user", "content": prompt}], tools=[])
        score = self._parse_score(reply.content)
        return JudgeVerdict(score=score, dimension="evidence_sufficiency", detail=reply.content or "")

    def _summarize_trace(self, entries: list[dict]) -> str:
        lines = []
        for e in entries[:20]:
            kind = e.get("kind", "?")
            if kind == "tool_call":
                tool = e.get("tool", e.get("name", "?"))
                args = e.get("arguments", {})
                lines.append(f"[tool_call] {tool}({json.dumps(args, ensure_ascii=False)[:100]})")
            elif kind == "observation":
                data = str(e.get("data", ""))[:150]
                lines.append(f"[observation] {data}")
            elif kind == "final":
                rc = e.get("root_cause", "")
                lines.append(f"[final] root_cause={rc}")
        return "\n".join(lines)

    def _parse_score(self, text: str | None) -> float:
        if not text:
            return 0.0
        match = re.search(r"(-?\d+\.?\d*)", text.strip())
        if match:
            score = float(match.group(1))
            return max(0.0, min(1.0, score))
        return 0.0


def fake_judge_model(expected_score: float = 0.8) -> FakeChatModel:
    return FakeChatModel([ModelReply(content=str(expected_score))])
