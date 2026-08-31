from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from open_tam.faults import FAULT_MODES
from open_tam.orchestrator.tools import Backend, InlineBackend


def run_patrol(
    reports_dir: Path | str,
    backend: Backend | None = None,
    now: datetime | None = None,
    window_minutes: int = 10,
) -> Path:
    """对所有注册故障模式的目标指标做窗口峰值 vs 阈值巡检，产出 Markdown 巡检报告。"""
    backend = backend or InlineBackend()
    now = now or datetime.now().replace(second=0, microsecond=0)
    start = now - timedelta(minutes=window_minutes)

    checks: list[dict] = []
    for mode in FAULT_MODES.values():
        raw = backend.execute("query_metrics", {
            "metric": mode.metric, "service": mode.service,
            "start": start.isoformat(), "end": now.isoformat(),
        })
        points = json.loads(raw)
        peak = max((p["value"] for p in points), default=0.0)
        status = "anomaly" if peak > mode.baseline_high else "normal"
        checks.append({
            "fault": mode.name, "service": mode.service, "metric": mode.metric,
            "peak": round(peak, 1), "threshold": mode.baseline_high, "status": status,
        })

    anomalies = [c for c in checks if c["status"] == "anomaly"]
    lines = [
        "# 巡检报告",
        "",
        f"- 巡检时间：{now.isoformat(timespec='seconds')}",
        f"- 检查窗口：最近 {window_minutes} 分钟",
        f"- 检查项：{len(checks)}，异常：{len(anomalies)}",
        "",
        "| 故障模式 | 服务 | 指标 | 窗口峰值 | 阈值 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for c in checks:
        status_cn = "异常" if c["status"] == "anomaly" else "正常"
        lines.append(
            f"| {c['fault']} | {c['service']} | {c['metric']} | {c['peak']} | {c['threshold']} | {status_cn} |"
        )
    if anomalies:
        lines += ["", "## 异常跟进", ""]
        for c in anomalies:
            mode = FAULT_MODES[c["fault"]]
            lines.append(
                f"- **{c['fault']}**（{c['service']}）：{mode.anomaly_desc}；"
                f"建议运行 `open-tam investigate` 深入排查"
            )

    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"patrol-{now.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
