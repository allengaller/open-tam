from __future__ import annotations

import asyncio
import threading

from open_tam.config import Settings
from open_tam.models import AlertEvent
from open_tam.orchestrator.investigate import run_investigation
from open_tam.tracing.trace import TraceRecorder
from open_tam.web.events import Investigation, InvestigationHub


def start_investigation(
    hub: InvestigationHub,
    alert: AlertEvent,
    *,
    fake: bool,
    transport: str,
    loop: asyncio.AbstractEventLoop,
) -> Investigation:
    """登记会话并在后台线程跑排查；TraceRecorder 挂 hub sink 做流式广播。

    loop：FastAPI 所在的事件循环（sink 广播经 call_soon_threadsafe 桥接进去）。
    """
    inv = hub.create(alert, fake=fake, transport=transport)
    inv.status = "running"
    threading.Thread(
        target=_run, args=(hub, inv, loop), daemon=True,
        name=f"investigate-{inv.id}",
    ).start()
    return inv


def _run(hub: InvestigationHub, inv: Investigation, loop: asyncio.AbstractEventLoop) -> None:
    settings = Settings.load()
    sink = hub.sink_for(inv.id)
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
        )
    except Exception as exc:
        hub.fail(inv.id, f"{type(exc).__name__}: {exc}")
        return
    hub.finish(inv.id, report_path=str(path), root_cause=result.root_cause,
               confidence=result.confidence, evidence=result.evidence,
               actions=result.actions)