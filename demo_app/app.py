from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException

from open_tam.faults import FAULT_MODES, FaultState
from open_tam.mock.metrics_data import generate_series


def create_app(state_dir: Path | str | None = None) -> FastAPI:
    state = FaultState(state_dir=state_dir)

    def current_cpu() -> float:
        now = datetime.now()
        pts = generate_series(
            metric="cpu_usage",
            service="demo-app",
            start=now.replace(second=0, microsecond=0),
            end=now,
            state=state,
        )
        return pts[-1].value if pts else 30.0

    app = FastAPI(title="demo-app", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics() -> dict:
        return {"cpu_usage": current_cpu()}

    @app.post("/faults/{name}")
    def inject(name: str) -> dict:
        if name not in FAULT_MODES:
            raise HTTPException(status_code=404, detail=f"unknown fault: {name}")
        state.activate(name)
        return {"injected": name}

    @app.delete("/faults/{name}")
    def clear(name: str) -> dict:
        state.clear(name)
        return {"cleared": name}

    return app


app = create_app()
