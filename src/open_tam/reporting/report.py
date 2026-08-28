from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from open_tam.models import AlertEvent
from open_tam.orchestrator.loop import DiagnosisResult


def render_report(
    alert: AlertEvent, result: DiagnosisResult, generated_at: datetime | None = None
) -> str:
    now = generated_at or datetime.now()
    lines = [
        f"# 根因分析报告 · {alert.alert_name}",
        "",
        f"- 告警 ID：`{alert.alert_id}`",
        f"- 服务：`{alert.service}`　指标：`{alert.metric}`（阈值 {alert.threshold}，当前 {alert.current_value}）",
        f"- 置信度：`{result.confidence}`　生成时间：{now.isoformat(timespec='seconds')}",
        "",
        "## 结论摘要",
        "",
        result.root_cause
        or "**未定位根因**（自动排查未收敛，请参考已排除项人工介入）",
        "",
        "## 异常清单",
        "",
    ]
    for ev in result.evidence or ["（无自动采集到的异常证据）"]:
        lines.append(f"- {ev}")
    if result.excluded:
        lines.append("")
        lines.append("已排除：")
        lines.extend(f"- {x}" for x in result.excluded)
    lines += ["", "## 建议动作", ""]
    if result.actions:
        lines.extend(f"{i}. {a}" for i, a in enumerate(result.actions, 1))
    else:
        lines.append("1. （无）")
    lines += ["", "## 排查过程", ""]
    for s in result.steps:
        args = json.dumps(s.arguments or {}, ensure_ascii=False)
        lines.append(f"{s.index + 1}. {s.thought or ''} 调用 `{s.tool_name}` {args}")
        obs = (s.observation or "")[:200]
        lines.append(f"   - 观察：`{obs}`")
    return "\n".join(lines)


def save_report(
    alert: AlertEvent, result: DiagnosisResult, reports_dir: Path | str = "reports"
) -> Path:
    d = Path(reports_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{datetime.now():%Y-%m-%d}-{alert.alert_id}.md"
    path.write_text(render_report(alert, result), encoding="utf-8")
    return path
