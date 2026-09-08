from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.receiver.alert_receiver import normalize_alert
from open_tam.web.events import InvestigationHub
from open_tam.web.service import start_investigation

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="open-tam web")
    hub = InvestigationHub()

    @app.post("/api/investigations", status_code=202)
    async def post_investigation(payload: dict) -> dict:
        if not isinstance(payload, dict) or "alert" not in payload:
            raise HTTPException(status_code=422, detail="payload must contain 'alert'")
        try:
            alert = normalize_alert(payload["alert"])
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        loop = asyncio.get_running_loop()
        inv = start_investigation(
            hub, alert,
            fake=bool(payload.get("fake", False)),
            transport=str(payload.get("transport", "inline")),
            loop=loop,
        )
        return {"id": inv.id, "status": inv.status}

    @app.get("/api/investigations/{investigation_id}/events")
    async def investigation_events(investigation_id: str) -> StreamingResponse:
        if hub.get(investigation_id) is None:
            raise HTTPException(status_code=404, detail="unknown investigation")
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        sub = hub.subscribe(investigation_id, queue=queue, loop=loop)

        async def stream():
            for event in sub.snapshot:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["kind"] in ("done", "error"):
                    return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["kind"] in ("done", "error"):
                    return

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/faults")
    async def list_faults() -> dict:
        return {"faults": [
            {"name": m.name, "service": m.service, "metric": m.metric,
             "anomaly_desc": m.anomaly_desc}
            for m in FAULT_MODES.values()
        ]}

    @app.post("/api/faults/{name}/activate")
    async def activate_fault(name: str) -> dict:
        if name not in FAULT_MODES:
            raise HTTPException(status_code=404, detail=f"unknown fault: {name}")
        FaultState().activate(name, duration_minutes=30)
        return {"activated": name}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app