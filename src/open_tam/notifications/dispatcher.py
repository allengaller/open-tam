"""Notification dispatcher for investigation events."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class NotificationType(str, Enum):
    INVESTIGATION_COMPLETE = "investigation_complete"
    ACTION_CONFIRM = "action_confirm"


@dataclass
class NotificationEvent:
    type: NotificationType
    title: str
    content: str
    investigation_id: str | None = None
    action_id: str | None = None


class Notifier(Protocol):
    def send(self, event: NotificationEvent) -> bool: ...


class NotificationDispatcher:
    def __init__(self, notifiers: list[Notifier] | None = None) -> None:
        self.notifiers = notifiers or []

    def add_notifier(self, notifier: Notifier) -> None:
        self.notifiers.append(notifier)

    def dispatch(self, event: NotificationEvent) -> list[bool]:
        results = []
        for notifier in self.notifiers:
            try:
                results.append(notifier.send(event))
            except Exception:
                results.append(False)
        return results
