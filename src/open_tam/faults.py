from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class FaultMode:
    """一个故障模式 = 一条可注入的故障故事，同时是行为评测集的一项。"""

    name: str
    service: str
    metric: str
    baseline_high: float
    spike_value: float
    anomaly_desc: str
    root_cause: str
    remediation: str
    log_signature: str = ""


FAULT_MODES: dict[str, FaultMode] = {
    "cpu_spike": FaultMode(
        name="cpu_spike",
        service="demo-app",
        metric="cpu_usage",
        baseline_high=45.0,
        spike_value=92.0,
        anomaly_desc="cpu_usage 从基线 ~30% 飙升至 ~92% 并持续",
        root_cause="demo-app /search 接口新版本引入低效正则回溯，导致 CPU 飙升",
        remediation="回滚 demo-app 最近一次发布，并优化 /search 的正则匹配逻辑",
    ),
}

_DEFAULT_STATE_DIR = Path(os.environ.get("OPEN_TAM_STATE_DIR", "var"))


class FaultState:
    """跨进程共享的故障状态（JSON 文件），demo-app 注入与 mock 数据源共用。"""

    def __init__(self, state_dir: Path | str | None = None) -> None:
        self.path = Path(state_dir) if state_dir else _DEFAULT_STATE_DIR
        self.path.mkdir(parents=True, exist_ok=True)
        self.file = self.path / "fault_state.json"

    def _load(self) -> dict:
        if not self.file.exists():
            return {}
        return json.loads(self.file.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def activate(self, name: str, duration_minutes: int = 30) -> None:
        if name not in FAULT_MODES:
            raise KeyError(f"unknown fault mode: {name}")
        data = self._load()
        data[name] = {
            "activated_at": datetime.now().isoformat(),
            "duration_minutes": duration_minutes,
        }
        self._save(data)

    def clear(self, name: str) -> None:
        data = self._load()
        data.pop(name, None)
        self._save(data)

    def window(self, name: str) -> tuple[datetime, datetime] | None:
        entry = self._load().get(name)
        if not entry:
            return None
        start = datetime.fromisoformat(entry["activated_at"])
        return start, start + timedelta(minutes=entry["duration_minutes"])

    def is_active(self, name: str, now: datetime | None = None) -> bool:
        win = self.window(name)
        if not win:
            return False
        now = now or datetime.now()
        return win[0] <= now <= win[1]

    def snapshot_time(self, name: str) -> datetime:
        win = self.window(name)
        assert win is not None, f"fault {name} not activated"
        return win[0]
