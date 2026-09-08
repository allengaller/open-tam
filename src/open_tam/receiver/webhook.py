from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from open_tam.models import AlertEvent
from open_tam.receiver.adapters import adapt_alert
from open_tam.receiver.dedup import AlertDedup

logger = logging.getLogger(__name__)


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """HMAC-SHA256 签名验证。"""
    if not secret:
        return True
    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_webhook_app(
    inbox_dir: Path | str = "var/inbox",
    state_dir: Path | str = "var",
    webhook_secret: str = "",
    dedup_window_seconds: int = 300,
) -> FastAPI:
    inbox = Path(inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)

    dedup = AlertDedup(
        window_seconds=dedup_window_seconds,
        persist_path=state / "dedup.json",
    )
    app = FastAPI(title="open-tam alert webhook")

    @app.post("/alerts", status_code=201)
    async def receive_alert(request: Request) -> dict:
        body = await request.body()

        if webhook_secret:
            signature = request.headers.get("X-Signature", "")
            if not verify_signature(body, signature, webhook_secret):
                raise HTTPException(status_code=401, detail="invalid signature")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="payload must be an object")

        try:
            event = adapt_alert(payload)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if not dedup.should_process(event.alert_name, event.service):
            return {"alert_id": event.alert_id, "dedup": True, "message": "duplicate suppressed"}

        (inbox / f"{event.alert_id}.json").write_text(
            event.model_dump_json(indent=2), encoding="utf-8"
        )
        return {"alert_id": event.alert_id, "dedup": False, "alert": event.model_dump(mode="json")}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "ts": time.time()}

    return app
