"""Priority queue for alert investigation tasks."""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any

from open_tam.models import AlertEvent


class Priority(IntEnum):
    P0 = 0  # Critical - immediate investigation
    P1 = 1  # High - next available
    P2 = 2  # Medium - queued
    P3 = 3  # Low - background


@dataclass(order=True)
class AlertTask:
    """A task in the priority queue."""
    priority: int
    created_at: datetime = field(compare=False)
    alert: AlertEvent = field(compare=False)
    group_id: str | None = field(default=None, compare=False)
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class PriorityQueue:
    """Priority queue for alert investigation tasks.

    P0 tasks preempt P2+ tasks.
    """

    def __init__(self) -> None:
        self._heap: list[AlertTask] = []
        self._counter = 0

    def push(self, alert: AlertEvent, priority: Priority | int, group_id: str | None = None) -> AlertTask:
        task = AlertTask(
            priority=int(priority),
            created_at=datetime.now(),
            alert=alert,
            group_id=group_id,
        )
        heapq.heappush(self._heap, task)
        self._counter += 1
        return task

    def pop(self) -> AlertTask | None:
        if self._heap:
            return heapq.heappop(self._heap)
        return None

    def peek(self) -> AlertTask | None:
        if self._heap:
            return self._heap[0]
        return None

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def clear(self) -> None:
        self._heap.clear()

    def get_all(self) -> list[AlertTask]:
        return sorted(self._heap)

    def get_by_priority(self, priority: Priority | int) -> list[AlertTask]:
        return [t for t in self._heap if t.priority == int(priority)]


def infer_priority(alert: AlertEvent) -> Priority:
    """Infer priority from alert severity and metric."""
    severity = alert.severity.lower()
    if severity == "critical":
        return Priority.P0
    if severity == "warning":
        return Priority.P2
    if severity == "info":
        return Priority.P3
    return Priority.P2
