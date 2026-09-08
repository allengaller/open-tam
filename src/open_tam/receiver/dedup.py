from __future__ import annotations

import json
import time
from pathlib import Path


class AlertDedup:
    """滑动窗口去重：同一 alert_name+service 在 window_seconds 内只触发一次排查。"""

    def __init__(self, window_seconds: int = 300, persist_path: Path | None = None) -> None:
        self._seen: dict[str, float] = {}
        self._window = window_seconds
        self._persist_path = persist_path
        if persist_path and persist_path.exists():
            try:
                data = json.loads(persist_path.read_text(encoding="utf-8"))
                self._seen = {k: float(v) for k, v in data.items()}
            except (json.JSONDecodeError, ValueError):
                self._seen = {}

    def should_process(self, alert_name: str, service: str) -> bool:
        key = f"{alert_name}:{service}"
        now = time.time()
        self._evict_expired(now)
        last = self._seen.get(key, 0)
        if now - last < self._window:
            return False
        self._seen[key] = now
        self._persist()
        return True

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self._window * 2
        expired = [k for k, v in self._seen.items() if v < cutoff]
        for k in expired:
            del self._seen[k]

    def _persist(self) -> None:
        if self._persist_path:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps(self._seen), encoding="utf-8"
            )

    @property
    def window_seconds(self) -> int:
        return self._window

    def state(self) -> dict[str, float]:
        return dict(self._seen)
