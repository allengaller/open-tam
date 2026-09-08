from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from open_tam.config import Settings
from open_tam.faults import FAULT_MODES, FaultMode, FaultState
from open_tam.investigation import run_investigation
from open_tam.models import AlertEvent
from open_tam.orchestrator.loop import FakeChatModel, ModelReply, ToolCall


@dataclass(frozen=True)
class EvalRun:
    fault: str
    root_cause: str | None
    keyword_hit: bool
    confidence: str
    steps: int
    elapsed_s: float


@dataclass(frozen=True)
class EvalReport:
    model_label: str
    runs: list[EvalRun]

    @property
    def total(self) -> int:
        return len(self.runs)

    @property
    def located_rate(self) -> float:
        return sum(r.root_cause is not None for r in self.runs) / self.total if self.total else 0.0

    @property
    def hit_rate(self) -> float:
        return sum(r.keyword_hit for r in self.runs) / self.total if self.total else 0.0

    @property
    def avg_steps(self) -> float:
        return sum(r.steps for r in self.runs) / self.total if self.total else 0.0

    @property
    def avg_elapsed_s(self) -> float:
        return sum(r.elapsed_s for r in self.runs) / self.total if self.total else 0.0


def alert_for(mode: FaultMode) -> AlertEvent:
    return AlertEvent.model_validate({
        "alert_name": f"{mode.metric} 异常",
        "service": mode.service,
        "metric": mode.metric,
        "threshold": mode.baseline_high,
        "current_value": mode.spike_value,
    })


def fake_orchestrator_model(mode: FaultMode) -> FakeChatModel:
    """故障感知的脚本化编排模型：按故障注册表的预期答案回放，仅验证评测链路。"""
    final = json.dumps({
        "root_cause": mode.root_cause,
        "evidence": [mode.anomaly_desc, f"日志特征: {mode.log_signature}"],
        "actions": [mode.remediation],
        "confidence": "high",
    }, ensure_ascii=False)
    return FakeChatModel([
        ModelReply(content="先问指标子 Agent 确认异常", tool_calls=[ToolCall(
            id="t1", name="ask_metric_agent",
            arguments={"question": f"{mode.service} 的 {mode.metric} 最近一小时是否异常？异常窗口与幅度？"})]),
        ModelReply(content="再向日志子 Agent 要现场证据", tool_calls=[ToolCall(
            id="t2", name="ask_log_agent",
            arguments={"question": f"检索 {mode.service} 最近一小时 ERROR/WARN 日志，找与 {mode.metric} 异常相关的证据"})]),
        ModelReply(content=f"```json\n{final}\n```", tool_calls=[]),
    ])


def keyword_hit(mode: FaultMode, root_cause: str | None) -> bool:
    if not root_cause:
        return False
    text = root_cause.lower()
    return any(kw.lower() in text for kw in mode.eval_keywords)


def run_eval(
    fault_names: list[str], *, settings: Settings, runs: int = 1, fake: bool
) -> EvalReport:
    model_label = "fake（脚本回放，仅验证评测链路）" if fake else settings.model_primary
    results: list[EvalRun] = []
    for name in fault_names:
        mode = FAULT_MODES[name]
        for _ in range(runs):
            alert = alert_for(mode)
            model = fake_orchestrator_model(mode) if fake else None
            state = FaultState()
            state.activate(name, duration_minutes=30)
            start = time.monotonic()
            try:
                outcome = run_investigation(alert, settings=settings, model=model)
            finally:
                state.clear(name)
            results.append(EvalRun(
                fault=name,
                root_cause=outcome.root_cause,
                keyword_hit=keyword_hit(mode, outcome.root_cause),
                confidence=outcome.confidence,
                steps=outcome.steps,
                elapsed_s=time.monotonic() - start,
            ))
    return EvalReport(model_label=model_label, runs=results)


def write_eval_report(report: EvalReport, reports_dir: Path) -> Path:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = reports_dir / f"eval-{ts}.md"
    lines = [
        "# open-tam 评测报告",
        "",
        f"- 模型: {report.model_label}",
        f"- 样本数: {report.total}（故障模式 × 运行次数）",
        f"- 根因定位率: {report.located_rate:.0%}",
        f"- 关键词命中率: {report.hit_rate:.0%}",
        f"- 平均步数: {report.avg_steps:.1f}",
        f"- 平均耗时: {report.avg_elapsed_s:.1f}s",
        "",
        "| 故障 | 根因 | 命中 | 置信度 | 步数 | 耗时s |",
        "|---|---|---|---|---|---|",
    ]
    for r in report.runs:
        cause = (r.root_cause or "未定位").replace("|", "\\|").replace("\n", " ")
        mark = "✓" if r.keyword_hit else "✗"
        lines.append(
            f"| {r.fault} | {cause} | {mark} | {r.confidence} | {r.steps} | {r.elapsed_s:.1f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
