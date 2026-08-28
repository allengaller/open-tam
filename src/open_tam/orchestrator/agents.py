from __future__ import annotations

import json

from open_tam.orchestrator.loop import ChatModel, ReActLoop
from open_tam.orchestrator.tools import Backend, InlineBackend

ORCHESTRATOR_PROMPT = """你是资深 SRE 运维专家（orchestrator）。收到告警后，通过两个子 Agent 排查：
- ask_metric_agent(question)：向指标分析子 Agent 提问，确认异常是否存在、异常窗口与幅度；
- ask_log_agent(question)：向日志检索子 Agent 提问，获取异常现场的日志证据。
先向指标子 Agent 确认异常，需要现场证据时再询问日志子 Agent；证据足够后定位根因。
最终**只输出一个 JSON 对象**（可包在 ```json 代码块中）：
{"root_cause": "<根因；无法定位则为 null>", "evidence": ["<证据>"], "actions": ["<建议动作>"], "confidence": "high|medium|low", "excluded": ["<已排除项>"]}
evidence 必须引用子 Agent 返回的关键证据原文。不要输出 JSON 以外的解释性文字。"""

METRIC_AGENT_PROMPT = """你是指标分析子 Agent。用 query_metrics 查询时序数据，回答"异常是否存在、何时开始、幅度多大"。
完成回答后只输出结论文本（不要 JSON、不要多余前缀）。"""

LOG_AGENT_PROMPT = """你是日志检索子 Agent。用 query_logs 检索异常现场日志（可按级别 ERROR/WARN 与关键字过滤），提炼与问题直接相关的日志证据。
完成回答后只输出证据清单文本，每条一行。"""


class SpecialistAgent:
    """专长子 Agent：独立系统提示 + 单一数据工具，由 orchestrator 以工具形式委托调用。"""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[dict],
        model: ChatModel,
        backend: Backend | None = None,
        max_steps: int = 5,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools
        self.model = model
        self.backend: Backend = backend or InlineBackend()
        self.max_steps = max_steps

    def run(self, question: str) -> str:
        loop = ReActLoop(
            model=self.model, backend=self.backend, max_steps=self.max_steps,
            system_prompt=self.system_prompt, tools=self.tools,
        )
        result = loop.run_prompt(
            self.system_prompt, question, alert_id=f"subagent-{self.name}"
        )
        return result.root_cause or "（无结论）"


class AgentBackend:
    """orchestrator 的工具后端：把 ask_* 委托工具路由到对应 SpecialistAgent。"""

    def __init__(self, specialists: dict[str, SpecialistAgent]) -> None:
        self.specialists = specialists

    def execute(self, name: str, args: dict) -> str:
        if name in self.specialists:
            return self.specialists[name].run(args["question"])
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
