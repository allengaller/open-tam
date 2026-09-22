from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from uuid import uuid4

from open_tam.models import AlertEvent


@dataclass
class Subscription:
    """一次 SSE 订阅：先重放 snapshot（订阅前已发生的事件），再消费 queue 增量。"""

    snapshot: list[dict]
    queue: asyncio.Queue


@dataclass
class Investigation:
    id: str
    alert: AlertEvent
    fake: bool
    transport: str
    status: str = "pending"  # pending | running | done | error
    events: list[dict] = field(default_factory=list)
    subscribers: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    confirmer: object | None = field(default=None, repr=False)


class InvestigationHub:
    """排查会话注册表 + 事件广播（单进程内存态，重启即清）。

    TraceRecorder 的 sink 在后台排查线程内被调用：加锁 append 事件缓存（赋 seq），
    再经 loop.call_soon_threadsafe 桥接进每个订阅者的 asyncio.Queue。
    """

    def __init__(self) -> None:
        self._investigations: dict[str, Investigation] = {}
        self._lock = threading.Lock()

    def create(self, alert: AlertEvent, *, fake: bool, transport: str) -> Investigation:
        inv = Investigation(id=uuid4().hex[:12], alert=alert, fake=fake, transport=transport)
        with self._lock:
            self._investigations[inv.id] = inv
        return inv

    def get(self, investigation_id: str) -> Investigation | None:
        return self._investigations.get(investigation_id)

    def sink_for(self, investigation_id: str):
        inv = self._investigations[investigation_id]

        def sink(entry: dict) -> None:
            with inv.lock:
                entry = {**entry, "seq": len(inv.events)}
                inv.events.append(entry)
                subscribers = list(inv.subscribers)
            for queue, loop in subscribers:
                loop.call_soon_threadsafe(queue.put_nowait, entry)

        return sink

    def subscribe(self, investigation_id: str, *, queue: asyncio.Queue,
                  loop: asyncio.AbstractEventLoop) -> Subscription:
        inv = self._investigations[investigation_id]
        with inv.lock:
            snapshot = list(inv.events)
            inv.subscribers.append((queue, loop))
        return Subscription(snapshot=snapshot, queue=queue)

    def finish(self, investigation_id: str, *, report_path: str, root_cause: str | None,
               confidence: str, evidence: list[str], actions: list[str],
               skill_used: dict | None = None) -> None:
        inv = self._investigations[investigation_id]
        inv.status = "done"
        self.sink_for(investigation_id)({
            "kind": "done", "report_path": report_path, "root_cause": root_cause,
            "confidence": confidence, "evidence": evidence, "actions": actions,
            "skill_used": skill_used,
        })

    def fail(self, investigation_id: str, error: str) -> None:
        inv = self._investigations[investigation_id]
        inv.status = "error"
        self.sink_for(investigation_id)({"kind": "error", "error": error})