from datetime import datetime

from open_tam.models import AlertEvent
from open_tam.orchestrator.loop import DiagnosisResult, Step
from open_tam.reporting.report import render_report, save_report


def _alert() -> AlertEvent:
    return AlertEvent.model_validate({
        "alert_id": "a1",
        "alert_name": "CPU使用率过高", "service": "demo-app",
        "metric": "cpu_usage", "threshold": 80, "current_value": 92.5,
    })


def _result() -> DiagnosisResult:
    return DiagnosisResult(
        alert_id="a1", root_cause="低效正则导致 CPU 飙升",
        evidence=["cpu_usage 达到 92"], actions=["回滚发布"],
        confidence="high", excluded=["OOM"],
        steps=[Step(index=0, thought="查指标", tool_name="query_metrics",
                    arguments={"metric": "cpu_usage"}, observation='[{"value": 92}]')],
    )


def test_render_contains_three_sections():
    md = render_report(_alert(), _result(), generated_at=datetime(2026, 8, 28, 12, 0))
    for heading in ("## 结论摘要", "## 异常清单", "## 建议动作"):
        assert heading in md
    assert "低效正则" in md
    assert "回滚发布" in md
    assert "cpu_usage" in md


def test_save_report_writes_dated_file(tmp_path):
    path = save_report(_alert(), _result(), reports_dir=tmp_path)
    assert path.exists()
    assert path.name.startswith("2026-")
    assert path.name.endswith("-a1.md")
    assert "## 结论摘要" in path.read_text(encoding="utf-8")


def test_render_unresolved_case():
    r = DiagnosisResult(alert_id="a2", root_cause=None, evidence=[],
                        actions=["人工介入"], confidence="low", excluded=["磁盘满"],
                        steps=[], raw_final=None)
    md = render_report(_alert(), r, generated_at=datetime(2026, 8, 28, 12, 0))
    assert "未定位" in md
    assert "磁盘满" in md
