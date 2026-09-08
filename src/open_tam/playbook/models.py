"""Playbook models for multi-step remediation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Sensitivity(str, Enum):
    SAFE = "safe"
    SENSITIVE = "sensitive"


class OnFailure(str, Enum):
    ABORT = "abort"
    CONTINUE = "continue"
    ROLLBACK = "rollback"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    DENIED = "denied"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


@dataclass
class PlaybookStep:
    """A single step in a playbook."""
    order: int
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    sensitivity: Sensitivity = Sensitivity.SAFE
    auto_execute: bool = True
    on_failure: OnFailure = OnFailure.ABORT
    description: str = ""


@dataclass
class Playbook:
    """A remediation playbook."""
    id: str
    name: str
    steps: list[PlaybookStep]
    trigger_pattern: str = "*"
    confidence_threshold: float = 0.7
    description: str = ""

    def matches(self, alert_name: str, confidence: float) -> bool:
        """Check if playbook matches the alert and confidence threshold."""
        import fnmatch
        if confidence < self.confidence_threshold:
            return False
        return fnmatch.fnmatch(alert_name, self.trigger_pattern)


@dataclass
class StepResult:
    """Result of executing a playbook step."""
    step: PlaybookStep
    status: StepStatus
    result: str | None = None
    error: str | None = None
    executed_at: datetime = field(default_factory=datetime.now)


@dataclass
class PlaybookResult:
    """Result of executing a playbook."""
    playbook_id: str
    steps: list[StepResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    @property
    def success(self) -> bool:
        return all(s.status == StepStatus.DONE for s in self.steps)

    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]
