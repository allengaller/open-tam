"""A/B 模型对比评测。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from open_tam.config import Settings
from open_tam.eval import EvalReport, alert_for, keyword_hit, run_eval
from open_tam.faults import FAULT_MODES, FaultState


@dataclass
class CompareResult:
    model_label: str
    report: EvalReport


@dataclass
class CompareReport:
    results: list[CompareResult]
    fault_names: list[str]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def models(self) -> list[str]:
        return [r.model_label for r in self.results]

    def summary_row(self, metric: str) -> dict[str, float]:
        return {r.model_label: getattr(r.report, metric) for r in self.results}


def run_compare(
    fault_names: list[str],
    model_labels: list[str],
    *,
    settings: Settings,
    runs: int = 1,
    fake: bool = True,
) -> CompareReport:
    results = []
    for label in model_labels:
        model_settings = Settings(
            **{**settings.__dict__, "model_primary": label}
        )
        report = run_eval(fault_names, settings=model_settings, runs=runs, fake=fake)
        results.append(CompareResult(model_label=label, report=report))
    return CompareReport(results=results, fault_names=fault_names)


def write_compare_report(report: CompareReport, reports_dir: Path) -> Path:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = reports_dir / f"eval-compare-{ts}.md"

    models = report.models
    metrics = [
        ("根因定位率", "located_rate", "{:.0%}"),
        ("关键词命中率", "hit_rate", "{:.0%}"),
        ("平均步数", "avg_steps", "{:.1f}"),
        ("平均耗时", "avg_elapsed_s", "{:.1f}s"),
    ]

    lines = [
        "# A/B 评测报告",
        "",
        f"- 时间: {report.timestamp}",
        f"- 故障模式: {', '.join(report.fault_names)}",
        f"- 模型: {' vs '.join(models)}",
        "",
        "| 指标 | " + " | ".join(models) + " |",
        "|---|" + "|".join(["---"] * len(models)) + "|",
    ]

    for label, attr, fmt in metrics:
        vals = [fmt.format(getattr(r.report, attr)) for r in report.results]
        lines.append(f"| {label} | " + " | ".join(vals) + " |")

    lines.extend(["", "## 逐故障明细", ""])
    for result in report.results:
        lines.append(f"### {result.model_label}")
        lines.append("")
        lines.append("| 故障 | 根因 | 命中 | 步数 | 耗时 |")
        lines.append("|---|---|---|---|---|")
        for r in result.report.runs:
            cause = (r.root_cause or "未定位").replace("|", "\\|").replace("\n", " ")
            mark = "✓" if r.keyword_hit else "✗"
            lines.append(f"| {r.fault} | {cause} | {mark} | {r.steps} | {r.elapsed_s:.1f}s |")
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
