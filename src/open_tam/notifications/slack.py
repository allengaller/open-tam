"""Slack webhook notifier."""
from __future__ import annotations

import json
import urllib.request

from open_tam.notifications.dispatcher import NotificationEvent


class SlackNotifier:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, event: NotificationEvent) -> bool:
        if not self.webhook_url:
            return False
        payload = {
            "text": f"*{event.title}*\n{event.content}",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False
