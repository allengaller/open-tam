from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from open_tam.config import Settings
from open_tam.faults import FAULT_MODES, FaultState
from open_tam.receiver.alert_receiver import normalize_alert
from open_tam.web.events import InvestigationHub
from open_tam.web.service import start_investigation

STATIC_DIR = Path(__file__).parent / "static"


def create_app(*, db=None, auth_enabled: bool | None = None) -> FastAPI:
    app = FastAPI(title="open-tam web")
    settings = Settings.load()
    if auth_enabled is None:
        auth_enabled = settings.auth_enabled
    hub = InvestigationHub()

    if db is None:
        from open_tam.persistence.database import get_database

        db = get_database(settings.database_url.replace("sqlite:///", ""))
    if auth_enabled:
        from open_tam.auth.middleware import AuthMiddleware

        app.add_middleware(AuthMiddleware, db=db, enabled=True)

    @app.post("/api/investigations", status_code=202)
    async def post_investigation(request: Request, payload: dict) -> dict:
        if not isinstance(payload, dict) or "alert" not in payload:
            raise HTTPException(status_code=422, detail="payload must contain 'alert'")
        user = getattr(request.state, "user", None)
        if user is not None:
            from open_tam.auth.roles import has_permission

            if not has_permission(user.role, "investigate"):
                raise HTTPException(status_code=403,
                                    detail="role does not allow investigate")
        try:
            alert = normalize_alert(payload["alert"])
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        loop = asyncio.get_running_loop()
        inv = start_investigation(
            hub, alert,
            fake=bool(payload.get("fake", False)),
            transport=str(payload.get("transport", "inline")),
            loop=loop, db=db,
            user_id=user.id if user is not None else None,
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

    @app.get("/api/me")
    async def me(request: Request) -> dict:
        user = getattr(request.state, "user", None)
        if user is None:
            return {"authenticated": False}
        return {"authenticated": True, "username": user.username, "role": user.role}

    @app.get("/api/history")
    async def history_list(limit: int = 20) -> dict:
        from open_tam.persistence.repositories import InvestigationRepository

        records = InvestigationRepository(db).list_all(limit=limit)
        return {"investigations": [
            {"id": r.id, "alert_id": r.alert_id, "user_id": r.user_id,
             "status": r.status, "root_cause": r.root_cause,
             "confidence": r.confidence, "created_at": r.created_at}
            for r in records
        ]}

    @app.get("/api/history/{investigation_id}")
    async def history_detail(investigation_id: str) -> dict:
        from open_tam.persistence.repositories import InvestigationRepository

        r = InvestigationRepository(db).get_by_id(investigation_id)
        if r is None:
            raise HTTPException(status_code=404, detail="unknown investigation")
        return {"id": r.id, "alert_id": r.alert_id, "user_id": r.user_id,
                "status": r.status, "root_cause": r.root_cause,
                "confidence": r.confidence, "report_path": r.report_path,
                "trace_path": r.trace_path, "created_at": r.created_at,
                "updated_at": r.updated_at}

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