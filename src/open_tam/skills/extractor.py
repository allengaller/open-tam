from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from open_tam.skills.models import Skill, SkillStep
from open_tam.tracing.trace import load_trace


def extract_skill_from_trace(trace_path: str | Path) -> Skill:
    """从单条 trace 中提取排查模板。"""
    entries = load_trace(str(trace_path))

    tool_calls = [e for e in entries if e.get("kind") == "tool_call"]
    steps = []
    for i, call in enumerate(tool_calls):
        steps.append(SkillStep(
            order=i + 1,
            action=call.get("tool", call.get("name", "unknown")),
            params=call.get("arguments", {}),
            expected_signal="",
            rationale="",
        ))

    final = next((e for e in entries if e.get("kind") == "final"), None)
    root_cause_hints = [final["root_cause"]] if final and final.get("root_cause") else []

    alert_received = next((e for e in entries if e.get("kind") == "alert_received"), None)
    alert_pattern = alert_received.get("alert_name", "*") if alert_received else "*"
    service = alert_received.get("service", "*") if alert_received else "*"

    evidence_keywords = _extract_evidence_keywords(entries)

    confidence = _calculate_confidence(entries)

    return Skill(
        id=_generate_skill_id(alert_pattern),
        name=f"{alert_pattern} 排查模板",
        alert_pattern=alert_pattern,
        service_pattern=service,
        description=f"从 trace {Path(trace_path).name} 自动提取",
        steps=steps,
        root_cause_hints=root_cause_hints,
        evidence_patterns=evidence_keywords,
        created_from=str(trace_path),
        created_at=datetime.now(UTC).isoformat(),
        confidence=confidence,
    )


def extract_skills_from_dir(traces_dir: str | Path) -> list[Skill]:
    """从目录中所有 trace 提取 Skill，按 alert_name 聚合取最高置信度。"""
    traces_path = Path(traces_dir)
    if not traces_path.exists():
        return []

    skills_by_pattern: dict[str, list[Skill]] = {}
    for trace_file in sorted(traces_path.glob("*.jsonl")):
        try:
            skill = extract_skill_from_trace(trace_file)
            key = f"{skill.alert_pattern}:{skill.service_pattern}"
            skills_by_pattern.setdefault(key, []).append(skill)
        except Exception:
            continue

    result = []
    for skills in skills_by_pattern.values():
        best = max(skills, key=lambda s: s.confidence)
        if len(skills) > 1:
            best.confidence = min(1.0, best.confidence + 0.1 * (len(skills) - 1))
            best.description = f"从 {len(skills)} 条 trace 聚合提取"
        result.append(best)
    return result


def _extract_evidence_keywords(entries: list[dict]) -> list[str]:
    keywords: Counter[str] = Counter()
    for e in entries:
        if e.get("kind") == "observation":
            text = str(e.get("data", ""))
            for kw in ["cpu", "memory", "slow", "error", "timeout", "oom", "query", "connection"]:
                if kw in text.lower():
                    keywords[kw] += 1
    return [kw for kw, _ in keywords.most_common(5)]


def _calculate_confidence(entries: list[dict]) -> float:
    has_final = any(e.get("kind") == "final" for e in entries)
    tool_calls = sum(1 for e in entries if e.get("kind") == "tool_call")
    if not has_final:
        return 0.3
    if tool_calls == 0:
        return 0.2
    return min(1.0, 0.5 + tool_calls * 0.1)


def _generate_skill_id(alert_pattern: str) -> str:
    safe = alert_pattern.replace("*", "all").replace(" ", "_").lower()
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{safe}_{ts}"
