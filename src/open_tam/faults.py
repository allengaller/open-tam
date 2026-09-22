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
    eval_keywords: tuple[str, ...] = ()  # 评测命中判定：根因文本应包含的关键词


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
        eval_keywords=("正则", "cpu"),
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
        eval_keywords=("索引", "全表扫描"),
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
        eval_keywords=("缓存",),
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
        eval_keywords=("连接池", "连接"),
    ),
    "pod_crash_loop": FaultMode(
        name="pod_crash_loop",
        service="demo-app",
        metric="pod_restart_count",
        baseline_mid=0.0,
        baseline_high=1.0,
        spike_value=5.0,
        anomaly_desc="Pod 在 5 分钟内重启超过 3 次（CrashLoopBackOff）",
        root_cause="应用启动失败或运行时 panic，容器反复崩溃重启",
        remediation="检查容器日志与 liveness probe 配置，修复启动错误后重新部署",
        log_signature="BackOff restarting failed container",
        eval_keywords=("CrashLoopBackOff", "容器"),
    ),
    "node_not_ready": FaultMode(
        name="node_not_ready",
        service="k8s-node",
        metric="node_ready",
        baseline_mid=1.0,
        baseline_high=0.5,
        spike_value=0.0,
        anomaly_desc="Node 状态变为 NotReady 超过 5 分钟",
        root_cause="kubelet 异常或节点资源耗尽导致 Node NotReady",
        remediation="检查 kubelet 日志与节点资源使用，必要时重启 kubelet 或驱逐 Pod",
        log_signature="Node not ready: kubelet stopped posting node status",
        eval_keywords=("kubelet", "NotReady"),
    ),
    "dns_failure": FaultMode(
        name="dns_failure",
        service="demo-app",
        metric="dns_lookup_failures",
        baseline_mid=0.0,
        baseline_high=1.0,
        spike_value=50.0,
        anomaly_desc="DNS 解析失败率飙升，Pod 无法访问外部服务",
        root_cause="CoreDNS Pod 异常或 ConfigMap 配置错误导致集群 DNS 故障",
        remediation="检查 CoreDNS Pod 状态与日志，验证 DNS ConfigMap 配置",
        log_signature="DNS lookup failed for external service",
        eval_keywords=("DNS", "CoreDNS"),
    ),
    "cert_expiry": FaultMode(
        name="cert_expiry",
        service="ingress",
        metric="cert_days_remaining",
        baseline_mid=30.0,
        baseline_high=14.0,
        spike_value=0.0,
        anomaly_desc="TLS 证书即将过期或已过期",
        root_cause="TLS 证书未配置自动续期，证书过期导致 HTTPS 连接失败",
        remediation="使用 cert-manager 配置自动续期，临时手动更新证书",
        log_signature="TLS certificate expired",
        eval_keywords=("证书", "TLS"),
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

    def activate(self, name: str, duration_minutes: int = 30,
                 region: str | None = None) -> None:
        """注入故障。region=None 表示全局生效；指定 region 时仅该区域异常。"""
        if name not in FAULT_MODES:
            raise KeyError(f"unknown fault mode: {name}")
        data = self._load()
        # 指标点按分钟对齐，故障窗口也对齐到分钟，避免注入后当前点落在窗口前
        data[name] = {
            "activated_at": datetime.now().replace(second=0, microsecond=0).isoformat(),
            "duration_minutes": duration_minutes,
            **({"region": region} if region else {}),
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

    def region_of(self, name: str) -> str | None:
        entry = self._load().get(name)
        return entry.get("region") if entry else None

    def is_active(self, name: str, now: datetime | None = None,
                  region: str | None = None) -> bool:
        win = self.window(name)
        if not win:
            return False
        # 查询方 region=None 表示不过滤；全局故障对任意区域生效
        fault_region = self.region_of(name)
        if fault_region and region and fault_region != region:
            return False
        now = now or datetime.now()
        return win[0] <= now <= win[1]

    def snapshot_time(self, name: str) -> datetime:
        win = self.window(name)
        assert win is not None, f"fault {name} not activated"
        return win[0]
