from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime
from uuid import uuid4

from open_tam.config import Settings
from open_tam.models import AlertEvent
from open_tam.orchestrator.investigate import run_investigation
from open_tam.tracing.trace import TraceRecorder
from open_tam.web.events import Investigation, InvestigationHub


class WebConfirmer:
    """敏感操作经 SSE 弹窗人工确认；排查线程阻塞等待 Web 端裁决。

    confirm() 由排查线程调用：推送 confirm_request 事件后等待 resolve()。
    超时未裁决视为拒绝（fail-safe）。
    """

    def __init__(self, sink, timeout_seconds: float = 120.0) -> None:
        self.sink = sink
        self.timeout = timeout_seconds
        self._lock = threading.Lock()
        self._pending: dict | None = None
        self._event = threading.Event()
        self._approved = False

    def confirm(self, action: str, arguments: dict) -> bool:
        request_id = uuid4().hex[:8]
        with self._lock:
            self._pending = {"request_id": request_id, "action": action,
                             "arguments": arguments}
            self._approved = False
            self._event.clear()
        self.sink({"kind": "confirm_request", "request_id": request_id,
                   "action": action, "arguments": arguments})
        if not self._event.wait(self.timeout):
            with self._lock:
                self._pending = None
            return False
        with self._lock:
            self._pending = None
            return self._approved

    def resolve(self, request_id: str, approved: bool) -> bool:
        with self._lock:
            if self._pending is None or self._pending["request_id"] != request_id:
                return False
            self._approved = approved
        self._event.set()
        return True

    @property
    def pending(self) -> dict | None:
        with self._lock:
            return dict(self._pending) if self._pending else None


def start_investigation(
    hub: InvestigationHub,
    alert: AlertEvent,
    *,
    fake: bool,
    transport: str,
    loop: asyncio.AbstractEventLoop,
    db=None,
    user_id: str | None = None,
) -> Investigation:
    """登记会话并在后台线程跑排查；TraceRecorder 挂 hub sink 做流式广播。

    loop：FastAPI 所在的事件循环（sink 广播经 call_soon_threadsafe 桥接进去）。
    db：可选 SQLite 连接；先落库再启动线程，避免状态回写打在 INSERT 之前。
    """
    inv = hub.create(alert, fake=fake, transport=transport)
    inv.status = "running"
    _persist_start(db, inv, alert, user_id)
    threading.Thread(
        target=_run, args=(hub, inv, loop, db), daemon=True,
        name=f"investigate-{inv.id}",
    ).start()
    return inv


def _persist_start(db, inv: Investigation, alert: AlertEvent, user_id: str | None) -> None:
    if db is None:
        return
    try:
        from open_tam.persistence.repositories import (
            AlertRecord,
            AlertRepository,
            InvestigationRecord,
            InvestigationRepository,
        )

        now = datetime.now().isoformat()
        AlertRepository(db).create(AlertRecord(
            id=f"{alert.alert_id}-{uuid.uuid4().hex[:8]}",
            alert_name=alert.alert_name, service=alert.service,
            metric=alert.metric, severity=alert.severity,
            payload=alert.model_dump(mode="json"), created_at=now,
        ))
        InvestigationRepository(db).create(InvestigationRecord(
            id=inv.id, alert_id=alert.alert_id, user_id=user_id,
            status="running", root_cause=None, confidence=None,
            report_path=None, trace_path=None,
            created_at=now, updated_at=now,
        ))
    except Exception:
        pass


def _match_skill(alert: AlertEvent, settings: Settings) -> dict | None:
    """与 run_investigation 相同的 Skill 匹配，用于 done 事件展示。"""
    try:
        from open_tam.skills.loader import SkillLoader

        skill = SkillLoader(settings.skills_dir).match(alert.alert_name, alert.service)
        if skill:
            return {"name": skill.name, "confidence": skill.confidence}
    except Exception:
        pass
    return None


def _run(hub: InvestigationHub, inv: Investigation, loop: asyncio.AbstractEventLoop,
         db) -> None:
    settings = Settings.load()
    sink = hub.sink_for(inv.id)
    inv.confirmer = WebConfirmer(sink)
    alert_id = inv.alert.alert_id
    trace = TraceRecorder(alert_id=alert_id, traces_dir=settings.traces_dir, sink=sink)
    metric_trace = TraceRecorder(alert_id=alert_id, traces_dir=settings.traces_dir,
                                 agent="metric", sink=sink)
    log_trace = TraceRecorder(alert_id=alert_id, traces_dir=settings.traces_dir,
                              agent="log", sink=sink)
    try:
        result, path = run_investigation(
            inv.alert, settings, fake=inv.fake, transport=inv.transport,
            trace=trace, metric_trace=metric_trace, log_trace=log_trace,
            confirmer=inv.confirmer,
        )
    except Exception as exc:
        _mark_db(db, inv.id, status="error")
        hub.fail(inv.id, f"{type(exc).__name__}: {exc}")
        return
    _mark_db(db, inv.id, status="done", root_cause=result.root_cause,
             confidence=result.confidence, report_path=str(path),
             trace_path=str(trace.path))
    hub.finish(inv.id, report_path=str(path), root_cause=result.root_cause,
               confidence=result.confidence, evidence=result.evidence,
               actions=result.actions, skill_used=_match_skill(inv.alert, settings))


def _mark_db(db, inv_id: str, *, status: str, root_cause: str | None = None,
             confidence: str | None = None, report_path: str | None = None,
             trace_path: str | None = None) -> None:
    if db is None:
        return
    try:
        from open_tam.persistence.repositories import InvestigationRepository

        InvestigationRepository(db).update_status(
            inv_id, status, root_cause=root_cause, confidence=confidence,
            report_path=report_path, trace_path=trace_path,
        )
    except Exception:
        pass