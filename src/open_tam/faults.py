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
    baseline_mid: float
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
        baseline_mid=30.0,
        baseline_high=45.0,
        spike_value=92.0,
        anomaly_desc="cpu_usage 从基线 ~30% 飙升至 ~92% 并持续",
        root_cause="demo-app /search 接口新版本引入低效正则回溯，导致 CPU 飙升",
        remediation="回滚 demo-app 最近一次发布，并优化 /search 的正则匹配逻辑",
        log_signature="WARN CPU usage above 85% for 60s on demo-app",
    ),
    "slow_query": FaultMode(
        name="slow_query",
        service="demo-app",
        metric="db_query_duration_ms",
        baseline_mid=120.0,
        baseline_high=300.0,
        spike_value=3200.0,
        anomaly_desc="db_query_duration_ms 从基线 ~120ms 飙升至 ~3200ms 并持续",
        root_cause="/orders 接口新增 SQL 未命中索引，全表扫描导致慢查询",
        remediation="为 orders(user_id, created_at) 建立联合索引，并回滚未加索引的临时 SQL",
        log_signature="Slow query detected: SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC took 3241ms",
    ),
    "oom": FaultMode(
        name="oom",
        service="demo-app",
        metric="memory_usage",
        baseline_mid=55.0,
        baseline_high=70.0,
        spike_value=95.0,
        anomaly_desc="memory_usage 从基线 ~55% 爬升至 ~95% 并触发容器终止",
        root_cause="本地缓存无淘汰策略，对象持续累积导致容器 OOMKilled",
        remediation="为本地缓存增加 TTL 与最大条数上限，临时将内存扩容至 2Gi 并重启",
        log_signature="java.lang.OutOfMemoryError: Java heap space — container will be OOMKilled",
    ),
    "connection_pool_exhausted": FaultMode(
        name="connection_pool_exhausted",
        service="demo-app",
        metric="db_active_connections",
        baseline_mid=20.0,
        baseline_high=40.0,
        spike_value=50.0,
        anomaly_desc="db_active_connections 打满至池上限 50 并伴随请求超时",
        root_cause="慢事务长期占用数据库连接未释放，连接池耗尽后新请求超时",
        remediation="缩短事务边界并为查询设置 statement timeout，临时重启应用释放连接",
        log_signature="HikariPool-1 - Connection is not available, request timed out after 30000ms",
    ),
}


class FaultState:
    """跨进程共享的故障状态（JSON 文件），demo-app 注入与 mock 数据源共用。"""

    def __init__(self, state_dir: Path | str | None = None) -> None:
        # 构造时读取环境变量（而非 import 时固化），保证测试可在运行期隔离
        self.path = Path(state_dir) if state_dir else Path(os.environ.get("OPEN_TAM_STATE_DIR", "var"))
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
        # 指标点按分钟对齐，故障窗口也对齐到分钟，避免注入后当前点落在窗口前
        data[name] = {
            "activated_at": datetime.now().replace(second=0, microsecond=0).isoformat(),
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
