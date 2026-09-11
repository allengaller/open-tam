from __future__ import annotations

from datetime import UTC, datetime
from fnmatch import fnmatch
from uuid import uuid4

from pydantic import BaseModel, Field


class SkillStep(BaseModel):
    order: int
    action: str
    params: dict = Field(default_factory=dict)
    expected_signal: str = ""
    rationale: str = ""


class Skill(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    name: str
    alert_pattern: str
    service_pattern: str = "*"
    description: str = ""
    steps: list[SkillStep] = Field(default_factory=list)
    root_cause_hints: list[str] = Field(default_factory=list)
    evidence_patterns: list[str] = Field(default_factory=list)
    created_from: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    confidence: float = 0.0

    def matches(self, alert_name: str, service: str = "") -> bool:
        if not fnmatch(alert_name, self.alert_pattern):
            return False
        if self.service_pattern != "*" and not fnmatch(service, self.service_pattern):
            return False
        return True

    def to_prompt_section(self) -> str:
        lines = [f"### Skill: {self.name} (confidence: {self.confidence:.2f})"]
        if self.description:
            lines.append(self.description)
        if self.steps:
            lines.append("\n建议排查步骤:")
            for step in sorted(self.steps, key=lambda s: s.order):
                params_str = ", ".join(f"{k}={v}" for k, v in step.params.items()) if step.params else ""
                lines.append(f"  {step.order}. [{step.action}] {params_str}")
                if step.expected_signal:
                    lines.append(f"     期望信号: {step.expected_signal}")
                if step.rationale:
                    lines.append(f"     原因: {step.rationale}")
        if self.root_cause_hints:
            lines.append(f"\n常见根因: {', '.join(self.root_cause_hints)}")
        if self.evidence_patterns:
            lines.append(f"关键证据: {', '.join(self.evidence_patterns)}")
        return "\n".join(lines)
