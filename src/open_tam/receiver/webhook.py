from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from open_tam.receiver.alert_receiver import normalize_alert


def create_webhook_app(inbox_dir: Path | str = "var/inbox") -> FastAPI:
    inbox = Path(inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="open-tam alert webhook")

    @app.post("/alerts", status_code=201)
    def receive_alert(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="payload must be an object")
        try:
            event = normalize_alert(payload)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        (inbox / f"{event.alert_id}.json").write_text(
            event.model_dump_json(indent=2), encoding="utf-8"
        )
        return {"alert": event.model_dump(mode="json")}

    return app
